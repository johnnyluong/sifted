from __future__ import annotations

import io
import json
import random
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select
from typer.testing import CliRunner

from sift import cli, db, runtime
from sift.config import Settings
from sift.domain import Channel, LinkState, Origin
from sift.inbox import export, imports, intake
from sift.models import ImportLink
from sift.runtime import Runtime
from sift.web.app import create_app
from tests.conftest import Clock

SAVED = {
    "saved_saved_media": [
        {"timestamp": 1729000000 + i, "label_values": [{"value": f"https://www.instagram.com/reel/R{i}/"}]}
        for i in range(4)
    ]
}
ZIP = {"content-type": "application/zip"}


def _zip(members: dict[str, object]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in members.items():
            z.writestr(name, json.dumps(body))
    return buf.getvalue()


@pytest.fixture
def client(rt: Runtime, tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(rt, run_background=False, dist=tmp_path / "no-dist")) as c:
        yield c


def _upload(client: TestClient, body: bytes, name: str = "meta.zip") -> dict:
    response = client.post("/api/imports", params={"filename": name}, content=body, headers=ZIP)
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_previews_and_deletes_the_zip(client: TestClient, rt: Runtime, clock: Clock) -> None:
    intake.submit("https://www.instagram.com/reel/R0/", Origin(Channel.web), clock(), llm_ready=True)
    view = _upload(client, _zip({"your_instagram_activity/saved/saved_posts.json": SAVED}))
    assert view["phase"] == "preview" and view["filename"] == "meta.zip"
    assert (view["counts"]["links"], view["counts"]["found"], view["counts"]["duplicate"]) == (4, 3, 1)
    assert [o["limit"] for o in view["options"]] == [None]
    assert view["actions"] == ["start", "cancel"]
    assert list(rt.settings.imports_dir.iterdir()) == [], "the upload never stays on disk"
    assert [v["id"] for v in client.get("/api/imports").json()] == [view["id"]]


def test_an_upload_without_saved_posts_says_what_to_upload(client: TestClient, rt: Runtime) -> None:
    response = client.post(
        "/api/imports", content=_zip({"your_instagram_activity/likes/liked_posts.json": {}}), headers=ZIP
    )
    assert response.status_code == 422
    assert response.json()["detail"].startswith("No saved posts in this zip. It has: your_instagram_activity/likes")
    assert client.post("/api/imports", content=b"not a zip", headers=ZIP).status_code == 422
    assert list(rt.settings.imports_dir.iterdir()) == []


def test_a_streamed_upload_spanning_write_blocks_arrives_intact(client: TestClient) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("media/clip.bin", random.Random(0).randbytes(2_500_000))
        z.writestr("saved/saved_posts.json", json.dumps(SAVED))
    body = buf.getvalue()
    chunks = (body[i : i + 65_536] for i in range(0, len(body), 65_536))
    response = client.post("/api/imports", content=chunks, headers=ZIP)
    assert response.status_code == 201, response.text
    assert response.json()["counts"]["found"] == 4


def test_the_server_prices_a_custom_newest_n(client: TestClient, rt: Runtime) -> None:
    view = _upload(client, _zip({"saved/saved_posts.json": SAVED}))
    per_post, gap = rt.pace.cost.usd, int(rt.pace.gap.total_seconds())
    three = client.get(f"/api/imports/{view['id']}/estimate", params={"limit": 3}).json()
    assert three == {"posts": 3, "usd": None if per_post is None else round(per_post * 3, 2), "seconds": 3 * gap}
    more = client.get(f"/api/imports/{view['id']}/estimate", params={"limit": 99}).json()
    assert more["posts"] == 4, "never more than the export has new"
    assert client.get("/api/imports/999/estimate", params={"limit": 3}).status_code == 404
    assert client.get(f"/api/imports/{view['id']}/estimate", params={"limit": -1}).status_code == 422


def test_a_damaged_member_is_a_422_not_a_crash(client: TestClient) -> None:
    body = _zip({"saved/saved_posts.json": SAVED}).replace(b"reel/R0", b"reel/X0", 1)
    response = client.post("/api/imports", content=body, headers=ZIP)
    assert response.status_code == 422 and response.json()["detail"].startswith("saved/saved_posts.json is damaged")


def test_the_preview_names_saved_files_skipped_for_size(
    client: TestClient, rt: Runtime, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(export, "MEMBER_MAX_BYTES", len(json.dumps(SAVED)))
    members = {"saved/saved_posts.json": SAVED, "saved/saved_collections.json": [SAVED, SAVED]}
    view = _upload(client, _zip(members))
    assert view["files_read"] == ["saved/saved_posts.json"]
    assert view["files_skipped_large"] == ["saved/saved_collections.json"]

    path = tmp_path / "meta.zip"
    path.write_bytes(_zip(members))
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime, "setup_logging", lambda *a, **kw: None)
    result = CliRunner().invoke(cli.app, ["import", str(path)], input="n\n")
    assert "Skipped saved/saved_collections.json (too large)" in result.output, result.output


def test_the_preview_says_which_saved_files_the_total_cap_left_unread(
    client: TestClient, rt: Runtime, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(export, "SCAN_MAX_BYTES", len(json.dumps(SAVED)) + 10)
    members: dict[str, object] = {"saved/saved_collections.json": SAVED, "saved/saved_posts.json": SAVED}
    view = _upload(client, _zip(members))
    assert view["files_read"] == ["saved/saved_posts.json"]
    assert (view["files_skipped_large"], view["files_skipped_budget"]) == ([], ["saved/saved_collections.json"])

    path = tmp_path / "meta.zip"
    path.write_bytes(_zip(members))
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime, "setup_logging", lambda *a, **kw: None)
    result = CliRunner().invoke(cli.app, ["import", str(path)], input="n\n")
    assert "Skipped saved/saved_collections.json (not read: over the 0 MB total)" in result.output, result.output
    assert "(too large)" not in result.output


def test_an_upload_over_the_cap_is_refused(client: TestClient, rt: Runtime) -> None:
    rt.settings.import_max_bytes = 100
    declared = client.post("/api/imports", content=b"x" * 500, headers=ZIP)
    assert declared.status_code == 413 and "IMPORT_MAX_BYTES" in declared.json()["detail"]
    streamed = client.post("/api/imports", content=iter([b"x" * 60, b"x" * 60]), headers=ZIP)
    assert streamed.status_code == 413
    assert list(rt.settings.imports_dir.iterdir()) == []


def test_start_pause_and_cancel_through_the_api(client: TestClient) -> None:
    view = _upload(client, _zip({"saved/saved_posts.json": SAVED}))
    base = f"/api/imports/{view['id']}/actions"
    started = client.post(f"{base}/start", json={"limit": 2}).json()
    assert started["phase"] == "running" and started["counts"]["waiting"] == 2 and started["counts"]["skipped"] == 2
    conflict = client.post(f"{base}/start")
    assert conflict.status_code == 409 and conflict.json()["detail"] == "cannot start an import that is running"
    assert client.post(f"{base}/pause").json()["pause_reason"] == "user"
    assert client.post(f"{base}/cancel").json()["phase"] == "cancelled"
    assert client.post("/api/imports/999/actions/cancel").status_code == 404
    assert client.get("/api/imports/999").status_code == 404
    assert client.post(f"{base}/start", json={"limit": 0}).status_code == 422


async def test_the_pulse_moves_on_import_changes_and_imports_are_quiet(
    client: TestClient, rt: Runtime, clock: Clock
) -> None:
    view = _upload(client, _zip({"saved/saved_posts.json": SAVED}))
    before = client.get("/api/status").json()["pulse"]["revision"]
    clock.advance(seconds=1)
    client.post(f"/api/imports/{view['id']}/actions/start")
    status = client.get("/api/status").json()
    assert status["pulse"]["revision"] != before

    imports.release_next(clock(), rt.pace, llm_ready=True)
    [motion] = client.get("/api/status").json()["in_motion"]
    assert motion["announce"] is False


async def test_a_worker_step_releases_an_imported_post_then_processes_it(
    client: TestClient, rt: Runtime, goal: int
) -> None:
    view = _upload(client, _zip({"saved/saved_posts.json": SAVED}))
    client.post(f"/api/imports/{view['id']}/actions/start", json={"limit": 1})
    claimed, outcome = await rt.worker.step()
    assert claimed and outcome is not None
    with db.read_session() as s:
        [link] = s.exec(select(ImportLink).where(ImportLink.state == LinkState.released)).all()
    assert link.item_id == outcome.item_id and outcome.origin_channel is Channel.export
    assert client.get(f"/api/imports/{view['id']}").json()["phase"] == "finished"


def test_the_imported_item_carries_its_channel(client: TestClient, rt: Runtime, clock: Clock) -> None:
    intake.submit("https://www.instagram.com/reel/X1/", Origin(Channel.export), clock(), llm_ready=True)
    [item] = client.get("/api/items", params={"view": "inbox"}).json()
    assert item["origin_channel"] == "export"


def test_cli_import_previews_then_starts_the_newest_n(
    rt: Runtime, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "meta.zip"
    path.write_bytes(_zip({"saved/saved_posts.json": SAVED}))
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime, "setup_logging", lambda *a, **kw: None)

    result = CliRunner().invoke(cli.app, ["import", str(path), "--limit", "2", "--yes"])
    assert result.exit_code == 0, result.output
    assert "Read saved/saved_posts.json" in result.output
    assert "    4 new, newest first" in result.output
    assert "Importing 2." in result.output and "Import 1 started." in result.output
    with db.read_session() as s:
        states = sorted(link.state.value for link in s.exec(select(ImportLink)))
    assert states == ["skipped", "skipped", "waiting", "waiting"]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (_zip({"likes/liked_posts.json": {}}), "No saved posts in this zip"),
        (_zip({"saved/saved_posts.json": SAVED}).replace(b"reel/R0", b"reel/X0", 1), "is damaged in this zip"),
    ],
    ids=["no-saves", "damaged"],
)
def test_cli_import_refuses_an_unreadable_zip(
    body: bytes, message: str, rt: Runtime, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "export.zip"
    path.write_bytes(body)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime, "setup_logging", lambda *a, **kw: None)
    result = CliRunner().invoke(cli.app, ["import", str(path)])
    assert result.exit_code == 1 and message in result.output and result.exception is not None
    assert isinstance(result.exception, SystemExit), "a message, not a traceback"
