from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sift import db, runtime
from sift.config import Settings
from sift.sources.base import CookieSource
from sift.web import spa


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool | None
    detail: str


def _binary(name: str) -> Check:
    path = shutil.which(name)
    return Check(name, path is not None, path or "not found: brew install ffmpeg")


def _ytdlp() -> Check:
    from yt_dlp.version import __version__

    return Check("yt-dlp", True, f"{__version__} (update with: uv run sift update-tools)")


def _whisper(settings: Settings) -> Check:
    try:
        import mlx_whisper  # noqa: F401
        from huggingface_hub import snapshot_download
    except ImportError as e:
        return Check("mlx-whisper", False, f"not importable: {e}")
    try:
        snapshot_download(settings.whisper_model, local_files_only=True)
    except Exception:
        return Check(
            "mlx-whisper", None, f"{settings.whisper_model} not downloaded yet; the first transcription fetches it"
        )
    return Check("mlx-whisper", True, f"{settings.whisper_model} cached")


def _cookies(settings: Settings) -> Check:
    label = settings.cookies_browser + (
        f" ({settings.cookies_browser_profile})" if settings.cookies_browser_profile else ""
    )
    try:
        jar = CookieSource(settings.cookies_browser, settings.cookies_browser_profile).load()
    except Exception as e:
        return Check("browser cookies", False, f"{label}: {type(e).__name__}: {str(e)[:120]}")
    domains = {c.domain.lstrip(".") for c in jar}
    ig = any(d.endswith("instagram.com") for d in domains)
    has_session = any(c.name == "sessionid" and c.domain.lstrip(".").endswith("instagram.com") for c in jar)
    threads = any(d.endswith(("threads.com", "threads.net")) for d in domains)
    if not ig or not has_session:
        return Check(
            "browser cookies", False, f"{label}: no logged-in Instagram session; log in with the secondary account"
        )
    return Check(
        "browser cookies",
        True,
        f"{label}: Instagram session found; Threads cookies {'found' if threads else 'missing'}",
    )


def _anthropic(settings: Settings) -> Check:
    if settings.llm_backend == "fake":
        return Check("anthropic", None, "LLM_BACKEND=fake: using the keyword-rule stand-in")
    if settings.anthropic_api_key is None:
        return Check("anthropic", None, "ANTHROPIC_API_KEY not set: items wait after transcription")
    import anthropic

    models = list(
        dict.fromkeys(
            (
                settings.extract_model,
                settings.effective_score_model,
                settings.digest_model,
                settings.outline_model,
                settings.brief_model,
            )
        )
    )
    model = models[0]
    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value(), max_retries=0, timeout=15)
        for model in models:
            client.models.retrieve(model)
    except anthropic.AuthenticationError:
        return Check("anthropic", False, "API key rejected")
    except anthropic.NotFoundError:
        return Check("anthropic", False, f"model {model!r} not found")
    except anthropic.APIError as e:
        return Check("anthropic", None, f"could not verify: {type(e).__name__}")
    return Check("anthropic", True, f"key valid, {', '.join(models)} available")


def _telegram(settings: Settings) -> Check:
    if settings.telegram_bot_token is None:
        return Check("telegram", None, "not configured (the bot is not built yet; use the web paste box)")
    return Check("telegram", None, "token set, but the bot is not built yet")


def _database(settings: Settings) -> Check:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db.configure(settings.db_url)
    current, head = runtime.revisions(settings)
    if current == head:
        return Check("database", True, f"{settings.db_path} at {head}")
    return Check("database", None, f"{settings.db_path} at {current or 'empty'}, head {head}: `sift run` migrates it")


def web_build(dist: Path = spa.DIST, src: Path = spa.DIST.parent / "src") -> Check:
    index = dist / "index.html"
    if not index.is_file():
        return Check("web UI", False, f"not built: {spa.BUILD}")
    newest = max((f.stat().st_mtime for f in src.rglob("*") if f.is_file()), default=0.0)
    if newest > index.stat().st_mtime:
        return Check("web UI", None, "web/src changed since the last build: bun run --cwd web build")
    return Check("web UI", True, f"built at {dist}")


def run_checks(settings: Settings, *, cookies: bool = True) -> list[Check]:
    checks: list[tuple[str, Callable[[], Check]]] = [
        ("ffmpeg", lambda: _binary("ffmpeg")),
        ("ffprobe", lambda: _binary("ffprobe")),
        ("yt-dlp", _ytdlp),
        ("browser cookies", lambda: _cookies(settings)),
        ("mlx-whisper", lambda: _whisper(settings)),
        ("anthropic", lambda: _anthropic(settings)),
        ("telegram", lambda: _telegram(settings)),
        ("database", lambda: _database(settings)),
        ("web UI", web_build),
    ]
    out: list[Check] = []
    for name, check in checks:
        if name == "browser cookies" and not cookies:
            out.append(Check(name, None, "skipped (--no-cookies)"))
            continue
        try:
            out.append(check())
        except Exception as e:
            out.append(Check(name, False, f"{type(e).__name__}: {e}"))
    return out
