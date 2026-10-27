from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sift import goals, pipeline
from sift.domain import QUIET_CHANNELS
from sift.inbox import imports
from sift.inbox.imports import Pace
from sift.inbox.notify import Notifier
from sift.items import store
from sift.items.store import Claim
from sift.items.views import ItemOutcome
from sift.organize.organizer import Organizer
from sift.pipeline import PipelineDeps

log = logging.getLogger(__name__)

POLL_S = 1.5


class Worker:
    def __init__(self, deps: PipelineDeps, notifier: Notifier, pace: Pace) -> None:
        self._deps = deps
        self._notifier = notifier
        self._pace = pace
        # MLX streams are per-thread and mlx-whisper caches its model, so transcription stays on one thread.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sift-pipeline")
        self._wake = asyncio.Event()
        self._organizer = Organizer(deps.clock)

    @property
    def deps(self) -> PipelineDeps:
        return self._deps

    async def _in_thread[T](self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, lambda: fn(*args, **kwargs))

    def _claim(self, only: int | None) -> Claim | None:
        now = self._deps.clock()
        return store.claim_next(
            now,
            fetch_blocked=self._deps.pacer.blocked(now),
            llm_ready=self._deps.llm is not None,
            goals_ready=goals.has_active_goals(),
            only=only,
        )

    def _release(self) -> None:
        try:
            imports.release_next(self._deps.clock(), self._pace, llm_ready=self._deps.llm is not None)
        except Exception:
            log.exception("import drip failed")

    def _organize(self) -> bool:
        return self._organizer.step(self._deps.llm, import_running=imports.running())

    def wake(self) -> None:
        """Event loop only: asyncio.Event is not thread-safe."""
        self._wake.set()

    async def step(self, only: int | None = None) -> tuple[bool, ItemOutcome | None]:
        if only is None:
            await self._in_thread(self._release)
        claim = await self._in_thread(self._claim, only)
        if claim is None:
            if only is not None:
                return False, None
            return await self._in_thread(self._organize), None
        outcome = await self._in_thread(pipeline.run, claim, self._deps)
        if outcome is not None and outcome.origin_channel not in QUIET_CHANNELS:
            try:
                await self._notifier.item_finished(outcome)
            except Exception:
                log.exception("notifier failed for item %s", claim.item_id)
        return True, outcome

    async def run(self, stop: asyncio.Event) -> None:
        log.info("worker started")
        while not stop.is_set():
            try:
                self._wake.clear()
                claimed, _ = await self.step()
            except Exception:
                log.exception("worker step failed")
                claimed = False
            if claimed:
                continue
            waiters = [asyncio.create_task(stop.wait()), asyncio.create_task(self._wake.wait())]
            await asyncio.wait(waiters, timeout=POLL_S, return_when=asyncio.FIRST_COMPLETED)
            for t in waiters:
                t.cancel()
        log.info("worker stopped")

    async def run_item(self, item_id: int) -> None:
        while (await self.step(only=item_id))[0]:
            pass

    async def shutdown(self) -> None:
        await asyncio.get_running_loop().run_in_executor(None, self._executor.shutdown, True)
