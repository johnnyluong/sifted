from __future__ import annotations

import shutil
import struct
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sift import db, media
from sift.domain import FailureKind, ItemStatus, MediaKind, ProcessingError, Source
from sift.llm.client import extract_prompt
from sift.llm.schemas import ExtractInput
from sift.media import SCREENSHOT_LONG_EDGE, image_format
from sift.models import Item
from sift.runtime import Runtime
from sift.sources import image
from sift.sources.base import FetchResult
from sift.sources.image import MAX_SET, MAX_TILES, THUMB_LONG_EDGE, ImageFetcher, Row, tile_budget, tiles
from sift.web.app import create_app

FIXTURE = Path(__file__).parent / "fixtures" / "screenshot.png"
PNG = FIXTURE.read_bytes()
HEIC = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0 converted"


@pytest.fixture
def client(rt: Runtime, tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(rt, run_background=False, dist=tmp_path / "no-dist")) as c:
        yield c


def _upload(client: TestClient, body: bytes, channel: str = "web") -> dict:
    response = client.post("/api/uploads", params={"channel": channel}, content=body)
    assert response.status_code == 202, response.text
    [result] = response.json()
    return result


def _row(item_id: int) -> Item:
    with db.read_session() as s:
        row = s.get(Item, item_id)
        assert row is not None
        return row


def test_an_uploaded_png_is_queued_as_an_image_post(client: TestClient, rt: Runtime) -> None:
    result = _upload(client, PNG)
    assert result["kind"] == "queued"
    item = result["item"]
    name = Path(item["url"]).name
    assert item["source"] == "image"
    assert item["url"] == f"/api/uploads/{name}"
    assert image.UPLOAD_NAME.match(name) and name.endswith(".png")
    assert (rt.settings.uploads_dir / name).read_bytes() == PNG, "the original is kept as sent"
    row = _row(item["id"])
    assert (row.source, row.clean_url, row.origin_channel) == (Source.image, item["url"], "web")
    assert row.status is ItemStatus.queued


def test_the_same_image_twice_is_a_duplicate(client: TestClient, rt: Runtime) -> None:
    first = _upload(client, PNG)
    again = _upload(client, PNG, channel="api")
    assert again["kind"] == "duplicate" and again["item"]["id"] == first["item"]["id"]
    assert len(list(rt.settings.uploads_dir.iterdir())) == 1


def test_text_is_refused_whatever_the_header_says(client: TestClient, rt: Runtime) -> None:
    response = client.post(
        "/api/uploads", content=b"https://www.instagram.com/reel/abc/", headers={"content-type": "image/png"}
    )
    assert response.status_code == 415
    assert "PNG, JPEG, WebP, GIF and HEIC" in response.json()["detail"]
    assert not rt.settings.uploads_dir.exists() or not any(rt.settings.uploads_dir.iterdir())


@pytest.mark.parametrize("declared", [True, False], ids=["content-length", "streamed"])
def test_an_image_over_the_cap_is_refused(client: TestClient, rt: Runtime, declared: bool) -> None:
    rt.settings.upload_max_bytes = len(PNG) - 1
    body = PNG if declared else iter([PNG[:100], PNG[100:]])
    response = client.post("/api/uploads", content=body)
    assert response.status_code == 413
    assert "UPLOAD_MAX_BYTES" in response.json()["detail"]


