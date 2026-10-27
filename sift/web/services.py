from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from hashlib import blake2b
from pathlib import Path
from typing import Annotated, Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from sift import digest, goals
from sift.domain import QUIET_CHANNELS, Channel, ImportAction, ItemStatus, Origin, Stage
from sift.inbox import export, imports, intake
from sift.inbox.imports import ImportView
from sift.items import queries, store
from sift.items.lifecycle import UserAction
from sift.items.views import ItemDetail, ItemSummary
from sift.organize import store as organize
from sift.runtime import Runtime

_WRITE_BLOCK = 1024 * 1024


class Notice(StrEnum):
    """Why Sift can't do its whole job right now. The SPA owns the wording."""

    fake_llm = "fake_llm"
    no_llm = "no_llm"
    no_goals = "no_goals"


class NavCounts(BaseModel):
    inbox: int
    kept: int
    archived: int
    topics: int = Field(description="Topics with at least one kept post.")


class Pulse(BaseModel):
    revision: str = Field(description="Changes whenever an item list, an item page or the digest list would change.")
    busy: bool = Field(
        description="An item is being processed or can start now, or a brief you asked for is being written. "
        "Poll fast while true."
    )


class ItemMotion(BaseModel):
    id: int
    state_label: str
    stage: Stage | None
    announce: bool = Field(description="False for imported posts: the SPA toasts only what you sent yourself.")


class StatusView(BaseModel):
    counts: dict[ItemStatus, int]
    nav: NavCounts
    llm: Literal["anthropic", "fake"] | None
    active_goals: int
    has_digest: bool
    notice: Notice | None
    threshold: int
    timezone: str = Field(description="IANA zone the SPA shows dates in, so they agree with digest_schedule.")
    digest_schedule: str = Field(description="When the weekly digest runs, e.g. 'Sundays at 6:00pm'.")
    pulse: Pulse
    in_motion: list[ItemMotion] = Field(
        description="Items being processed or about to be; one that leaves has settled."
    )


class QueuedSubmission(BaseModel):
    kind: Literal["queued"] = "queued"
    item: ItemSummary


class DuplicateSubmission(BaseModel):
    kind: Literal["duplicate"] = "duplicate"
    item: ItemSummary


class RejectedSubmission(BaseModel):
    kind: Literal["rejected"] = "rejected"
    url: str
    reason: str


SubmissionView = Annotated[QueuedSubmission | DuplicateSubmission | RejectedSubmission, Field(discriminator="kind")]


def rt(request: Request) -> Runtime:
    return request.app.state.rt


async def submit(request: Request, text: str, channel: Channel) -> list[SubmissionView]:
    runtime = rt(request)
    results = await run_in_threadpool(
        intake.submit,
        text,
        Origin(channel),
        runtime.clock(),
        llm_ready=runtime.llm_ready,
        resolve=runtime.worker.deps.fetchers.resolve,
    )
    if any(isinstance(r, intake.Queued) for r in results):
        runtime.worker.wake()
    return [_submission(r) for r in results]


def _submission(sub: intake.Submission) -> SubmissionView:
    match sub:
        case intake.Queued(item=item):
            return QueuedSubmission(item=item)
        case intake.Duplicate(item=item):
            return DuplicateSubmission(item=item)
        case intake.Rejected(url=url, reason=reason):
            return RejectedSubmission(url=url, reason=reason)


async def act(request: Request, item_id: int, action: UserAction) -> ItemDetail:
    runtime = rt(request)
    try:
        detail = await run_in_threadpool(
            store.apply_action, item_id, action, runtime.clock(), llm_ready=runtime.llm_ready
        )
    except store.ItemNotFound as e:
        raise HTTPException(404, "Item not found") from e
    except store.InvalidTransition as e:
        raise HTTPException(409, str(e)) from e
    if detail.status is ItemStatus.queued:
        runtime.worker.wake()
    return detail


async def apply_setup(request: Request, body: goals.SetupApply) -> list[goals.GoalView]:
    runtime = rt(request)
    try:
        views = await run_in_threadpool(goals.apply_setup, body, runtime.clock())
    except goals.GoalNotFound as e:
        raise HTTPException(404, "Goal not found") from e
    except goals.SetupConflict as e:
        raise HTTPException(409, str(e)) from e
    runtime.worker.wake()
    return views


async def organize_write[T](request: Request, fn: Callable[..., T], *args: object, wake: bool = False) -> T:
    runtime = rt(request)
    try:
        result = await run_in_threadpool(fn, *args, runtime.clock())
    except organize.NotFound as e:
        raise HTTPException(404, str(e)) from e
    except organize.Conflict as e:
        raise HTTPException(409, str(e)) from e
    if wake:
        runtime.worker.wake()
    return result


