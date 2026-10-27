from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, Field, StringConstraints
from sqlmodel import col, select

from sift import db
from sift.domain import GoalCategory
from sift.llm.client import LLM
from sift.llm.schemas import GoalBrief, ProposedGoal, SetupAnswerIn, SetupDraft, SetupInput
from sift.models import PROFILE_ID, Goal, Profile

GoalTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
GoalDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=600)]
ValuesText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4_000)]
AnswerText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1_000)]
ShortId = Annotated[str, StringConstraints(max_length=40)]
MAX_DRAFT_GOALS = 6


class GoalView(BaseModel):
    id: int
    title: str
    description: str
    category: GoalCategory
    active: bool
    created_at: datetime
    updated_at: datetime


class GoalNotFound(Exception):
    pass


def _view(row: Goal) -> GoalView:
    return GoalView.model_validate(row, from_attributes=True)


def list_goals(*, active_only: bool = False) -> list[GoalView]:
    with db.read_session() as s:
        q = select(Goal).order_by(col(Goal.active).desc(), col(Goal.created_at))
        if active_only:
            q = q.where(Goal.active == True)  # noqa: E712
        return [_view(g) for g in s.exec(q).all()]


def has_active_goals() -> bool:
    with db.read_session() as s:
        return s.exec(select(Goal.id).where(Goal.active == True).limit(1)).first() is not None  # noqa: E712


def create_goal(title: str, description: str, category: GoalCategory, now: datetime) -> GoalView:
    with db.write_session() as s:
        row = Goal(
            title=title.strip(), description=description.strip(), category=category, created_at=now, updated_at=now
        )
        s.add(row)
        s.flush()
        return _view(row)


def update_goal(
    goal_id: int,
    now: datetime,
    *,
    title: str | None = None,
    description: str | None = None,
    category: GoalCategory | None = None,
    active: bool | None = None,
) -> GoalView:
    with db.write_session() as s:
        row = s.get(Goal, goal_id)
        if row is None:
            raise GoalNotFound(goal_id)
        if title is not None:
            row.title = title.strip()
        if description is not None:
            row.description = description.strip()
        if category is not None:
            row.category = category
        if active is not None:
            row.active = active
        row.updated_at = now
        return _view(row)


def get_values() -> str:
    with db.read_session() as s:
        row = s.get(Profile, PROFILE_ID)
        return row.values_text if row else ""


def set_values(text: str, now: datetime) -> str:
    with db.write_session() as s:
        row = s.get(Profile, PROFILE_ID) or Profile(id=PROFILE_ID, updated_at=now)
        row.values_text = text.strip()
        row.updated_at = now
        s.add(row)
        return row.values_text


def scoring_context() -> tuple[str, list[GoalBrief]]:
    goals = [
        GoalBrief(id=g.id, title=g.title, description=g.description, category=g.category)
        for g in list_goals(active_only=True)
    ]
    return get_values(), goals


class QuestionKind(StrEnum):
    text = "text"
    one = "one"
    many = "many"


class Choice(BaseModel):
    id: str
    label: str


class SetupQuestion(BaseModel):
    id: str
    kind: QuestionKind
    prompt: str
    hint: str | None = None
    choices: list[Choice] = []
    other: str | None = Field(default=None, description="Label of a write-in field beside the choices, if any.")


def _choices(*pairs: tuple[str, str]) -> list[Choice]:
    return [Choice(id=i, label=label) for i, label in pairs]


