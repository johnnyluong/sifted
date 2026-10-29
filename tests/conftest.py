from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sift import goals, runtime
from sift.config import Settings
from sift.domain import GoalCategory
from sift.llm.client import LLM
from sift.llm.fake import FakeLLM
from sift.runtime import Overrides, Runtime
from tests.fakes import FakeFetcher, FakeTranscriber, fake_fetchers, no_media_tools


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> datetime:
        self.now += timedelta(**kw)
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path / "data", llm_backend="fake", fetch_delay_seconds=0)  # pyright: ignore[reportCallIssue]


@pytest.fixture
def fetcher() -> FakeFetcher:
    return FakeFetcher()


@pytest.fixture
def transcriber() -> FakeTranscriber:
    return FakeTranscriber()


@pytest.fixture
def llm() -> LLM | None:
    return FakeLLM()


@pytest.fixture
def rt(
    settings: Settings,
    fetcher: FakeFetcher,
    transcriber: FakeTranscriber,
    llm: LLM | None,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Runtime]:
    no_media_tools(monkeypatch.setattr)
    r = runtime.build_runtime(
        settings,
        Overrides(
            fetchers=fake_fetchers(settings.uploads_dir, fetcher),
            transcriber=transcriber,
            llm=llm,
            use_llm_override=True,
            clock=clock,
        ),
    )
    runtime.migrate(settings)
    yield r


@pytest.fixture
def goal(rt: Runtime, clock: Clock) -> int:
    g = goals.create_goal(
        "Eat my way through the East Village tacos",
        "Find the best tacos and restaurant spots in the East Village",
        GoalCategory.personal,
        clock(),
    )
    return g.id
