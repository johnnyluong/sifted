from __future__ import annotations

import random
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest

from sift.llm.schemas import (
    BriefDraft,
    BriefPointDraft,
    BriefSectionDraft,
    NewTopic,
    OutlineDraft,
    RebuiltTopicDraft,
    TopicFitDraft,
    TopicMergeDraft,
    TopicPlanDraft,
    TopicRebuildDraft,
)
from sift.organize import model
from sift.organize.model import (
    BRIEF_MAX_WAIT,
    BRIEF_SETTLE,
    Brief,
    BriefCitation,
    BriefClock,
    BriefPoint,
    BriefSection,
    BriefSource,
    ExistingTopic,
    Member,
    ProposedTopic,
    Unsorted,
)

T0 = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def draft(**kw: object) -> OutlineDraft:
    base: dict[str, object] = {"gist": "g", "key_points": ["p"], "labels": [], "topic_id": None, "new_topic": None}
    return OutlineDraft.model_validate(base | kw)


def test_normalize_trims_and_never_rejects() -> None:
    out = model.normalize_outline(
        draft(
            gist="word " * 60,
            key_points=["a", "b", "A", "c", "d", "e", "f", "g"],
            labels=["#SEO", "SEO", "Google  Search Console", "one two three four", ""],
        ),
        [],
    )
    assert len(out.gist) <= model.GIST_MAX and out.gist.endswith("…")
    assert out.key_points == ("a", "b", "c", "d", "e")
    assert out.labels == ("seo", "google search console")


def test_a_post_with_no_points_keeps_its_gist_as_the_one_point() -> None:
    assert model.normalize_outline(draft(gist="Rewrite titles", key_points=[" "]), []).key_points == ("Rewrite titles",)


def test_invented_topic_id_falls_back_to_the_proposal() -> None:
    new = NewTopic(name="The SEO", description="Search.")
    assert model.normalize_outline(draft(topic_id=7), [7]).topic == ExistingTopic(7)
    assert model.normalize_outline(draft(topic_id=999, new_topic=new), [7]).topic == ProposedTopic(
        "The SEO", "seo", "Search."
    )
    assert model.normalize_outline(draft(topic_id=999), [7]).topic == Unsorted()
    assert model.normalize_outline(draft(new_topic=NewTopic(name="!!", description="")), []).topic == Unsorted()


def test_slug_folds_case_punctuation_and_a_leading_the() -> None:
    assert model.slug("SEO & GEO") == "seo geo"
    assert model.slug("The NYC Date Spots") == "nyc date spots"
    assert model.slug("The") == "the"


def member(item_id: int, points: int, *, relevance: int = 70, at: int = 0) -> Member:
    return Member(
        item_id=item_id,
        title=f"Post {item_id}",
        gist="g",
        item_type="idea",
        points=tuple(f"point {item_id}.{i}" for i in range(points)),
        relevance=relevance,
        received_at=T0 + timedelta(minutes=at),
        outlined_at=T0,
    )


def test_parse_brief_drops_unknown_sources_and_uncited_points() -> None:
    numbered = model.number_points([member(1, 2, relevance=90), member(2, 1)])
    assert numbered.by_number == {1: model.PointRef(1, 0), 2: model.PointRef(1, 1), 3: model.PointRef(2, 0)}
    d = BriefDraft(
        overview="o",
        sections=[
            BriefSectionDraft(
                heading="A",
                points=[
                    BriefPointDraft(text="merged", sources=[1, 3, 3, 99]),
                    BriefPointDraft(text="invented", sources=[42]),
                ],
            ),
            BriefSectionDraft(heading="Empty", points=[BriefPointDraft(text="x", sources=[])]),
        ],
    )
    brief = model.parse_brief(d, numbered)
    assert [s.heading for s in brief.sections] == ["A"]
    [point] = brief.sections[0].points
    assert [(c.item_id, c.index, c.text) for c in point.cites] == [(1, 0, "point 1.0"), (2, 0, "point 2.0")]
    assert [(s.item_id, s.points) for s in brief.sources] == [(1, 2), (2, 1)]


