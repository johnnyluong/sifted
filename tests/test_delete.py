from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import col, select

from sift import db
from sift.domain import ItemStatus, LinkState, Source
from sift.llm.fake import FakeLLM
from sift.models import DigestEntry, Import, ImportLink, Item, Outline, OutlineLabel
from sift.organize.organizer import Organizer
from sift.runtime import Runtime
from sift.web.app import create_app
from tests.conftest import Clock

FIXTURES = Path(__file__).parent / "fixtures"
PNG = (FIXTURES / "screenshot.png").read_bytes()
JPEG = b"\xff\xd8\xff\xe0 another image"


@pytest.fixture
def client(rt: Runtime, tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(rt, run_background=False, dist=tmp_path / "no-dist")) as c:
        yield c


async def _kept(client: TestClient, rt: Runtime, clock: Clock, *codes: str) -> list[int]:
    ids = []
    for code in codes:
        [r] = client.post("/api/items", json={"text": f"https://www.instagram.com/reel/{code}/"}).json()
        await rt.worker.run_item(r["item"]["id"])
        clock.advance(minutes=1)
        ids.append(r["item"]["id"])
    org = Organizer(clock)
    while org.step(FakeLLM(), import_running=False):
        pass
    return ids


def _released_from_an_import(item_id: int, clock: Clock) -> int:
    with db.write_session() as s:
        imp = Import(
            filename="export.zip",
            created_at=clock(),
            updated_at=clock(),
            files_read=[],
            files_skipped_large=[],
            files_skipped_budget=[],
            unsupported=[],
        )
        s.add(imp)
        s.flush()
        row = s.get(Item, item_id)
        assert row is not None and imp.id is not None
        link = ImportLink(
            import_id=imp.id,
            source=row.source,
            canonical_id=row.canonical_id,
            clean_url=row.clean_url,
            url=row.url,
            state=LinkState.released,
            item_id=item_id,
            released_at=clock(),
        )
        s.add(link)
        s.flush()
        assert link.id is not None
        return link.id


def _link(link_id: int) -> tuple[LinkState, int | None, datetime | None]:
    with db.read_session() as s:
        link = s.get(ImportLink, link_id)
        assert link is not None
        return link.state, link.item_id, link.released_at


def _rows_naming(item_id: int) -> dict[str, int]:
    with db.read_session() as s:
        return {
            "item": len(s.exec(select(Item).where(Item.id == item_id)).all()),
            "outline": len(s.exec(select(Outline).where(Outline.item_id == item_id)).all()),
            "labels": len(s.exec(select(OutlineLabel).where(OutlineLabel.item_id == item_id)).all()),
            "digest": len(s.exec(select(DigestEntry).where(DigestEntry.item_id == item_id)).all()),
            "import": len(s.exec(select(ImportLink).where(ImportLink.item_id == item_id)).all()),
        }


def _topic(client: TestClient) -> dict:
    [group] = client.get("/api/topics").json()["groups"]
    [topic] = group["topics"]
    return topic


async def test_deleting_an_archived_post_removes_it_and_every_row_and_file_that_names_it(
    client: TestClient, rt: Runtime, clock: Clock, goal: int
) -> None:
    stays, gone = await _kept(client, rt, clock, "STAY", "GONE")
    digest = client.post("/api/digests").json()
    assert gone in digest["item_ids"]
    link = _released_from_an_import(gone, clock)
    released_at = clock()
    client.post(f"/api/items/{gone}/actions/archive")
    workdir = rt.settings.media_dir / str(gone)
    assert workdir.is_dir()
    assert client.get(f"/api/items/{gone}").json()["can_delete"] is True
    assert [r["can_delete"] for r in client.get("/api/items", params={"view": "archived"}).json()] == [True]
    assert _rows_naming(gone) == {"item": 1, "outline": 1, "labels": 3, "digest": 1, "import": 1}
    assert (_topic(client)["kept"], _topic(client)["archived"]) == (1, 1)

    response = client.delete(f"/api/items/{gone}")

    assert response.status_code == 204 and response.content == b""
    assert _rows_naming(gone) == {"item": 0, "outline": 0, "labels": 0, "digest": 0, "import": 0}
    assert _link(link) == (LinkState.released, None, released_at), "detached, so the import's cap still counts it"
    assert not workdir.exists() and (rt.settings.media_dir / str(stays)).is_dir()
    assert client.get(f"/api/items/{gone}").status_code == 404
    assert (_topic(client)["kept"], _topic(client)["archived"]) == (1, 0)
    assert client.get("/api/status").json()["nav"]["archived"] == 0
    page = client.get(f"/api/digests/{digest['id']}")
    assert page.status_code == 200 and page.json()["item_ids"] == [stays]
    assert client.get("/api/digests").json()["latest"]["id"] == digest["id"]

    [again] = client.post("/api/items", json={"text": "https://www.instagram.com/reel/GONE/"}).json()
    assert again["kind"] == "queued"
    assert again["item"]["id"] > gone, "a deleted post's id is never handed to a new post"


async def test_a_post_that_is_not_archived_is_refused_and_left_whole(
    client: TestClient, rt: Runtime, clock: Clock, goal: int
) -> None:
    [kept] = await _kept(client, rt, clock, "KEPT")
    [queued] = client.post("/api/items", json={"text": "https://www.instagram.com/reel/QUEUED/"}).json()
    before = _rows_naming(kept)
    assert client.get(f"/api/items/{kept}").json()["can_delete"] is False

    for item_id, status in ((kept, "kept"), (queued["item"]["id"], "queued")):
        response = client.delete(f"/api/items/{item_id}")
        assert response.status_code == 409
        assert response.json()["detail"] == f"Only an archived post can be deleted; this one is {status}."

    assert _rows_naming(kept) == before
    assert (rt.settings.media_dir / str(kept)).is_dir()
    assert client.get(f"/api/items/{queued['item']['id']}").status_code == 200
    assert client.delete("/api/items/999").status_code == 404


def _archive_directly(item_id: int) -> None:
    with db.write_session() as s:
        row = s.get(Item, item_id)
        assert row is not None
        row.status = ItemStatus.archived


def test_an_uploaded_image_another_post_uses_is_kept(client: TestClient, rt: Runtime) -> None:
    [single] = client.post("/api/uploads", params={"channel": "web"}, content=PNG).json()
    png = Path(single["item"]["url"]).name
    jpeg = client.post("/api/uploads/files", content=JPEG).json()["name"]
    [pair] = client.post("/api/uploads/sets", json={"names": [png, jpeg], "channel": "web"}).json()
    for result in (single, pair):
        _archive_directly(result["item"]["id"])
    uploads = rt.settings.uploads_dir

    assert client.delete(f"/api/items/{single['item']['id']}").status_code == 204
    assert (uploads / png).is_file(), "the set still reads it"

    assert client.delete(f"/api/items/{pair['item']['id']}").status_code == 204
    assert not (uploads / png).exists() and not (uploads / jpeg).exists()
    with db.read_session() as s:
        assert s.exec(select(Item).where(col(Item.source) == Source.image)).all() == []
    [again] = client.post("/api/uploads", params={"channel": "web"}, content=PNG).json()
    assert again["kind"] == "queued" and (uploads / png).is_file()