def test_heic_is_stored_as_the_converted_jpeg(client: TestClient, rt: Runtime, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[bytes] = []
    monkeypatch.setattr(image, "heif_to_jpeg", lambda data: sent.append(data) or JPEG)
    item = _upload(client, HEIC)["item"]
    assert sent == [HEIC]
    assert item["url"].endswith(".jpg")
    assert (rt.settings.uploads_dir / Path(item["url"]).name).read_bytes() == JPEG
    assert _upload(client, HEIC)["kind"] == "duplicate"
    assert sent == [HEIC], "a repeat upload is not converted again"


def test_a_heic_that_cannot_be_converted_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(data: bytes) -> bytes:
        raise image.NotAnImage("This HEIC image could not be converted to JPEG.")

    monkeypatch.setattr(image, "heif_to_jpeg", fail)
    response = client.post("/api/uploads", content=HEIC)
    assert response.status_code == 415


@pytest.mark.skipif(shutil.which("sips") is None, reason="sips is macOS only")
def test_sips_turns_a_real_heic_into_a_jpeg(tmp_path: Path) -> None:
    heic = tmp_path / "photo.heic"
    subprocess.run(["sips", "-s", "format", "heic", str(FIXTURE), "--out", str(heic)], capture_output=True, check=True)
    data = heic.read_bytes()
    assert image_format(data) == "heif"
    assert image_format(image.heif_to_jpeg(data)) == "jpg"


def test_an_upload_is_served_by_its_name(client: TestClient) -> None:
    url = _upload(client, PNG)["item"]["url"]
    response = client.get(url)
    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "name", ["..", "..%2Fsift.db", "%2E%2E%2Fsift.db", "notes.txt", f"{'a' * 32}.svg", f"{'A' * 32}.png", "x.part"]
)
def test_only_stored_upload_names_are_served(client: TestClient, rt: Runtime, name: str) -> None:
    rt.settings.uploads_dir.mkdir(parents=True)
    (rt.settings.data_dir / "sift.db").touch()
    for planted in ("notes.txt", f"{'a' * 32}.svg", f"{'A' * 32}.png", "x.part"):
        (rt.settings.uploads_dir / planted).write_bytes(PNG)
    response = client.get(f"/api/uploads/{name}")
    assert response.status_code in (404, 422), response.status_code
    assert response.headers["content-type"].startswith("application/json")


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

