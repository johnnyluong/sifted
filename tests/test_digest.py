from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sift import db, digest
from sift.digest import REPEAT_LIMIT, QueueEntry, layout, plan, select_items, to_text
from sift.domain import Channel, DigestRole, ItemStatus, ItemType, Source
from sift.items import queries
from sift.items.queries import DigestCandidate
from sift.items.views import ItemSummary
from sift.llm.schemas import DigestDraft, GoalLine, TopPick
from sift.models import Digest, DigestEntry, Item
from sift.runtime import Runtime
from tests.conftest import Clock

T0 = datetime(2026, 10, 11, 22, 0, tzinfo=UTC)


def cand(
    i: int,
    *,
    score: int = 70,
    shown: int = 0,
    since: int = 0,
    decided: datetime | None = None,
    item_type: ItemType = ItemType.idea,
    goal: int | None = 1,
) -> DigestCandidate:
    return DigestCandidate(
        id=i,
        title=f"Item {i}",
        item_type=item_type,
        summary=f"Summary {i}",
        next_action=f"Action {i}",
        relevance_reason=f"Reason {i}",
        matched_goal_id=goal,
        relevance_score=score,
        decided_at=decided or T0 - timedelta(days=1),
        times_surfaced=shown,
        times_surfaced_since_interaction=since,
    )


def test_new_items_and_carryovers() -> None:
    sel = select_items(
        [cand(1), cand(2, shown=1, since=1), cand(3, shown=1, since=1, decided=T0 + timedelta(days=1))], T0
    )
    assert [c.id for c in sel.new] == [1, 3]
    assert [c.id for c in sel.carryover] == [2]


def test_repeat_cap_until_interaction() -> None:
    capped = cand(1, shown=REPEAT_LIMIT, since=REPEAT_LIMIT)
    touched = cand(2, shown=REPEAT_LIMIT, since=0)
    sel = select_items([capped, touched], T0)
    assert [c.id for c in sel.carryover] == [2]
    assert not sel.new


def test_plan_keeps_only_valid_picks_then_queues_new_then_carryovers() -> None:
    sel = select_items(
        [cand(1, score=90), cand(2), cand(3, score=50), cand(4, score=80), cand(5, shown=1, since=1)], T0
    )
    draft = DigestDraft.model_construct(
        opening="  ",
        top=[
            TopPick(item_id=3, why=" Now. ", next_action=" Do it. "),
            TopPick(item_id=3, why="dup", next_action="n"),
            TopPick(item_id=99, why="made up", next_action="n"),
            TopPick(item_id=5, why="", next_action=""),
            TopPick(item_id=1, why="w", next_action="n"),
            TopPick(item_id=4, why="one too many", next_action="n"),
        ],
        by_goal=[GoalLine(item_id=2, line=" Line for two "), GoalLine(item_id=5, line="not new")],
    )
    p = plan(sel, draft)
    assert p.opening is None
    assert [(e.item_id, e.role) for e in p.queue] == [
        (3, DigestRole.pick),
        (5, DigestRole.pick),
        (1, DigestRole.pick),
        (4, DigestRole.new),
        (2, DigestRole.new),
    ]
    assert (p.queue[0].why, p.queue[0].next_action) == ("Now.", "Do it.")
    assert (p.queue[1].why, p.queue[1].next_action) == ("Reason 5", "Action 5")
    assert [e.line for e in p.queue] == [None, None, None, "Summary 4", "Line for two"]


def test_plan_without_a_valid_pick_takes_the_top_scores_and_benches_the_rest() -> None:
    sel = select_items([cand(1, score=60), cand(2, score=95), cand(3, shown=1, since=1, score=99), cand(4)], T0)
    p = plan(
        sel, DigestDraft(opening="A week for tacos.", top=[TopPick(item_id=42, why="w", next_action="n")], by_goal=[])
    )
    assert p.opening == "A week for tacos."
    assert [(e.item_id, e.role) for e in p.queue] == [
        (3, DigestRole.pick),
        (2, DigestRole.pick),
        (4, DigestRole.pick),
        (1, DigestRole.new),
    ]
    assert (p.queue[0].why, p.queue[0].next_action) == ("Reason 3", "Action 3")