def brief_of(points: list[list[tuple[int, int]]], sizes: dict[int, int]) -> Brief:
    return Brief(
        overview="",
        sections=[
            BriefSection(
                heading="h",
                points=[
                    BriefPoint(text="t", cites=[BriefCitation(item_id=i, index=x, text="") for i, x in p])
                    for p in points
                ],
            )
        ],
        sources=[BriefSource(item_id=i, outlined_at=T0, points=n) for i, n in sizes.items()],
    )


@dataclass(frozen=True, slots=True)
class Stamp:
    item_id: int
    relevance: int
    received_at: datetime
    outlined_at: datetime = T0


def ranks(*ids: int, relevance: dict[int, int] | None = None) -> dict[int, Stamp]:
    return {i: Stamp(i, (relevance or {}).get(i, 70), T0 + timedelta(minutes=i)) for i in ids}


def test_a_post_with_an_uncited_point_never_folds() -> None:
    brief = brief_of([[(1, 0), (2, 0)], [(1, 1)], [(1, 2)]], {1: 3, 2: 2})
    assert model.derive_folds(brief, ranks(1, 2)) == {}
    every_point_cited = brief_of([[(1, 0), (2, 0)], [(1, 1), (2, 1)], [(1, 2)]], {1: 3, 2: 2})
    assert model.derive_folds(every_point_cited, ranks(1, 2)) == {2: 1}


def test_equal_posts_fold_under_the_earlier_one_and_never_chain() -> None:
    twins = brief_of([[(1, 0), (2, 0)]], {1: 1, 2: 1})
    assert model.derive_folds(twins, ranks(1, 2)) == {2: 1}
    chain = brief_of([[(1, 0), (2, 0), (3, 0)], [(1, 1), (2, 1)]], {1: 2, 2: 2, 3: 1})
    assert model.derive_folds(chain, ranks(1, 2, 3)) == {2: 1, 3: 1}


def test_folds_only_consider_the_current_sources() -> None:
    twins = brief_of([[(1, 0), (2, 0)]], {1: 1, 2: 1})
    assert model.derive_folds(twins, ranks(2)) == {}


def test_no_cover_is_ever_itself_covered() -> None:
    rng = random.Random(7)
    for _ in range(3000):
        sizes = {m: rng.randint(1, 4) for m in range(1, rng.randint(2, 7) + 1)}
        refs = [(m, i) for m, n in sizes.items() for i in range(n)]
        rng.shuffle(refs)
        points: list[list[tuple[int, int]]] = []
        while refs:
            take = rng.randint(1, 3)
            points.append(refs[:take])
            refs = refs[take:]
        if rng.random() < 0.2 and len(points) > 1:
            points.pop()
        folds = model.derive_folds(
            brief_of(points, sizes), ranks(*sizes, relevance={m: rng.randint(40, 95) for m in sizes})
        )
        assert not set(folds.values()) & set(folds)


def stamp(item_id: int, *, relevance: int = 70, outlined: int = 0) -> Stamp:
    return Stamp(item_id, relevance, T0, T0 + timedelta(seconds=outlined))


def test_basis_changes_on_membership_and_reoutline() -> None:
    base = model.basis([stamp(1), stamp(2)])
    assert model.basis([stamp(2), stamp(1)]) == base
    assert model.basis([stamp(1)]) != base
    assert model.basis([stamp(1), stamp(2), stamp(3)]) != base
    assert model.basis([stamp(1), stamp(2, outlined=1)]) != base


def test_basis_covers_only_the_posts_a_brief_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model, "BRIEF_MAX_SOURCES", 2)
    base = model.basis([stamp(1, relevance=90), stamp(2, relevance=80)])
    assert model.basis([stamp(1, relevance=90), stamp(2, relevance=80), stamp(3, relevance=10)]) == base
    assert model.basis([stamp(1, relevance=90), stamp(2, relevance=80), stamp(3, relevance=85)]) != base
    assert model.basis([stamp(1, relevance=90), stamp(2, relevance=80, outlined=1), stamp(3, relevance=10)]) != base


