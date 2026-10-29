from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingTCPServer
from typing import TYPE_CHECKING

import httpx
import pytest
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from sift.domain import FailureKind, MediaKind, ProcessingError, Source, SourceRef
from sift.media import MAX_FRAMES, MAX_IMAGES
from sift.sources.base import CookieSource, FetchResult
from sift.sources.instagram import (
    MAX_SLIDES,
    InstagramFetcher,
    author_of,
    best_image,
    dead_post,
    downloaded_video,
    short_error,
    slides_of,
)
from sift.sources.threads import Media, ThreadsFetcher, looks_like_thread, parse_oembed, parse_page

if TYPE_CHECKING:
    from yt_dlp import _Params

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_oembed_fixture() -> None:
    post = parse_oembed(json.loads((FIXTURES / "threads_oembed.json").read_text()))
    assert post.author_handle == "chef.ana"
    assert post.text.startswith("My 3-step weeknight pasta")
    assert "View on Threads" not in post.text
    assert not post.looks_like_thread


def test_parse_oembed_without_blockquote() -> None:
    post = parse_oembed({"html": "<div></div>", "author_name": "@someone"})
    assert post.author_handle == "someone" and post.text == ""


def test_thread_markers() -> None:
    assert looks_like_thread("How we hit $10k MRR (1/5)")
    assert looks_like_thread("A thread 🧵 on pricing")
    assert looks_like_thread("Why pricing pages fail 1/")
    assert not looks_like_thread("Just one post about tacos")
    assert not looks_like_thread("The diner is open 24/7")


def test_parse_page_finds_text_image_and_video() -> None:
    html = (
        '<html><head><meta property="og:description" content="Pasta tips">'
        '<meta property="og:image" content="https://cdn.example/x.jpg"></head><body>'
        '<script type="application/json">{"video_versions":[{"type":101,"url":"https:\\/\\/cdn.example\\/v.mp4"}]}</script>'
        "</body></html>"
    )
    page = parse_page(html, "T1")
    assert (page.text, page.image_url, page.media) == (
        "Pasta tips",
        "https://cdn.example/x.jpg",
        (Media(None, "https://cdn.example/v.mp4"),),
    )
    assert (page.before, page.after) == ((), ())


def test_a_long_carousel_is_capped_with_a_note() -> None:
    entries = [{"id": str(i)} for i in range(MAX_SLIDES + 7)]
    slides, notes = slides_of({"_type": "playlist", "entries": entries})
    assert [s["id"] for s in slides] == [str(i) for i in range(MAX_SLIDES)]
    assert notes == [f"Carousel: read the first {MAX_SLIDES} of {MAX_SLIDES + 7} slides."]
    assert slides_of({"id": "single"}) == ([{"id": "single"}], [])


def test_a_slide_image_is_its_largest_thumbnail() -> None:
    slide = {
        "thumbnails": [{"url": "big", "width": 1080, "height": 1350}, {"url": "small", "width": 320, "height": 400}]
    }
    assert best_image(slide) == "big"
    assert best_image({"thumbnail": "only"}) == "only"


def _image_slide(code: str) -> dict[str, object]:
    return {
        "id": code,
        "formats": [],
        "thumbnails": [{"url": f"https://cdn.example/{code}.jpg", "width": 1080, "height": 1350}],
    }