BANDS = ["red", "lime", "blue", "white", "yellow", "cyan", "magenta", "black"]
RGB = {
    "red": (255, 0, 0),
    "lime": (0, 255, 0),
    "blue": (0, 0, 255),
    "white": (255, 255, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "black": (0, 0, 0),
}


def _banded(path: Path, width: int, band: int, colors: list[str]) -> bytes:
    inputs = [arg for c in colors for arg in ("-f", "lavfi", "-i", f"color=c={c}:s={width}x{band}")]
    stack = "".join(f"[{i}]" for i in range(len(colors))) + f"vstack=inputs={len(colors)}"
    subprocess.run(
        ["ffmpeg", "-v", "error", *inputs, "-filter_complex", stack, "-frames:v", "1", str(path)], check=True
    )
    return path.read_bytes()


def _size(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    width, height = out.split(",")
    return int(width), int(height)


def _color(path: Path) -> str:
    rgb = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
        check=True,
    ).stdout
    return min(RGB, key=lambda c: sum((a - b) ** 2 for a, b in zip(RGB[c], rgb, strict=True)))


def _fetch(tmp_path: Path, *images: bytes) -> tuple[FetchResult, Path]:
    folder = tmp_path / "uploads"
    ref = image.upload_ref([image.store(data, folder) for data in images])
    workdir = tmp_path / "media" / "7"
    return ImageFetcher(folder).fetch(ref, workdir), workdir


@pytest.mark.parametrize(
    ("width", "height", "rows"),
    [
        (1200, 1800, [Row(0, 1800)]),
        (2000, 900, [Row(0, 900)]),
        (1200, 1801, [Row(0, 901), Row(901, 900)]),
        (1179, 2556, [Row(0, 1278), Row(1278, 1278)]),
        (1000, 6000, [Row(0, 1500), Row(1500, 1500), Row(3000, 1500), Row(4500, 1500)]),
    ],
)
def test_tiles_cover_the_image_top_to_bottom_no_taller_than_one_and_a_half_widths(
    width: int, height: int, rows: list[Row]
) -> None:
    assert tiles(width, height) == rows


@needs_ffmpeg
def test_an_image_is_read_as_one_jpeg_slide_with_a_small_jpeg_thumbnail(tmp_path: Path) -> None:
    data = _banded(tmp_path / "photo.png", 1200, 900, ["red", "blue"])
    result, workdir = _fetch(tmp_path, data)
    assert result.media_kind is MediaKind.image and result.author_handle is None
    assert result.slide_paths == (workdir / "slides" / "slide_01.jpg",)
    [slide] = result.slide_paths
    assert slide.read_bytes().startswith(b"\xff\xd8\xff") and _size(slide) == (1200, 1800)
    thumbnail = workdir / "thumbnail.jpg"
    assert result.thumbnail_path == thumbnail
    assert thumbnail.read_bytes().startswith(b"\xff\xd8\xff")
    assert _size(thumbnail) == (320, THUMB_LONG_EDGE)
    assert thumbnail.stat().st_size < len(data)
    assert result.notes.lines == ()
    assert sorted(p.name for p in workdir.rglob("*") if p.is_file()) == ["slide_01.jpg", "thumbnail.jpg"], (
        "the raw upload is not copied into the workdir"
    )


@needs_ffmpeg
def test_a_tall_screenshot_is_read_as_tiles_in_order(tmp_path: Path) -> None:
    colors = BANDS[:4]
    result, workdir = _fetch(tmp_path, _banded(tmp_path / "scroll.png", 300, 450, colors))
    assert [p.name for p in result.slide_paths] == [f"slide_0{i}.jpg" for i in range(1, 5)]
    assert [_size(p) for p in result.slide_paths] == [(300, 450)] * 4
    assert [_color(p) for p in result.slide_paths] == colors
    assert result.thumbnail_path == workdir / "thumbnail.jpg"
    assert _color(workdir / "thumbnail.jpg") == "red", "the thumbnail shows the top"
    assert result.notes.lines == ()


@needs_ffmpeg
def test_a_very_long_screenshot_is_read_from_the_top_and_says_so(tmp_path: Path) -> None:
    result, _ = _fetch(tmp_path, _banded(tmp_path / "scroll.png", 100, 150, BANDS))
    assert len(result.slide_paths) == MAX_TILES
    assert [_color(p) for p in result.slide_paths] == BANDS[:MAX_TILES]
    assert result.notes.lines == (f"Read the top {MAX_TILES} parts of a very long screenshot.",)


def _exif_orientation(jpeg: bytes, orientation: int) -> bytes:
    tiff = b"MM\x00\x2a" + struct.pack(">IH", 8, 1) + struct.pack(">HHIHH", 0x0112, 3, 1, orientation, 0) + bytes(4)
    body = b"Exif\x00\x00" + tiff
    return jpeg[:2] + b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body + jpeg[2:]


@needs_ffmpeg
def test_a_photo_tagged_to_rotate_is_read_upright_and_whole(tmp_path: Path) -> None:
    sideways = tmp_path / "sideways.jpg"
    inputs = [arg for c in ("red", "blue") for arg in ("-f", "lavfi", "-i", f"color=c={c}:s=200x200")]
    subprocess.run(
        ["ffmpeg", "-v", "error", *inputs, "-filter_complex", "hstack", "-frames:v", "1", "-q:v", "2", str(sideways)],
        check=True,
    )
    result, _ = _fetch(tmp_path, _exif_orientation(sideways.read_bytes(), 6))
    sizes = [_size(p) for p in result.slide_paths]
    assert {w for w, _ in sizes} == {200} and sum(h for _, h in sizes) == 400, "the 200x400 upright photo, whole"
    assert (_color(result.slide_paths[0]), _color(result.slide_paths[-1])) == ("red", "blue")


@needs_ffmpeg
def test_a_transparent_png_is_read_on_white(tmp_path: Path) -> None:
    clear = tmp_path / "clear.png"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black@0:s=200x300,format=rgba",
            "-frames:v",
            "1",
            str(clear),
        ],
        check=True,
    )
    result, workdir = _fetch(tmp_path, clear.read_bytes())
    assert [_color(p) for p in result.slide_paths] == ["white"]
    assert _color(workdir / "thumbnail.jpg") == "white"