async def upload_import(request: Request, filename: str) -> ImportView:
    runtime = rt(request)
    cap = runtime.settings.import_max_bytes
    too_big = f"The export is larger than IMPORT_MAX_BYTES ({cap:,} bytes)."
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > cap:
        raise HTTPException(413, too_big)
    folder = runtime.settings.imports_dir
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}.zip"
    try:
        size = 0
        block = bytearray()
        with path.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > cap:
                    raise HTTPException(413, too_big)
                block += chunk
                if len(block) >= _WRITE_BLOCK:
                    await run_in_threadpool(f.write, block)
                    block.clear()
            await run_in_threadpool(f.write, block)
        scan = await run_in_threadpool(export.scan, path)
    except export.NotAnExport as e:
        raise HTTPException(422, str(e)) from e
    finally:
        path.unlink(missing_ok=True)
    return await run_in_threadpool(
        imports.stage, scan, filename, runtime.clock(), runtime.pace, llm_ready=runtime.llm_ready
    )


async def import_action(request: Request, import_id: int, action: ImportAction, limit: int | None) -> ImportView:
    runtime = rt(request)
    try:
        view = await run_in_threadpool(
            imports.apply, import_id, action, runtime.clock(), runtime.pace, llm_ready=runtime.llm_ready, limit=limit
        )
    except imports.ImportNotFound as e:
        raise HTTPException(404, "Import not found") from e
    except imports.InvalidImportAction as e:
        raise HTTPException(409, str(e)) from e
    if action in (ImportAction.start, ImportAction.resume):
        runtime.worker.wake()
    return view


async def generate_digest(request: Request) -> digest.DigestView | None:
    runtime = rt(request)
    return await digest.deliver_digest(runtime.clock(), runtime.llm, runtime.notifier)


def status(runtime: Runtime) -> StatusView:
    settings = runtime.settings
    activity = queries.activity(llm_ready=runtime.llm_ready)
    c = activity.counts
    return StatusView(
        counts=c,
        nav=NavCounts(
            inbox=sum(c[s] for s in queries.INBOX),
            kept=sum(c[s] for s in queries.KEPT),
            archived=sum(c[s] for s in queries.ARCHIVED),
            topics=activity.organize.topics,
        ),
        llm="fake" if settings.llm_backend == "fake" else ("anthropic" if runtime.llm else None),
        active_goals=activity.active_goals,
        has_digest=activity.last_digest_at is not None,
        notice=notice(runtime, activity.active_goals),
        threshold=settings.keep_threshold,
        timezone=settings.timezone,
        digest_schedule=digest_schedule(settings.digest_cron),
        pulse=pulse(activity, runtime.clock(), llm_ready=runtime.llm_ready),
        in_motion=[
            ItemMotion(
                id=i.id, state_label=i.state_label, stage=i.stage, announce=i.origin_channel not in QUIET_CHANNELS
            )
            for i in activity.moving
        ],
    )


def notice(runtime: Runtime, active_goals: int) -> Notice | None:
    if runtime.settings.llm_backend == "fake":
        return Notice.fake_llm
    if runtime.llm is None:
        return Notice.no_llm
    if active_goals == 0:
        return Notice.no_goals
    return None


def pulse(act: queries.Activity, now: datetime, *, llm_ready: bool) -> Pulse:
    basis = (
        sorted(act.counts.items()),
        [(i.id, i.state_label, i.next_attempt_at, i.last_error) for i in act.moving],
        act.last_interaction_at,
        act.last_digest_at,
        act.last_goal_change_at,
        act.last_import_change_at,
        act.organize.last_change_at,
        act.organize.writing_brief,
        act.active_goals,
    )
    busy = any(_runnable(i, now) for i in act.moving) or (llm_ready and act.organize.writing_brief)
    return Pulse(revision=blake2b(repr(basis).encode(), digest_size=8).hexdigest(), busy=busy)


def _runnable(item: ItemSummary, now: datetime) -> bool:
    return item.next_attempt_at is None or item.next_attempt_at <= now


_DAYS = {
    "sun": "Sundays",
    "mon": "Mondays",
    "tue": "Tuesdays",
    "wed": "Wednesdays",
    "thu": "Thursdays",
    "fri": "Fridays",
    "sat": "Saturdays",
}


def digest_schedule(cron: str) -> str:
    minute, hour, dom, month, dow = cron.split()
    days = _days_in_words(dow.lower()) if dom == month == "*" else None
    if days is None or not (minute.isdigit() and hour.isdigit()):
        return "on its schedule"
    h, m = int(hour), int(minute)
    return f"{days} at {(h % 12) or 12}:{m:02d}{'am' if h < 12 else 'pm'}"


def _days_in_words(dow: str) -> str | None:
    if dow == "*":
        return "Daily"
    first, _, last = dow.partition("-")
    if last and first in _DAYS and last in _DAYS:
        return f"{_DAYS[first]} to {_DAYS[last]}"
    names = dow.split(",")
    if not all(n in _DAYS for n in names):
        return None
    days = [_DAYS[n] for n in names]
    return days[0] if len(days) == 1 else f"{', '.join(days[:-1])} and {days[-1]}"


def thumbnail_file(runtime: Runtime, item_id: int) -> Path | None:
    rel = queries.thumbnail_path(item_id)
    if not rel:
        return None
    data_dir = runtime.settings.data_dir.resolve()
    path = (data_dir / rel).resolve()
    if not path.is_relative_to(data_dir / "media") or not path.is_file():
        return None
    return path
