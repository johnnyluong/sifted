from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sift.domain import Source
from sift.inbox import export
from sift.inbox.export import NotAnExport

OLD_SHAPE = {
    "saved_saved_media": [
        {
            "title": "lucali",
            "string_map_data": {
                "Saved on": {"href": "https://www.instagram.com/reel/OLD1/?igsh=xyz", "timestamp": 1698000000}
            },
        }
    ]
}
NEW_SHAPE = {
    "saved_saved_media": [
        {
            "timestamp": 1729000000,
            "label_values": [
                {"label": "URL", "value": "https://www.instagram.com/p/NEW1/"},
                {
                    "label": "Owner",
                    "dict": [{"dict": [{"label": "URL", "value": "https://www.instagram.com/someuser"}]}],
                },
            ],
        },
        {
            "timestamp": 1729000500000,
            "label_values": [{"label": "URL", "value": "https://www.instagram.com/reel/MS1/"}],
        },
        {"timestamp": 1729000600, "value": "see https://www.instagram.com/stories/chef/3456/ too"},
    ]
}
THREADS_SAVED = {
    "text_post_app_saved": [
        {"timestamp": 1727000000, "media": [{"uri": "https://www.threads.com/@chef/post/THR1"}]},
    ]
}
LIKED = {"likes_media_likes": [{"string_map_data": {"": {"href": "https://www.instagram.com/p/LIKED1/"}}}]}
VIEWED = {
    "impressions_history_posts_seen": [{"string_map_data": {"Author": {"value": "https://www.instagram.com/p/SEEN1/"}}}]
}
DM = {"messages": [{"share": {"link": "https://www.instagram.com/reel/DM1/"}}]}


def _zip(tmp_path: Path, members: dict[str, object]) -> Path:
    path = tmp_path / "export.zip"
    with zipfile.ZipFile(path, "w") as z:
        for name, body in members.items():
            z.writestr(name, body if isinstance(body, str) else json.dumps(body))
    return path


def _full_export(tmp_path: Path) -> Path:
    return _zip(
        tmp_path,
        {
            "your_instagram_activity/saved/saved_posts.json": OLD_SHAPE,
            "your_instagram_activity/saved/saved_collections.json": NEW_SHAPE,
            "your_instagram_activity/threads/saved_threads.json": THREADS_SAVED,
            "your_instagram_activity/likes/liked_posts.json": LIKED,
            "ads_information/ads_and_topics/posts_viewed.json": VIEWED,
            "your_instagram_activity/messages/inbox/saved_by_grace_1/message_1.json": DM,
            "your_instagram_activity/messages/inbox/grace_2/saved_posts.json": DM,
        },
    )


def test_reads_only_saved_files(tmp_path: Path) -> None:
    scan = export.scan(_full_export(tmp_path))
    assert scan.files_read == [
        "your_instagram_activity/saved/saved_posts.json",
        "your_instagram_activity/saved/saved_collections.json",
    ]
    codes = {link.ref.canonical_id for link in scan.links}
    assert codes == {"OLD1", "NEW1", "MS1"}
    assert not codes & {"LIKED1", "SEEN1", "DM1", "THR1"}


def test_both_known_shapes_carry_their_saved_time(tmp_path: Path) -> None:
    scan = export.scan(_full_export(tmp_path))
    saved = {link.ref.canonical_id: link.saved_at for link in scan.links}
    assert saved["OLD1"] == datetime.fromtimestamp(1698000000, UTC)
    assert saved["NEW1"] == datetime.fromtimestamp(1729000000, UTC)
    assert saved["MS1"] == datetime.fromtimestamp(1729000500, UTC), "milliseconds are read as such"


def test_profiles_are_dropped_and_stories_are_unreadable(tmp_path: Path) -> None:
    scan = export.scan(_full_export(tmp_path))
    assert scan.unsupported == ["https://www.instagram.com/stories/chef/3456/"]
    assert sorted((link.ref.source, link.ref.canonical_id) for link in scan.links) == [
        (Source.instagram, "MS1"),
        (Source.instagram, "NEW1"),
        (Source.instagram, "OLD1"),
    ]


def test_a_threads_link_in_an_instagram_file_is_left_out(tmp_path: Path) -> None:
    saved = {
        "saved_saved_media": [{"timestamp": 1729000000, "media": [{"uri": "https://www.threads.com/@chef/post/THR2"}]}]
    }
    scan = export.scan(_zip(tmp_path, {"saved/saved_posts.json": saved}))
    assert scan.links == [] and scan.unsupported == []


def test_a_username_with_threads_in_it_still_imports(tmp_path: Path) -> None:
    path = _zip(tmp_path, {"instagram-nyc_threads-2026-10-26/saved/saved_posts.json": OLD_SHAPE})
    [link] = export.scan(path).links
    assert link.ref.canonical_id == "OLD1"


def test_a_post_saved_twice_counts_once_with_its_earliest_time(tmp_path: Path) -> None:
    later = {
        "saved_saved_media": [
            {"timestamp": 1730000000, "label_values": [{"value": "https://www.instagram.com/reel/OLD1/"}]}
        ]
    }
    path = _zip(
        tmp_path,
        {"saved/saved_collections.json": later, "saved/saved_posts.json": OLD_SHAPE},
    )
    [link] = export.scan(path).links
    assert link.saved_at == datetime.fromtimestamp(1698000000, UTC)


