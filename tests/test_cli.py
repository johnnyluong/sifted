from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from sqlmodel import select
from typer.testing import CliRunner

from sift import cli, db, runtime
from sift.cli import strip_terminal_controls
from sift.config import Settings
from sift.domain import Channel, Origin
from sift.inbox import intake
from sift.models import Item
from sift.runtime import Runtime
from tests.conftest import Clock

URL = "https://www.instagram.com/reel/ABC123/"
HOSTILE = "Pan\x1b]0;owned\x07 \x1b[31mdeal"


def test_strip_terminal_controls_removes_escapes_and_controls() -> None:
    assert strip_terminal_controls("a\x1b[31mred\x1b[0m\x07 b\r\x1b]0;title\x07c\x9b\tok\n") == "ared bc\tok\n"


@pytest.fixture
def cli_on(rt: Runtime, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Runtime:
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime, "setup_logging", lambda *a, **kw: None)
    monkeypatch.setattr(runtime, "build_runtime", lambda *a, **kw: rt)
    return rt


def test_process_strips_controls_from_a_duplicates_title(cli_on: Runtime, clock: Clock) -> None:
    intake.submit(URL, Origin(Channel.web), clock(), llm_ready=True)
    with db.write_session() as s:
        item = s.exec(select(Item)).one()
        item.title = HOSTILE
        s.add(item)
    result = CliRunner().invoke(cli.app, ["process", URL])
    assert "Already saved" in result.output, result.output
    assert "\x1b" not in result.output and "\x07" not in result.output
    assert "Pan deal" in result.output


def test_import_strips_controls_from_member_names(cli_on: Runtime, tmp_path: Path) -> None:
    saved = {"saved_saved_media": [{"timestamp": 1729000000, "label_values": [{"value": URL}]}]}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("saved/saved_posts\x1b]0;owned\x07.json", json.dumps(saved))
    path = tmp_path / "meta.zip"
    path.write_bytes(buf.getvalue())
    result = CliRunner().invoke(cli.app, ["import", str(path)], input="n\n")
    assert "Read saved/saved_posts.json" in result.output, result.output
    assert "\x1b" not in result.output