def summary(i: int, status: ItemStatus = ItemStatus.kept, **kw: Any) -> ItemSummary:
    fields: dict[str, Any] = {
        "id": i,
        "source": Source.instagram,
        "url": f"https://www.instagram.com/reel/I{i}/",
        "origin_channel": Channel.web,
        "status": status,
        "state_label": status.value,
        "waiting_for": None,
        "status_reason": None,
        "received_at": T0,
        "author_handle": None,
        "thumbnail_url": None,
        "media_kind": None,
        "item_type": ItemType.idea,
        "title": f"Item {i}",
        "summary": f"Summary {i}",
        "next_action": None,
        "relevance_score": 70,
        "matched_goal_id": None,
        "matched_goal_title": None,
        "user_override": None,
        "threshold_decision": None,
        "stage": None,
        "failure_kind": None,
        "failure_hint": None,
        "next_attempt_at": None,
        "last_error": None,
        "actions": [],
        "in_motion": False,
        "gist": None,
        "labels": [],
        "topic": None,
        "covered_by": None,
    }
    return ItemSummary(**(fields | kw))


QUEUE = [
    QueueEntry(1, DigestRole.pick, "why 1", "next 1", None),
    QueueEntry(2, DigestRole.pick, "why 2", "next 2", None),
    QueueEntry(3, DigestRole.pick, "why 3", "next 3", None),
    QueueEntry(4, DigestRole.new, "reason 4", "action 4", "line 4"),
    QueueEntry(5, DigestRole.new, "reason 5", "action 5", "line 5"),
    QueueEntry(6, DigestRole.carryover, "reason 6", "action 6", None),
]


def _ids(picks: list[digest.DigestPick]) -> list[int]:
    return [p.item.id for p in picks]


def test_a_done_pick_hands_its_place_to_the_next_in_the_queue() -> None:
    items = {i: summary(i) for i in range(1, 7)}
    before = layout(QUEUE, items, {})
    assert _ids(before.top) == [1, 2, 3] and not any(p.refill for p in before.top)
    assert before.done == [] and [[x.item.id for x in g.lines] for g in before.groups] == [[4, 5]]

    items[1] = summary(1, ItemStatus.done)
    after = layout(QUEUE, items, {})
    assert _ids(after.top) == [2, 3, 4] and [p.refill for p in after.top] == [False, False, True]
    assert (after.top[2].why, after.top[2].next_action) == ("reason 4", "action 4")
    assert _ids(after.done) == [1]
    assert [[x.item.id for x in g.lines] for g in after.groups] == [[5]]

    items[1] = summary(1)
    assert layout(QUEUE, items, {}) == before


def test_done_lists_every_shown_done_post_and_carryovers_that_moved_up() -> None:
    items = {i: summary(i) for i in range(1, 7)}
    items[5] = summary(5, ItemStatus.done)
    out = layout(QUEUE, items, {})
    assert _ids(out.top) == [1, 2, 3] and _ids(out.done) == [5]
    assert [[x.item.id for x in g.lines] for g in out.groups] == [[4]], "a done new post leaves its goal group"

    items[5] = summary(5)
    items[1] = summary(1, ItemStatus.done)
    assert _ids(layout(QUEUE, items, {}).top) == [2, 3, 4]
    items[4] = summary(4, ItemStatus.done)
    out = layout(QUEUE, items, {})
    assert _ids(out.top) == [2, 3, 5] and _ids(out.done) == [1, 4], "a new post done after moving up is under Done"
    assert out.groups == []

    items[6] = summary(6, ItemStatus.done)
    assert _ids(layout(QUEUE, items, {}).done) == [1, 4], "a carryover reached once the top is full stays out"
    items[5] = summary(5, ItemStatus.done)
    out = layout(QUEUE, items, {})
    assert _ids(out.top) == [2, 3] and _ids(out.done) == [1, 4, 5, 6]


