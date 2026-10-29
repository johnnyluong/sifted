from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import takewhile
from pathlib import Path
from typing import Any, ClassVar, Protocol, cast

import httpx
from bs4 import BeautifulSoup

from sift.domain import FailureKind, MediaKind, Notes, ProcessingError, Source, SourceRef
from sift.media import MAX_FRAMES, MAX_IMAGES
from sift.sources.base import BROWSER_HEADERS, CookieSource, FetchResult
from sift.sources.urls import shared_post

log = logging.getLogger(__name__)

OEMBED_URL = "https://graph.threads.net/v1.0/oembed"
_BOILERPLATE = re.compile(r"^(view on threads|post by @[\w.]+|threads)$", re.I)
_AUTHOR_IN_URL = re.compile(r"threads\.(?:com|net)/@(?P<user>[\w.]+)/")
_THREAD_MARKER = re.compile(r"(\(\d+\s*/\s*\d*\)|(?:^|\s)1/\s*$|🧵|\(cont)", re.I)
_DOWNLOAD_ERRORS = (httpx.HTTPError, httpx.InvalidURL)
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


@dataclass(frozen=True, slots=True)
class Media:
    image_url: str | None
    video_url: str | None


@dataclass(frozen=True, slots=True)
class ThreadPost:
    text: str
    media: tuple[Media, ...]


@dataclass(frozen=True, slots=True)
class PostPage:
    text: str | None
    image_url: str | None
    media: tuple[Media, ...]
    before: tuple[ThreadPost, ...] = ()
    after: tuple[ThreadPost, ...] = ()
    cut_off: bool = False
    skipped_others: bool = False


