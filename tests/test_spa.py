from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sift.runtime import Runtime
from sift.web import openapi
from sift.web.app import create_app, write_allowed

INDEX = "<!doctype html><div id=root></div>"


def _build(dist: Path) -> None:
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX)
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)")
    (dist / "favicon.svg").write_text("<svg/>")


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    d = tmp_path / "dist"
    _build(d)
    (tmp_path / "secret.txt").write_text("outside dist")
    return d


@pytest.fixture
def client(rt: Runtime, dist: Path) -> Iterator[TestClient]:
    with TestClient(create_app(rt, run_background=False, dist=dist)) as c:
        yield c


@pytest.mark.parametrize("path", ["/", "/inbox", "/kept?q=tacos&goal=3", "/items/12", "/digests/4", "/nope"])
def test_client_routes_get_index_without_caching(client: TestClient, path: str) -> None:
    r = client.get(path)
    assert r.status_code == 200 and r.text == INDEX and r.headers["cache-control"] == "no-cache"


def test_hashed_assets_cache_forever_and_root_files_revalidate(client: TestClient) -> None:
    asset = client.get("/assets/index-abc123.js")
    assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
    assert client.get("/favicon.svg").headers["cache-control"] == "no-cache"
    assert client.head("/inbox").status_code == 200


@pytest.mark.parametrize("path", ["/assets/index-old999.js", "/assets/gone/chunk.css", "/assets"])
def test_missing_assets_are_not_found(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404


def test_unknown_api_paths_stay_json(client: TestClient) -> None:
    for path in ("/api", "/api/nope", "/api/items/1/nope"):
        r = client.get(path)
        assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


def test_api_docs_win_over_the_catch_all(client: TestClient) -> None:
    r = client.get("/api/docs")
    assert r.status_code == 200 and "swagger" in r.text.lower()


def test_no_file_outside_dist(client: TestClient) -> None:
    for path in (
        "/../secret.txt",
        "/%2e%2e/secret.txt",
        "/assets/../../secret.txt",
        "/assets/%2e%2e/%2e%2e/secret.txt",
    ):
        assert "outside dist" not in client.get(path).text


def test_missing_build_explains_itself_then_recovers_without_a_restart(rt: Runtime, tmp_path: Path) -> None:
    dist = tmp_path / "later"
    with TestClient(create_app(rt, run_background=False, dist=dist)) as c:
        page = c.get("/inbox")
        assert page.status_code == 503 and "bun run --cwd web build" in page.text
        assert c.get("/api/status").status_code == 200
        assert c.get("/health").text == "ok"
        _build(dist)
        assert c.get("/inbox").text == INDEX


@pytest.mark.parametrize(
    ("site", "origin", "host", "allowed"),
    [
        pytest.param("same-origin", "http://localhost:5173", "127.0.0.1:8000", True, id="vite-dev-proxy"),
        pytest.param("same-origin", None, "127.0.0.1:8000", True, id="same-origin-no-origin"),
        pytest.param("none", None, "127.0.0.1:8000", True, id="user-initiated"),
        pytest.param("cross-site", "https://evil.example", "127.0.0.1:8000", False, id="cross-site"),
        pytest.param("same-site", "http://localhost:3000", "127.0.0.1:8000", False, id="other-localhost-port"),
        pytest.param(None, "https://evil.example", "127.0.0.1:8000", False, id="no-fetch-metadata-foreign-origin"),
        pytest.param(None, "http://127.0.0.1:8000", "127.0.0.1:8000", True, id="no-fetch-metadata-same-origin"),
        pytest.param(None, None, "127.0.0.1:8000", True, id="curl"),
    ],
)
def test_write_guard(site: str | None, origin: str | None, host: str, allowed: bool) -> None:
    assert write_allowed(site, origin, host) is allowed


def test_write_guard_is_wired_and_answers_json(client: TestClient) -> None:
    refused = client.put("/api/values", json={"values_text": "x"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert refused.status_code == 403 and refused.json() == {"detail": "Cross-site request refused"}
    no_metadata = client.put("/api/values", json={"values_text": "x"}, headers={"Origin": "https://evil.example"})
    assert no_metadata.status_code == 403
    ok = client.put("/api/values", json={"values_text": "x"}, headers={"Sec-Fetch-Site": "same-origin"})
    assert ok.status_code == 200
    assert client.get("/api/values", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


def test_codegen_document_matches_the_served_schema(client: TestClient) -> None:
    assert client.get("/api/openapi.json").json() == openapi.document()


def test_doctor_reports_a_missing_or_stale_build(tmp_path: Path) -> None:
    import os

    from sift.doctor import web_build

    dist, src = tmp_path / "dist", tmp_path / "src"
    src.mkdir()
    (src / "main.tsx").write_text("x")
    assert web_build(dist, src).ok is False
    _build(dist)
    os.utime(src / "main.tsx", (0, 0))
    assert web_build(dist, src).ok is True
    os.utime(src / "main.tsx", None)
    os.utime(dist / "index.html", (0, 0))
    assert web_build(dist, src).ok is None
