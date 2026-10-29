from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import blake2b
from typing import assert_never

from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlmodel import Session, col, select

from sift import db
from sift.config import Settings
from sift.domain import (
    Channel,
    FailureKind,
    Hold,
    ImportAction,
    ImportPhase,
    ItemStatus,
    LinkState,
    Origin,
    PauseReason,
    Source,
    SourceRef,
)
from sift.inbox.export import ExportScan
from sift.items import queries, store, views
from sift.llm import pricing
from sift.llm.pricing import ItemCost
from sift.models import Import, ImportLink, Item

log = logging.getLogger(__name__)

AUTO_PAUSE_FAILURES = 5
JITTER = 0.35
DAY = timedelta(hours=24)
UNSUPPORTED_SAMPLE = 50
OPTION_SIZES = (50, 100)
NEWEST_FIRST = (col(ImportLink.saved_at).desc().nulls_last(), col(ImportLink.id))

ALLOWED_FROM: dict[ImportAction, frozenset[ImportPhase]] = {
    ImportAction.start: frozenset({ImportPhase.preview}),
    ImportAction.pause: frozenset({ImportPhase.running}),
    ImportAction.resume: frozenset({ImportPhase.paused}),
    ImportAction.cancel: frozenset({ImportPhase.preview, ImportPhase.running, ImportPhase.paused}),
}


class ImportNotFound(Exception):
    pass


