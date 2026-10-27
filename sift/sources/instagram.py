from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast

import httpx
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from sift.domain import FailureKind, MediaKind, Notes, ProcessingError, Source, SourceRef
from sift.sources.base import BROWSER_HEADERS, CookieSource, FetchResult
from sift.sources.urls import shared_post

if TYPE_CHECKING:
    from yt_dlp import _Params
    from yt_dlp.extractor.common import _InfoDict

log = logging.getLogger(__name__)

_IMAGE_EXTS = (".jpg", ".jpeg", ".webp", ".png")
MAX_SLIDES = 10
_ENTRY_FIELDS = ("extractor", "extractor_key", "webpage_url", "webpage_url_basename", "webpage_url_domain")
_SUBJECT = r"(post|page|content|media|video|reel)"
_GONE = re.compile(
    rf"{_SUBJECT} (isn't|is not|is no longer) available|{_SUBJECT} (is )?unavailable"
    rf"|{_SUBJECT} (has been|was) (removed|deleted)|may have been removed"
    rf"|{_SUBJECT} (does not|doesn't) exist|media not found"
    r"|registered users who follow|(account|post|profile) is private",
    re.IGNORECASE,
)
_HTTP_ERROR = re.compile(r"HTTP Error (\d{3})")
_ACCOUNT_TROUBLE = re.compile(
    r"rate.?limit|login page|log in to access|no longer valid|empty media response|requested format"
    r"|geo.?restrict|from your location|in your (country|region)|years old|age.?restricted|verify your age",
    re.IGNORECASE,
)


class _YtdlpLogger:
    def __init__(self, ydl: object = None) -> None:
        pass

    def debug(self, message: str) -> None:
        log.debug(message)

    def info(self, message: str) -> None:
        log.debug(message)

    def warning(self, message: str, *, once: bool = False, only_once: bool = False) -> None:
        log.info(message)

    def error(self, message: str) -> None:
        log.warning(message)

    def stdout(self, message: str) -> None:
        log.debug(message)

    def stderr(self, message: str) -> None:
        log.info(message)


def short_error(e: BaseException) -> str:
    text = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    return text.removeprefix("ERROR: ")[:300]


def _http_status(e: BaseException) -> int | None:
    seen: set[int] = set()
    current: BaseException | None = e
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = getattr(current, "status", None)
        if isinstance(status, int):
            return status
        nested = getattr(current, "exc_info", None)
        inner = nested[1] if isinstance(nested, tuple) and len(nested) > 1 else None
        current = (
            getattr(current, "cause", None)
            or current.__cause__
            or (inner if isinstance(inner, BaseException) else None)
        )
    return None


def _extraction_failure(e: DownloadError) -> ProcessingError:
    reason = short_error(e)
    if dead_post(reason, _http_status(e)):
        return ProcessingError(
            FailureKind.post_unavailable,
            f"Instagram says this post is gone or private to Sift's account: {reason}",
            retryable=False,
        )
    return ProcessingError(FailureKind.download_failed, reason, retryable=True)


def _media_failure(e: DownloadError) -> ProcessingError:
    return ProcessingError(FailureKind.download_failed, short_error(e), retryable=True)


def dead_post(message: str, status: int | None) -> bool:
    if _ACCOUNT_TROUBLE.search(message):
        return False
    if status is None and (m := _HTTP_ERROR.search(message)):
        status = int(m.group(1))
    if status is not None:
        return status in (404, 410)
    return bool(_GONE.search(message))


def author_of(info: dict[str, Any]) -> str | None:
    for key in ("channel", "uploader_id", "uploader"):
        value = info.get(key)
        if isinstance(value, str) and value and not value.isdigit():
            return value
    return None


def slides_of(info: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    if info.get("_type") != "playlist":
        return [info], []
    entries = [e for e in info.get("entries") or [] if e]
    notes = [f"Carousel: read the first {MAX_SLIDES} of {len(entries)} slides."] if len(entries) > MAX_SLIDES else []
    return (entries[:MAX_SLIDES] or [info]), notes


def is_video(slide: dict[str, Any]) -> bool:
    return bool(slide.get("formats") or slide.get("url"))


def best_image(slide: dict[str, Any]) -> str | None:
    thumbs = [t for t in slide.get("thumbnails") or [] if t.get("url")]
    if not thumbs:
        return slide.get("thumbnail")
    return str(max(thumbs, key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))["url"])


