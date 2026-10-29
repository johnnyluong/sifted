from __future__ import annotations

import shutil
import uuid
from collections.abc import AsyncIterator, Callable
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
from sift.sources import image

_WRITE_BLOCK = 1024 * 1024


class Notice(StrEnum):
    """Why Sift can't do its whole job right now. The SPA owns the wording."""

    fake_llm = "fake_llm"
    no_llm = "no_llm"
    no_goals = "no_goals"


class NavCounts(BaseModel):
    inbox: int
    kept: int = Field(description="Kept and done posts, leaving out kept posts on the wishlist.")
    wishlist: int = Field(description="Kept posts on the wishlist.")
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


async def delete_item(request: Request, item_id: int) -> None:
    runtime = rt(request)
    try:
        uploads = await run_in_threadpool(store.delete_archived, item_id)
    except store.ItemNotFound as e:
        raise HTTPException(404, "Item not found") from e
    except store.InvalidTransition as e:
        raise HTTPException(409, str(e)) from e
    workdir = runtime.worker.deps.workdir(item_id)
    await run_in_threadpool(_remove_files, workdir, runtime.settings.uploads_dir, uploads)


def _remove_files(workdir: Path, uploads_dir: Path, uploads: list[str]) -> None:
    shutil.rmtree(workdir, ignore_errors=True)
    for name in uploads:
        if (path := image.stored_file(uploads_dir, name)) is not None:
            path.unlink(missing_ok=True)


async def set_wishlist(request: Request, item_id: int, on: bool | None) -> ItemDetail:
    runtime = rt(request)
    try:
        return await run_in_threadpool(store.set_wishlist, item_id, on, runtime.clock(), llm_ready=runtime.llm_ready)
    except store.ItemNotFound as e:
        raise HTTPException(404, "Item not found") from e
    except store.InvalidTransition as e:
        raise HTTPException(409, str(e)) from e


async def set_keep_reason(request: Request, item_id: int, goal_id: int | None, note: str) -> ItemDetail:
    runtime = rt(request)
    try:
        return await run_in_threadpool(
            store.set_keep_reason, item_id, goal_id, note, runtime.clock(), llm_ready=runtime.llm_ready
        )
    except store.ItemNotFound as e:
        raise HTTPException(404, "Item not found") from e
    except goals.GoalNotFound as e:
        raise HTTPException(404, "Goal not found") from e
    except store.InvalidTransition as e:
        raise HTTPException(409, str(e)) from e


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


async def _capped_body(request: Request, cap: int, too_big: str) -> AsyncIterator[bytes]:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > cap:
        raise HTTPException(413, too_big)
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > cap:
            raise HTTPException(413, too_big)
        yield chunk


async def store_image(request: Request) -> str:
    runtime = rt(request)
    cap = runtime.settings.upload_max_bytes
    data = bytearray()
    async for chunk in _capped_body(request, cap, f"The image is larger than UPLOAD_MAX_BYTES ({cap:,} bytes)."):
        data += chunk
    try:
        return await run_in_threadpool(image.store, bytes(data), runtime.settings.uploads_dir)
    except image.NotAnImage as e:
        raise HTTPException(415, str(e)) from e


async def upload_image(request: Request, channel: Channel) -> list[SubmissionView]:
    return [await _submit_images(request, [await store_image(request)], channel)]


async def submit_image_set(request: Request, names: list[str], channel: Channel) -> list[SubmissionView]:
    folder = rt(request).settings.uploads_dir
    missing = await run_in_threadpool(lambda: [name for name in names if image.stored_file(folder, name) is None])
    if missing:
        raise HTTPException(422, f"{missing[0]} is not stored. Send it to POST /api/uploads/files first.")
    return [await _submit_images(request, names, channel)]


async def _submit_images(request: Request, names: list[str], channel: Channel) -> SubmissionView:
    runtime = rt(request)
    ref = image.upload_ref(names)
    result = await run_in_threadpool(
        intake.submit_ref, ref, ref.clean_url, Origin(channel), runtime.clock(), llm_ready=runtime.llm_ready
    )
    if isinstance(result, intake.Queued):
        runtime.worker.wake()
    return _submission(result)


async def upload_import(request: Request, filename: str) -> ImportView:
    runtime = rt(request)
    cap = runtime.settings.import_max_bytes
    folder = runtime.settings.imports_dir
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}.zip"
    try:
        block = bytearray()
        with path.open("wb") as f:
            async for chunk in _capped_body(
                request, cap, f"The export is larger than IMPORT_MAX_BYTES ({cap:,} bytes)."
            ):
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
    shelves = activity.shelves
    return StatusView(
        counts=activity.counts,
        nav=NavCounts(
            inbox=shelves[queries.Shelf.inbox],
            kept=shelves[queries.Shelf.kept],
            wishlist=shelves[queries.Shelf.wishlist],
            archived=shelves[queries.Shelf.archived],
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
        sorted(act.shelves.items()),
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


def upload_file(runtime: Runtime, name: str) -> Path | None:
    return image.stored_file(runtime.settings.uploads_dir, name)


def thumbnail_file(runtime: Runtime, item_id: int) -> Path | None:
    rel = queries.thumbnail_path(item_id)
    if not rel:
        return None
    data_dir = runtime.settings.data_dir.resolve()
    path = (data_dir / rel).resolve()
    if not path.is_relative_to(data_dir / "media") or not path.is_file():
        return None
    return path