QUESTIONS: tuple[SetupQuestion, ...] = (
    SetupQuestion(
        id="saving",
        kind=QuestionKind.text,
        prompt="What have you saved lately, and why?",
        hint="The reasons or patterns behind your recent saves.",
    ),
    SetupQuestion(
        id="working_toward",
        kind=QuestionKind.text,
        prompt="What are you working toward in the next few months?",
        hint="A project, a habit, a plan. Each one can become a goal.",
    ),
    SetupQuestion(
        id="areas",
        kind=QuestionKind.many,
        prompt="Which areas do you save about?",
        choices=_choices(
            ("marketing", "Marketing and growing a business"),
            ("career", "Work and career skills"),
            ("food", "Restaurants, bars and food spots"),
            ("experiences", "Things to do and places to go"),
            ("cooking", "Recipes and cooking"),
            ("fitness", "Fitness and health"),
            ("products", "Products and tools"),
            ("ideas", "Ideas and inspiration"),
        ),
        other="Something else",
    ),
    SetupQuestion(
        id="with_whom",
        kind=QuestionKind.many,
        prompt="Who do you plan things with?",
        choices=_choices(("friends", "Friends"), ("partner", "A partner"), ("family", "Family"), ("solo", "Just me")),
    ),
    SetupQuestion(
        id="not_returning",
        kind=QuestionKind.text,
        prompt="Why do you rarely go back to what you save?",
    ),
    SetupQuestion(
        id="noise",
        kind=QuestionKind.text,
        prompt="What counts as noise for you?",
        hint="Posts you save but would rather Sift archive.",
    ),
    SetupQuestion(
        id="strictness",
        kind=QuestionKind.one,
        prompt="How strict should Sift be?",
        choices=_choices(
            ("strict", "Strict: keep only what I would act on soon"),
            ("balanced", "Balanced"),
            ("loose", "Loose: keep anything that might help later"),
        ),
    ),
)
_QUESTION = {q.id: q for q in QUESTIONS}


class SetupAnswer(BaseModel):
    question_id: ShortId
    text: AnswerText = Field(default="", description="The written answer, or the write-in beside the choices.")
    picked: list[ShortId] = Field(default=[], max_length=12)


def check_answers(answers: list[SetupAnswer]) -> list[SetupAnswer]:
    seen: set[str] = set()
    for a in answers:
        q = _QUESTION.get(a.question_id)
        if q is None:
            raise ValueError(f"There is no question {a.question_id!r}.")
        if q.id in seen:
            raise ValueError(f"{q.id!r} is answered twice.")
        seen.add(q.id)
        if unknown := set(a.picked) - {c.id for c in q.choices}:
            raise ValueError(f"{q.id!r} offers no choice {min(unknown)!r}.")
        if q.kind is QuestionKind.one and len(set(a.picked)) > 1:
            raise ValueError(f"{q.id!r} takes one choice.")
        if a.text and q.kind is not QuestionKind.text and q.other is None:
            raise ValueError(f"{q.id!r} takes no written answer.")
    if not any(a.text or a.picked for a in answers):
        raise ValueError("Answer at least one question.")
    return answers


SetupAnswers = Annotated[list[SetupAnswer], Field(max_length=len(QUESTIONS)), AfterValidator(check_answers)]


class GoalDraft(BaseModel):
    title: GoalTitle
    description: GoalDescription = ""
    category: GoalCategory = GoalCategory.other
    revises: int = Field(default=0, ge=0, description="The id of the goal this rewrites, or 0 for a new goal.")


class SetupPlan(BaseModel):
    add: list[GoalDraft] = Field(
        max_length=8,
        description="Goals to add or rewrite; a new goal that matches a goal's title revives it, unless "
        "`deactivate` also lists that goal.",
    )
    deactivate: list[int] = Field(
        default=[],
        max_length=50,
        description="Active goals to deactivate; they stay listed and can be reactivated.",
    )
    values_text: ValuesText


class SetupApply(SetupPlan):
    answers: SetupAnswers


class SetupView(BaseModel):
    questions: list[SetupQuestion]
    answers: list[SetupAnswer] = Field(description="The answers from the last setup you saved; empty before the first.")
    setup_at: datetime | None


class SetupConflict(Exception):
    pass


def setup_view() -> SetupView:
    with db.read_session() as s:
        row = s.get(Profile, PROFILE_ID)
    return SetupView(
        questions=list(QUESTIONS),
        answers=_answers_still_valid(row.setup_answers if row else None),
        setup_at=row.setup_at if row else None,
    )


def _answers_still_valid(raw: list[dict[str, Any]] | None) -> list[SetupAnswer]:
    try:
        return check_answers([SetupAnswer.model_validate(a) for a in raw or []])
    except ValueError:
        return []


def draft_setup(answers: list[SetupAnswer], llm: LLM) -> SetupPlan:
    values, active = scoring_context()
    draft, _ = llm.draft_setup(SetupInput(answers=_answered(answers), current_goals=active, current_values=values))
    return normalize_setup(draft, active)