def downloaded_video(entry: dict[str, Any]) -> Path | None:
    for d in entry.get("requested_downloads") or []:
        path = Path(d.get("filepath") or "")
        if path.suffix.lower() not in _IMAGE_EXTS and path.is_file():
            return path
    return None


def _download_image(url: str | None, path: Path) -> Path | None:
    if not url:
        return None
    try:
        resp = httpx.get(url, timeout=20, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError:
        log.info("image download failed", exc_info=True)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)
    return path


def _find_thumbnail(workdir: Path) -> Path | None:
    for path in sorted(workdir.glob("media.*")):
        if path.suffix.lower() in _IMAGE_EXTS:
            return path
    return None


def _plain(info: Mapping[str, Any]) -> dict[str, Any]:
    return dict(info)


class InstagramFetcher:
    source: ClassVar[Source] = Source.instagram

    def __init__(self, cookies: CookieSource) -> None:
        self._cookies = cookies

    def _options(self, workdir: Path) -> _Params:
        return {
            "cookiesfrombrowser": self._cookies.as_ytdlp_option(),
            "outtmpl": str(workdir / "media.%(ext)s"),
            "format": "best[ext=mp4][height<=1080]/best[height<=1080]/best",
            "writethumbnail": True,
            "postprocessors": [{"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"}],
            "ignore_no_formats_error": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "logger": _YtdlpLogger(),
        }

    def resolve_share(self, ref: SourceRef) -> SourceRef:
        try:
            resp = httpx.get(ref.clean_url, headers=BROWSER_HEADERS, timeout=10, follow_redirects=True)
        except httpx.HTTPError as e:
            raise ProcessingError(
                FailureKind.download_failed, f"Could not open the share link: {type(e).__name__}", retryable=True
            ) from e
        return shared_post(Source.instagram, str(resp.url))

    def fetch(self, ref: SourceRef, workdir: Path) -> FetchResult:
        workdir.mkdir(parents=True, exist_ok=True)
        with YoutubeDL(self._options(workdir)) as ydl:
            try:
                # Unprocessed: yt-dlp raises "No video formats found" when downloading a carousel's image slides.
                extracted = ydl.extract_info(ref.clean_url, download=False, process=False)
            except DownloadError as e:
                raise _extraction_failure(e) from e
            info = _plain(ydl.sanitize_info(extracted) or {})
            slides, notes = slides_of(info)
            video_slide = next((s for s in slides if is_video(s)), None)
            video_path = None
            if video_slide is not None:
                # Playlist processing would copy these into each entry, and processing an entry reads them.
                entry = {k: info[k] for k in _ENTRY_FIELDS if k in info} | video_slide
                try:
                    video_path = downloaded_video(
                        _plain(ydl.process_ie_result(cast("_InfoDict", entry), download=True) or {})
                    )
                except DownloadError as e:
                    raise _media_failure(e) from e

        watched = video_slide if video_path else None
        if video_slide is not None and watched is None:
            notes.append("The video could not be downloaded.")
        images = [s for s in slides if s is not watched]
        slide_paths = [
            p
            for i, s in enumerate(images, 1)
            if (p := _download_image(best_image(s), workdir / "slides" / f"slide_{i:02d}.jpg"))
        ]
        if missing := len(images) - len(slide_paths):
            notes.append(f"{missing} of {len(images)} slide images could not be downloaded.")
        if sum(map(is_video, slides)) > 1:
            notes.append("Carousel: only the first video was watched; the others were read from their cover image.")
        first = slides[0]
        cover = _find_thumbnail(workdir) if watched else None
        covers = [cover, *slide_paths] if first is watched else [*slide_paths, cover]
        thumbnail = next((p for p in covers if p), None) or _download_image(best_image(info), workdir / "thumbnail.jpg")

        return FetchResult(
            media_kind=MediaKind.video if video_path else MediaKind.image,
            author_handle=author_of(info) or author_of(first),
            caption=info.get("description") or first.get("description"),
            video_path=video_path,
            thumbnail_path=thumbnail,
            slide_paths=tuple(slide_paths),
            raw_metadata={k: info.get(k) for k in ("id", "title", "duration", "timestamp", "like_count", "webpage_url")}
            | {"slides": len(slides)},
            notes=Notes(tuple(notes)),
        )
