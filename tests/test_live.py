from __future__ import annotations

import os
from pathlib import Path

import pytest

from sift import goals, runtime
from sift.config import Settings
from sift.domain import Channel, GoalCategory, ItemStatus, Origin
from sift.inbox import intake
from sift.items import queries

pytestmark = pytest.mark.live


async def test_real_url_end_to_end(tmp_path: Path) -> None:
    url = os.environ.get("SIFT_LIVE_URL")
    if not url:
        pytest.skip("set SIFT_LIVE_URL to a reel or Threads post")
    settings = Settings(data_dir=tmp_path / "data")
    if settings.anthropic_api_key is None:
        pytest.skip("ANTHROPIC_API_KEY is not set")
    rt = runtime.build_runtime(settings)
    runtime.migrate(settings)
    goals.create_goal("Learn useful things", "anything practical I can act on", GoalCategory.personal, rt.clock())
    [r] = intake.submit(url, Origin(Channel.cli), rt.clock(), llm_ready=rt.llm_ready)
    assert isinstance(r, intake.Queued)
    await rt.worker.run_item(r.item.id)
    item = queries.get_item(r.item.id, llm_ready=rt.llm_ready)
    assert item is not None
    assert item.status in (ItemStatus.kept, ItemStatus.archived), (item.status_reason, item.last_error)
    assert item.card is not None and item.relevance_score is not None