def test_brief_due_settles_and_waits_for_imports() -> None:
    base = BriefClock(
        brief_basis="old",
        pending_basis="new",
        pending_since=T0,
        dirty_since=T0,
        requested_at=None,
        brief_at=T0 - timedelta(days=1),
    )

    def clock(**changes: object) -> BriefClock:
        return replace(base, **changes)

    assert not model.brief_due(clock(), "new", T0 + timedelta(minutes=10), import_running=False)
    assert model.brief_due(clock(), "new", T0 + BRIEF_SETTLE, import_running=False)
    assert not model.brief_due(clock(), "new", T0 + BRIEF_SETTLE, import_running=True)
    assert model.brief_due(clock(), "new", T0 + BRIEF_MAX_WAIT, import_running=True)
    assert not model.brief_due(clock(brief_basis="new"), "new", T0 + BRIEF_MAX_WAIT, import_running=False)
    assert model.brief_due(clock(brief_basis="new", requested_at=T0), "new", T0, import_running=False)


def test_plan_merges_run_smaller_into_larger_skip_dismissed_and_never_chain() -> None:
    d = TopicPlanDraft(
        new_topics=[NewTopic(name="Places", description="d"), NewTopic(name="places", description="dup")],
        merges=[
            TopicMergeDraft(from_id=1, into_id=2),
            TopicMergeDraft(from_id=2, into_id=3),
            TopicMergeDraft(from_id=4, into_id=4),
            TopicMergeDraft(from_id=5, into_id=99),
            TopicMergeDraft(from_id=6, into_id=7),
        ],
    )
    plan = model.normalize_plan(d, {1: 9, 2: 3, 3: 5, 4: 1, 5: 1, 6: 1, 7: 2}, dismissed={frozenset((6, 7))})
    assert [t.slug for t in plan.new_topics] == ["places"]
    assert plan.merges == ((2, 1),)


def test_a_dismissal_holds_after_the_sizes_flip_the_pair() -> None:
    d = TopicPlanDraft(new_topics=[], merges=[TopicMergeDraft(from_id=7, into_id=6)])
    assert model.normalize_plan(d, {6: 1, 7: 2}, dismissed={frozenset((7, 6))}).merges == ()


def rebuilt(name: str, continues: list[int], posts: list[int]) -> RebuiltTopicDraft:
    return RebuiltTopicDraft(name=name, description=f"{name} posts.", continues=continues, posts=posts)


def test_a_rebuild_folds_repeated_names_and_keeps_only_offered_ids_once() -> None:
    d = TopicRebuildDraft(
        topics=[
            rebuilt("App building", [1, 99], [10, 11, 77]),
            rebuilt("Marketing", [1, 2], [11, 12]),
            rebuilt("  app BUILDING ", [3], [13]),
            rebuilt("!!!", [4], [14]),
            rebuilt("Nothing yet", [], []),
            rebuilt("Unknown ids", [99], [77]),
        ]
    )
    plan = model.normalize_rebuild(d, topic_ids=[1, 2, 3, 4], post_ids=[10, 11, 12, 13, 14, 15], pinned={})
    assert [(t.topic.name, t.continues, t.posts) for t in plan.topics] == [
        ("App building", (1, 3), (10, 11, 13)),
        ("Marketing", (2,), (12,)),
    ]
    assert plan.unsorted == (14, 15)
    assert plan.retiring == (4,)


def test_a_rebuild_keeps_a_post_moved_by_hand_with_the_topic_that_continues_its_pick() -> None:
    d = TopicRebuildDraft(topics=[rebuilt("Food", [1], [10]), rebuilt("NYC outings", [2], [11])])
    plan = model.normalize_rebuild(d, topic_ids=[1, 2, 3], post_ids=[10, 11, 12], pinned={10: 2, 12: 3})
    assert [t.posts for t in plan.topics] == [(), (10, 11)]
    assert plan.unsorted == (12,)


def test_a_rebuild_caps_the_number_of_topics() -> None:
    d = TopicRebuildDraft(topics=[rebuilt(f"Shelf {i}", [], [i]) for i in range(model.MAX_TOPICS + 3)])
    plan = model.normalize_rebuild(d, topic_ids=[], post_ids=list(range(model.MAX_TOPICS + 3)), pinned={})
    assert len(plan.topics) == model.MAX_TOPICS
    assert plan.unsorted == tuple(range(model.MAX_TOPICS, model.MAX_TOPICS + 3))


def test_a_fit_keeps_only_offered_posts_in_their_order() -> None:
    assert model.normalize_fit(TopicFitDraft(posts=[12, 99, 10, 12]), offered=[10, 11, 12]) == (10, 12)
