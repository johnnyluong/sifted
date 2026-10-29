from __future__ import annotations

import re

from sift.domain import Decision, GoalCategory, ItemType
from sift.llm.schemas import (
    BriefDraft,
    BriefInput,
    BriefPointDraft,
    BriefSectionDraft,
    Card,
    DigestDraft,
    DigestInput,
    ExtractInput,
    ExtractOutput,
    GoalLine,
    IdeaCard,
    IdeaDetails,
    Ingredient,
    NewTopic,
    OtherCard,
    OtherDetails,
    OutlineDraft,
    OutlineInput,
    PlaceCard,
    PlaceDetails,
    PlaybookCard,
    PlaybookDetails,
    ProductCard,
    ProductDetails,
    ProposedGoal,
    RebuiltTopicDraft,
    RecipeCard,
    RecipeDetails,
    ScoreInput,
    ScoreOutput,
    SetupDraft,
    SetupInput,
    TopicFitDraft,
    TopicFitInput,
    TopicMergeDraft,
    TopicPlanDraft,
    TopicPlanInput,
    TopicRebuildDraft,
    TopicRebuildInput,
    TopPick,
)

MODEL = "fake"

_KEYWORDS: list[tuple[ItemType, re.Pattern[str]]] = [
    (ItemType.recipe, re.compile(r"\b(recipe|ingredients?|tbsp|tsp|cups?|bake|simmer|cook)\b", re.I)),
    (ItemType.place, re.compile(r"\b(restaurant|cafe|café|bar|bakery|menu|reservation|neighborhood|spot)\b", re.I)),
    (ItemType.playbook, re.compile(r"\b(steps?|strategy|playbook|how to|framework|growth|marketing|funnel)\b", re.I)),
    (ItemType.product, re.compile(r"(\$\d|\bprice\b|\bbuy\b|\bproduct\b)", re.I)),
]
_FREE = re.compile(r"\b(free|open[- ]source|github)\b", re.I)
_WORD = re.compile(r"[a-z]{4,}")
_STOP = frozenset({"this", "that", "with", "from", "your", "have", "what", "will", "about", "into", "more", "they"})


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def _sentences(text: str, n: int) -> str:
    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return " ".join(parts[:n])[:400]


def _card(item_type: ItemType, title: str, summary: str, text: str) -> Card:
    lines = [ln.strip("-• ").strip() for ln in text.splitlines() if ln.strip()][:6]
    action = "Review this and decide on one next step."
    match item_type:
        case ItemType.recipe:
            return RecipeCard(
                item_type=ItemType.recipe,
                title=title,
                summary=summary,
                next_action="Cook this once this week.",
                details=RecipeDetails(
                    dish=title,
                    ingredients=[Ingredient(name=ln, amount=None) for ln in lines[1:4]],
                    steps=lines[1:],
                    total_time=None,
                    notes=[],
                ),
            )
        case ItemType.place:
            return PlaceCard(
                item_type=ItemType.place,
                title=title,
                summary=summary,
                next_action="Save it to your maps list.",
                details=PlaceDetails(
                    name=title,
                    kind=None,
                    neighborhood=None,
                    city=None,
                    address=None,
                    why_notable=summary or None,
                    what_to_order_or_do=lines[1:3],
                    price_hint=None,
                    maps_query=title,
                ),
            )
        case ItemType.playbook:
            return PlaybookCard(
                item_type=ItemType.playbook,
                title=title,
                summary=summary,
                next_action=action,
                details=PlaybookDetails(goal=title, steps=lines[1:] or [summary], tools=[], examples=[], caveats=[]),
            )
        case ItemType.product:
            return ProductCard(
                item_type=ItemType.product,
                title=title,
                summary=summary,
                next_action=action,
                details=ProductDetails(
                    name=title, what_it_is=summary, price=None, link=None, wishlist=not _FREE.search(text)
                ),
            )
        case ItemType.idea:
            return IdeaCard(
                item_type=ItemType.idea,
                title=title,
                summary=summary,
                next_action=action,
                details=IdeaDetails(core_idea=summary or title, creator=None, how_to_apply=None),
            )
        case ItemType.other:
            return OtherCard(
                item_type=ItemType.other,
                title=title,
                summary=summary,
                next_action=None,
                details=OtherDetails(key_points=lines[:4]),
            )


_SHELF: dict[ItemType, str] = {
    ItemType.place: "Places",
    ItemType.recipe: "Recipes",
    ItemType.playbook: "Playbooks",
    ItemType.idea: "Ideas",
    ItemType.product: "Products",
    ItemType.other: "Other saves",
}


def _card_points(card: Card) -> list[str]:
    match card.details:
        case PlaceDetails(what_to_order_or_do=items) | PlaybookDetails(steps=items) | RecipeDetails(steps=items):
            points = items
        case OtherDetails(key_points=items):
            points = items
        case _:
            points = []
    return [p for p in points if p.strip()][:5] or [_sentences(card.summary, 1) or card.title]


def _shelf_key(name: str) -> str:
    return name.casefold().rstrip("s")


