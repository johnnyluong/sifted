from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from sift.domain import SHARE_PREFIX, FailureKind, ProcessingError, Source, SourceRef

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_TRAILING = ".,;:!?)]}>\"'"

_IG_HOSTS = frozenset({"instagram.com", "www.instagram.com", "m.instagram.com"})
_THREADS_HOSTS = frozenset({"threads.com", "www.threads.com", "threads.net", "www.threads.net"})

_IG_PATH = re.compile(r"^/(?:(?!share/)[\w.]+/)?(?P<kind>reels?|p)/(?P<code>[\w-]+)/?$")
_IG_SHARE = re.compile(r"^/share/(?P<kind>reels?|p)/(?P<code>[\w-]+)/?$")
_THREADS_POST = re.compile(r"^/@(?P<user>[\w.]+)/post/(?P<code>[\w-]+)/?$")
_THREADS_SHORT = re.compile(r"^/t/(?P<code>[\w-]+)/?$")
_THREADS_SHARE = re.compile(r"^/share/(?P<code>[\w-]+)/?$")


class UnsupportedKind(StrEnum):
    meta_page = "meta_page"  # at most one path segment: a profile or the home page
    meta_other = "meta_other"  # deeper than that, such as a story
    not_meta = "not_meta"


@dataclass(frozen=True, slots=True)
class Unsupported:
    url: str
    reason: str
    kind: UnsupportedKind


def find_urls(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for match in URL_RE.finditer(text):
        seen.setdefault(match.group(0).rstrip(_TRAILING), None)
    return list(seen)


def parse_url(url: str) -> SourceRef | Unsupported:
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    path = parts.path

    if host in _IG_HOSTS:
        if m := _IG_PATH.match(path):
            code = m.group("code")
            segment = "p" if m.group("kind") == "p" else "reel"
            return SourceRef(Source.instagram, code, f"https://www.instagram.com/{segment}/{code}/")
        if m := _IG_SHARE.match(path):
            code = m.group("code")
            return SourceRef(
                Source.instagram, f"{SHARE_PREFIX}{code}", f"https://www.instagram.com/share/{m.group('kind')}/{code}/"
            )
        return Unsupported(url, "Only Instagram reel and post links are supported.", _meta_kind(path))

    if host in _THREADS_HOSTS:
        if m := _THREADS_POST.match(path):
            code = m.group("code")
            return SourceRef(
                source=Source.threads,
                canonical_id=code,
                clean_url=f"https://www.threads.com/@{m.group('user')}/post/{code}",
            )
        if m := _THREADS_SHORT.match(path):
            code = m.group("code")
            return SourceRef(
                source=Source.threads,
                canonical_id=code,
                clean_url=f"https://www.threads.com/t/{code}",
            )
        if m := _THREADS_SHARE.match(path):
            code = m.group("code")
            return SourceRef(Source.threads, f"{SHARE_PREFIX}{code}", f"https://www.threads.com/share/{code}/")
        return Unsupported(url, "Only links to a single Threads post are supported.", _meta_kind(path))

    return Unsupported(url, "Not an Instagram or Threads link.", UnsupportedKind.not_meta)


def shared_post(source: Source, final_url: str) -> SourceRef:
    ref = parse_url(final_url)
    if isinstance(ref, Unsupported) or ref.source is not source or ref.is_share:
        raise ProcessingError(
            FailureKind.unsupported_url,
            f"{source.value.title()} did not redirect this share link to a post. Open it and paste the post's own link.",
            retryable=False,
        )
    return ref


def _meta_kind(path: str) -> UnsupportedKind:
    segments = [s for s in path.split("/") if s]
    return UnsupportedKind.meta_page if len(segments) <= 1 else UnsupportedKind.meta_other