def _obj(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _media_nodes(node: object) -> Iterator[dict[str, Any]]:
    if isinstance(node, list):
        for child in cast(list[object], node):
            yield from _media_nodes(child)
    elif isinstance(node, dict):
        for key, child in cast(dict[str, object], node).items():
            if key == "media" and isinstance(child, dict):
                yield cast(dict[str, Any], child)
            yield from _media_nodes(child)


def _thread(info: dict[str, Any], key: str) -> tuple[list[dict[str, Any]], bool]:
    posts = _obj(_obj(info.get(key)).get("posts"))
    edges = posts.get("edges")
    nodes = [_obj(_obj(edge).get("node")) for edge in (edges if isinstance(edges, list) else [])]
    return [n for n in nodes if n], bool(_obj(posts.get("page_info")).get("has_next_page"))


def _first_url(versions: object) -> str | None:
    if isinstance(versions, list) and versions and isinstance(url := _obj(versions[0]).get("url"), str):
        return url
    return None


def _media(post: dict[str, Any]) -> tuple[Media, ...]:
    slides = post.get("carousel_media")
    nodes = [_obj(s) for s in slides] if isinstance(slides, list) and slides else [post]
    found = (
        Media(_first_url(_obj(n.get("image_versions2")).get("candidates")), _first_url(n.get("video_versions")))
        for n in nodes
    )
    return tuple(m for m in found if m.image_url or m.video_url)


def _thread_post(node: dict[str, Any]) -> ThreadPost:
    text = _obj(node.get("caption")).get("text")
    return ThreadPost(text.strip() if isinstance(text, str) else "", _media(node))


def _username(node: dict[str, Any]) -> object:
    return _obj(node.get("user")).get("username")


def parse_page(html: str, code: str) -> PostPage:
    soup = BeautifulSoup(html, "html.parser")

    def meta(prop: str) -> str | None:
        tag = soup.find("meta", attrs={"property": prop})
        content = tag.get("content") if tag is not None else None
        return str(content) if content else None

    nodes: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": "application/json"}):
        body = script.string or ""
        if '"text_post_app_info"' in body:
            try:
                nodes.extend(_media_nodes(json.loads(body)))
            except json.JSONDecodeError:
                continue
    mains = [n for n in nodes if n.get("code") == code]
    if not mains or (pk := mains[0].get("pk")) is None:
        m = _VIDEO_URL.search(html)
        video = (Media(None, json.loads(f'"{m.group("url")}"')),) if m else ()
        return PostPage(meta("og:description"), meta("og:image"), video)

    before: list[dict[str, Any]] = []
    after: list[dict[str, Any]] = []
    cut_off = False
    # The thread around the post hangs off a separate node keyed by the post's pk.
    for n in nodes:
        if str(n.get("id", "")).startswith(f"{pk}_"):
            info = _obj(n.get("text_post_app_info"))
            earlier, more_earlier = _thread(info, "containing_thread")
            later, more_later = _thread(info, "self_thread")
            before, after, cut_off = before or earlier, after or later, cut_off or more_earlier or more_later
    author = _username(mains[0])
    own = list(takewhile(lambda n: author is not None and _username(n) == author, reversed(before)))[::-1]
    return PostPage(
        meta("og:description"),
        meta("og:image"),
        next((m for n in mains if (m := _media(n))), ()),
        before=tuple(_thread_post(n) for n in own),
        after=tuple(_thread_post(n) for n in after),
        cut_off=cut_off,
        skipped_others=author is not None and len(own) < len(before),
    )


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


def _download(http: httpx.Client, url: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with http.stream("GET", url, headers=BROWSER_HEADERS, timeout=60, follow_redirects=True) as resp:
            resp.raise_for_status()
            with path.open("wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
    except _DOWNLOAD_ERRORS:
        path.unlink(missing_ok=True)
        raise
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

    def _image(self, url: str, path: Path) -> Path | None:
        try:
            return _download(self._http, url, path)
        except _DOWNLOAD_ERRORS:
            log.info("threads image download failed")
            return None

    def fetch(self, ref: SourceRef, workdir: Path) -> FetchResult:
        workdir.mkdir(parents=True, exist_ok=True)
        post = self._oembed(ref)
        notes: list[str] = []
        page = None
        try:
            page = parse_page(self._pages.get(ref.clean_url), ref.canonical_id)
        except Exception as e:
            log.info("threads page fetch failed for %s: %s", ref.canonical_id, type(e).__name__)
            notes.append("Could not open the post page, so its photos and videos were skipped.")
        main = ThreadPost(post.text or (page.text if page else None) or "", page.media if page else ())
        before, after = (page.before, page.after) if page else ((), ())
        thread = (*before, main, *after)
        text = "\n\n".join(p.text for p in thread if p.text)
        if page is not None and (before or after):
            if page.cut_off:
                notes.append(f"Read {len(thread)} posts of this thread; Threads did not send the rest.")
            else:
                notes.append(f"Read all {len(thread)} posts of this thread.")
            if page.skipped_others:
                notes.append("Earlier posts by other people in this conversation were not read.")
        elif looks_like_thread(text):
            notes.append("Looks like part of a multi-post thread; only this post was read.")

        media = [m for p in thread for m in p.media]
        videos = [m for m in media if m.video_url]
        watched = next((m for m in main.media if m.video_url), None) or next(iter(videos), None)
        video_path = None
        if watched is not None and watched.video_url:
            try:
                video_path = _download(self._http, watched.video_url, workdir / "media.mp4")
            except _DOWNLOAD_ERRORS as e:
                instead = "read its cover image instead" if watched.image_url else "used the text only"
                notes.append(f"The video could not be downloaded ({type(e).__name__}); {instead}.")
                watched = None
        if video_path is not None and len(videos) > 1:
            notes.append(f"Watched only one of the {len(videos)} videos in this thread.")
        images = [(p is main, m.image_url) for p in thread for m in p.media if m is not watched and m.image_url]
        room = MAX_IMAGES - (MAX_FRAMES if video_path else 0)
        if len(images) > room:
            notes.append(f"Read {room} of {len(images)} photos and video covers, this post's own first.")
            kept = sorted(sorted(range(len(images)), key=lambda i: not images[i][0])[:room])
            images = [images[i] for i in kept]
        slide_paths = [
            p
            for i, (_, url) in enumerate(images, 1)
            if (p := self._image(url, workdir / "slides" / f"slide_{i:02d}.jpg"))
        ]
        if missing := len(images) - len(slide_paths):
            notes.append(f"{missing} of {len(images)} images could not be downloaded.")
        og_image = page.image_url if page else None
        thumbnail = (og_image and self._image(og_image, workdir / "thumbnail.jpg")) or next(iter(slide_paths), None)
        if not text and video_path is None and not slide_paths:
            raise ProcessingError(
                FailureKind.download_failed, "Threads returned no text for this post.", retryable=True
            )

        kind = MediaKind.video if video_path else MediaKind.image if slide_paths else MediaKind.text
        return FetchResult(
            media_kind=kind,
            author_handle=post.author_handle or _author_in(ref.clean_url),
            post_text=text or None,
            video_path=video_path,
            thumbnail_path=thumbnail,
            slide_paths=tuple(slide_paths),
            raw_metadata={"oembed_author": post.author_handle, "had_video": bool(videos)},
            notes=Notes(tuple(notes)),
        )