def _answered(answers: list[SetupAnswer]) -> list[SetupAnswerIn]:
    given = {a.question_id: a for a in answers}
    out: list[SetupAnswerIn] = []
    for q in QUESTIONS:
        a = given.get(q.id)
        if a is None:
            continue
        parts = [c.label for c in q.choices if c.id in a.picked]
        text = a.text if q.kind is QuestionKind.text else "; ".join([*parts, *([a.text] if a.text else [])])
        if text:
            out.append(SetupAnswerIn(id=q.id, question=q.prompt, answer=text))
    return out


def normalize_setup(draft: SetupDraft, current: list[GoalBrief]) -> SetupPlan:
    ids = {g.id for g in current}
    by_title = {g.title.casefold(): g.id for g in current}
    seen: set[str] = set()
    rows: list[tuple[str, ProposedGoal]] = []
    for g in draft.goals:
        title = " ".join(g.title.split())[:120].strip()
        if title and title.casefold() not in seen:
            seen.add(title.casefold())
            rows.append((title, g))
    # Explicit revises claim their goals before any title match, so row order never decides which one survives.
    claims: list[int] = []
    for _, g in rows:
        claims.append(g.revises if g.revises in ids and g.revises not in claims else 0)
    revised = set(claims) - {0}
    add: list[GoalDraft] = []
    for (title, g), revises in zip(rows, claims, strict=True):
        if not revises:
            revises = by_title.get(title.casefold(), 0)
            if revises in revised:
                continue
        description = g.description.strip()[:600]
        add.append(GoalDraft(title=title, description=description, category=g.category, revises=revises))
    add = add[:MAX_DRAFT_GOALS]
    retirable = ids - {g.revises for g in add}
    return SetupPlan(
        add=add,
        deactivate=list(dict.fromkeys(i for i in draft.deactivate if i in retirable)),
        values_text=draft.values_text.strip()[:4_000],
    )


def apply_setup(body: SetupApply, now: datetime) -> list[GoalView]:
    with db.write_session() as s:
        rows = {g.id: g for g in s.exec(select(Goal)).all()}
        revisions = [d for d in body.add if d.revises]
        revised = {d.revises for d in revisions}
        if missing := {*body.deactivate, *revised} - rows.keys():
            raise GoalNotFound(min(missing))
        if len(revised) < len(revisions):
            raise SetupConflict("Two drafted goals update the same goal. Keep one.")
        for goal_id in body.deactivate:
            row = rows[goal_id]
            if row.active:
                row.active, row.updated_at = False, now
        for draft in revisions:
            rows[draft.revises].title = draft.title
            _fill(rows[draft.revises], draft, now)
        for draft in revisions:
            if any(g.title.casefold() == draft.title.casefold() for g in rows.values() if g.id != draft.revises):
                raise SetupConflict(f"Another goal is already called {draft.title}. Pick a different title.")
        # Matched after the renames, so a second apply finds the goal the first one created.
        by_title = {g.title.casefold(): g for g in rows.values()}
        for draft in body.add:
            if draft.revises:
                continue
            row = by_title.get(draft.title.casefold())
            if row is not None and row.id in body.deactivate:
                raise SetupConflict(f"You turned off {row.title} and also added it. Keep one.")
            if row is not None and row.id in revised:
                raise SetupConflict(f"Two goals are called {row.title}. Pick a different title.")
            if row is None:
                row = Goal(title=draft.title, created_at=now, updated_at=now)
                by_title[draft.title.casefold()] = row
                s.add(row)
            _fill(row, draft, now)
        if s.exec(select(Goal.id).where(Goal.active == True).limit(1)).first() is None:  # noqa: E712
            raise SetupConflict("Keep at least one goal active.")
        profile = s.get(Profile, PROFILE_ID) or Profile(id=PROFILE_ID, updated_at=now)
        profile.values_text = body.values_text
        profile.setup_answers = [a.model_dump() for a in body.answers]
        profile.setup_at = profile.updated_at = now
        s.add(profile)
    return list_goals()


def _fill(row: Goal, draft: GoalDraft, now: datetime) -> None:
    row.active, row.category, row.description, row.updated_at = True, draft.category, draft.description, now