class InvalidImportAction(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Pace:
    gap: timedelta
    daily_cap: int
    cost: ItemCost

    @classmethod
    def from_settings(cls, settings: Settings) -> Pace:
        return cls(
            gap=timedelta(seconds=settings.import_gap_seconds),
            daily_cap=settings.import_daily_cap,
            cost=pricing.item_cost(settings),
        )


@dataclass(frozen=True, slots=True)
class DripState:
    in_flight: bool
    next_release_at: datetime | None
    released_last_day: tuple[datetime, ...]
    recent_failures: tuple[bool, ...]


@dataclass(frozen=True, slots=True)
class Release:
    pass


@dataclass(frozen=True, slots=True)
class Wait:
    hold: Hold
    until: datetime | None


@dataclass(frozen=True, slots=True)
class AutoPause:
    pass


Gate = Release | Wait | AutoPause


def gate(state: DripState, now: datetime, pace: Pace) -> Gate:
    if len(state.recent_failures) >= AUTO_PAUSE_FAILURES and all(state.recent_failures[:AUTO_PAUSE_FAILURES]):
        return AutoPause()
    if state.in_flight:
        return Wait(Hold.in_flight, None)
    over = len(state.released_last_day) - pace.daily_cap
    if over >= 0:
        return Wait(Hold.daily_cap, state.released_last_day[over] + DAY)
    if state.next_release_at is not None and now < state.next_release_at:
        return Wait(Hold.gap, state.next_release_at)
    return Release()


def gap_for(link_id: int, gap: timedelta) -> timedelta:
    u = int.from_bytes(blake2b(str(link_id).encode(), digest_size=8).digest()) / 2**64
    return gap * (1 - JITTER + 2 * JITTER * u)


def drip_duration(posts: int, pace: Pace) -> timedelta:
    if posts <= 0:
        return timedelta(0)
    per_day = max(1, min(pace.daily_cap, int(DAY / pace.gap)))
    full_days = (posts - 1) // per_day
    return full_days * DAY + (posts - full_days * per_day) * pace.gap


class PostCost(BaseModel):
    usd: float | None = Field(description="None when a configured model has no known price.")
    tokens: int


class Estimate(BaseModel):
    posts: int
    usd: float | None
    seconds: int = Field(description="Time for the drip to release every post, at the import pace and daily cap.")


class QueueOption(BaseModel):
    limit: int | None = Field(description="Newest N; null for all.")
    estimate: Estimate


class PaceView(BaseModel):
    gap_seconds: int
    daily_cap: int


class ImportCounts(BaseModel):
    links: int = Field(description="Distinct supported posts in the export.")
    found: int
    waiting: int
    released: int
    duplicate: int
    skipped: int
    kept: int
    archived: int
    failed: int
    in_progress: int


class CurrentPost(BaseModel):
    item_id: int
    state_label: str


class ImportView(BaseModel):
    id: int
    filename: str
    phase: ImportPhase
    created_at: datetime
    started_at: datetime | None
    files_read: list[str]
    files_skipped_large: list[str] = Field(description="Saved files left unread because each is over the size cap.")
    files_skipped_budget: list[str] = Field(
        description="Saved files left unread because the scan's total read budget ran out before them."
    )
    unsupported_count: int
    unsupported_sample: list[str]
    counts: ImportCounts
    max_posts: int | None
    per_post: PostCost
    options: list[QueueOption] = Field(description="Preview only: the server's priced choices.")
    remaining: Estimate | None = Field(description="Running or paused: what is still waiting.")
    pace: PaceView
    hold: Hold | None = Field(description="Running only: why no post is being released right now.")
    hold_until: datetime | None
    pause_reason: PauseReason | None
    current: CurrentPost | None = Field(description="The imported post in flight, if any.")
    actions: list[ImportAction]


def phase(row: Import, waiting: int) -> ImportPhase:
    if row.cancelled_at is not None:
        return ImportPhase.cancelled
    if row.started_at is None:
        return ImportPhase.preview
    if waiting == 0:
        return ImportPhase.finished
    if row.paused_at is not None:
        return ImportPhase.paused
    return ImportPhase.running


def allowed_actions(ph: ImportPhase, found: int) -> list[ImportAction]:
    return [a for a, froms in ALLOWED_FROM.items() if ph in froms and not (a is ImportAction.start and found == 0)]


def estimate(posts: int, pace: Pace) -> Estimate:
    per_post = pace.cost.usd
    return Estimate(
        posts=posts,
        usd=None if per_post is None else round(per_post * posts, 2),
        seconds=int(drip_duration(posts, pace).total_seconds()),
    )


def estimate_newest(import_id: int, limit: int, pace: Pace) -> Estimate:
    with db.read_session() as s:
        if s.get(Import, import_id) is None:
            raise ImportNotFound(import_id)
        found = _state_counts(s, import_id)[LinkState.found]
    return estimate(min(limit, found), pace)


def queue_options(new: int, pace: Pace) -> list[QueueOption]:
    sizes = [n for n in OPTION_SIZES if n < new]
    options = [QueueOption(limit=n, estimate=estimate(n, pace)) for n in sizes]
    if new > 0:
        options.append(QueueOption(limit=None, estimate=estimate(new, pace)))
    return options


def stage(scan: ExportScan, filename: str, now: datetime, pace: Pace, *, llm_ready: bool) -> ImportView:
    with db.write_session() as s:
        in_items = _item_ids(s, [link.ref for link in scan.links])
        row = Import(
            filename=filename,
            created_at=now,
            updated_at=now,
            files_read=scan.files_read,
            files_skipped_large=scan.files_skipped_large,
            files_skipped_budget=scan.files_skipped_budget,
            unsupported=scan.unsupported[:UNSUPPORTED_SAMPLE],
            unsupported_count=len(scan.unsupported),
        )
        s.add(row)
        s.flush()
        assert row.id is not None
        for link in scan.links:
            key = (link.ref.source, link.ref.canonical_id)
            s.add(
                ImportLink(
                    import_id=row.id,
                    source=link.ref.source,
                    canonical_id=link.ref.canonical_id,
                    clean_url=link.ref.clean_url,
                    url=link.url,
                    saved_at=link.saved_at,
                    state=LinkState.duplicate if key in in_items else LinkState.found,
                    item_id=in_items.get(key),
                )
            )
        s.flush()
        return _view(s, row, now, pace, llm_ready=llm_ready)


def _item_ids(s: Session, refs: list[SourceRef]) -> dict[tuple[Source, str], int]:
    out: dict[tuple[Source, str], int] = {}
    codes = sorted({r.canonical_id for r in refs})
    for i in range(0, len(codes), 500):
        rows = s.exec(
            select(Item.id, Item.source, Item.canonical_id).where(col(Item.canonical_id).in_(codes[i : i + 500]))
        ).all()
        out.update({(Source(source), code): item_id for item_id, source, code in rows if item_id is not None})
    return out


def apply(
    import_id: int, action: ImportAction, now: datetime, pace: Pace, *, llm_ready: bool, limit: int | None = None
) -> ImportView:
    with db.write_session() as s:
        row = s.get(Import, import_id)
        if row is None:
            raise ImportNotFound(import_id)
        counts = _state_counts(s, import_id)
        ph = phase(row, counts[LinkState.waiting])
        if action not in allowed_actions(ph, counts[LinkState.found]):
            raise InvalidImportAction(f"cannot {action} an import that is {ph}")
        match action:
            case ImportAction.start:
                found = s.exec(_links(import_id, LinkState.found).order_by(*NEWEST_FIRST)).all()
                for i, link in enumerate(found):
                    link.state = LinkState.waiting if limit is None or i < limit else LinkState.skipped
                row.started_at = now
                row.max_posts = limit
            case ImportAction.pause:
                row.paused_at = now
                row.pause_reason = PauseReason.user
            case ImportAction.resume:
                row.paused_at = None
                row.pause_reason = None
                row.resumed_at = now
            case ImportAction.cancel:
                for link in s.exec(
                    select(ImportLink).where(
                        ImportLink.import_id == import_id,
                        col(ImportLink.state).in_([LinkState.found, LinkState.waiting]),
                    )
                ).all():
                    link.state = LinkState.skipped
                row.cancelled_at = now
            case _:
                assert_never(action)
        row.updated_at = now
        s.flush()
        return _view(s, row, now, pace, llm_ready=llm_ready)


def release_next(now: datetime, pace: Pace, *, llm_ready: bool) -> Gate | None:
    with db.read_session() as s:
        row = _running_import(s)
        if row is None:
            return None
        decision = gate(_drip_state(s, row, now), now, pace)
        link = _next_link(s, row) if isinstance(decision, Release) else None
    match decision:
        case Wait():
            return decision
        case AutoPause():
            _auto_pause(row, now)
            return decision
        case Release():
            assert link is not None and link.id is not None
            return decision if _release(link.id, now, pace, llm_ready=llm_ready) else None


def running() -> bool:
    with db.read_session() as s:
        return _running_import(s) is not None


def _running_import(s: Session) -> Import | None:
    waiting = select(ImportLink.import_id).where(ImportLink.state == LinkState.waiting)
    return s.exec(
        select(Import)
        .where(
            col(Import.started_at).is_not(None),
            col(Import.paused_at).is_(None),
            col(Import.cancelled_at).is_(None),
            col(Import.id).in_(waiting),
        )
        .order_by(col(Import.id))
        .limit(1)
    ).first()


def _next_link(s: Session, row: Import) -> ImportLink | None:
    assert row.id is not None
    return s.exec(_links(row.id, LinkState.waiting).order_by(*NEWEST_FIRST).limit(1)).first()


def _links(import_id: int, state: LinkState):
    return select(ImportLink).where(ImportLink.import_id == import_id, ImportLink.state == state)


def _in_flight_filter(now: datetime):
    return (
        Item.origin_channel == Channel.export,
        col(Item.status).in_(list(queries.PENDING)),
        or_(col(Item.next_attempt_at).is_(None), col(Item.next_attempt_at) <= now),
    )


def _drip_state(s: Session, row: Import, now: datetime) -> DripState:
    assert row.id is not None and row.started_at is not None
    in_flight = s.exec(select(Item.id).where(*_in_flight_filter(now)).limit(1)).first() is not None
    since = row.resumed_at or row.started_at
    recent = s.exec(
        select(Item.fetched_at, Item.failure_kind, Item.next_attempt_at)
        .join(ImportLink, col(ImportLink.item_id) == col(Item.id))
        .where(
            ImportLink.import_id == row.id,
            ImportLink.state == LinkState.released,
            col(ImportLink.released_at) >= since,
            # A dead post neither counts nor resets: an expired session also makes live posts read as private.
            or_(col(Item.failure_kind).is_(None), col(Item.failure_kind) != FailureKind.post_unavailable),
        )
        .order_by(col(ImportLink.released_at).desc(), col(ImportLink.id).desc())
        .limit(AUTO_PAUSE_FAILURES)
    ).all()
    released = s.exec(
        select(ImportLink.released_at)
        .where(col(ImportLink.released_at) > now - DAY)
        .order_by(col(ImportLink.released_at))
    ).all()
    return DripState(
        in_flight=in_flight,
        next_release_at=s.exec(select(func.max(Import.next_release_at))).one(),
        released_last_day=tuple(t for t in released if t is not None),
        recent_failures=tuple(_failed_download(fetched, kind, retry_at) for fetched, kind, retry_at in recent),
    )


def _failed_download(fetched_at: datetime | None, kind: str | None, next_attempt_at: datetime | None) -> bool:
    return fetched_at is None and (kind == FailureKind.download_failed or next_attempt_at is not None)


def _auto_pause(row: Import, now: datetime) -> None:
    with db.write_session() as s:
        current = s.get(Import, row.id)
        if current is None or current.paused_at is not None or current.cancelled_at is not None:
            return
        current.paused_at = now
        current.pause_reason = PauseReason.download_failures
        current.updated_at = now
    log.info("import %s paused itself after %d failed downloads in a row", row.id, AUTO_PAUSE_FAILURES)


def _release(link_id: int, now: datetime, pace: Pace, *, llm_ready: bool) -> bool:
    with db.write_session() as s:
        link = s.get(ImportLink, link_id)
        assert link is not None
        row = s.get(Import, link.import_id)
        assert row is not None
        # release_next's gate read is stale by now; a Pause or Cancel since then must win.
        if link.state != LinkState.waiting or row.paused_at is not None or row.cancelled_at is not None:
            return False
        ref = SourceRef(link.source, link.canonical_id, link.clean_url)
        result = store.enqueue_in(s, ref, link.url, Origin(Channel.export), now, llm_ready=llm_ready)
        item = result.item
        link.item_id = item.id
        match result:
            case store.Created():
                link.state = LinkState.released
                link.released_at = now
                row.next_release_at = now + gap_for(link_id, pace.gap)
            case store.Existing():
                link.state = LinkState.duplicate
        row.updated_at = now
    log.info("import %s: link %s -> item %s (%s)", link.import_id, link_id, item.id, link.state)
    return True


def list_imports(now: datetime, pace: Pace, *, llm_ready: bool) -> list[ImportView]:
    with db.read_session() as s:
        rows = s.exec(select(Import).order_by(col(Import.id).desc())).all()
        return [_view(s, row, now, pace, llm_ready=llm_ready) for row in rows]


def get_import(import_id: int, now: datetime, pace: Pace, *, llm_ready: bool) -> ImportView | None:
    with db.read_session() as s:
        row = s.get(Import, import_id)
        return None if row is None else _view(s, row, now, pace, llm_ready=llm_ready)


def _state_counts(s: Session, import_id: int) -> Counter[LinkState]:
    rows = s.exec(
        select(ImportLink.state, func.count()).where(ImportLink.import_id == import_id).group_by(col(ImportLink.state))
    ).all()
    return Counter({LinkState(state): n for state, n in rows})


def _view(s: Session, row: Import, now: datetime, pace: Pace, *, llm_ready: bool) -> ImportView:
    assert row.id is not None
    states = _state_counts(s, row.id)
    outcomes = Counter(
        s.exec(
            select(Item.status)
            .join(ImportLink, col(ImportLink.item_id) == col(Item.id))
            .where(ImportLink.import_id == row.id, ImportLink.state == LinkState.released)
        ).all()
    )
    ph = phase(row, states[LinkState.waiting])
    hold: Wait | None = None
    current: CurrentPost | None = None
    if ph is ImportPhase.running:
        decision = gate(_drip_state(s, row, now), now, pace)
        hold = decision if isinstance(decision, Wait) else None
        flight = s.exec(
            select(Item)
            .join(ImportLink, col(ImportLink.item_id) == col(Item.id))
            .where(ImportLink.import_id == row.id, *_in_flight_filter(now))
            .limit(1)
        ).first()
        if flight is not None and flight.id is not None:
            label = views.state_label(flight, queries.readiness(s, llm_ready=llm_ready))
            current = CurrentPost(item_id=flight.id, state_label=label)
    found = states[LinkState.found]
    return ImportView(
        id=row.id,
        filename=row.filename,
        phase=ph,
        created_at=row.created_at,
        started_at=row.started_at,
        files_read=row.files_read,
        files_skipped_large=row.files_skipped_large,
        files_skipped_budget=row.files_skipped_budget,
        unsupported_count=row.unsupported_count,
        unsupported_sample=row.unsupported,
        counts=ImportCounts(
            links=sum(states.values()),
            found=found,
            waiting=states[LinkState.waiting],
            released=states[LinkState.released],
            duplicate=states[LinkState.duplicate],
            skipped=states[LinkState.skipped],
            kept=outcomes[ItemStatus.kept] + outcomes[ItemStatus.done],
            archived=outcomes[ItemStatus.archived],
            failed=outcomes[ItemStatus.failed],
            in_progress=sum(outcomes[status] for status in queries.PENDING),
        ),
        max_posts=row.max_posts,
        per_post=PostCost(usd=pace.cost.usd, tokens=pace.cost.tokens),
        options=queue_options(found, pace) if ph is ImportPhase.preview else [],
        remaining=estimate(states[LinkState.waiting], pace)
        if ph in (ImportPhase.running, ImportPhase.paused)
        else None,
        pace=PaceView(gap_seconds=int(pace.gap.total_seconds()), daily_cap=pace.daily_cap),
        hold=hold.hold if hold else None,
        hold_until=hold.until if hold else None,
        pause_reason=row.pause_reason if ph is ImportPhase.paused else None,
        current=current,
        actions=allowed_actions(ph, found),
    )