def test_html_export_is_read_without_dates(tmp_path: Path) -> None:
    page = '<a href="https://www.instagram.com/reel/HTML1/?utm=1&amp;x=2">reel</a>'
    [link] = export.scan(_zip(tmp_path, {"your_instagram_activity/saved/saved_posts.html": page})).links
    assert link.ref.canonical_id == "HTML1" and link.saved_at is None


@pytest.mark.parametrize(
    ("path", "saved"),
    [
        ("your_instagram_activity/saved/saved_posts.json", True),
        ("your_instagram_activity/saved/saved_collections.json", True),
        ("your_instagram_activity/threads/saved_threads.json", False),
        ("your_instagram_activity/likes/liked_posts.json", False),
        ("your_instagram_activity/messages/inbox/saved_by_grace_1/message_1.json", False),
        ("your_instagram_activity/saved/saved_posts.jpg", False),
        ("your_instagram_activity/unsaved_drafts.json", False),
    ],
)
def test_saved_member_rule(path: str, saved: bool) -> None:
    assert export.is_saved_member(path) is saved


def test_an_export_without_saved_files_names_what_it_has(tmp_path: Path) -> None:
    path = _zip(
        tmp_path,
        {"your_instagram_activity/likes/liked_posts.json": LIKED, "personal_information/profile.json": {}},
    )
    with pytest.raises(NotAnExport) as caught:
        export.scan(path)
    message = str(caught.value)
    assert message.startswith("No saved posts in this zip.")
    assert "your_instagram_activity/likes" in message and "personal_information/profile.json" in message


def test_an_empty_zip_and_a_non_zip_are_refused(tmp_path: Path) -> None:
    with pytest.raises(NotAnExport, match="It is empty"):
        export.scan(_zip(tmp_path, {}))
    with pytest.raises(NotAnExport, match="not a zip"):
        export.scan(io.BytesIO(b"plain text"))


def _patched(path: Path, edit: dict[bytes, dict[int, bytes]]) -> Path:
    data = bytearray(path.read_bytes())
    for signature, fields in edit.items():
        at = data.index(signature)
        for offset, value in fields.items():
            data[at + offset : at + offset + len(value)] = value
    path.write_bytes(bytes(data))
    return path


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        ({b'"https://www.instagram.com/reel/OLD1': {1: b"X"}}, "saved/saved_posts.json is damaged"),
        ({b"PK\x03\x04": {6: b"\x01"}, b"PK\x01\x02": {8: b"\x01"}}, "saved/saved_posts.json is password-protected"),
        ({b"PK\x03\x04": {8: b"\x63"}, b"PK\x01\x02": {10: b"\x63"}}, "uses a compression Sift can't read"),
    ],
    ids=["bad-crc", "encrypted", "compression"],
)
def test_an_unreadable_member_is_not_an_export(
    edit: dict[bytes, dict[int, bytes]], message: str, tmp_path: Path
) -> None:
    path = _patched(_zip(tmp_path, {"saved/saved_posts.json": OLD_SHAPE}), edit)
    with pytest.raises(NotAnExport, match=message):
        export.scan(path)


def test_an_oversized_member_is_skipped_without_using_up_the_scan_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    small = json.dumps(OLD_SHAPE)
    monkeypatch.setattr(export, "MEMBER_MAX_BYTES", len(small))
    monkeypatch.setattr(export, "SCAN_MAX_BYTES", len(small) + 10)
    big = {"saved_saved_media": [OLD_SHAPE] * 3}
    scan = export.scan(_zip(tmp_path, {"saved/saved_collections.json": big, "saved/saved_posts.json": OLD_SHAPE}))
    assert scan.files_skipped_large == ["saved/saved_collections.json"]
    assert scan.files_read == ["saved/saved_posts.json"]
    assert [link.ref.canonical_id for link in scan.links] == ["OLD1"]


def test_saved_posts_are_read_before_collections_when_the_scan_cap_runs_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    posts, collections = json.dumps(OLD_SHAPE), json.dumps(NEW_SHAPE)
    monkeypatch.setattr(export, "SCAN_MAX_BYTES", max(len(posts), len(collections)) + 10)
    members: dict[str, object] = {"saved/saved_collections.json": NEW_SHAPE, "saved/saved_posts.json": OLD_SHAPE}
    scan = export.scan(_zip(tmp_path, members))
    assert scan.files_read == ["saved/saved_posts.json"]
    assert scan.files_skipped_budget == ["saved/saved_collections.json"]
    assert scan.files_skipped_large == [], "a file under the per-file limit is not too large"


def test_an_export_whose_saved_files_are_all_too_large_names_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(export, "MEMBER_MAX_BYTES", 10)
    with pytest.raises(NotAnExport, match=r"too large to read: saved/saved_posts\.json"):
        export.scan(_zip(tmp_path, {"saved/saved_posts.json": OLD_SHAPE}))