@needs_ffmpeg
def test_a_failure_after_the_image_is_read_can_be_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def busy(image: Path, out: Path, vf: str, quality: int = 4) -> Path:
        raise ProcessingError(
            FailureKind.transcription_failed, "ffmpeg failed: No space left on device", retryable=True
        )

    monkeypatch.setattr(media, "write_jpeg", busy)
    with pytest.raises(ProcessingError) as e:
        _fetch(tmp_path, _banded(tmp_path / "photo.png", 200, 100, ["red", "blue"]))
    assert e.value.retryable and e.value.message == "ffmpeg failed: No space left on device"
    assert not [p for p in (tmp_path / "media").rglob("*") if p.is_file()], "nothing is left behind"


@needs_ffmpeg
def test_an_image_ffmpeg_cannot_decode_fails_for_good(tmp_path: Path) -> None:
    with pytest.raises(ProcessingError) as e:
        _fetch(tmp_path, PNG[:40] + b"\x00" * 200)
    assert e.value.kind is FailureKind.unsupported_url and not e.value.retryable
    assert e.value.message == "Sift could not read this image."
    assert not list((tmp_path / "media").rglob("*.jpg"))


def test_the_fetcher_fails_for_good_when_the_upload_is_gone(tmp_path: Path) -> None:
    ref = image.upload_ref([image.store(PNG, tmp_path / "uploads")])
    shutil.rmtree(tmp_path / "uploads")
    with pytest.raises(ProcessingError) as e:
        ImageFetcher(tmp_path / "uploads").fetch(ref, tmp_path / "media" / "1")
    assert e.value.kind is FailureKind.post_unavailable and not e.value.retryable
    assert e.value.message == "The uploaded image is no longer in data/uploads."


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (PNG, "png"),
        (b"\xff\xd8\xff\xdb", "jpg"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "webp"),
        (b"GIF89a\x01\x00", "gif"),
        (HEIC, "heif"),
        (b"\x00\x00\x00\x18ftypisom", None),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", None),
        (b"", None),
    ],
)
def test_the_type_comes_from_the_bytes(data: bytes, kind: str | None) -> None:
    assert image_format(data) == kind


@needs_ffmpeg
async def test_an_image_post_becomes_a_scored_card_from_one_frame(client: TestClient, rt: Runtime, goal: int) -> None:
    item_id = _upload(client, PNG)["item"]["id"]
    await rt.worker.run_item(item_id)
    row = _row(item_id)
    assert row.status in (ItemStatus.kept, ItemStatus.archived), row.last_error
    assert row.scored_at is not None and row.title is not None
    assert row.frame_paths == [f"media/{item_id}/frames/slide_01.jpg"]
    assert row.thumbnail_path == f"media/{item_id}/thumbnail.jpg"
    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["author_handle"] is None and detail["card"] is not None
    assert client.get(detail["thumbnail_url"]).content.startswith(b"\xff\xd8\xff")
    listed = client.get("/api/items").json()
    assert [i["id"] for i in listed] == [item_id]


@needs_ffmpeg
async def test_an_image_post_reaches_the_model_at_the_screenshot_edge(
    client: TestClient, rt: Runtime, goal: int, tmp_path: Path
) -> None:
    item_id = _upload(client, _banded(tmp_path / "shot.png", 1200, 900, ["white", "black"]))["item"]["id"]
    await rt.worker.run_item(item_id)
    [frame] = _row(item_id).frame_paths or []
    assert max(_size(rt.settings.data_dir / frame)) == SCREENSHOT_LONG_EDGE


def _store(client: TestClient, body: bytes) -> str:
    response = client.post("/api/uploads/files", content=body)
    assert response.status_code == 201, response.text
    return response.json()["name"]


def _set(client: TestClient, names: list[str], channel: str = "web") -> dict:
    response = client.post("/api/uploads/sets", json={"names": names, "channel": channel})
    assert response.status_code == 202, response.text
    [result] = response.json()
    return result


