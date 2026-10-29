from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from sift import db
from sift.domain import (
    Channel,
    FailureKind,
    ItemStatus,
    ItemType,
    MediaKind,
    Origin,
    ProcessingError,
    Source,
    SourceRef,
)
from sift.inbox import intake
from sift.items import queries, store
from sift.items.lifecycle import UserAction
from sift.items.views import ItemOutcome
from sift.llm.client import LLM
from sift.llm.fake import FakeLLM
from sift.llm.schemas import (
    ExtractInput,
    ExtractOutput,
    ProductCard,
    ProductDetails,
    ScoreInput,
    ScoreOutput,
)
from sift.media import SLIDE_LONG_EDGE
from sift.models import Item
from sift.runtime import Runtime
from tests.conftest import Clock
from tests.fakes import FakeFetcher, FakeTranscriber, download_error

URL = "https://www.instagram.com/reel/TACO1/"


def _row(item_id: int) -> Item:
    with db.read_session() as s:
        row = s.get(Item, item_id)
        assert row is not None
        return row


def _submit(rt: Runtime, clock: Clock, url: str = URL) -> int:
    [r] = intake.submit(url, Origin(Channel.cli), clock(), llm_ready=rt.llm_ready)
    assert isinstance(r, intake.Queued)
    return r.item.id


async def test_link_to_kept_card(rt: Runtime, clock: Clock, goal: int, transcriber: FakeTranscriber) -> None:
    item_id = _submit(rt, clock)
    await rt.worker.run_item(item_id)
    item = queries.get_item(item_id, llm_ready=rt.llm_ready)
    assert item is not None
    assert item.status is ItemStatus.kept, item.relevance_reason
    assert item.item_type is ItemType.place
    assert item.matched_goal_id == goal
    assert item.transcript == transcriber.text
    assert item.card is not None and item.card.item_type is ItemType.place
    assert item.extract_model == "fake"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
async def test_carousel_slides_reach_extraction(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []
    extract = FakeLLM.extract

    def spy(self: FakeLLM, inp: ExtractInput) -> tuple[ExtractOutput, str]:
        seen.append(inp.frames)
        return extract(self, inp)

    monkeypatch.setattr(FakeLLM, "extract", spy)
    fetcher.kind = MediaKind.image
    fetcher.slides = tuple(tmp_path / f"slide_{i:02d}.jpg" for i in (1, 2))
    for slide in fetcher.slides:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=1080x1350", "-frames:v", "1", str(slide)],
            check=True,
        )
    item_id = _submit(rt, clock)
    await rt.worker.run_item(item_id)
    workdir = rt.worker.deps.workdir(item_id)
    assert seen == [[str(workdir / "frames" / "slide_01.jpg"), str(workdir / "frames" / "slide_02.jpg")]]
    assert _row(item_id).status is ItemStatus.kept
    sizes = {
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", frame],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        for frame in seen[0]
    }
    assert sizes == {f"820,{SLIDE_LONG_EDGE}"}, "an Instagram slide keeps the slide edge"


SHARE = "https://www.threads.com/share/BAa/"
POST = SourceRef(Source.threads, "De2", "https://www.threads.com/@chef.ana/post/De2")


