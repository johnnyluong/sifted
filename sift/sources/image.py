from __future__ import annotations

import hashlib
import math
import re
import subprocess
import tempfile
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, NamedTuple

from sift import media
from sift.domain import FailureKind, MediaKind, Notes, ProcessingError, Source, SourceRef
from sift.sources.base import FetchResult

UPLOAD_NAME = re.compile(r"^[0-9a-f]{32}\.(png|jpg|webp|gif)$")
UPLOADS_PATH = "/api/uploads/"
READABLE = "Sift reads PNG, JPEG, WebP, GIF and HEIC images."

MAX_ASPECT = 1.5
MAX_TILES = 6
MAX_SET = 10
THUMB_LONG_EDGE = 480


class NotAnImage(Exception):
    pass


class Row(NamedTuple):
    top: int
    height: int


def heif_to_jpeg(data: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.heic", Path(tmp) / "out.jpg"
        src.write_bytes(data)
        try:
            proc = subprocess.run(
                ["sips", "-s", "format", "jpeg", str(src), "--out", str(dst)], capture_output=True, timeout=120
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            raise NotAnImage(f"This HEIC image could not be converted: {type(e).__name__}.") from e
        if proc.returncode != 0 or not dst.is_file():
            raise NotAnImage("This HEIC image could not be converted to JPEG.")
        return dst.read_bytes()


def store(data: bytes, folder: Path) -> str:
    kind = media.image_format(data)
    if kind is None:
        raise NotAnImage(READABLE)
    canonical_id = hashlib.sha256(data).hexdigest()[:32]
    path = folder / f"{canonical_id}.{'jpg' if kind == 'heif' else kind}"
    if not path.is_file():
        stored = heif_to_jpeg(data) if kind == "heif" else data
        folder.mkdir(parents=True, exist_ok=True)
        part = folder / f"{uuid.uuid4().hex}.part"
        part.write_bytes(stored)
        part.replace(path)
    return path.name


def upload_ref(names: Sequence[str]) -> SourceRef:
    unique = list(dict.fromkeys(names))
    return SourceRef(Source.image, _upload_id(unique), UPLOADS_PATH + ",".join(unique))


def _upload_id(names: list[str]) -> str:
    if len(names) == 1:
        return Path(names[0]).stem
    return hashlib.sha256(",".join(names).encode()).hexdigest()[:32]


def upload_names(clean_url: str) -> list[str]:
    return clean_url.removeprefix(UPLOADS_PATH).split(",")


def tiles(width: int, height: int) -> list[Row]:
    count = math.ceil(height / (width * MAX_ASPECT))
    step = math.ceil(height / count)
    return [Row(top, min(step, height - top)) for top in range(0, height, step)]


def tile_budget(counts: Sequence[int]) -> list[int]:
    room = media.MAX_IMAGES - len(counts)
    out: list[int] = []
    for count in counts:
        take = min(count, MAX_TILES, 1 + room)
        room -= take - 1
        out.append(take)
    return out


def stored_file(folder: Path, name: str) -> Path | None:
    if not UPLOAD_NAME.match(name):
        return None
    path = folder / name
    return path if path.is_file() else None


class ImageFetcher:
    source: ClassVar[Source] = Source.image

    def __init__(self, folder: Path) -> None:
        self._folder = folder

    def resolve_share(self, ref: SourceRef) -> SourceRef:
        return ref

    def fetch(self, ref: SourceRef, workdir: Path) -> FetchResult:
        names = upload_names(ref.clean_url)
        uploads: list[Path] = []
        for i, name in enumerate(names):
            path = stored_file(self._folder, name)
            if path is None:
                gone = "The uploaded image is" if len(names) == 1 else f"Image {i + 1} of {len(names)} is"
                raise ProcessingError(
                    FailureKind.post_unavailable, f"{gone} no longer in data/uploads.", retryable=False
                )
            uploads.append(path)
        flats = [workdir / f"upright_{i:02d}.png" for i in range(len(uploads))]
        try:
            for i, (upload, flat) in enumerate(zip(uploads, flats, strict=True)):
                try:
                    media.upright(upload, flat)
                except ProcessingError as e:
                    if not e.retryable:
                        raise
                    which = "this image" if len(names) == 1 else f"image {i + 1} of {len(names)}"
                    raise ProcessingError(
                        FailureKind.unsupported_url, f"Sift could not read {which}.", retryable=False
                    ) from e
            rows = [tiles(*media.image_size(flat)) for flat in flats]
            counts = tile_budget([len(r) for r in rows])
            crops = [(flat, row) for flat, r, n in zip(flats, rows, counts, strict=True) for row in r[:n]]
            slides = tuple(
                media.write_jpeg(
                    flat, workdir / "slides" / f"slide_{i:02d}.jpg", f"crop=iw:{row.height}:0:{row.top}", quality=2
                )
                for i, (flat, row) in enumerate(crops, start=1)
            )
            thumbnail = media.write_jpeg(slides[0], workdir / "thumbnail.jpg", media.fit(THUMB_LONG_EDGE))
        finally:
            for flat in flats:
                flat.unlink(missing_ok=True)
        return FetchResult(
            media_kind=MediaKind.image,
            author_handle=None,
            slide_paths=slides,
            thumbnail_path=thumbnail,
            notes=Notes(_set_note(len(rows)) + _cut_note(len(rows), len(slides), sum(len(r) for r in rows))),
        )


def _set_note(images: int) -> tuple[str, ...]:
    return (f"This post is {images} images of one thing, in reading order.",) if images > 1 else ()


def _cut_note(images: int, read: int, parts: int) -> tuple[str, ...]:
    if read == parts:
        return ()
    if images == 1:
        return (f"Read the top {MAX_TILES} parts of a very long screenshot.",)
    return (f"Read {read} of the {parts} parts of these {images} screenshots, each from its top.",)
