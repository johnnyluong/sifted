from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StringConstraints

from sift import digest, goals
from sift.digest import DigestsView, DigestView
from sift.domain import Channel, GoalCategory, ImportAction, ItemStatus, ItemType, ProcessingError
from sift.goals import GoalDescription, GoalTitle, GoalView, SetupAnswers, SetupApply, SetupPlan, SetupView, ValuesText
from sift.inbox import imports
from sift.inbox.imports import ImportView
from sift.items import queries
from sift.items.lifecycle import UserAction
from sift.items.queries import ItemFilter
from sift.items.views import ItemDetail, ItemOrganization, ItemSummary
from sift.organize import store as organize
from sift.organize.model import TOPIC_NAME_MAX
from sift.organize.store import Dissolved, LabelCount, TopicDetail, TopicsView
from sift.web import services
from sift.web.services import StatusView, SubmissionView, rt

router = APIRouter(prefix="/api")

VIEWS: dict[str, frozenset[ItemStatus]] = {"inbox": queries.INBOX, "kept": queries.KEPT, "archived": queries.ARCHIVED}

TopicName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=TOPIC_NAME_MAX)]


class SubmitBody(BaseModel):
    text: str
    channel: Literal["web", "api"] = "api"


class GoalCreate(BaseModel):
    title: GoalTitle
    description: GoalDescription = ""
    category: GoalCategory = GoalCategory.other


class GoalPatch(BaseModel):
    title: GoalTitle | None = None
    description: GoalDescription | None = None
    category: GoalCategory | None = None
    active: bool | None = None


class ValuesBody(BaseModel):
    values_text: ValuesText


class SetupAnswersBody(BaseModel):
    answers: SetupAnswers


class StartBody(BaseModel):
    limit: int | None = Field(default=None, ge=1, description="Import only the newest N; null for all.")


class TopicMove(BaseModel):
    topic_id: int | None = Field(description="null returns the post to Sift's pick.")


class TopicPatch(BaseModel):
    name: TopicName | None = None
    description: str | None = None


class MergeBody(BaseModel):
    into_id: int


ZIP_BODY = {
    "requestBody": {
        "required": True,
        "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
    }
}


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/status")
def status(request: Request) -> StatusView:
    return services.status(rt(request))


@router.get("/items")
def list_items(
    request: Request,
    view: Literal["inbox", "kept", "archived"] | None = None,
    status: list[ItemStatus] = Query(default_factory=list),
    goal_id: int | None = None,
    type: ItemType | None = None,
    q: str | None = None,
    topic_id: int | None = None,
    label: str | None = None,
    limit: int = Query(500, ge=1, le=500),
) -> list[ItemSummary]:
    statuses = frozenset(status) or VIEWS.get(view or "", frozenset(ItemStatus))
    f = ItemFilter(statuses=statuses, goal_id=goal_id, item_type=type, q=q, topic_id=topic_id, label=label, limit=limit)
    return queries.list_items(f, llm_ready=rt(request).llm_ready)


@router.post("/items", status_code=202)
async def submit(request: Request, body: SubmitBody) -> list[SubmissionView]:
    return await services.submit(request, body.text, Channel(body.channel))


@router.get("/items/{item_id}")
def get_item(request: Request, item_id: int) -> ItemDetail:
    item = queries.get_item(item_id, llm_ready=rt(request).llm_ready)
    if item is None:
        raise HTTPException(404, "Item not found")
    return item


@router.get(
    "/items/{item_id}/thumbnail",
    response_class=FileResponse,
    responses={200: {"content": {"image/*": {}}, "description": "The post's thumbnail image."}},
)
def thumbnail(request: Request, item_id: int) -> FileResponse:
    path = services.thumbnail_file(rt(request), item_id)
    if path is None:
        raise HTTPException(404, "No thumbnail")
    return FileResponse(path, headers={"Cache-Control": "max-age=86400"})


@router.post("/items/{item_id}/actions/{action}")
async def act(request: Request, item_id: int, action: UserAction) -> ItemDetail:
    return await services.act(request, item_id, action)


@router.put("/items/{item_id}/topic", responses={404: {}, 409: {"description": "The post is not organized yet."}})
async def move_item(request: Request, item_id: int, body: TopicMove) -> ItemOrganization:
    return await services.organize_write(request, organize.move_item, item_id, body.topic_id)


@router.get("/topics")
def list_topics() -> TopicsView:
    return organize.list_topics()


@router.get("/topics/{topic_id}")
def get_topic(topic_id: int) -> TopicDetail:
    detail = organize.get_topic(topic_id)
    if detail is None:
        raise HTTPException(404, "Topic not found")
    return detail


@router.patch("/topics/{topic_id}", responses={409: {"description": "Another topic has that name: merge instead."}})
async def patch_topic(request: Request, topic_id: int, body: TopicPatch) -> TopicDetail:
    return await services.organize_write(request, organize.rename_topic, topic_id, body.name, body.description)


@router.post("/topics/{topic_id}/merge")
async def merge_topic(request: Request, topic_id: int, body: MergeBody) -> TopicDetail:
    return await services.organize_write(request, organize.merge_topics, topic_id, body.into_id)