async def test_a_queued_share_link_is_stored_as_its_post(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    item_id = _submit(rt, clock, SHARE)
    fetcher.shares["share-BAa"] = POST
    await rt.worker.run_item(item_id)
    row = _row(item_id)
    assert (row.canonical_id, row.clean_url, row.status) == ("De2", POST.clean_url, ItemStatus.kept)
    assert fetcher.calls == [POST]
    [again] = intake.submit(POST.clean_url, Origin(Channel.web), clock(), llm_ready=True)
    assert isinstance(again, intake.Duplicate) and again.item.id == item_id


async def test_a_queued_share_link_to_a_saved_post_is_removed(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    saved = _submit(rt, clock, POST.clean_url)
    await rt.worker.run_item(saved)
    share = _submit(rt, clock, SHARE)
    fetcher.shares["share-BAa"] = POST
    clock.advance(minutes=5)
    await rt.worker.run_item(share)
    with db.read_session() as s:
        assert s.get(Item, share) is None
    assert fetcher.calls == [POST], "the post is not downloaded twice"
    assert _row(saved).status is ItemStatus.kept


async def test_video_is_deleted_but_thumbnail_kept(rt: Runtime, clock: Clock, goal: int) -> None:
    item_id = _submit(rt, clock)
    await rt.worker.run_item(item_id)
    workdir = rt.worker.deps.workdir(item_id)
    assert not (workdir / "media.mp4").exists()
    assert (workdir / "thumbnail.jpg").exists()


async def test_noise_is_archived_with_reason(rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher) -> None:
    fetcher.caption = "Monday motivation: grind harder, sleep less."
    item_id = _submit(rt, clock)
    await rt.worker.run_item(item_id)
    item = queries.get_item(item_id, llm_ready=rt.llm_ready)
    assert item is not None and item.status is ItemStatus.archived
    assert item.status_reason


@pytest.mark.parametrize("llm", [None])
async def test_without_llm_items_wait_after_transcription(
    rt: Runtime, clock: Clock, goal: int, llm: LLM | None, transcriber: FakeTranscriber
) -> None:
    item_id = _submit(rt, clock)
    await rt.worker.run_item(item_id)
    item = queries.get_item(item_id, llm_ready=rt.llm_ready)
    assert item is not None
    assert item.status is ItemStatus.queued
    assert item.state_label == "Waiting for LLM" and item.waiting_for == "llm"
    assert item.transcript and transcriber.calls == 1
    assert item.attempts == 0


async def test_scoring_waits_for_a_goal_then_finishes(rt: Runtime, clock: Clock) -> None:
    from sift import goals
    from sift.domain import GoalCategory

    item_id = _submit(rt, clock)
    await rt.worker.run_item(item_id)
    item = queries.get_item(item_id, llm_ready=rt.llm_ready)
    assert item is not None and item.state_label == "Waiting for goals" and item.card is not None
    assert item.waiting_for == "goals"
    goals.create_goal("East Village tacos", "best tacos spots", GoalCategory.personal, clock())
    await rt.worker.run_item(item_id)
    item = queries.get_item(item_id, llm_ready=rt.llm_ready)
    assert item is not None and item.status is ItemStatus.kept and item.waiting_for is None


async def test_retryable_failure_backs_off_then_succeeds(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    fetcher.errors = [download_error()]
    item_id = _submit(rt, clock)
    await rt.worker.run_item(item_id)
    item = queries.get_item(item_id, llm_ready=rt.llm_ready)
    assert item is not None and item.status is ItemStatus.queued and item.state_label == "Retrying soon"
    assert item.waiting_for is None
    clock.advance(minutes=2)
    await rt.worker.run_item(item_id)
    item = queries.get_item(item_id, llm_ready=rt.llm_ready)
    assert item is not None and item.status is ItemStatus.kept
    assert len(fetcher.calls) == 2


async def test_gives_up_after_four_attempts(rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher) -> None:
    fetcher.errors = [download_error() for _ in range(4)]
    item_id = _submit(rt, clock)
    for _ in range(4):
        await rt.worker.run_item(item_id)
        clock.advance(hours=1)
    item = queries.get_item(item_id, llm_ready=rt.llm_ready)
    assert item is not None and item.status is ItemStatus.failed
    assert item.failure_kind is FailureKind.download_failed
    assert item.failure_hint and "update-tools" in item.failure_hint
    retried = store.apply_action(item_id, UserAction.retry, clock(), llm_ready=rt.llm_ready)
    assert retried.status is ItemStatus.queued
    await rt.worker.run_item(item_id)
    item = queries.get_item(item_id, llm_ready=rt.llm_ready)
    assert item is not None and item.status is ItemStatus.kept


async def test_unsupported_post_fails_without_retry(rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher) -> None:
    fetcher.errors = [ProcessingError(FailureKind.unsupported_url, "private post", retryable=False)]
    item_id = _submit(rt, clock)
    await rt.worker.run_item(item_id)
    item = queries.get_item(item_id, llm_ready=rt.llm_ready)
    assert item is not None and item.status is ItemStatus.failed and len(fetcher.calls) == 1


async def test_unexpected_exception_is_classified_by_stage(
    rt: Runtime, clock: Clock, goal: int, transcriber: FakeTranscriber
) -> None:
    def boom(media: object) -> str:
        raise RuntimeError("metal device lost")

    transcriber.transcribe = boom
    item_id = _submit(rt, clock)
    await rt.worker.run_item(item_id)
    item = queries.get_item(item_id, llm_ready=rt.llm_ready)
    assert item is not None and item.status is ItemStatus.queued
    assert item.last_error and "Transcription failed" in item.last_error
    assert item.media_kind is MediaKind.video


async def test_text_post_skips_transcription(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher, transcriber: FakeTranscriber
) -> None:
    fetcher.kind = MediaKind.text
    item_id = _submit(rt, clock, "https://www.threads.com/@a/post/TXT1")
    await rt.worker.run_item(item_id)
    item = queries.get_item(item_id, llm_ready=rt.llm_ready)
    assert item is not None and item.status in (ItemStatus.kept, ItemStatus.archived)
    assert transcriber.calls == 0


async def test_a_dead_post_can_be_archived_but_not_kept(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    fetcher.errors = [ProcessingError(FailureKind.download_failed, "gone", retryable=False)]
    item_id = _submit(rt, clock)
    await rt.worker.run_item(item_id)
    failed = queries.get_item(item_id, llm_ready=rt.llm_ready)
    assert failed is not None and failed.status is ItemStatus.failed and len(fetcher.calls) == 1
    assert failed.actions == [UserAction.archive, UserAction.retry]

    archived = store.apply_action(item_id, UserAction.archive, clock(), llm_ready=rt.llm_ready)
    assert archived.status is ItemStatus.archived and archived.actions == [UserAction.reprocess]
    with pytest.raises(store.InvalidTransition, match="never scored"):
        store.apply_action(item_id, UserAction.keep, clock(), llm_ready=rt.llm_ready)
    after = queries.get_item(item_id, llm_ready=rt.llm_ready)
    assert after is not None and after.status is ItemStatus.archived


async def test_archiving_a_failed_post_dismisses_it_without_judging_it(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    fetcher.errors = [ProcessingError(FailureKind.download_failed, "Instagram says this post is gone", retryable=False)]
    item_id = _submit(rt, clock)
    await rt.worker.run_item(item_id)

    archived = store.apply_action(item_id, UserAction.archive, clock(), llm_ready=rt.llm_ready)
    assert archived.status is ItemStatus.archived and archived.user_override is None
    assert archived.status_reason == "Instagram says this post is gone", "the failure stays visible"
    assert _row(item_id).decided_at == clock()
    assert queries.recent_override_examples() == []

    requeued = store.apply_action(item_id, UserAction.reprocess, clock(), llm_ready=rt.llm_ready)
    row = _row(item_id)
    assert requeued.status is ItemStatus.queued and requeued.status_reason is None
    assert (row.failure_kind, row.last_error) == (None, None), "a requeued post carries no stale failure"
    await rt.worker.run_item(item_id)
    rescored = queries.get_item(item_id, llm_ready=rt.llm_ready)
    assert rescored is not None and rescored.status is ItemStatus.kept and rescored.user_override is None
    assert queries.recent_override_examples() == []


async def test_imported_posts_are_not_announced(
    rt: Runtime, clock: Clock, goal: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    announced: list[int] = []

    async def spy(outcome: ItemOutcome) -> None:
        announced.append(outcome.item_id)

    monkeypatch.setattr(rt.notifier, "item_finished", spy)
    [imported] = intake.submit("https://www.instagram.com/reel/IMP/", Origin(Channel.export), clock(), llm_ready=True)
    pasted = _submit(rt, clock)
    assert isinstance(imported, intake.Queued)
    await rt.worker.run_item(imported.item.id)
    await rt.worker.run_item(pasted)
    assert announced == [pasted]


class LinkingLLM(FakeLLM):
    def __init__(self, link: str) -> None:
        self.link = link

    def extract(self, inp: ExtractInput) -> tuple[ExtractOutput, str]:
        out, model = super().extract(inp)
        details = ProductDetails(name="Pan", what_it_is="A pan", price=None, link=self.link, wishlist=True)
        card = ProductCard(
            item_type=ItemType.product,
            title=out.card.title,
            summary=out.card.summary,
            next_action=None,
            details=details,
        )
        return ExtractOutput(card=card, on_screen_text=None), model


@pytest.mark.parametrize(
    ("llm", "stored"),
    [
        (LinkingLLM("https://evil.example/buy"), None),
        (LinkingLLM("https://pans.example/buy"), "https://pans.example/buy"),
    ],
)
async def test_a_product_link_is_stored_only_when_the_post_states_it(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher, stored: str | None
) -> None:
    fetcher.caption = "This pan changed my cooking. Get it at pans.example/buy"
    item_id = _submit(rt, clock)
    await rt.worker.run_item(item_id)
    row = _row(item_id)
    assert row.item_type is ItemType.product and (row.details or {}).get("link") == stored


class InventingLLM(FakeLLM):
    def score(self, inp: ScoreInput) -> tuple[ScoreOutput, str]:
        out, model = super().score(inp)
        return out.model_copy(update={"matched_goal_id": 999}), model


@pytest.mark.parametrize("llm", [InventingLLM()])
async def test_an_invented_goal_id_is_not_stored(rt: Runtime, clock: Clock, goal: int) -> None:
    item_id = _submit(rt, clock)
    await rt.worker.run_item(item_id)
    row = _row(item_id)
    assert row.scored_at is not None and row.matched_goal_id is None