def _distinct(n: int) -> list[bytes]:
    return [PNG + bytes([i]) for i in range(n)]


def test_storing_an_image_queues_nothing(client: TestClient, rt: Runtime) -> None:
    name = _store(client, PNG)
    assert (rt.settings.uploads_dir / name).read_bytes() == PNG
    assert client.get("/api/items").json() == []
    refused = client.post("/api/uploads/files", content=b"not an image")
    assert refused.status_code == 415
    rt.settings.upload_max_bytes = len(PNG) - 1
    assert client.post("/api/uploads/files", content=PNG + b"!").status_code == 413


def test_a_set_of_stored_images_is_queued_as_one_post(client: TestClient, rt: Runtime) -> None:
    names = [_store(client, data) for data in _distinct(3)]
    result = _set(client, names)
    assert result["kind"] == "queued"
    item = result["item"]
    assert item["source"] == "image" and item["url"] == "/api/uploads/" + ",".join(names)
    row = _row(item["id"])
    assert (row.clean_url, row.origin_channel, row.status) == (item["url"], "web", ItemStatus.queued)
    assert len(client.get("/api/items").json()) == 1
    detail = client.get(f"/api/items/{item['id']}").json()
    assert detail["images"] == [f"/api/uploads/{name}" for name in names]
    assert [client.get(url).content for url in detail["images"]] == _distinct(3)


def test_the_same_set_again_is_a_duplicate_and_a_reordered_set_is_not(client: TestClient) -> None:
    names = [_store(client, data) for data in _distinct(3)]
    first = _set(client, names)["item"]["id"]
    again = _set(client, names, channel="api")
    assert again["kind"] == "duplicate" and again["item"]["id"] == first
    reordered = _set(client, [names[1], names[0], names[2]])
    assert reordered["kind"] == "queued" and reordered["item"]["id"] != first


def test_a_set_of_one_is_the_single_upload(client: TestClient) -> None:
    single = _upload(client, PNG)["item"]
    again = _set(client, [Path(single["url"]).name])
    assert again["kind"] == "duplicate" and again["item"]["id"] == single["id"]
    assert client.get(f"/api/items/{single['id']}").json()["images"] == [single["url"]]


def test_a_set_over_the_limit_or_naming_an_unstored_image_is_refused(client: TestClient) -> None:
    names = [_store(client, data) for data in _distinct(MAX_SET + 1)]
    assert client.post("/api/uploads/sets", json={"names": names}).status_code == 422
    assert client.post("/api/uploads/sets", json={"names": []}).status_code == 422
    unstored = client.post("/api/uploads/sets", json={"names": [names[0], f"{'b' * 32}.png"]})
    assert unstored.status_code == 422 and "is not stored" in unstored.json()["detail"]
    assert client.post("/api/uploads/sets", json={"names": [names[0], "../sift.db"]}).status_code == 422
    assert client.get("/api/items").json() == []


def test_a_set_with_a_missing_image_fails_for_good(tmp_path: Path) -> None:
    folder = tmp_path / "uploads"
    names = [image.store(data, folder) for data in _distinct(3)]
    (folder / names[1]).unlink()
    with pytest.raises(ProcessingError) as e:
        ImageFetcher(folder).fetch(image.upload_ref(names), tmp_path / "media" / "1")
    assert e.value.kind is FailureKind.post_unavailable and not e.value.retryable
    assert e.value.message == "Image 2 of 3 is no longer in data/uploads."


@needs_ffmpeg
def test_a_set_with_an_unreadable_image_names_it(tmp_path: Path) -> None:
    with pytest.raises(ProcessingError) as e:
        _fetch(tmp_path, PNG, PNG[:40] + b"\x00" * 200)
    assert e.value.kind is FailureKind.unsupported_url and not e.value.retryable
    assert e.value.message == "Sift could not read image 2 of 2."