class FakeLLM:
    def extract(self, inp: ExtractInput) -> tuple[ExtractOutput, str]:
        text = "\n".join(t for t in (inp.caption, inp.post_text, inp.transcript) if t)
        item_type = next((t for t, rx in _KEYWORDS if rx.search(text)), ItemType.idea if text else ItemType.other)
        first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        title = (first[:77] + "...") if len(first) > 80 else (first or "Untitled post")
        summary = _sentences(text, 2) or "No text was found in this post."
        return ExtractOutput(card=_card(item_type, title, summary, text), on_screen_text=None), MODEL

    def score(self, inp: ScoreInput) -> tuple[ScoreOutput, str]:
        card_words = _words(f"{inp.card.title} {inp.card.summary}")
        best_id, best = None, 0
        for g in inp.goals:
            overlap = len(card_words & _words(f"{g.title} {g.description}"))
            if overlap > best:
                best_id, best = g.id, overlap
        value_hits = len(card_words & _words(inp.values_text))
        score = min(100, 30 + 15 * best + 5 * value_hits)
        goal = next((g.title for g in inp.goals if g.id == best_id), None)
        reason = f'Shares themes with your goal "{goal}".' if goal else "No clear link to your active goals."
        decision = Decision.keep if score >= inp.threshold else Decision.archive
        return ScoreOutput(
            relevance_score=score, matched_goal_id=best_id, relevance_reason=reason, decision=decision
        ), MODEL

    def compose_digest(self, inp: DigestInput) -> tuple[DigestDraft, str]:
        ranked = sorted(
            inp.items, key=lambda i: (i.status != "new", i.relevance_score is None, -(i.relevance_score or 0))
        )
        top = [
            TopPick(
                item_id=i.item_id,
                why=f"One of your most relevant saves (score {i.relevance_score}).",
                next_action=i.next_action or "Spend 20 minutes on it.",
            )
            for i in ranked[:3]
        ]
        picked = {p.item_id for p in top}
        lines = [
            GoalLine(item_id=i.item_id, line=i.summary[:140])
            for i in ranked
            if i.item_id not in picked and i.status == "new"
        ]
        return DigestDraft(opening=None, top=top, by_goal=lines), MODEL

    def outline(self, inp: OutlineInput) -> tuple[OutlineDraft, str]:
        card = inp.card
        words = _words(f"{card.title} {card.summary}")
        match = next((t for t in inp.topics if _words(t.name) & words), None)
        shelf = next((t for t in inp.topics if t.name == _SHELF[card.item_type]), match)
        new = None
        if shelf is None and inp.may_create_topic:
            new = NewTopic(name=_SHELF[card.item_type], description=f"Saved {card.item_type.value} posts.")
        labels = sorted(_words(card.title), key=lambda w: (-len(w), w))[:3]
        return OutlineDraft(
            gist=_sentences(card.summary, 1)[:90] or card.title,
            key_points=_card_points(card),
            labels=labels,
            topic_id=shelf.id if shelf else None,
            new_topic=new,
        ), MODEL

    def compose_brief(self, inp: BriefInput) -> tuple[BriefDraft, str]:
        merged: dict[str, BriefPointDraft] = {}
        for source in inp.sources:
            for point in source.points:
                key = " ".join(point.text.casefold().split())
                if key in merged:
                    merged[key].sources.append(point.n)
                else:
                    merged[key] = BriefPointDraft(text=point.text, sources=[point.n])
        return BriefDraft(
            overview=f"{len(inp.sources)} saves on {inp.topic}.",
            sections=[BriefSectionDraft(heading="Key points", points=list(merged.values()))],
        ), MODEL

    def plan_topics(self, inp: TopicPlanInput) -> tuple[TopicPlanDraft, str]:
        types = dict.fromkeys(p.item_type for p in inp.posts)
        new = [NewTopic(name=_SHELF[t], description=f"Saved {t.value} posts.") for t in types]
        by_key: dict[str, list[int]] = {}
        for t in sorted(inp.topics, key=lambda t: -t.posts):
            by_key.setdefault(_shelf_key(t.name), []).append(t.id)
        merges = [TopicMergeDraft(from_id=ids[1], into_id=ids[0]) for ids in by_key.values() if len(ids) > 1]
        return TopicPlanDraft(new_topics=new, merges=merges), MODEL

    def draft_setup(self, inp: SetupInput) -> tuple[SetupDraft, str]:
        areas = next((a.answer.split("; ") for a in inp.answers if a.id == "areas"), [])
        goals = [
            ProposedGoal(
                title=a,
                description=f"Saved posts about {a.lower()} worth acting on.",
                category=GoalCategory.other,
                revises=next((g.id for g in inp.current_goals if g.title.casefold() in a.casefold()), 0),
            )
            for a in areas
            if a.strip()
        ][:5]
        goals = goals or [
            ProposedGoal(
                title="Act on what I save",
                description="Turn saved posts into things I do.",
                category=GoalCategory.personal,
                revises=0,
            )
        ]
        values = "\n".join(a.answer for a in inp.answers if a.id != "areas")
        return SetupDraft(goals=goals, deactivate=[], values_text=values), MODEL

    def rebuild_topics(self, inp: TopicRebuildInput) -> tuple[TopicRebuildDraft, str]:
        shelves: dict[str, list[int]] = {}
        for p in inp.posts:
            shelves.setdefault(_SHELF[p.item_type], []).append(p.id)
        return TopicRebuildDraft(
            topics=[
                RebuiltTopicDraft(
                    name=name,
                    description=f"Saved {name.lower()}.",
                    continues=[t.id for t in inp.topics if _shelf_key(t.name) == _shelf_key(name)],
                    posts=posts,
                )
                for name, posts in shelves.items()
            ]
        ), MODEL

    def fit_topic(self, inp: TopicFitInput) -> tuple[TopicFitDraft, str]:
        words = _words(f"{inp.topic} {inp.description}")
        return TopicFitDraft(posts=[p.id for p in inp.posts if words & _words(f"{p.title} {p.gist}")]), MODEL
