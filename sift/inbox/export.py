"""Meta does not document the export's JSON and has renamed its keys between exports, so nothing here
reads a key by name."""

from __future__ import annotations

import html
import json
import re
import zipfile
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import IO, Any

from sift.domain import Source, SourceRef
from sift.sources import urls

MEMBER_MAX_BYTES = 64 * 1024 * 1024
SCAN_MAX_BYTES = 256 * 1024 * 1024
READABLE = frozenset({".json", ".html", ".htm"})
_TOKEN = re.compile(r"[a-z0-9]+")
_EARLIEST = datetime(2010, 1, 1, tzinfo=UTC).timestamp()
_LATEST = datetime(2100, 1, 1, tzinfo=UTC).timestamp()


class NotAnExport(Exception):
    pass


@dataclass(frozen=True, slots=True)
class FoundLink:
    ref: SourceRef
    url: str
    saved_at: datetime | None


@dataclass(frozen=True, slots=True)
class ExportScan:
    links: list[FoundLink]
    unsupported: list[str]
    files_read: list[str]
    files_skipped_large: list[str]
    files_skipped_budget: list[str]


def is_saved_member(path: str) -> bool:
    """DM folders are named after the other account, so anything under messages/ or inbox/ is refused
    even when a folder name starts with "saved_"."""
    p = PurePosixPath(path)
    tokens = set(_TOKEN.findall(path.lower()))
    return p.suffix.lower() in READABLE and "saved" in tokens and not tokens & {"messages", "inbox"}


def _read_order(path: str) -> int:
    """Saved posts first and collections last, so the scan budget goes to the files that matter most."""
    tokens = set(_TOKEN.findall(path.lower()))
    if "collections" in tokens:
        return 2
    return 0 if tokens & {"posts", "threads"} else 1


def scan(zip_path: Path | IO[bytes]) -> ExportScan:
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        raise NotAnExport("This is not a zip file. Upload the .zip Meta emailed you, without unpacking it.") from e
    found: dict[tuple[Source, str], FoundLink] = {}
    unsupported: dict[str, None] = {}
    files_read: list[str] = []
    too_large: list[str] = []
    over_budget: list[str] = []
    total = 0
    with archive:
        members = [m for m in archive.infolist() if not m.is_dir()]
        saved = sorted((m for m in members if is_saved_member(m.filename)), key=lambda m: _read_order(m.filename))
        for info in saved:
            if info.file_size > MEMBER_MAX_BYTES:
                too_large.append(info.filename)
                continue
            if total + info.file_size > SCAN_MAX_BYTES:
                over_budget.append(info.filename)
                continue
            total += info.file_size
            text = _read(archive, info).decode("utf-8", "replace")
            files_read.append(info.filename)
            for url, saved_at in _links_in(text, PurePosixPath(info.filename).suffix.lower()):
                match _classify(url):
                    case SourceRef() as ref:
                        key = (ref.source, ref.canonical_id)
                        prior = found.get(key)
                        if prior is None or _earlier(saved_at, prior.saved_at):
                            found[key] = FoundLink(ref, url, saved_at)
                    case str() as unreadable:
                        unsupported.setdefault(unreadable, None)
                    case None:
                        pass
    if not files_read:
        raise NotAnExport(
            _too_large_message(too_large) if too_large else _no_saves_message([m.filename for m in members])
        )
    return ExportScan(list(found.values()), list(unsupported), files_read, too_large, over_budget)


def _read(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    name = info.filename
    try:
        return archive.read(info)
    except (zipfile.BadZipFile, zlib.error, EOFError) as e:
        raise NotAnExport(f"{name} is damaged in this zip ({e}). Download the export from Meta again.") from e
    # NotImplementedError subclasses RuntimeError, so it has to be caught first.
    except NotImplementedError as e:
        raise NotAnExport(f"{name} uses a compression Sift can't read ({e}). Upload the zip as Meta sent it.") from e
    except RuntimeError as e:
        raise NotAnExport(f"{name} is password-protected ({e}). Upload the zip exactly as Meta sent it.") from e


def _too_large_message(names: list[str]) -> str:
    return (
        f"Every saved file in this zip is too large to read: {', '.join(names)}. Sift reads saved files up to"
        f" {MEMBER_MAX_BYTES // 2**20} MB each; request only Saved, format JSON, for a smaller export."
    )


def _earlier(a: datetime | None, b: datetime | None) -> bool:
    return a is not None and (b is None or a < b)


def _links_in(text: str, suffix: str) -> Iterator[tuple[str, datetime | None]]:
    if suffix == ".json":
        try:
            yield from _walk(json.loads(text), None)
            return
        except json.JSONDecodeError:
            pass
    for url in urls.find_urls(html.unescape(text)):
        yield url, None


def _walk(node: object, saved_at: datetime | None) -> Iterator[tuple[str, datetime | None]]:
    """Both known shapes put the timestamp on the object that holds the URL or on its parent:
    {"string_map_data": {"Saved on": {"href": url, "timestamp": t}}} and
    {"timestamp": t, "label_values": [{"label": "URL", "value": url}]}."""
    match node:
        case dict():
            here = _timestamp_of(node) or saved_at
            for value in node.values():
                yield from _walk(value, here)
        case list():
            for value in node:
                yield from _walk(value, saved_at)
        case str():
            for url in urls.find_urls(node):
                yield url, saved_at
        case _:
            pass


def _timestamp_of(obj: dict[Any, Any]) -> datetime | None:
    for key, value in obj.items():
        if isinstance(key, str) and "timestamp" in key.lower() and isinstance(value, int | float):
            seconds = value / 1000 if value > _LATEST else value
            if _EARLIEST <= seconds <= _LATEST:
                return datetime.fromtimestamp(seconds, UTC)
    return None


def _classify(url: str) -> SourceRef | str | None:
    """A profile is dropped silently: newer exports list each saved post's owner next to it."""
    match urls.parse_url(url):
        case SourceRef() as ref:
            return ref
        case urls.Unsupported(kind=urls.UnsupportedKind.meta_other):
            return url
        case urls.Unsupported():
            return None


def _no_saves_message(names: list[str]) -> str:
    shown = sorted({"/".join(PurePosixPath(n).parts[:2]) for n in names})
    found = f" It has: {', '.join(shown[:8])}." if shown else " It is empty."
    return (
        "No saved posts in this zip."
        + found
        + " Meta splits big exports into parts; try the other parts, or request only Saved"
        " (Accounts Center > Your information and permissions > Download your information >"
        " Some of your information > Saved, format JSON)."
    )