def test_the_prompt_for_one_image_says_nothing_of_several() -> None:
    single = extract_prompt(
        ExtractInput(
            source=Source.image,
            author_handle=None,
            caption=None,
            post_text=None,
            transcript=None,
            frames=["slide_01.jpg"],
            notes=[],
        )
    )
    assert "with no caption and no author. Read every word in it.\n" in single
    assert "screenshots" not in single


@pytest.mark.parametrize(
    ("counts", "taken"),
    [
        ([8], [MAX_TILES]),
        ([1, 1, 1], [1, 1, 1]),
        ([6, 6, 6], [6, 5, 1]),
        ([2, 9, 3, 4], [2, 6, 3, 1]),
        ([3] * MAX_SET, [3, 1, 1, 1, 1, 1, 1, 1, 1, 1]),
    ],
)
def test_every_image_gets_its_first_tile_and_the_rest_go_in_reading_order(counts: list[int], taken: list[int]) -> None:
    assert tile_budget(counts) == taken
    assert sum(taken) <= media.MAX_IMAGES


@needs_ffmpeg
def test_a_set_is_read_in_order_with_the_first_image_as_its_thumbnail(tmp_path: Path) -> None:
    colors = ["red", "blue", "lime"]
    shots = [_banded(tmp_path / f"{c}.png", 300, 150, [c, c]) for c in colors]
    result, workdir = _fetch(tmp_path, *shots)
    assert [p.name for p in result.slide_paths] == ["slide_01.jpg", "slide_02.jpg", "slide_03.jpg"]
    assert [_color(p) for p in result.slide_paths] == colors
    assert result.thumbnail_path == workdir / "thumbnail.jpg"
    assert _color(workdir / "thumbnail.jpg") == "red"
    assert result.notes.lines == ("This post is 3 images of one thing, in reading order.",)
    assert not list(workdir.glob("upright*")), "the upright copies are removed"


@needs_ffmpeg
def test_a_long_set_is_cut_to_the_slide_budget_and_says_how_much_was_read(tmp_path: Path) -> None:
    shots = [_banded(tmp_path / f"{i}.png", 100, 150, BANDS[i : i + 6]) for i in range(3)]
    result, _ = _fetch(tmp_path, *shots)
    assert len(result.slide_paths) == media.MAX_IMAGES
    assert [_color(p) for p in result.slide_paths] == BANDS[0:6] + BANDS[1:6] + BANDS[2:3]
    assert result.notes.lines == (
        "This post is 3 images of one thing, in reading order.",
        "Read 12 of the 18 parts of these 3 screenshots, each from its top.",
    )


@needs_ffmpeg
async def test_a_set_becomes_one_card_from_every_image(
    client: TestClient, rt: Runtime, goal: int, tmp_path: Path
) -> None:
    shots = [_banded(tmp_path / f"{c}.png", 300, 150, [c, c]) for c in ("red", "blue")]
    item_id = _set(client, [_store(client, data) for data in shots])["item"]["id"]
    await rt.worker.run_item(item_id)
    row = _row(item_id)
    assert row.status in (ItemStatus.kept, ItemStatus.archived), row.last_error
    assert row.frame_paths == [f"media/{item_id}/frames/slide_01.jpg", f"media/{item_id}/frames/slide_02.jpg"]
    thumbnail = f"media/{item_id}/thumbnail.jpg"
    assert row.thumbnail_path == thumbnail
    assert _color(rt.settings.data_dir / thumbnail) == "red", "the first image is the thumbnail"


def test_an_image_repeated_in_a_set_is_read_once(client: TestClient) -> None:
    a, b = (_store(client, data) for data in _distinct(2))
    item = _set(client, [a, b, a])["item"]
    assert item["url"] == f"/api/uploads/{a},{b}"
    single = _set(client, [b, b])
    assert single["item"]["url"] == f"/api/uploads/{b}"


def test_every_image_of_the_largest_set_fits_the_slide_budget() -> None:
    assert MAX_SET <= media.MAX_IMAGES
    assert sum(tile_budget([MAX_TILES] * MAX_SET)) == media.MAX_IMAGES
