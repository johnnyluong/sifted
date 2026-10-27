from __future__ import annotations

import logging
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

from sift import goals
from sift.domain import ProcessingError, Source, Stage
from sift.items import queries, store
from sift.items.lifecycle import STAGE_FAILURE, next_stage
from sift.items.store import Claim, ClaimLost, WorkItem
from sift.items.views import ItemOutcome
from sift.llm import guards
from sift.llm.client import LLM
from sift.llm.schemas import ExtractInput, ScoreInput
from sift.media import Transcriber, process_media
from sift.sources import Fetchers
from sift.sources.base import FetchResult

log = logging.getLogger(__name__)


class Pacer:
    def __init__(self, delays: dict[Source, float], clock: Callable[[], datetime]) -> None:
        self._delays = delays
        self._clock = clock
        self._last: dict[Source, datetime] = {}
        self._lock = threading.Lock()

    def mark(self, source: Source) -> None:
        with self._lock:
            self._last[source] = self._clock()

    def blocked(self, now: datetime) -> frozenset[Source]:
        with self._lock:
            return frozenset(s for s, t in self._last.items() if now < t + timedelta(seconds=self._delays.get(s, 0)))


@dataclass(frozen=True, slots=True)
class PipelineDeps:
    fetchers: Fetchers
    transcriber: Transcriber
    llm: LLM | None
    pacer: Pacer
    data_dir: Path
    keep_media: bool
    threshold: int
    clock: Callable[[], datetime]

    def workdir(self, item_id: int) -> Path:
        return self.data_dir / "media" / str(item_id)

    def resolve(self, path: Path | None) -> Path | None:
        return None if path is None else self.data_dir / path

    def relative(self, path: Path | None) -> Path | None:
        return None if path is None else path.resolve().relative_to(self.data_dir.resolve())


class _Release(Exception):
    pass


class _Duplicate(Exception):
    pass


def run(claim: Claim, deps: PipelineDeps) -> ItemOutcome | None:
    stage: Stage | None = None
    try:
        while True:
            row = store.load(claim)
            stage = next_stage(row)
            match stage:
                case Stage.fetch:
                    _fetch(claim, row, deps)
                case Stage.media:
                    _media(claim, row, deps)
                case Stage.extract:
                    _extract(claim, row, deps)
                case Stage.score:
                    return _score(claim, row, deps)
                case None:
                    raise AssertionError("claimed an item with nothing left to do")
    except _Release:
        store.release(claim)
        return None
    except _Duplicate:
        return None
    except ClaimLost:
        log.warning("claim lost for item %s", claim.item_id)
        return None
    except ProcessingError as e:
        log.info("item %s failed at %s: %s", claim.item_id, stage, e.message)
        return store.record_failure(claim, e, deps.clock())
    except Exception as e:
        log.exception("unexpected error in %s for item %s", stage, claim.item_id)
        err = ProcessingError(
            STAGE_FAILURE[stage or Stage.fetch], f"Unexpected {type(e).__name__} during {stage}.", retryable=True
        )
        return store.record_failure(claim, err, deps.clock(), detail=f"{type(e).__name__}: {e}")


def _fetch(claim: Claim, row: WorkItem, deps: PipelineDeps) -> None:
    try:
        ref = deps.fetchers.resolve(row.ref)
        if ref != row.ref and (removed := store.rekey(claim, ref)) is not None:
            log.info("item %s was a share link to item %s; removed it", row.id, removed.item_id)
            shutil.rmtree(deps.workdir(row.id), ignore_errors=True)
            raise _Duplicate
        result: FetchResult = deps.fetchers.for_source(row.source).fetch(ref, deps.workdir(row.id))
    finally:
        deps.pacer.mark(row.source)
    result = replace(
        result,
        video_path=deps.relative(result.video_path),
        thumbnail_path=deps.relative(result.thumbnail_path),
        slide_paths=tuple(p for p in map(deps.relative, result.slide_paths) if p),
    )
    store.record_fetch(claim, result, deps.clock())


def _media(claim: Claim, row: WorkItem, deps: PipelineDeps) -> None:
    assert row.media_kind is not None
    video = deps.resolve(row.media_path)
    result = process_media(
        row.media_kind,
        video,
        deps.resolve(row.thumbnail_path),
        [p for p in map(deps.resolve, row.slide_paths) if p],
        deps.workdir(row.id),
        deps.transcriber,
    )
    result = replace(result, frame_paths=[p for p in (deps.relative(f) for f in result.frame_paths) if p])
    delete = video is not None and not deps.keep_media
    store.record_media(claim, result, deps.clock(), media_deleted=delete)
    if delete and video is not None:
        video.unlink(missing_ok=True)


def _extract(claim: Claim, row: WorkItem, deps: PipelineDeps) -> None:
    if deps.llm is None:
        raise _Release
    frames = [str(p) for p in (deps.resolve(f) for f in row.frame_paths) if p and p.exists()]
    inp = ExtractInput(
        source=row.source,
        author_handle=row.author_handle,
        caption=row.caption,
        post_text=row.post_text,
        transcript=row.transcript,
        frames=frames,
        notes=list(row.notes),
    )
    out, model = deps.llm.extract(inp)
    store.record_extraction(claim, guards.ground_links(out, inp), model, deps.clock())


def _score(claim: Claim, row: WorkItem, deps: PipelineDeps) -> ItemOutcome:
    values, active = goals.scoring_context()
    if deps.llm is None or not active:
        raise _Release
    assert row.card is not None
    inp = ScoreInput(
        card=row.card,
        values_text=values,
        goals=active,
        examples=queries.recent_override_examples(10),
        threshold=deps.threshold,
    )
    out, model = deps.llm.score(inp)
    return store.record_score(claim, guards.drop_invented_goal(out, inp), model, deps.threshold, deps.clock())
