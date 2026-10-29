from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import event
from sqlmodel import Session, col, select

from sift import db, digest
from sift.domain import BriefState, Channel, FailureKind, ItemStatus, Origin, ProcessingError
from sift.inbox import intake
from sift.items import queries, store
from sift.items.lifecycle import UserAction
from sift.items.queries import ItemFilter, Shelf
from sift.items.views import ItemDetail
from sift.llm.client import LLM
from sift.llm.fake import FakeLLM
from sift.llm.schemas import (
    BriefDraft,
    BriefInput,
    NewTopic,
    OutlineDraft,
    OutlineInput,
    TopicPlanDraft,
    TopicPlanInput,
)
from sift.models import Item, Outline, OutlineLabel, Topic, TopicMergeSuggestion
from sift.organize import model
from sift.organize import store as organize
from sift.organize.organizer import OUTLINE_ATTEMPTS, Organizer
from sift.runtime import Runtime
from sift.web import services
from tests.conftest import Clock
from tests.fakes import FakeFetcher

TACOS = "Best tacos in the East Village. The al pastor at this spot is worth the line."
BIRRIA = "Birria tacos in the East Village restaurant. Get the consomme on the side."
NOISE = "Monday motivation: grind harder, sleep less."


async def post(rt: Runtime, clock: Clock, fetcher: FakeFetcher, code: str, caption: str = TACOS) -> int:
    fetcher.caption = caption
    [r] = intake.submit(f"https://www.instagram.com/reel/{code}/", Origin(Channel.cli), clock(), llm_ready=True)
    assert isinstance(r, intake.Queued)
    await rt.worker.run_item(r.item.id)
    clock.advance(minutes=1)
    return r.item.id


def settle(org: Organizer, llm: LLM, *, limit: int = 100) -> int:
    steps = 0
    while org.step(llm, import_running=False):
        steps += 1
        assert steps < limit, "organizer never went idle"
    return steps


def proposing(name: str) -> model.Outline:
    return model.Outline("g", ("p",), (), model.ProposedTopic(name, model.slug(name), ""))


def outline_row(item_id: int) -> Outline:
    with db.read_session() as s:
        row = s.get(Outline, item_id)
        assert row is not None
        return row


def topics() -> list[Topic]:
    with db.read_session() as s:
        return list(s.exec(select(Topic).order_by(col(Topic.id))).all())


def kept(*, topic_id: int | None = None, label: str | None = None) -> list[queries.ItemSummary]:
    f = ItemFilter(statuses=frozenset(ItemStatus), shelf=Shelf.kept, topic_id=topic_id, label=label)
    return queries.list_items(f, llm_ready=True)


def item(item_id: int) -> ItemDetail:
    detail = queries.get_item(item_id, llm_ready=True)
    assert detail is not None
    return detail


MEMBERS_QUERY = "coalesce(outlines.topic_override_id, outlines.topic_id) IN"