@router.delete("/topics/{topic_id}")
async def dissolve_topic(request: Request, topic_id: int) -> Dissolved:
    return await services.organize_write(request, organize.dissolve_topic, topic_id, wake=True)


@router.post("/topics/{topic_id}/brief", status_code=202, responses={409: {"description": "Fewer than two posts."}})
async def request_brief(request: Request, topic_id: int) -> TopicDetail:
    return await services.organize_write(request, organize.request_brief, topic_id, wake=True)


@router.post("/topics/{topic_id}/suggestions/{into_id}/dismiss")
async def dismiss_suggestion(request: Request, topic_id: int, into_id: int) -> TopicsView:
    return await services.organize_write(request, organize.dismiss_suggestion, topic_id, into_id)


@router.get("/labels")
def list_labels(topic_id: int | None = None) -> list[LabelCount]:
    return organize.labels(topic_id)


@router.get("/goals")
def list_goals() -> list[GoalView]:
    return goals.list_goals()


@router.post("/goals", status_code=201)
def create_goal(request: Request, body: GoalCreate) -> GoalView:
    return goals.create_goal(body.title, body.description, body.category, rt(request).clock())


@router.patch("/goals/{goal_id}")
def patch_goal(request: Request, goal_id: int, body: GoalPatch) -> GoalView:
    try:
        return goals.update_goal(goal_id, rt(request).clock(), **body.model_dump(exclude_unset=True))
    except goals.GoalNotFound as e:
        raise HTTPException(404, "Goal not found") from e


@router.get("/values")
def get_values() -> ValuesBody:
    return ValuesBody(values_text=goals.get_values())


@router.put("/values")
def put_values(request: Request, body: ValuesBody) -> ValuesBody:
    return ValuesBody(values_text=goals.set_values(body.values_text, rt(request).clock()))


@router.get("/setup")
def get_setup() -> SetupView:
    return goals.setup_view()


@router.post(
    "/setup/draft",
    responses={502: {"description": "The LLM call failed."}, 503: {"description": "No LLM is configured."}},
)
def draft_setup(request: Request, body: SetupAnswersBody) -> SetupPlan:
    llm = rt(request).llm
    if llm is None:
        raise HTTPException(503, "Set ANTHROPIC_API_KEY (or LLM_BACKEND=fake) to draft goals, or add them by hand.")
    try:
        return goals.draft_setup(body.answers, llm)
    except ProcessingError as e:
        raise HTTPException(502, f"The draft could not be written: {e.message}") from e


@router.post(
    "/setup/apply",
    responses={404: {}, 409: {"description": "No goal would stay active, or the plan clashes with a goal's title."}},
)
async def apply_setup(request: Request, body: SetupApply) -> list[GoalView]:
    return await services.apply_setup(request, body)


@router.get("/digests")
def list_digests(request: Request) -> DigestsView:
    return digest.list_digests(llm_ready=rt(request).llm_ready)


@router.get("/digests/{digest_id}")
def get_digest(request: Request, digest_id: int) -> DigestView:
    view = digest.get_digest(digest_id, llm_ready=rt(request).llm_ready)
    if view is None:
        raise HTTPException(404, "Digest not found")
    return view


@router.post("/digests", status_code=201)
async def create_digest(request: Request) -> DigestView:
    try:
        view = await services.generate_digest(request)
    except digest.DigestUnavailable as e:
        raise HTTPException(503, str(e)) from e
    except ProcessingError as e:
        raise HTTPException(502, f"The digest could not be written: {e.message}") from e
    if view is None:
        raise HTTPException(
            409, f"Nothing new to surface: every kept item is done or has been shown {digest.REPEAT_LIMIT} times."
        )
    return view


@router.post(
    "/imports",
    status_code=201,
    openapi_extra=ZIP_BODY,
    responses={413: {"description": "Over IMPORT_MAX_BYTES."}, 422: {"description": "Not an export with saved posts."}},
)
async def upload_import(request: Request, filename: Annotated[str, Query(max_length=200)] = "export.zip") -> ImportView:
    return await services.upload_import(request, filename)


@router.get("/imports")
def list_imports(request: Request) -> list[ImportView]:
    runtime = rt(request)
    return imports.list_imports(runtime.clock(), runtime.pace, llm_ready=runtime.llm_ready)


@router.get("/imports/{import_id}")
def get_import(request: Request, import_id: int) -> ImportView:
    runtime = rt(request)
    view = imports.get_import(import_id, runtime.clock(), runtime.pace, llm_ready=runtime.llm_ready)
    if view is None:
        raise HTTPException(404, "Import not found")
    return view


@router.get("/imports/{import_id}/estimate")
def import_estimate(request: Request, import_id: int, limit: Annotated[int, Query(ge=0)]) -> imports.Estimate:
    try:
        return imports.estimate_newest(import_id, limit, rt(request).pace)
    except imports.ImportNotFound as e:
        raise HTTPException(404, "Import not found") from e


@router.post("/imports/{import_id}/actions/{action}")
async def import_action(
    request: Request, import_id: int, action: ImportAction, body: StartBody | None = None
) -> ImportView:
    return await services.import_action(request, import_id, action, body.limit if body else None)
