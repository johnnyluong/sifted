from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Protocol

import httpx
from bs4 import BeautifulSoup

from sift.domain import FailureKind, MediaKind, Notes, ProcessingError, Source, SourceRef
from sift.sources.base import BROWSER_HEADERS, CookieSource, FetchResult
from sift.sources.urls import shared_post

log = logging.getLogger(__name__)

OEMBED_URL = "https://graph.threads.net/v1.0/oembed"
_BOILERPLATE = re.compile(r"^(view on threads|post by @[\w.]+|threads)$", re.I)
_AUTHOR_IN_URL = re.compile(r"threads\.(?:com|net)/@(?P<user>[\w.]+)/")
_THREAD_MARKER = re.compile(r"(\(\d+\s*/\s*\d*\)|(?:^|\s)1/\s*$|🧵|\(cont)", re.I)
_VIDEO_URL = re.compile(r'"video_versions"\s*:\s*\[\s*\{[^\]]*?"url"\s*:\s*"(?P<url>[^"]+)"')


@dataclass(frozen=True, slots=True)
class OEmbedPost:
    author_handle: str | None
    text: str
    looks_like_thread: bool


def looks_like_thread(text: str) -> bool:
    return bool(_THREAD_MARKER.search(text))


def _author_in(url: str) -> str | None:
    m = _AUTHOR_IN_URL.search(url)
    return m.group("user") if m else None


def parse_oembed(payload: dict[str, object]) -> OEmbedPost:
    html = payload.get("html")
    soup = BeautifulSoup(html if isinstance(html, str) else "", "html.parser")
    quote = soup.find("blockquote")
    author = None
    text = ""
    if quote is not None:
        permalink = str(quote.get("data-text-post-permalink") or "")
        if not permalink and (a := quote.find("a", href=True)) is not None:
            permalink = str(a.get("href") or "")
        author = _author_in(permalink)
        lines = [ln.strip() for ln in quote.get_text("\n").splitlines()]
        text = "\n".join(ln for ln in lines if ln and not _BOILERPLATE.match(ln))
    if author is None and isinstance(name := payload.get("author_name"), str):
        author = name.lstrip("@") or None
    return OEmbedPost(author, text, looks_like_thread(text))


def parse_page(html: str) -> tuple[str | None, str | None, str | None]:
    soup = BeautifulSoup(html, "html.parser")

    def meta(prop: str) -> str | None:
        tag = soup.find("meta", attrs={"property": prop})
        content = tag.get("content") if tag is not None else None
        return str(content) if content else None

    video = None
    if m := _VIDEO_URL.search(html):
        video = json.loads(f'"{m.group("url")}"')
    return meta("og:description"), meta("og:image"), video


class PageSource(Protocol):
    def get(self, url: str) -> str: ...


# Threads serves a browser User-Agent a page that renders in script, without the post text or the share
# redirect; any other client gets the server-rendered page.
_PAGE_HEADERS = {k: v for k, v in BROWSER_HEADERS.items() if k != "User-Agent"}


class CookiePageSource:
    def __init__(self, cookies: CookieSource) -> None:
        self._cookies = cookies
        self._jar: httpx.Cookies | None = None

    def _load(self) -> httpx.Cookies:
        if self._jar is None:
            jar = httpx.Cookies()
            for c in self._cookies.load():
                if c.domain.lstrip(".").endswith(("threads.com", "threads.net")) and c.value is not None:
                    jar.set(c.name, c.value, domain=c.domain, path=c.path)
            self._jar = jar
        return self._jar

    def get(self, url: str) -> str:
        try:
            resp = httpx.get(url, headers=_PAGE_HEADERS, cookies=self._load(), timeout=20, follow_redirects=True)
            resp.raise_for_status()
        except httpx.HTTPError:
            self._jar = None
            raise
        return resp.text


def _download(url: str, path: Path) -> Path:
    with httpx.stream("GET", url, headers=BROWSER_HEADERS, timeout=60, follow_redirects=True) as resp:
        resp.raise_for_status()
        with path.open("wb") as f:
            for chunk in resp.iter_bytes():
                f.write(chunk)
    return path


class ThreadsFetcher:
    source: ClassVar[Source] = Source.threads

    def __init__(self, pages: PageSource, http: httpx.Client) -> None:
        self._pages = pages
        self._http = http

    def _oembed(self, ref: SourceRef) -> OEmbedPost:
        try:
            resp = self._http.get(OEMBED_URL, params={"url": ref.clean_url})
        except httpx.HTTPError as e:
            raise ProcessingError(
                FailureKind.download_failed, f"Threads oEmbed: {type(e).__name__}", retryable=True
            ) from e
        if resp.status_code in (400, 404):
            raise ProcessingError(
                FailureKind.post_unavailable, "Threads says this post is gone or private.", retryable=False
            )
        if resp.status_code >= 400:
            raise ProcessingError(
                FailureKind.download_failed, f"Threads oEmbed returned {resp.status_code}.", retryable=True
            )
        return parse_oembed(resp.json())

    def resolve_share(self, ref: SourceRef) -> SourceRef:
        try:
            resp = self._http.get(ref.clean_url, timeout=10, follow_redirects=True)
        except httpx.HTTPError as e:
            raise ProcessingError(
                FailureKind.download_failed, f"Could not open the share link: {type(e).__name__}", retryable=True
            ) from e
        return shared_post(Source.threads, str(resp.url))

    def fetch(self, ref: SourceRef, workdir: Path) -> FetchResult:
        workdir.mkdir(parents=True, exist_ok=True)
        post = self._oembed(ref)
        notes: list[str] = []
        text, image_url, video_url = post.text, None, None
        try:
            page_text, image_url, video_url = parse_page(self._pages.get(ref.clean_url))
            text = text or page_text or ""
        except Exception as e:
            log.info("threads page fetch failed for %s: %s", ref.canonical_id, type(e).__name__)
            notes.append("Could not open the post page, so any video was skipped.")

        video_path = None
        if video_url:
            try:
                video_path = _download(video_url, workdir / "media.mp4")
            except httpx.HTTPError as e:
                notes.append(f"Video could not be downloaded ({type(e).__name__}); used the text only.")
        thumbnail = None
        if image_url:
            try:
                thumbnail = _download(image_url, workdir / "thumbnail.jpg")
            except httpx.HTTPError:
                log.info("threads thumbnail download failed")
        if not text and video_path is None:
            raise ProcessingError(
                FailureKind.download_failed, "Threads returned no text for this post.", retryable=True
            )
        if looks_like_thread(text):
            notes.append("Looks like part of a multi-post thread; only this post was read.")

        return FetchResult(
            media_kind=MediaKind.video if video_path else MediaKind.text,
            author_handle=post.author_handle or _author_in(ref.clean_url),
            post_text=text or None,
            video_path=video_path,
            thumbnail_path=thumbnail,
            raw_metadata={"oembed_author": post.author_handle, "had_video": bool(video_url)},
            notes=Notes(tuple(notes)),
        )
