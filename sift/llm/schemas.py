"""The SDK strips numeric and length bounds from the wire schema and checks them client-side."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, GetCoreSchemaHandler, TypeAdapter
from pydantic_core import CoreSchema, core_schema

from sift.domain import Decision, GoalCategory, ItemType, Source


@dataclass(frozen=True, slots=True)
class Clip:
    n: int

    def __get_pydantic_core_schema__(self, source: Any, handler: GetCoreSchemaHandler) -> CoreSchema:
        return core_schema.no_info_after_validator_function(lambda v: v[: self.n], handler(source))


Short = Annotated[str, Clip(200)]
Line = Annotated[str, Clip(500)]
Para = Annotated[str, Clip(2_000)]
Body = Annotated[str, Clip(10_000)]
Speech = Annotated[str, Clip(30_000)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlaceDetails(_Strict):
    name: Short
    kind: Short | None = Field(description="restaurant, bar, cafe, park, shop, museum, ...")
    neighborhood: Short | None
    city: Short | None
    address: Line | None = Field(description="Only if stated.")
    why_notable: Para | None
    what_to_order_or_do: list[Line]
    price_hint: Short | None
    maps_query: Line = Field(description="A Google Maps search query that finds this place.")


class Ingredient(_Strict):
    name: Line
    amount: Short | None = Field(description="Only if stated, e.g. '2 tbsp'.")


class RecipeDetails(_Strict):
    dish: Short
    ingredients: list[Ingredient]
    steps: list[Line]
    total_time: Short | None
    notes: list[Line]


class PlaybookDetails(_Strict):
    goal: Line = Field(description="What the tactic achieves.")
    steps: list[Line] = Field(description="Ordered.")
    tools: list[Short]
    examples: list[Line]
    caveats: list[Line]


class IdeaDetails(_Strict):
    core_idea: Para
    creator: Short | None
    how_to_apply: Para | None


class ProductDetails(_Strict):
    name: Short
    what_it_is: Para
    price: Short | None
    link: Para | None
    wishlist: bool = Field(
        description="True when it is something I might buy for myself: a physical product, clothing, gear, "
        "home goods, a ticketed or paid event, a paid app or course. False for free software, open-source "
        "repos and services to research."
    )


class OtherDetails(_Strict):
    key_points: list[Line]


class _CardBase(_Strict):
    title: Annotated[str, Clip(120)]
    summary: Para = Field(description="2 to 3 sentences.")
    next_action: Line | None = Field(description="One concrete thing I could do, or null.")


class PlaceCard(_CardBase):
    item_type: Literal[ItemType.place]
    details: PlaceDetails


class RecipeCard(_CardBase):
    item_type: Literal[ItemType.recipe]
    details: RecipeDetails


class PlaybookCard(_CardBase):
    item_type: Literal[ItemType.playbook]
    details: PlaybookDetails


class IdeaCard(_CardBase):
    item_type: Literal[ItemType.idea]
    details: IdeaDetails


class ProductCard(_CardBase):
    item_type: Literal[ItemType.product]
    details: ProductDetails


class OtherCard(_CardBase):
    item_type: Literal[ItemType.other]
    details: OtherDetails


Card = Annotated[
    PlaceCard | RecipeCard | PlaybookCard | IdeaCard | ProductCard | OtherCard, Field(discriminator="item_type")
]

_card_adapter: TypeAdapter[Card] = TypeAdapter(Card)


def parse_card(
    item_type: ItemType, title: str, summary: str | None, next_action: str | None, details: dict[str, Any]
) -> Card:
    return _card_adapter.validate_python(
        {
            "item_type": item_type,
            "title": title,
            "summary": summary or "",
            "next_action": next_action,
            "details": details,
        }
    )


class ExtractOutput(_Strict):
    card: Card
    on_screen_text: Speech | None = Field(
        description="Text read from the images (video frames or slides), verbatim, or null."
    )


class ScoreOutput(_Strict):
    relevance_score: int = Field(ge=0, le=100)
    matched_goal_id: int | None
    relevance_reason: Line = Field(description="One sentence.")
    decision: Decision


class TopPick(_Strict):
    item_id: int
    why: Line = Field(description="Why act on it this week, tied to a goal by name.")
    next_action: Line


class GoalLine(_Strict):
    item_id: int
    line: Line = Field(description="One short bullet.")


class DigestDraft(_Strict):
    opening: Line | None = Field(description="One sentence framing the week, or null.")
    top: list[TopPick] = Field(max_length=3)
    by_goal: list[GoalLine]


class GoalBrief(_Strict):
    id: int
    title: Short
    description: Para
    category: GoalCategory


class ExtractInput(_Strict):
    source: Source
    author_handle: Short | None
    caption: Body | None
    post_text: Body | None
    transcript: Speech | None
    frames: list[str]
    notes: list[Line]


class OverrideExample(_Strict):
    title: Short
    item_type: ItemType
    summary: Para
    system_decision: Decision
    user_decision: Decision
    reason: Para = ""


class ScoreInput(_Strict):
    card: Card
    values_text: Body
    goals: list[GoalBrief]
    examples: list[OverrideExample]
    threshold: int


class DigestItemBrief(_Strict):
    item_id: int
    title: Short
    item_type: ItemType
    summary: Para
    next_action: Line | None
    goal_id: int | None
    relevance_score: int | None
    status: Literal["new", "carryover"]


class DigestInput(_Strict):
    values_text: Body
    goals: list[GoalBrief]
    items: list[DigestItemBrief]


class TopicOption(_Strict):
    id: int
    name: Short
    description: Line
    size: int = Field(description="Posts already on this topic.")


class TopicMoveExample(_Strict):
    title: Short
    from_topic: Short | None
    to_topic: Short


class OutlineInput(_Strict):
    source: Source
    card: Card
    caption: Body | None
    on_screen_text: Body | None
    transcript_excerpt: Body | None
    topics: list[TopicOption]
    may_create_topic: bool
    label_vocabulary: list[Short]
    moves: list[TopicMoveExample]


class NewTopic(_Strict):
    name: Short = Field(
        description="1 to 3 words, the shelf a person would name, e.g. 'Marketing and growth', 'NYC outings'."
    )
    description: Line = Field(description="One sentence: what belongs here.")


class OutlineDraft(_Strict):
    gist: Line = Field(description="One line under 90 characters: what you get from the post, not its title.")
    key_points: list[Line] = Field(
        description="1 to 5 standalone facts, steps or recommendations from the post, each under 120 characters."
    )
    labels: list[Short] = Field(description="2 to 5 short lowercase labels. Reuse vocabulary labels when they fit.")
    topic_id: int | None = Field(description="id of the existing topic this post belongs on, or null.")
    new_topic: NewTopic | None = Field(description="Only when no existing topic fits and creating one is allowed.")


class BriefPointIn(_Strict):
    n: int
    text: Line


class BriefSourceIn(_Strict):
    title: Short
    item_type: ItemType
    gist: Line
    points: list[BriefPointIn]


class BriefInput(_Strict):
    topic: Short
    topic_description: Line
    goals: list[GoalBrief]
    sources: list[BriefSourceIn]
    previous_points: list[Line]


class BriefPointDraft(_Strict):
    text: Line = Field(description="One merged point, under 160 characters.")
    sources: list[int] = Field(description="Every input point number this point restates or draws on.")


class BriefSectionDraft(_Strict):
    heading: Short
    points: list[BriefPointDraft]


class BriefDraft(_Strict):
    overview: Para = Field(description="One sentence on what this topic's saves add up to.")
    sections: list[BriefSectionDraft]


class PlanTopicLine(_Strict):
    id: int
    name: Short
    description: Line
    posts: int


class PlanPost(_Strict):
    title: Short
    item_type: ItemType
    summary: Para


class TopicPlanInput(_Strict):
    goals: list[GoalBrief]
    topics: list[PlanTopicLine]
    retired: list[Short]
    posts: list[PlanPost]


class TopicMergeDraft(_Strict):
    from_id: int
    into_id: int


class TopicPlanDraft(_Strict):
    new_topics: list[NewTopic] = Field(description="Shelves for the posts given; empty when no posts are given.")
    merges: list[TopicMergeDraft] = Field(description="Existing topics that are the same shelf; at most two.")


class RebuildPostIn(_Strict):
    id: int
    title: Short
    item_type: ItemType
    gist: Line
    labels: list[Short]
    topic: Short | None = Field(description="The topic it sits on now, or null.")
    moved_by_hand: bool = Field(description="The person put it on its topic themselves.")


class RebuildTopicIn(_Strict):
    id: int
    name: Short
    description: Line
    posts: int


class TopicRebuildInput(_Strict):
    goals: list[GoalBrief]
    topics: list[RebuildTopicIn]
    posts: list[RebuildPostIn]


class RebuiltTopicDraft(_Strict):
    name: Short = Field(description="1 to 3 plain words, the shelf a person would name, e.g. 'Marketing and growth'.")
    description: Line = Field(description="One sentence: what belongs here.")
    continues: list[int] = Field(description="ids of current topics this one keeps or absorbs; empty for a new shelf.")
    posts: list[int] = Field(description="ids of the posts placed on this topic.")


class TopicRebuildDraft(_Strict):
    topics: list[RebuiltTopicDraft]


class TopicFitInput(_Strict):
    topic: Short
    description: Line
    posts: list[RebuildPostIn]


class TopicFitDraft(_Strict):
    posts: list[int] = Field(description="ids of the posts that belong on the new topic more than where they are.")


class SetupAnswerIn(_Strict):
    id: Short
    question: Line
    answer: Para = Field(description="The free answer, or the picked choice labels joined by '; '.")


class KeptAnyway(_Strict):
    title: Short
    reason: Para


class SetupInput(_Strict):
    answers: list[SetupAnswerIn]
    current_goals: list[GoalBrief]
    current_values: Body
    kept_anyway: list[KeptAnyway] = []


class ProposedGoal(_Strict):
    title: Short = Field(description="Under 60 characters: the outcome, in their words.")
    description: Para = Field(description="One or two sentences: why it matters and which saved posts serve it.")
    category: GoalCategory
    revises: int = Field(description="The id of the current goal this rewrites, or 0 for a new goal.")


class SetupDraft(_Strict):
    goals: list[ProposedGoal] = Field(description="New goals, and current goals whose wording changes.")
    deactivate: list[int] = Field(description="ids of current goals the answers contradict or that duplicate another.")
    values_text: Body = Field(description="3 to 6 short lines in their voice.")