def _carousel_fetch(
    info: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[FetchResult, list[str], list[object]]:
    import sift.sources.instagram as instagram

    downloads: list[str] = []
    processed: list[object] = []

    class Ydl:
        def __init__(self, params: object) -> None:
            pass

        def __enter__(self) -> Ydl:
            return self

        def __exit__(self, *exc: object) -> None:
            pass

        def extract_info(self, url: str, download: bool, process: bool) -> dict[str, object]:
            assert not process, "processing a carousel runs format selection on its image slides"
            return info

        def sanitize_info(self, info: dict[str, object]) -> dict[str, object]:
            return info

        def process_ie_result(self, entry: dict[str, object], download: bool) -> dict[str, object]:
            assert entry["extractor"] == "Instagram", "processing an entry reads the playlist's extractor"
            processed.append(entry["id"])
            if entry.get("broken"):
                return {}
            video = tmp_path / "media.mp4"
            video.write_bytes(b"v")
            return {"requested_downloads": [{"filepath": str(video)}]}

    def download_image(url: str | None, path: Path) -> Path | None:
        assert url
        downloads.append(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"img")
        return path

    monkeypatch.setattr(instagram, "YoutubeDL", Ydl)
    monkeypatch.setattr(instagram, "_download_image", download_image)
    ref = SourceRef(Source.instagram, "C1", "https://www.instagram.com/p/C1/")
    return InstagramFetcher(CookieSource("chrome", None)).fetch(ref, tmp_path), downloads, processed


def test_an_image_carousel_reads_every_slide(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    info = {"_type": "playlist", "description": "cap", "channel": "jay", "entries": [_image_slide(c) for c in "ABC"]}
    result, downloads, processed = _carousel_fetch(info, tmp_path, monkeypatch)
    assert processed == [], "no slide is a video"
    assert downloads == [f"https://cdn.example/{c}.jpg" for c in "ABC"]
    assert [p.name for p in result.slide_paths] == ["slide_01.jpg", "slide_02.jpg", "slide_03.jpg"]
    assert result.media_kind is MediaKind.image and result.video_path is None
    assert result.thumbnail_path == result.slide_paths[0]
    assert (result.caption, result.author_handle, result.notes.lines) == ("cap", "jay", ())


def test_a_video_that_downloads_nothing_is_read_from_its_cover(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    info = {
        "id": "R1",
        "extractor": "Instagram",
        "broken": True,
        "formats": [{"url": "v"}],
        "thumbnails": [{"url": "https://cdn.example/R1.jpg"}],
    }
    result, downloads, processed = _carousel_fetch(info, tmp_path, monkeypatch)
    assert processed == ["R1"] and downloads == ["https://cdn.example/R1.jpg"]
    assert result.media_kind is MediaKind.image and result.thumbnail_path == result.slide_paths[0]
    assert result.notes.lines == ("The video could not be downloaded.",)


def test_a_mixed_carousel_watches_the_first_video(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = {"id": "V1", "formats": [{"url": "v"}], "thumbnails": [{"url": "https://cdn.example/V1.jpg"}]}
    second = {"id": "V2", "formats": [{"url": "v"}], "thumbnails": [{"url": "https://cdn.example/V2.jpg"}]}
    info = {
        "_type": "playlist",
        "extractor": "Instagram",
        "description": "cap",
        "entries": [_image_slide("A"), video, second],
    }
    result, downloads, processed = _carousel_fetch(info, tmp_path, monkeypatch)
    assert processed == ["V1"]
    assert downloads == ["https://cdn.example/A.jpg", "https://cdn.example/V2.jpg"]
    assert result.media_kind is MediaKind.video and result.video_path == tmp_path / "media.mp4"
    assert result.thumbnail_path == result.slide_paths[0], "the first slide is the cover"
    assert result.notes.lines == (
        "Carousel: only the first video was watched; the others were read from their cover image.",
    )


def test_instagram_video_is_the_downloaded_non_image_file(tmp_path: Path) -> None:
    video = tmp_path / "media.mp4"
    video.write_bytes(b"v")
    thumb = tmp_path / "media.jpg"
    thumb.write_bytes(b"t")
    assert downloaded_video({"requested_downloads": [{"filepath": str(video)}]}) == video
    assert downloaded_video({"requested_downloads": [{"filepath": str(thumb)}]}) is None
    assert downloaded_video({}) is None


def test_instagram_author_prefers_handle_over_numeric_id() -> None:
    assert author_of({"uploader_id": "12345", "channel": "tacofan"}) == "tacofan"
    assert author_of({"uploader_id": "12345"}) is None


def test_short_error_strips_prefix() -> None:
    assert short_error(Exception("ERROR: [Instagram] ABC: login required\nmore")) == "[Instagram] ABC: login required"


def test_arc_is_a_supported_cookie_browser(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="arc cookies database"):
        CookieSource("arc", str(tmp_path)).load()


def test_keychain_is_asked_once_per_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    from yt_dlp import cookies as ytdlp_cookies
    from yt_dlp.utils import Popen

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: object) -> tuple[bytes, None, int]:
        calls.append(cmd)
        return b"secret\n", None, 0

    monkeypatch.setattr(Popen, "run", fake_run)
    get_password = getattr(ytdlp_cookies, "_get_mac_keyring_password")  # noqa: B009
    keyring = f"SiftTest-{uuid.uuid4().hex}"
    assert get_password(keyring, ytdlp_cookies.YDLLogger()) == b"secret"
    assert get_password(keyring, ytdlp_cookies.YDLLogger()) == b"secret"
    assert len(calls) == 1


def test_keychain_cache_is_installed_when_yt_dlp_knows_arc(monkeypatch: pytest.MonkeyPatch) -> None:
    from yt_dlp import cookies as ytdlp_cookies

    from sift.sources import base

    asked: list[str] = []

    def ask(keyring_name: str, logger: object) -> bytes:
        asked.append(keyring_name)
        return b"secret"

    monkeypatch.setattr(ytdlp_cookies, "CHROMIUM_BASED_BROWSERS", ytdlp_cookies.CHROMIUM_BASED_BROWSERS | {"arc"})
    monkeypatch.setattr(ytdlp_cookies, "_get_mac_keyring_password", ask)
    base._patch_ytdlp_cookies()  # pyright: ignore[reportPrivateUsage]
    installed = getattr(ytdlp_cookies, "_get_mac_keyring_password")  # noqa: B009
    base._patch_ytdlp_cookies()  # pyright: ignore[reportPrivateUsage]
    assert getattr(ytdlp_cookies, "_get_mac_keyring_password") is installed  # noqa: B009
    assert installed("Arc", None) == installed("Arc", None) == b"secret"
    assert asked == ["Arc"]


def test_arc_patch_stands_down_when_yt_dlp_renames_its_settings_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    from yt_dlp import cookies as ytdlp_cookies

    from sift.sources import base

    monkeypatch.setattr(ytdlp_cookies, "CHROMIUM_BASED_BROWSERS", ytdlp_cookies.CHROMIUM_BASED_BROWSERS - {"arc"})
    monkeypatch.setattr(ytdlp_cookies, "SUPPORTED_BROWSERS", ytdlp_cookies.SUPPORTED_BROWSERS - {"arc"})
    monkeypatch.delattr(ytdlp_cookies, "_get_chromium_based_browser_settings")
    base._patch_ytdlp_cookies()  # pyright: ignore[reportPrivateUsage]
    assert "arc" not in ytdlp_cookies.SUPPORTED_BROWSERS


def test_keychain_cache_stands_down_when_yt_dlp_renames_its_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    from yt_dlp import cookies as ytdlp_cookies

    from sift.sources import base

    monkeypatch.delattr(ytdlp_cookies, "_get_mac_keyring_password")
    base._patch_ytdlp_cookies()  # pyright: ignore[reportPrivateUsage]
    assert not hasattr(ytdlp_cookies, "_get_mac_keyring_password")


@pytest.mark.parametrize(
    ("message", "status", "dead"),
    [
        ("[Instagram] C1: Video info extraction failed: HTTP Error 404: Not Found", None, True),
        ("[Instagram] C1: Unable to download JSON metadata", 404, True),
        ("[Instagram] C1: Post isn't available", None, True),
        (
            "[Instagram] C1: This content is only available for registered users who follow this account. "
            "Use --cookies-from-browser or --cookies for the authentication.",
            None,
            True,
        ),
        ("[Instagram] C1: Restricted Video: You must be 18 years old or over to see this video", None, False),
        ("[Instagram] C1: Restricted Video: verify your age to watch", None, False),
        ("[generic] C1: This video is not available from your location due to geo restriction", None, False),
        ("[Instagram] C1: This content isn't available in your country", None, False),
        ('[Instagram] C1: Impersonate target "chrome" is not available', None, False),
        ("[Instagram] C1: Unable to read cookies: the profile was deleted or removed", None, False),
        ("[Instagram] C1: The link you followed may be broken, or the page may have been removed.", None, True),
        ("[Instagram] C1: This post has been deleted", None, True),
        ("[Instagram] C1: This account is private", None, True),
        (
            "[Instagram] C1: The webpage request was redirected to the login page. "
            "You have exceeded the rate-limit for accessing posts anonymously",
            None,
            False,
        ),
        ("[Instagram] C1: Instagram sent an empty media response. Check if this post is accessible", None, False),
        ("[Instagram] C1: You need to log in to access this content", None, False),
        ("[Instagram] C1: Requested format is not available", None, False),
        ("HTTP Error 429: Too Many Requests", 429, False),
        ("HTTP Error 503: Service Unavailable", None, False),
        ("[Instagram] C1: Unable to download webpage: HTTP Error 503: Service Unavailable", 503, False),
        ("[Instagram] C1: HTTP Error 502: Bad Gateway. The post may have been removed", None, False),
        ("[Instagram] C1: Unable to download JSON metadata: HTTP Error 403: Forbidden", 403, False),
        ("[Instagram] C1: This post is unavailable", None, True),
        ("<urlopen error timed out>", None, False),
    ],
)
def test_dead_post_classification(message: str, status: int | None, dead: bool) -> None:
    assert dead_post(message, status) is dead


def _fetch_failing_with(error: DownloadError, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProcessingError:
    import sift.sources.instagram as instagram

    class Ydl:
        def __init__(self, params: object) -> None:
            pass

        def __enter__(self) -> Ydl:
            return self

        def __exit__(self, *exc: object) -> None:
            pass

        def extract_info(self, url: str, download: bool, process: bool) -> None:
            raise error

    monkeypatch.setattr(instagram, "YoutubeDL", Ydl)
    fetcher = InstagramFetcher(CookieSource("chrome", None))
    ref = SourceRef(Source.instagram, "C1", "https://www.instagram.com/reel/C1/")
    with pytest.raises(ProcessingError) as caught:
        fetcher.fetch(ref, tmp_path)
    return caught.value


@pytest.mark.parametrize(
    ("message", "kind", "retryable"),
    [
        ("ERROR: [Instagram] C1: Post isn't available", FailureKind.post_unavailable, False),
        ("ERROR: HTTP Error 429: Too Many Requests", FailureKind.download_failed, True),
        (
            "ERROR: [Instagram] C1: Unable to download webpage: HTTP Error 503: Service Unavailable",
            FailureKind.download_failed,
            True,
        ),
    ],
)
def test_instagram_fetch_does_not_retry_a_dead_post(
    message: str, kind: FailureKind, retryable: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    err = _fetch_failing_with(DownloadError(message), tmp_path, monkeypatch)
    assert err.kind is kind and err.retryable is retryable


def test_an_error_whose_cause_chain_loops_is_classified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    error = DownloadError("ERROR: [Instagram] C1: something odd")
    error.__cause__ = error
    err = _fetch_failing_with(error, tmp_path, monkeypatch)
    assert err.kind is FailureKind.download_failed and err.retryable


@pytest.mark.parametrize(
    ("page", "media", "kind", "retryable"),
    [
        (404, 200, FailureKind.post_unavailable, False),
        (200, 404, FailureKind.download_failed, True),
    ],
)
def test_only_a_404_for_the_post_itself_means_the_post_is_gone(
    page: int, media: int, kind: FailureKind, retryable: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sift.sources.instagram as instagram

    requests: list[str] = []

    class Server(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            status = page if len(requests) == 1 else media
            self.send_response(status)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", "4" if status == 200 else "0")
            self.end_headers()
            if status == 200:
                self.wfile.write(b"mp4!")

    class NoBrowserCookies(YoutubeDL):
        def __init__(self, params: _Params) -> None:
            params.pop("cookiesfrombrowser", None)
            super().__init__(params)

    # Not HTTPServer: its bind does a reverse DNS lookup that can stall for half a minute.
    server = ThreadingTCPServer(("127.0.0.1", 0), Server)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(instagram, "YoutubeDL", NoBrowserCookies)
    url = f"http://127.0.0.1:{server.server_address[1]}/reel/C1.mp4"
    try:
        with pytest.raises(ProcessingError) as caught:
            InstagramFetcher(CookieSource("chrome", None)).fetch(SourceRef(Source.instagram, "C1", url), tmp_path)
    finally:
        server.shutdown()
    assert len(requests) == (1 if page == 404 else 2), "the post page, then its media"
    assert caught.value.kind is kind and caught.value.retryable is retryable


def test_threads_404_is_a_dead_post_not_a_retry(tmp_path: Path) -> None:
    http = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(404)))

    class NoPages:
        def get(self, url: str) -> str:
            raise AssertionError("a 404 from oEmbed must not fall back to the page")

    fetcher = ThreadsFetcher(pages=NoPages(), http=http)
    with pytest.raises(ProcessingError) as caught:
        fetcher.fetch(SourceRef(Source.threads, "T1", "https://www.threads.com/t/T1"), tmp_path)
    assert caught.value.kind is FailureKind.post_unavailable and not caught.value.retryable


def test_threads_share_link_resolves_to_its_post() -> None:
    post = "https://www.threads.com/@textura.eu/post/De2UaSjkVVC"

    def handler(request: httpx.Request) -> httpx.Response:
        if "/share/" in request.url.path:
            return httpx.Response(302, headers={"location": f"{post}?xmt=abc&slof=1"})
        return httpx.Response(200, text="<html></html>")

    fetcher = ThreadsFetcher(pages=_NoPages(), http=httpx.Client(transport=httpx.MockTransport(handler)))
    ref = fetcher.resolve_share(SourceRef(Source.threads, "share-BAa", "https://www.threads.com/share/BAa/"))
    assert ref == SourceRef(Source.threads, "De2UaSjkVVC", post)


def test_instagram_share_link_resolves_to_its_post(monkeypatch: pytest.MonkeyPatch) -> None:
    import sift.sources.instagram as instagram

    final = "https://www.instagram.com/reel/C9xyz/?igsh=abc"
    monkeypatch.setattr(
        instagram.httpx, "get", lambda url, **kw: httpx.Response(200, request=httpx.Request("GET", final))
    )
    fetcher = InstagramFetcher(CookieSource("chrome", None))
    ref = fetcher.resolve_share(SourceRef(Source.instagram, "share-Ab", "https://www.instagram.com/share/reel/Ab/"))
    assert ref == SourceRef(Source.instagram, "C9xyz", "https://www.instagram.com/reel/C9xyz/")


def test_threads_share_link_that_does_not_reach_a_post_is_unsupported() -> None:
    http = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, text="login")))
    fetcher = ThreadsFetcher(pages=_NoPages(), http=http)
    with pytest.raises(ProcessingError) as caught:
        fetcher.resolve_share(SourceRef(Source.threads, "share-BAa", "https://www.threads.com/share/BAa/"))
    assert caught.value.kind is FailureKind.unsupported_url and not caught.value.retryable


class _NoPages:
    def get(self, url: str) -> str:
        raise AssertionError("no page fetch after a failed oEmbed")


def _fetch_thread(page: str, tmp_path: Path, *, code: str = "T1", first: str = "Part one, a thread 1/") -> FetchResult:
    oembed = {"html": f"<blockquote><p>{first}</p></blockquote>", "author_name": "@founder"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "graph.threads.net":
            return httpx.Response(200, json=oembed)
        if "/broken." in request.url.path:
            return httpx.Response(500)
        return httpx.Response(200, content=str(request.url).encode())

    http = httpx.Client(transport=httpx.MockTransport(handler))

    class Page:
        def get(self, url: str) -> str:
            return page

    ref = SourceRef(Source.threads, code, f"https://www.threads.com/@founder/post/{code}")
    return ThreadsFetcher(pages=Page(), http=http).fetch(ref, tmp_path)


def _post(text: str | None, user: str = "founder", **extra: object) -> dict[str, object]:
    return {"caption": {"text": text} if text is not None else None, "user": {"username": user}, **extra}


def _photo(name: str) -> dict[str, object]:
    return {"image_versions2": {"candidates": [{"url": f"https://cdn.example/{name}.jpg"}]}}


def _video(name: str) -> dict[str, object]:
    return {**_photo(f"{name}-cover"), "video_versions": [{"url": f"https://cdn.example/{name}.mp4"}]}


def _downloaded(paths: tuple[Path, ...]) -> list[str]:
    return [p.read_text().removeprefix("https://cdn.example/") for p in paths]


def _thread_page(
    after: list[dict[str, object]],
    *,
    before: list[dict[str, object]] | None = None,
    more: bool = False,
    more_before: bool = False,
    main: dict[str, object] | None = None,
) -> str:
    def thread(key: str, nodes: list[dict[str, object]], next_page: bool = False) -> dict[str, object]:
        return {key: {"posts": {"edges": [{"node": n} for n in nodes], "page_info": {"has_next_page": next_page}}}}

    video = {"video_versions": [{"url": "https://cdn.example/other.mp4"}]}
    data = {
        "relatedPosts": {"media": {"id": "5_2", "text_post_app_info": thread("self_thread", [_post("Not this one")])}},
        "media": {"code": "T1", "pk": "7", "user": {"username": "founder"}, "video_versions": [], **(main or {})},
        "thread": {
            "media": {
                "id": "7_9",
                "text_post_app_info": {
                    **thread("containing_thread", before or [], more_before),
                    **thread("self_thread", after, more),
                },
            }
        },
        "later": {"media": {"code": "T3", "pk": "8", **video}},
    }
    payload = json.dumps({"require": [[{"__bbox": {"result": {"data": data}}}]]})
    return f'<html><body><script type="application/json">{payload}</script></body></html>'


THREAD_OPENINGS = ["He spent months emailing", "Reddit and niche Facebook", "The Reddit unlock", "Avneesh breaks down"]


@pytest.mark.parametrize(("fixture", "code", "part"), [("first", "De9xrVOmpY5", 0), ("third", "De9xt7tmod4", 2)])
def test_a_saved_thread_reads_in_order_from_any_of_its_posts(
    fixture: str, code: str, part: int, tmp_path: Path
) -> None:
    page = (FIXTURES / f"threads_thread_{fixture}_post.html").read_text()
    result = _fetch_thread(page, tmp_path, code=code, first=THREAD_OPENINGS[part])
    text = result.post_text or ""
    assert [text.count(o) for o in THREAD_OPENINGS] == [1, 1, 1, 1]
    assert [text.find(o) for o in THREAD_OPENINGS] == sorted(text.find(o) for o in THREAD_OPENINGS)
    assert result.notes.lines == ("Read all 4 posts of this thread.",)
    assert result.media_kind is MediaKind.image
    assert len(result.slide_paths) == 2, "the two photos of the first post"


def test_only_the_posts_own_thread_is_read(tmp_path: Path) -> None:
    result = _fetch_thread(
        _thread_page([{**_post("Part two"), **_photo("p")}, _post(None), _post(" Part four ")]), tmp_path
    )
    assert result.post_text == "Part one, a thread 1/\n\nPart two\n\nPart four"
    assert result.video_path is None, "a video outside the thread is not read"
    assert _downloaded(result.slide_paths) == ["p.jpg"]
    assert result.notes.lines == ("Read all 4 posts of this thread.",)


def test_every_photo_and_video_in_the_thread_is_read(tmp_path: Path) -> None:
    before = [{**_post("Part one"), "carousel_media": [_photo("a"), _video("early")]}]
    page = _thread_page([{**_post("Part three"), **_photo("c")}], before=before, main=_video("own"))
    result = _fetch_thread(page, tmp_path, first="Part two")
    assert result.media_kind is MediaKind.video
    assert result.video_path is not None and result.video_path.read_text().endswith("own.mp4"), (
        "the shared post's video"
    )
    assert _downloaded(result.slide_paths) == ["a.jpg", "early-cover.jpg", "c.jpg"]
    assert result.notes.lines == (
        "Read all 3 posts of this thread.",
        "Watched only one of the 2 videos in this thread.",
    )


@pytest.mark.parametrize(
    ("video", "kind", "slides", "fallback"),
    [
        (_video("broken"), MediaKind.image, ["broken-cover.jpg"], "read its cover image instead"),
        ({"video_versions": [{"url": "https://cdn.example/broken.mp4"}]}, MediaKind.text, [], "used the text only"),
    ],
)
def test_a_video_that_will_not_download_falls_back(
    video: dict[str, object], kind: MediaKind, slides: list[str], fallback: str, tmp_path: Path
) -> None:
    result = _fetch_thread(_thread_page([], main=video), tmp_path, first="Look")
    assert (result.media_kind, result.video_path) == (kind, None)
    assert _downloaded(result.slide_paths) == slides
    assert result.notes.lines == (f"The video could not be downloaded (HTTPStatusError); {fallback}.",)


def test_too_many_images_keep_the_posts_own_and_leave_room_for_the_video(tmp_path: Path) -> None:
    room = MAX_IMAGES - MAX_FRAMES
    before = [{**_post("Part one"), "carousel_media": [_photo(f"b{i}") for i in range(room + 2)]}]
    page = _thread_page([], before=before, main={"carousel_media": [_video("own"), _photo("mine")]})
    result = _fetch_thread(page, tmp_path, first="Part two")
    assert result.video_path is not None
    assert _downloaded(result.slide_paths) == [*(f"b{i}.jpg" for i in range(room - 1)), "mine.jpg"]
    assert result.notes.lines[-1] == f"Read {room} of {room + 3} photos and video covers, this post's own first."


def test_a_photo_post_without_text_is_read_from_its_photos(tmp_path: Path) -> None:
    photos = [_photo(f"p{i}") for i in range(MAX_IMAGES + 2)]
    result = _fetch_thread(
        _thread_page([], main={"carousel_media": [*photos[:2], _photo("broken"), *photos[2:]]}), tmp_path, first=""
    )
    assert (result.media_kind, result.post_text) == (MediaKind.image, None)
    assert len(result.slide_paths) == MAX_IMAGES - 1
    assert result.thumbnail_path == result.slide_paths[0]
    assert result.notes.lines == (
        f"Read {MAX_IMAGES} of {MAX_IMAGES + 3} photos and video covers, this post's own first.",
        f"1 of {MAX_IMAGES} images could not be downloaded.",
    )


def test_a_reply_keeps_only_its_authors_run_of_posts(tmp_path: Path) -> None:
    before = [_post("Someone's question", user="asker"), _post("My answer"), _post("More of my answer")]
    result = _fetch_thread(_thread_page([], before=before), tmp_path, first="Last of my answer")
    assert result.post_text == "My answer\n\nMore of my answer\n\nLast of my answer"
    assert result.notes.lines == (
        "Read all 3 posts of this thread.",
        "Earlier posts by other people in this conversation were not read.",
    )


def test_a_thread_whose_first_post_has_no_text_is_read_from_the_rest(tmp_path: Path) -> None:
    result = _fetch_thread(_thread_page([_post("Part two")], more=True), tmp_path, first="")
    assert result.post_text == "Part two"
    assert result.notes.lines == ("Read 2 posts of this thread; Threads did not send the rest.",)


def test_a_thread_missing_its_start_says_so(tmp_path: Path) -> None:
    result = _fetch_thread(_thread_page([], before=[_post("Part two")], more_before=True), tmp_path, first="Part three")
    assert result.post_text == "Part two\n\nPart three"
    assert result.notes.lines == ("Read 2 posts of this thread; Threads did not send the rest.",)


def test_a_video_slide_in_the_post_is_its_video() -> None:
    slides = [{"video_versions": []}, {"video_versions": [{"url": "https://cdn.example/slide.mp4"}]}]
    payload = json.dumps({"media": {"code": "T1", "pk": "7", "carousel_media": slides, "text_post_app_info": {}}})
    page = parse_page(f'<script type="application/json">{payload}</script>', "T1")
    assert page.media == (Media(None, "https://cdn.example/slide.mp4"),)


def test_a_post_without_follow_ups_keeps_the_partial_thread_note(tmp_path: Path) -> None:
    result = _fetch_thread("<html></html>", tmp_path)
    assert result.post_text == "Part one, a thread 1/"
    assert result.notes.lines == ("Looks like part of a multi-post thread; only this post was read.",)