@contextmanager
def statements() -> Iterator[list[str]]:
    seen: list[str] = []

    def hook(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        seen.append(statement)

    event.listen(db.engine(), "before_cursor_execute", hook)
    try:
        yield seen
    finally:
        event.remove(db.engine(), "before_cursor_execute", hook)


class Refusing(FakeLLM):
    def __init__(self) -> None:
        self.outlined: list[str] = []

    def outline(self, inp: OutlineInput) -> tuple[OutlineDraft, str]:
        self.outlined.append(inp.card.title)
        if "Best tacos" in inp.card.title:
            raise ProcessingError(FailureKind.llm_failed, "declined", retryable=False)
        return super().outline(inp)


async def test_new_posts_get_a_gist_labels_and_a_topic(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    a = await post(rt, clock, fetcher, "A1")
    b = await post(rt, clock, fetcher, "B1", BIRRIA)
    org = Organizer(clock)
    settle(org, FakeLLM())

    rows = {r.id: r for r in kept()}
    topic = rows[a].topic
    assert rows[a].gist and rows[a].labels and topic is not None
    assert rows[b].topic == topic
    assert outline_row(a).model == "fake"
    with db.read_session() as s:
        assert {lb.label for lb in s.exec(select(OutlineLabel).where(OutlineLabel.item_id == a)).all()} == set(
            rows[a].labels
        )
    only_a = next(label for label in rows[a].labels if label not in rows[b].labels)
    assert [r.id for r in kept(label=only_a)] == [a]
    assert {r.id for r in kept(topic_id=topic.id)} == {a, b}


async def test_the_first_backfill_seeds_topics_from_a_batch(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    for i in range(model.SEED_MIN_POSTS):
        await post(rt, clock, fetcher, f"S{i}", f"Taco number {i} in the East Village restaurant spot.")
    calls: list[TopicPlanInput] = []

    class Counting(FakeLLM):
        def plan_topics(self, inp: TopicPlanInput) -> tuple[TopicPlanDraft, str]:
            calls.append(inp)
            return super().plan_topics(inp)

    org = Organizer(clock)
    org.step(Counting(), import_running=False)
    assert len(calls) == 1 and len(calls[0].posts) == model.SEED_MIN_POSTS
    assert [t.name for t in topics()] == ["Places"]


async def test_a_seed_that_names_no_topics_runs_once(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    for i in range(model.SEED_MIN_POSTS):
        await post(rt, clock, fetcher, f"S{i}", f"Taco number {i} in the East Village restaurant spot.")
    calls: list[TopicPlanInput] = []

    class Empty(FakeLLM):
        def plan_topics(self, inp: TopicPlanInput) -> tuple[TopicPlanDraft, str]:
            calls.append(inp)
            return TopicPlanDraft(new_topics=[], merges=[]), "fake"

    settle(Organizer(clock), Empty())
    assert len(calls) == 1
    assert organize.next_outline_targets(10) == []


async def test_backfill_outlines_kept_posts_first_then_newest(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    old = await post(rt, clock, fetcher, "OLD")
    noise = await post(rt, clock, fetcher, "NOISE", NOISE)
    new = await post(rt, clock, fetcher, "NEW", BIRRIA)
    assert item(noise).status is ItemStatus.archived
    assert [t.item_id for t in organize.next_outline_targets(10)] == [new, old, noise]


async def test_reprocess_hides_the_old_outline_and_keeps_the_move(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    a = await post(rt, clock, fetcher, "A1")
    org = Organizer(clock)
    settle(org, FakeLLM())
    with db.write_session() as s:
        s.add(Topic(name="Date night", slug="date night", created_at=clock(), updated_at=clock()))
    other = next(t for t in topics() if t.name == "Date night")
    assert other.id is not None
    organize.move_item(a, other.id, clock())

    store.apply_action(a, UserAction.reprocess, clock(), llm_ready=True)
    queued = queries.get_item(a, llm_ready=True)
    assert queued is not None and queued.gist is None and queued.organization is None

    await rt.worker.run_item(a)
    settle(org, FakeLLM())
    detail = queries.get_item(a, llm_ready=True)
    assert detail is not None and detail.organization is not None
    assert detail.topic is not None and detail.topic.id == other.id
    assert detail.organization.topic_chosen_by == "you"


async def test_an_outline_is_dropped_when_the_item_changed_during_the_call(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    a = await post(rt, clock, fetcher, "A1")
    [target] = organize.next_outline_targets(5)
    stale = organize.OutlineTarget(a, target.extracted_at - timedelta(seconds=1))
    pick = model.Outline("g", ("p",), (), model.Unsorted())
    assert organize.record_outline(stale, pick, "fake", clock()) is False
    with db.read_session() as s:
        assert s.get(Outline, a) is None


async def test_an_outline_follows_a_merge_or_dissolve_that_landed_during_the_call(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    a = await post(rt, clock, fetcher, "A1")
    b = await post(rt, clock, fetcher, "B1", BIRRIA)
    now = clock()
    with db.write_session() as s:
        for name in ("Tacos", "Mexican food", "Burritos"):
            s.add(Topic(name=name, slug=model.slug(name), created_at=now, updated_at=now))
    tacos, mexican, burritos = (t.id for t in topics())
    assert tacos and mexican and burritos
    [ta, tb] = sorted(organize.next_outline_targets(5), key=lambda t: t.item_id)

    organize.merge_topics(tacos, mexican, now)
    assert organize.record_outline(ta, model.Outline("g", ("p",), (), model.ExistingTopic(tacos)), "fake", now)
    assert outline_row(a).topic_id == mexican and not outline_row(a).needs_topic

    organize.dissolve_topic(burritos, now)
    assert organize.record_outline(tb, model.Outline("g", ("p",), (), model.ExistingTopic(burritos)), "fake", now)
    assert outline_row(b).topic_id is None and outline_row(b).needs_topic
    assert b in {t.item_id for t in organize.next_outline_targets(5)}


async def test_a_dissolved_name_is_never_recreated(rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher) -> None:
    a = await post(rt, clock, fetcher, "A1")
    org = Organizer(clock)
    settle(org, FakeLLM())
    [places] = topics()
    assert places.id is not None
    gone = organize.dissolve_topic(places.id, clock())
    assert gone.rehoming == 1
    clock.advance(minutes=1)
    settle(org, FakeLLM())
    assert [t.name for t in topics()] == ["Places"]
    assert outline_row(a).topic_id is None and not outline_row(a).needs_topic
    assert item(a).status is ItemStatus.kept


async def brief_two_twins(rt: Runtime, clock: Clock, fetcher: FakeFetcher) -> tuple[int, int, int, Organizer]:
    first = await post(rt, clock, fetcher, "TWIN1")
    second = await post(rt, clock, fetcher, "TWIN2")
    org = Organizer(clock)
    settle(org, FakeLLM())
    [topic] = topics()
    assert topic.id is not None
    organize.request_brief(topic.id, clock())
    settle(org, FakeLLM())
    return first, second, topic.id, org


async def test_identical_posts_fold_and_covered_by_is_always_sent(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    first, second, topic_id, _ = await brief_two_twins(rt, clock, fetcher)
    covered_by = {r.id: r.covered_by for r in kept()}
    assert covered_by[first] is None
    cover = covered_by[second]
    assert cover is not None and cover.id == first

    detail = queries.get_item(first, llm_ready=True)
    assert detail is not None and detail.organization is not None
    assert [c.id for c in detail.organization.covers] == [second] and detail.organization.cited_in == 1
    topic = organize.get_topic(topic_id)
    assert topic is not None and topic.folded == 1 and topic.brief is not None
    assert topic.freshness.posts == topic.freshness.in_brief == 2
    numbers = {src.item.id: src.n for src in topic.brief.sources}
    assert {src.item.id: src.covered_by for src in topic.brief.sources} == {first: None, second: numbers[first]}
    assert topic.brief.sections[0].points[0].corroborated


async def test_a_fold_stops_applying_when_either_post_changes(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    first, second, _, _ = await brief_two_twins(rt, clock, fetcher)
    with db.write_session() as s:
        s.add(Topic(name="Elsewhere", slug="elsewhere", created_at=clock(), updated_at=clock()))
    elsewhere = next(t.id for t in topics() if t.name == "Elsewhere")
    assert elsewhere is not None
    organize.move_item(second, elsewhere, clock())
    assert {r.id: r.covered_by for r in kept()}[second] is None

    organize.move_item(second, None, clock())
    assert {r.id: r.covered_by for r in kept()}[second] is not None
    store.apply_action(first, UserAction.archive, clock(), llm_ready=True)
    assert {r.id: r.covered_by for r in kept()}[second] is None


async def test_a_move_outlasts_a_merge_and_merging_twice_is_a_no_op(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    a = await post(rt, clock, fetcher, "A1")
    now = clock()
    with db.write_session() as s:
        for name in ("Tacos", "Mexican food"):
            s.add(Topic(name=name, slug=model.slug(name), created_at=now, updated_at=now))
    org = Organizer(clock)
    settle(org, FakeLLM())
    tacos, mexican = (t.id for t in topics() if t.name in ("Tacos", "Mexican food"))
    assert tacos and mexican
    organize.move_item(a, tacos, now)

    detail = organize.merge_topics(tacos, mexican, now)
    assert detail.id == mexican and outline_row(a).topic_override_id == mexican
    assert organize.merge_topics(tacos, mexican, now).id == mexican
    alias = organize.get_topic(tacos)
    assert alias is not None and alias.id == mexican
    with pytest.raises(organize.Conflict):
        organize.merge_topics(mexican, tacos, now)

    target = organize.OutlineTarget(a, outline_row(a).extracted_at)
    pick = model.normalize_outline(
        OutlineDraft(
            gist="g", key_points=["p"], labels=[], topic_id=None, new_topic=NewTopic(name="Tacos", description="")
        ),
        [],
    )
    assert organize.record_outline(target, pick, "fake", now)
    assert outline_row(a).topic_id == mexican


async def test_a_requested_brief_beats_backfill_and_holds_busy(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    await post(rt, clock, fetcher, "TWIN1")
    await post(rt, clock, fetcher, "TWIN2")
    org = Organizer(clock)
    settle(org, FakeLLM())
    [topic] = topics()
    assert topic.id is not None
    late = await post(rt, clock, fetcher, "LATE", BIRRIA)
    organize.request_brief(topic.id, clock())
    before = services.status(rt)
    assert before.pulse.busy

    org.step(FakeLLM(), import_running=False)
    assert topics()[0].brief is not None
    with db.read_session() as s:
        assert s.get(Outline, late) is None
    after = services.status(rt)
    assert not after.pulse.busy and after.pulse.revision != before.pulse.revision


async def test_briefs_wait_for_the_topic_to_settle(rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher) -> None:
    await post(rt, clock, fetcher, "TWIN1")
    await post(rt, clock, fetcher, "TWIN2")
    org = Organizer(clock)
    settle(org, FakeLLM())
    assert topics()[0].brief is None and topics()[0].dirty_since is not None
    clock.advance(seconds=model.BRIEF_SETTLE.total_seconds())
    assert not org.step(FakeLLM(), import_running=True)
    assert org.step(FakeLLM(), import_running=False)
    assert topics()[0].brief is not None and topics()[0].dirty_since is None


async def test_a_brief_for_a_merged_topic_is_dropped(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    await post(rt, clock, fetcher, "TWIN1")
    await post(rt, clock, fetcher, "TWIN2")
    org = Organizer(clock)
    settle(org, FakeLLM())
    with db.write_session() as s:
        s.add(Topic(name="Food", slug="food", created_at=clock(), updated_at=clock()))
    places, food = topics()
    assert places.id and food.id
    organize.request_brief(places.id, clock())
    [target] = organize.brief_targets(clock(), import_running=False)
    prepared = organize.brief_input(target.topic_id)
    assert prepared is not None
    organize.merge_topics(places.id, food.id, clock())
    brief = model.parse_brief(FakeLLM().compose_brief(prepared.inp)[0], prepared.numbered)
    assert organize.record_brief(target, prepared.basis, brief, "fake", clock()) is False
    assert all(t.brief is None for t in topics())


async def test_the_digest_leaves_out_a_covered_post(rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher) -> None:
    first, second, _, _ = await brief_two_twins(rt, clock, fetcher)
    cands = {c.id: c for c in queries.digest_candidates()}
    assert cands[second].covered_by == first
    sel = digest.select_items(list(cands.values()), None)
    assert [c.id for c in sel.new] == [first]


async def test_merge_suggestions_wait_for_you_and_a_dismissal_sticks(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    now = clock()
    with db.write_session() as s:
        for name in ("Place", "Places"):
            s.add(Topic(name=name, slug=model.slug(name), created_at=now, updated_at=now))
    org = Organizer(clock)
    assert org.step(FakeLLM(), import_running=False)
    view = organize.list_topics()
    [suggestion] = view.suggestions
    assert {suggestion.source.name, suggestion.into.name} == {"Place", "Places"}
    assert all(t.merged_into_id is None for t in topics())

    for name in ("Other", "More"):
        clock.advance(minutes=1)
        with db.write_session() as s:
            s.add(Topic(name=name, slug=name.casefold(), created_at=clock(), updated_at=clock()))
        assert org.step(FakeLLM(), import_running=False)
        if name == "Other":
            assert organize.list_topics().suggestions == [suggestion]
            organize.dismiss_suggestion(suggestion.source.id, suggestion.into.id, clock())
    assert organize.list_topics().suggestions == []
    with db.read_session() as s:
        assert len(s.exec(select(TopicMergeSuggestion)).all()) == 1
    assert not org.step(FakeLLM(), import_running=False)


async def test_an_unsorted_kept_post_is_retried_after_the_topics_change(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    a = await post(rt, clock, fetcher, "A1")
    noise = await post(rt, clock, fetcher, "NOISE", NOISE)
    for target in organize.next_outline_targets(5):
        assert organize.record_outline(target, model.Outline("g", ("p",), (), model.Unsorted()), "fake", clock())
    assert organize.next_outline_targets(5) == []
    clock.advance(minutes=1)
    with db.write_session() as s:
        s.add(Topic(name="Places", slug="places", created_at=clock(), updated_at=clock()))
    assert [t.item_id for t in organize.next_outline_targets(5)] == [a]

    store.apply_action(noise, UserAction.keep, clock(), llm_ready=True)
    assert {t.item_id for t in organize.next_outline_targets(5)} == {a, noise}


async def test_a_taxonomy_change_gives_a_blocked_unsorted_post_fresh_attempts(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    await post(rt, clock, fetcher, "A1")
    [target] = organize.next_outline_targets(5)
    assert organize.record_outline(target, model.Outline("g", ("p",), (), model.Unsorted()), "fake", clock())
    org, llm = Organizer(clock), Refusing()
    for name in ("Places", "Food"):
        clock.advance(minutes=1)
        with db.write_session() as s:
            s.add(Topic(name=name, slug=name.casefold(), created_at=clock(), updated_at=clock()))
        for _ in range(OUTLINE_ATTEMPTS + 1):
            settle(org, llm)
            clock.advance(minutes=31)
    assert len(llm.outlined) == 2 * OUTLINE_ATTEMPTS


async def test_a_failing_post_backs_off_alone(rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher) -> None:
    bad = await post(rt, clock, fetcher, "BAD")
    good = await post(rt, clock, fetcher, "GOOD", BIRRIA)
    org = Organizer(clock)
    settle(org, Refusing())
    with db.read_session() as s:
        assert s.get(Outline, bad) is None and s.get(Outline, good) is not None
    clock.advance(minutes=31)
    settle(org, FakeLLM())
    assert outline_row(bad).gist


async def test_the_worker_organizes_when_nothing_can_be_claimed(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    a = await post(rt, clock, fetcher, "A1")
    claimed, outcome = await rt.worker.step()
    assert claimed and outcome is None
    assert outline_row(a).gist


async def test_failing_posts_never_starve_the_rest(rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher) -> None:
    good = await post(rt, clock, fetcher, "GOOD", BIRRIA)
    for i in range(30):
        await post(rt, clock, fetcher, f"BAD{i}")
    settle(Organizer(clock), Refusing())
    assert outline_row(good).gist


async def test_a_post_that_keeps_failing_stops_costing_calls_until_reprocessed(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    bad = await post(rt, clock, fetcher, "BAD")
    org, llm = Organizer(clock), Refusing()
    for _ in range(OUTLINE_ATTEMPTS + 2):
        settle(org, llm)
        clock.advance(minutes=31)
    assert len(llm.outlined) == OUTLINE_ATTEMPTS

    store.apply_action(bad, UserAction.reprocess, clock(), llm_ready=True)
    await rt.worker.run_item(bad)
    settle(org, FakeLLM())
    assert outline_row(bad).gist
    assert not org._outline_failures


async def test_asking_again_after_a_failed_brief_retries_at_once(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    await post(rt, clock, fetcher, "TWIN1")
    await post(rt, clock, fetcher, "TWIN2")
    org = Organizer(clock)
    settle(org, FakeLLM())
    [topic] = topics()
    assert topic.id is not None

    class Down(FakeLLM):
        def compose_brief(self, inp: BriefInput) -> tuple[BriefDraft, str]:
            raise ProcessingError(FailureKind.llm_failed, "outage", retryable=True)

    organize.request_brief(topic.id, clock())
    assert org.step(Down(), import_running=False)
    assert topics()[0].brief is None and not services.status(rt).pulse.busy

    clock.advance(minutes=1)
    organize.request_brief(topic.id, clock())
    assert org.step(FakeLLM(), import_running=False)
    assert topics()[0].brief is not None and not services.status(rt).pulse.busy


async def test_a_dismissed_pair_is_never_suggested_the_other_way(rt: Runtime, clock: Clock) -> None:
    now = clock()
    with db.write_session() as s:
        for name in ("Place", "Places"):
            s.add(Topic(name=name, slug=model.slug(name), created_at=now, updated_at=now))
    a, b = (t.id for t in topics())
    assert a and b
    organize.record_suggestions([(a, b)], now)
    organize.dismiss_suggestion(a, b, now)
    organize.record_suggestions([(b, a)], now)
    assert organize.list_topics().suggestions == []
    check = organize.merge_check(since=None)
    assert check is not None and check.dismissed == {frozenset((a, b))}


async def test_only_kept_posts_create_topics_up_to_a_cap_on_live_topics(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(organize, "MAX_TOPICS", 2)
    a = await post(rt, clock, fetcher, "A1")
    b = await post(rt, clock, fetcher, "B1", BIRRIA)
    noise = await post(rt, clock, fetcher, "NOISE", NOISE)
    assert item(noise).status is ItemStatus.archived
    now = clock()
    targets = {t.item_id: t for t in organize.next_outline_targets(5)}

    inp = organize.outline_input(targets[noise])
    assert inp is not None and not inp.may_create_topic
    assert organize.record_outline(targets[noise], proposing("Grind"), "fake", now)
    assert outline_row(noise).topic_id is None and topics() == []

    inp = organize.outline_input(targets[a])
    assert inp is not None and inp.may_create_topic
    assert organize.record_outline(targets[a], proposing("Tacos"), "fake", now)
    [tacos] = topics()
    assert outline_row(a).topic_id == tacos.id
    assert organize.record_outline(targets[noise], proposing("Tacos"), "fake", now)
    assert outline_row(noise).topic_id == tacos.id

    with db.write_session() as s:
        s.add(Topic(name="Empty", slug="empty", created_at=now, updated_at=now))
    inp = organize.outline_input(targets[b])
    assert inp is not None and not inp.may_create_topic
    assert organize.record_outline(targets[b], proposing("Birria"), "fake", now)
    assert outline_row(b).topic_id is None


async def test_an_idle_step_reads_each_topic_s_members_once_without_their_text(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    await post(rt, clock, fetcher, "TWIN1")
    await post(rt, clock, fetcher, "TWIN2")
    org = Organizer(clock)
    settle(org, FakeLLM())
    with statements() as sql:
        assert not org.step(FakeLLM(), import_running=False)
    assert sum(MEMBERS_QUERY in q for q in sql) == 1
    assert not any("items.transcript" in q for q in sql)


async def test_the_item_page_reads_the_topic_s_members_once(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    first, second, _, _ = await brief_two_twins(rt, clock, fetcher)
    with statements() as sql:
        detail = item(second)
    assert detail.covered_by is not None and detail.covered_by.id == first
    assert detail.organization is not None and detail.organization.covered_by == detail.covered_by
    assert sum(MEMBERS_QUERY in q for q in sql) == 1


async def test_a_brief_records_the_members_it_read(rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher) -> None:
    await post(rt, clock, fetcher, "TWIN1")
    await post(rt, clock, fetcher, "TWIN2")
    third = await post(rt, clock, fetcher, "THIRD", BIRRIA)
    settle(Organizer(clock), FakeLLM())
    [topic] = topics()
    assert topic.id is not None
    organize.request_brief(topic.id, clock())
    [target] = organize.brief_targets(clock(), import_running=False)
    store.apply_action(third, UserAction.archive, clock(), llm_ready=True)

    prepared = organize.brief_input(topic.id)
    assert prepared is not None and len(prepared.numbered.members) == 2
    brief = model.parse_brief(FakeLLM().compose_brief(prepared.inp)[0], prepared.numbered)
    assert organize.record_brief(target, prepared.basis, brief, "fake", clock())
    detail = organize.get_topic(topic.id)
    assert detail is not None and detail.brief_state is BriefState.fresh


async def test_a_label_filter_ignores_a_stale_outline(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    a = await post(rt, clock, fetcher, "A1")
    org = Organizer(clock)
    settle(org, FakeLLM())
    label = item(a).labels[0]
    assert [r.id for r in kept(label=label)] == [a]

    store.apply_action(a, UserAction.reprocess, clock(), llm_ready=True)
    await rt.worker.run_item(a)
    assert item(a).status is ItemStatus.kept and item(a).gist is None
    assert kept(label=label) == []


async def test_a_label_filter_normalizes_like_outlines(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    a = await post(rt, clock, fetcher, "A1")
    settle(Organizer(clock), FakeLLM())
    label = item(a).labels[0]
    assert [r.id for r in kept(label=f" #{label.upper()}. ")] == [a]
    assert kept(label="#") == []


async def test_decor_and_covers_never_load_post_text(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    first, second, _, _ = await brief_two_twins(rt, clock, fetcher)
    with db.read_session() as s:
        rows = s.exec(select(Item, Outline).join(Outline, col(Outline.item_id) == col(Item.id))).all()
        with statements() as sql:
            decor = organize.decor(s, rows)
            covered = organize.covered_items(s)
    cover = decor[second].covered_by
    assert cover is not None and cover.id == first and covered == {second: first}
    assert sql and not any("transcript" in q for q in sql)


async def test_a_brief_covers_the_top_posts_and_ignores_changes_to_the_rest(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(model, "BRIEF_MAX_SOURCES", 2)
    oldest = await post(rt, clock, fetcher, "TWIN1")
    await post(rt, clock, fetcher, "TWIN2")
    await post(rt, clock, fetcher, "THIRD", BIRRIA)
    org = Organizer(clock)
    settle(org, FakeLLM())
    [topic] = topics()
    assert topic.id is not None
    organize.request_brief(topic.id, clock())
    settle(org, FakeLLM())
    detail = organize.get_topic(topic.id)
    assert detail is not None and detail.brief_state is BriefState.fresh
    assert (detail.freshness.posts, detail.freshness.in_brief) == (3, 2)

    store.apply_action(oldest, UserAction.archive, clock(), llm_ready=True)
    clock.advance(seconds=model.BRIEF_MAX_WAIT.total_seconds())
    assert not org.step(FakeLLM(), import_running=False)
    detail = organize.get_topic(topic.id)
    assert detail is not None and detail.brief_state is BriefState.fresh
    assert (detail.freshness.posts, detail.freshness.in_brief) == (2, 2)


async def test_settling_briefs_never_overwrites_a_move_that_landed_after_the_read(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, second, topic_id, _ = await brief_two_twins(rt, clock, fetcher)
    with db.write_session() as s:
        s.add(Topic(name="Elsewhere", slug="elsewhere", created_at=clock(), updated_at=clock()))
    elsewhere = next(t.id for t in topics() if t.name == "Elsewhere")
    assert elsewhere is not None
    organize.move_item(second, elsewhere, clock())
    original = db.write_session

    @contextmanager
    def move_back_first() -> Iterator[Session]:
        monkeypatch.setattr(db, "write_session", original)
        organize.move_item(second, None, clock())
        with original() as s:
            yield s

    monkeypatch.setattr(db, "write_session", move_back_first)
    organize.brief_targets(clock(), import_running=False)
    detail = organize.get_topic(topic_id)
    assert detail is not None and detail.brief is not None and detail.brief_state is BriefState.fresh


class CountingBriefs(FakeLLM):
    def __init__(self, fail: bool = False) -> None:
        self.briefs = 0
        self.fail = fail

    def compose_brief(self, inp: BriefInput) -> tuple[BriefDraft, str]:
        self.briefs += 1
        if self.fail:
            raise ProcessingError(FailureKind.llm_failed, "outage", retryable=True)
        return super().compose_brief(inp)


async def two_posts_on_a_topic(rt: Runtime, clock: Clock, fetcher: FakeFetcher) -> tuple[int, Organizer]:
    await post(rt, clock, fetcher, "TWIN1")
    await post(rt, clock, fetcher, "TWIN2")
    org = Organizer(clock)
    settle(org, FakeLLM())
    [topic] = topics()
    assert topic.id is not None
    return topic.id, org


async def test_a_brief_that_fails_to_record_drops_the_request_and_backs_off(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    topic_id, org = await two_posts_on_a_topic(rt, clock, fetcher)

    def broken(*_: object) -> bool:
        raise RuntimeError("disk full")

    monkeypatch.setattr(organize, "record_brief", broken)
    llm = CountingBriefs()
    clock.advance(minutes=10)
    organize.request_brief(topic_id, clock())
    assert org.step(llm, import_running=False)
    assert not services.status(rt).pulse.busy

    clock.advance(seconds=model.BRIEF_SETTLE.total_seconds() - 9 * 60)
    assert organize.brief_targets(clock(), import_running=False) != []
    assert not org.step(llm, import_running=False)
    assert llm.briefs == 1


async def test_a_failed_drop_never_hides_the_brief_error_or_skips_the_backoff(
    rt: Runtime,
    clock: Clock,
    goal: int,
    fetcher: FakeFetcher,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    topic_id, org = await two_posts_on_a_topic(rt, clock, fetcher)

    def locked(*_: object) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(organize, "drop_request", locked)
    llm = CountingBriefs(fail=True)
    organize.request_brief(topic_id, clock())
    assert org.step(llm, import_running=False)
    assert "outage" in caplog.text
    assert not org.step(llm, import_running=False)
    assert llm.briefs == 1


async def test_a_brief_requested_while_one_is_written_runs_next(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    topic_id, org = await two_posts_on_a_topic(rt, clock, fetcher)

    class AskedAgain(FakeLLM):
        def compose_brief(self, inp: BriefInput) -> tuple[BriefDraft, str]:
            organize.request_brief(topic_id, clock.advance(seconds=1))
            return super().compose_brief(inp)

    organize.request_brief(topic_id, clock())
    assert org.step(AskedAgain(), import_running=False)
    detail = organize.get_topic(topic_id)
    assert detail is not None and detail.brief is not None and detail.brief_state is BriefState.writing
    assert services.status(rt).pulse.busy

    assert org.step(FakeLLM(), import_running=False)
    detail = organize.get_topic(topic_id)
    assert detail is not None and detail.brief_state is BriefState.fresh


async def test_a_seed_that_fails_to_record_is_retried(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    for i in range(model.SEED_MIN_POSTS):
        await post(rt, clock, fetcher, f"S{i}", f"Taco number {i} in the East Village restaurant spot.")
    record_seed = organize.record_seed
    failures = [RuntimeError("database is locked")]

    def flaky(*args: Any) -> int:
        if failures:
            raise failures.pop()
        return record_seed(*args)

    monkeypatch.setattr(organize, "record_seed", flaky)
    plans: list[TopicPlanInput] = []

    class Counting(FakeLLM):
        def plan_topics(self, inp: TopicPlanInput) -> tuple[TopicPlanDraft, str]:
            plans.append(inp)
            return super().plan_topics(inp)

    org = Organizer(clock)
    assert org.step(Counting(), import_running=False)
    assert topics() == []
    clock.advance(minutes=31)
    assert org.step(Counting(), import_running=False)
    assert len(plans) == 2 and [t.name for t in topics()] == ["Places"]
