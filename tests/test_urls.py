import pytest

from sift.domain import Source
from sift.sources.urls import Unsupported, UnsupportedKind, find_urls, parse_url


@pytest.mark.parametrize(
    ("url", "source", "code", "clean"),
    [
        (
            "https://www.instagram.com/reel/DQx7abc_1/?igsh=MTZ4cm",
            Source.instagram,
            "DQx7abc_1",
            "https://www.instagram.com/reel/DQx7abc_1/",
        ),
        (
            "https://instagram.com/reels/DQx7abc_1",
            Source.instagram,
            "DQx7abc_1",
            "https://www.instagram.com/reel/DQx7abc_1/",
        ),
        (
            "https://www.instagram.com/someuser/reel/DQx7abc_1/",
            Source.instagram,
            "DQx7abc_1",
            "https://www.instagram.com/reel/DQx7abc_1/",
        ),
        (
            "https://www.instagram.com/p/C9-xyz/?utm_source=ig_web_copy_link",
            Source.instagram,
            "C9-xyz",
            "https://www.instagram.com/p/C9-xyz/",
        ),
        (
            "https://www.threads.com/@chef.ana/post/DA1b2C3?xmt=AQG",
            Source.threads,
            "DA1b2C3",
            "https://www.threads.com/@chef.ana/post/DA1b2C3",
        ),
        (
            "https://www.threads.net/@chef.ana/post/DA1b2C3",
            Source.threads,
            "DA1b2C3",
            "https://www.threads.com/@chef.ana/post/DA1b2C3",
        ),
        ("https://threads.net/t/DA1b2C3/", Source.threads, "DA1b2C3", "https://www.threads.com/t/DA1b2C3"),
    ],
)
def test_parse_supported(url: str, source: Source, code: str, clean: str) -> None:
    ref = parse_url(url)
    assert not isinstance(ref, Unsupported)
    assert (ref.source, ref.canonical_id, ref.clean_url) == (source, code, clean)


def test_tracking_params_do_not_change_the_dedup_key() -> None:
    a = parse_url("https://www.instagram.com/reel/ABC123/?igsh=one")
    b = parse_url("https://www.instagram.com/reel/ABC123/?igsh=two&utm_medium=share")
    c = parse_url("https://www.instagram.com/p/ABC123/")
    assert not isinstance(a, Unsupported) and not isinstance(b, Unsupported) and not isinstance(c, Unsupported)
    assert (a.source, a.canonical_id) == (b.source, b.canonical_id) == (c.source, c.canonical_id)


def test_share_links_are_kept_for_the_fetcher_to_resolve() -> None:
    ref = parse_url("https://www.instagram.com/share/reel/BAabc123XYZ/?igsh=x")
    assert not isinstance(ref, Unsupported)
    assert ref.canonical_id == "share-BAabc123XYZ"
    assert ref.clean_url == "https://www.instagram.com/share/reel/BAabc123XYZ/"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/someuser/",
        "https://www.threads.com/@chef.ana",
        "https://www.tiktok.com/@x/video/1",
        "https://example.com",
    ],
)
def test_parse_unsupported(url: str) -> None:
    assert isinstance(parse_url(url), Unsupported)


@pytest.mark.parametrize(
    ("url", "kind"),
    [
        ("https://www.instagram.com/someuser/", UnsupportedKind.meta_page),
        ("https://www.threads.com/@chef.ana", UnsupportedKind.meta_page),
        ("https://www.instagram.com/", UnsupportedKind.meta_page),
        ("https://www.instagram.com/stories/chef/3456/", UnsupportedKind.meta_other),
        ("https://www.threads.com/@chef/reposts/1", UnsupportedKind.meta_other),
        ("https://www.tiktok.com/@x/video/1", UnsupportedKind.not_meta),
        ("https://example.com/a/b/c", UnsupportedKind.not_meta),
    ],
)
def test_an_unsupported_link_says_whether_it_is_a_meta_page(url: str, kind: UnsupportedKind) -> None:
    result = parse_url(url)
    assert isinstance(result, Unsupported) and result.kind is kind


def test_find_urls_trims_punctuation_and_dedups() -> None:
    text = "look (https://www.instagram.com/reel/AAA/), also https://www.instagram.com/reel/AAA/ and https://threads.net/t/BBB."
    assert find_urls(text) == ["https://www.instagram.com/reel/AAA/", "https://threads.net/t/BBB"]


def test_find_urls_none() -> None:
    assert find_urls("no links here") == []


def test_threads_share_links_are_kept_for_the_fetcher_to_resolve() -> None:
    ref = parse_url("https://www.threads.com/share/BAagF0Zg5_/")
    assert not isinstance(ref, Unsupported)
    assert ref.source is Source.threads
    assert ref.canonical_id == "share-BAagF0Zg5_"
    assert ref.clean_url == "https://www.threads.com/share/BAagF0Zg5_/"
