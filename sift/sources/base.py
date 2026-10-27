from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Protocol

from yt_dlp import cookies as ytdlp_cookies
from yt_dlp.cookies import YoutubeDLCookieJar

from sift.domain import MediaKind, Notes, Source, SourceRef

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/141.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass(frozen=True, slots=True)
class CookieSource:
    browser: str
    profile: str | None

    def as_ytdlp_option(self) -> tuple[str, ...]:
        return (self.browser, self.profile) if self.profile else (self.browser,)

    def load(self) -> YoutubeDLCookieJar:
        return ytdlp_cookies.extract_cookies_from_browser(self.browser, self.profile)


_SETTINGS_HOOK = "_get_chromium_based_browser_settings"
_KEYCHAIN_HOOK = "_get_mac_keyring_password"


class _CachedKeychain:
    """yt-dlp asks the Keychain on every download, and each ask can prompt for the login password."""

    def __init__(self, ask: Callable[[str, Any], bytes | None]) -> None:
        self._ask = ask
        self._passwords: dict[str, bytes] = {}

    def __call__(self, keyring_name: str, logger: Any) -> bytes | None:
        if keyring_name in self._passwords:
            return self._passwords[keyring_name]
        password = self._ask(keyring_name, logger)
        if password is not None:
            self._passwords[keyring_name] = password
        return password


def _patch_ytdlp_cookies() -> None:
    keychain_password: Callable[[str, Any], bytes | None] | None = getattr(ytdlp_cookies, _KEYCHAIN_HOOK, None)
    if keychain_password is not None and not isinstance(keychain_password, _CachedKeychain):
        setattr(ytdlp_cookies, _KEYCHAIN_HOOK, _CachedKeychain(keychain_password))
    chromium_settings: Callable[[str], dict[str, Any]] | None = getattr(ytdlp_cookies, _SETTINGS_HOOK, None)
    if "arc" in ytdlp_cookies.CHROMIUM_BASED_BROWSERS or chromium_settings is None:
        return

    # yt-dlp has no Arc entry; Arc is Chromium with its own data dir and keychain item.
    def browser_settings(browser_name: str) -> dict[str, Any]:
        if browser_name != "arc":
            return chromium_settings(browser_name)
        return {
            "browser_dir": str(Path.home() / "Library/Application Support/Arc/User Data"),
            "keyring_name": "Arc",
            "supports_profiles": True,
        }

    setattr(ytdlp_cookies, _SETTINGS_HOOK, browser_settings)
    ytdlp_cookies.CHROMIUM_BASED_BROWSERS.add("arc")
    ytdlp_cookies.SUPPORTED_BROWSERS.add("arc")


_patch_ytdlp_cookies()


@dataclass(frozen=True, slots=True)
class FetchResult:
    media_kind: MediaKind
    author_handle: str | None
    caption: str | None = None
    post_text: str | None = None
    video_path: Path | None = None
    thumbnail_path: Path | None = None
    slide_paths: tuple[Path, ...] = ()
    raw_metadata: dict[str, Any] = field(default_factory=dict[str, Any])
    notes: Notes = field(default_factory=Notes)


class Fetcher(Protocol):
    source: ClassVar[Source]

    def resolve_share(self, ref: SourceRef) -> SourceRef: ...

    def fetch(self, ref: SourceRef, workdir: Path) -> FetchResult: ...