def test_archived_and_reprocessing_posts_appear_nowhere() -> None:
    items = {i: summary(i) for i in range(1, 7)}
    items[2] = summary(2, ItemStatus.archived)
    items[5] = summary(5, ItemStatus.queued)
    del items[3]
    out = layout(QUEUE, items, {})
    assert _ids(out.top) == [1, 4, 6] and out.done == [] and out.groups == []
    assert [p.refill for p in out.top] == [False, True, True]


def test_groups_sort_goals_then_places_with_the_catch_alls_last() -> None:
    queue = [QueueEntry(i, DigestRole.new, None, None, None) for i in range(1, 9)]
    items = {
        1: summary(1),
        2: summary(2),
        3: summary(3),
        4: summary(4, matched_goal_title="Cook more"),
        5: summary(5, matched_goal_title="Apps"),
        6: summary(6, item_type=ItemType.place),
        7: summary(7, item_type=ItemType.place),
        8: summary(8),
    }
    out = layout(queue, items, {7: "Chelsea, New York"})
    assert [(g.kind, g.heading, [x.item.id for x in g.lines]) for g in out.groups] == [
        ("goal", "Apps", [5]),
        ("goal", "Cook more", [4]),
        ("goal", "Other", [8]),
        ("places", "Chelsea, New York", [7]),
        ("places", "Elsewhere", [6]),
    ]
    assert out.groups[0].lines[0].line == "Summary 5"


def test_to_text_is_plain() -> None:
    view = digest.DigestView(
        id=1,
        period_start=T0,
        period_end=T0,
        created_at=T0,
        model="fake",
        sent_at=None,
        opening="A week for tacos.",
        top=[digest.DigestPick(item=summary(1, title="[x](https://evil)"), why="w", next_action="n", refill=False)],
        done=[],
        groups=[digest.DigestGroup(kind="goal", heading="Other", lines=[digest.DigestLine(item=summary(2), line="l")])],
        item_ids=[1, 2],
    )
    assert to_text(view) == (
        "A week for tacos.\n\nTo act on this week\n1. [x](https://evil) (#1)\n   w\n   Next: n\n\nOther\n- Item 2 (#2): l"
    )


def test_only_shown_entries_count_toward_the_repeat_limit(rt: Runtime, clock: Clock) -> None:
    with db.write_session() as s:
        for i in (1, 2, 3):
            s.add(
                Item(
                    id=i,
                    source=Source.instagram,
                    canonical_id=f"C{i}",
                    url=f"https://www.instagram.com/reel/C{i}/",
                    clean_url=f"https://www.instagram.com/reel/C{i}/",
                    origin_channel=Channel.web,
                    received_at=clock(),
                    status=ItemStatus.kept,
                )
            )
        s.add(Digest(id=1, period_start=clock(), period_end=clock(), created_at=clock(), model="fake"))
        s.flush()
        for position, (i, role) in enumerate([(1, DigestRole.pick), (2, DigestRole.new), (3, DigestRole.carryover)], 1):
            s.add(DigestEntry(digest_id=1, item_id=i, position=position, role=role))
    counts = {c.id: c.times_surfaced for c in queries.digest_candidates()}
    assert counts == {1: 1, 2: 1, 3: 0}


def test_due_on_startup_after_a_missed_sunday() -> None:
    monday = datetime(2026, 10, 19, 14, 0, tzinfo=UTC)
    last_sunday_fire = digest.last_fire_before("0 18 * * SUN", "America/New_York", monday)
    assert last_sunday_fire is not None and last_sunday_fire.weekday() == 6
    assert digest.due_on_startup(None, "0 18 * * SUN", "America/New_York", monday)
    assert not digest.due_on_startup(monday, "0 18 * * SUN", "America/New_York", monday)
