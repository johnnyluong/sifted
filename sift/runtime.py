from __future__ import annotations

import asyncio
import fcntl
import logging
import logging.handlers
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO

import anthropic
import httpx
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from alembic import command
from sift import db, digest
from sift.config import Settings
from sift.domain import Source
from sift.inbox.imports import Pace
from sift.inbox.notify import LogNotifier, Notifier
from sift.items import store
from sift.llm.client import LLM, AnthropicLLM
from sift.llm.fake import FakeLLM
from sift.media import MlxWhisperTranscriber, Transcriber
from sift.pipeline import Pacer, PipelineDeps
from sift.sources import Fetchers
from sift.sources.base import CookieSource
from sift.sources.instagram import InstagramFetcher
from sift.sources.threads import CookiePageSource, ThreadsFetcher
from sift.worker import Worker

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
THREADS_DELAY_S = 2.0


class AlreadyRunning(Exception):
    pass


class _RedactingFormatter(logging.Formatter):
    def __init__(self, fmt: str, secrets: list[str]) -> None:
        super().__init__(fmt)
        self._secrets = [s for s in secrets if len(s) >= 6]

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for s in self._secrets:
            text = text.replace(s, "[redacted]")
        return text


def setup_logging(settings: Settings, *, console: bool = True) -> None:
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = _RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s", settings.secrets())
    file_handler = logging.handlers.RotatingFileHandler(
        settings.logs_dir / "sift.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    handlers: list[logging.Handler] = [file_handler]
    if console:
        handlers.append(logging.StreamHandler())
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)
    for noisy in ("httpx", "httpcore", "anthropic", "apscheduler.executors.default"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def build_llm(settings: Settings) -> LLM | None:
    if settings.llm_backend == "fake":
        return FakeLLM()
    if settings.anthropic_api_key is None:
        return None
    return AnthropicLLM(
        anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value(), max_retries=2, timeout=180.0),
        extract_model=settings.extract_model,
        score_model=settings.effective_score_model,
        digest_model=settings.digest_model,
        outline_model=settings.outline_model,
        brief_model=settings.brief_model,
        effort=settings.llm_effort,
    )


@dataclass(frozen=True, slots=True)
class Overrides:
    fetchers: Fetchers | None = None
    transcriber: Transcriber | None = None
    llm: LLM | None = None
    use_llm_override: bool = False
    notifier: Notifier | None = None
    clock: Callable[[], datetime] | None = None


@dataclass(frozen=True, slots=True)
class Runtime:
    settings: Settings
    llm: LLM | None
    notifier: Notifier
    worker: Worker
    clock: Callable[[], datetime]
    pace: Pace

    @property
    def llm_ready(self) -> bool:
        return self.llm is not None


def build_runtime(settings: Settings, overrides: Overrides | None = None) -> Runtime:
    o = overrides or Overrides()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db.configure(settings.db_url)
    clock = o.clock or db.utcnow
    cookies = CookieSource(settings.cookies_browser, settings.cookies_browser_profile)
    fetchers = o.fetchers or Fetchers(
        instagram=InstagramFetcher(cookies),
        threads=ThreadsFetcher(CookiePageSource(cookies), httpx.Client(timeout=20)),
    )
    llm = o.llm if o.use_llm_override else build_llm(settings)
    notifier = o.notifier or LogNotifier()
    pacer = Pacer({Source.instagram: settings.fetch_delay_seconds, Source.threads: THREADS_DELAY_S}, clock)
    deps = PipelineDeps(
        fetchers=fetchers,
        transcriber=o.transcriber or MlxWhisperTranscriber(settings.whisper_model),
        llm=llm,
        pacer=pacer,
        data_dir=settings.data_dir.resolve(),
        keep_media=settings.keep_media,
        threshold=settings.keep_threshold,
        clock=clock,
    )
    pace = Pace.from_settings(settings)
    return Runtime(
        settings=settings, llm=llm, notifier=notifier, worker=Worker(deps, notifier, pace), clock=clock, pace=pace
    )


def alembic_config(settings: Settings) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.db_url)
    cfg.attributes["skip_logging"] = True
    return cfg


def revisions(settings: Settings) -> tuple[str | None, str | None]:
    head = ScriptDirectory.from_config(alembic_config(settings)).get_current_head()
    with db.engine().connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    return current, head


def migrate(settings: Settings) -> None:
    command.upgrade(alembic_config(settings), "head")


class _RunLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._fh: IO[str] | None = None

    def try_acquire(self) -> bool:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fh = self._path.open("w")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fh.close()
            return False
        self._fh = fh
        return True

    def release(self) -> None:
        if self._fh is not None:
            fcntl.flock(self._fh, fcntl.LOCK_UN)
            self._fh.close()
            self._fh = None


def worker_running(settings: Settings) -> bool:
    lock = _RunLock(settings.run_lock_path)
    if lock.try_acquire():
        lock.release()
        return False
    return True


@contextmanager
def worker_role(rt: Runtime) -> Iterator[bool]:
    lock = _RunLock(rt.settings.run_lock_path)
    if not lock.try_acquire():
        yield False
        return
    try:
        migrate(rt.settings)
        requeued, failed = store.reset_stuck(rt.clock())
        if requeued or failed:
            log.info("startup: requeued %d interrupted item(s), failed %d", requeued, failed)
        yield True
    finally:
        lock.release()


def _start_scheduler(rt: Runtime) -> tuple[AsyncIOScheduler, asyncio.Task[None] | None]:
    s = rt.settings
    scheduler = AsyncIOScheduler(timezone=s.timezone)

    async def job() -> None:
        try:
            await digest.deliver_digest(rt.clock(), rt.llm, rt.notifier)
        except Exception:
            log.exception("scheduled digest failed")

    scheduler.add_job(
        job,
        CronTrigger.from_crontab(s.digest_cron, timezone=s.timezone),
        coalesce=True,
        max_instances=1,
        misfire_grace_time=6 * 3600,
    )
    scheduler.start()
    if digest.due_on_startup(digest.latest_created_at(), s.digest_cron, s.timezone, rt.clock()):
        return scheduler, asyncio.get_running_loop().create_task(job())
    return scheduler, None


@asynccontextmanager
async def lifespan(rt: Runtime) -> AsyncIterator[None]:
    with worker_role(rt) as is_worker:
        if not is_worker:
            raise AlreadyRunning(f"another Sift process holds {rt.settings.run_lock_path}")
        stop = asyncio.Event()
        scheduler, catch_up = _start_scheduler(rt)
        task = asyncio.create_task(rt.worker.run(stop))
        try:
            yield
        finally:
            stop.set()
            scheduler.shutdown(wait=False)
            # A running stage cannot be interrupted; a second Ctrl+C force-quits, and the
            # next startup requeues the item.
            log.info("finishing the current item before shutting down")
            try:
                await task
            finally:
                await rt.worker.shutdown()
                if catch_up is not None:
                    await catch_up
