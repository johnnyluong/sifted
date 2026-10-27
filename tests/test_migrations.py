from __future__ import annotations

import sqlalchemy as sa
from sqlmodel import col, select

from alembic import command
from sift import db, digest, runtime
from sift.config import Settings
from sift.domain import Channel, DigestRole, ItemStatus, ItemType, Source
from sift.models import DigestEntry, Item
from tests.conftest import Clock

BEFORE_QUEUE = "3fc56085a339"

LEGACY = """A week to ship.

## Top 3 to act on this week
1. **[Tacos](/items/3)**

   Why tacos now.

   Next: Book Friday.

2. **[A pick the parse cannot read](/items/1)**

   A why
   on two lines.

   Next: n


## By goal

### Other
- [Search tips](/items/2): Line for two.

## Places

### Elsewhere
- [Bar](/items/4): Line for four.
"""


def _item(i: int, clock: Clock, item_type: ItemType) -> Item:
    return Item(
        id=i,
        source=Source.instagram,
        canonical_id=f"M{i}",
        url=f"https://www.instagram.com/reel/M{i}/",
        clean_url=f"https://www.instagram.com/reel/M{i}/",
        origin_channel=Channel.web,
        received_at=clock(),
        status=ItemStatus.kept,
        extracted_at=clock(),
        item_type=item_type,
        title=f"Item {i}",
        summary=f"Summary {i}",
        details={},
        next_action=f"Action {i}",
        relevance_reason=f"Reason {i}",
    )


def _queue() -> list[tuple[int, int, DigestRole, str | None, str | None, str | None]]:
    with db.read_session() as s:
        rows = s.exec(select(DigestEntry).order_by(col(DigestEntry.position))).all()
    return [(e.position, e.item_id, e.role, e.why, e.next_action, e.line) for e in rows]


def test_old_digests_become_queues_and_round_trip(settings: Settings, clock: Clock) -> None:
    settings.data_dir.mkdir(parents=True)
    db.configure(settings.db_url)
    cfg = runtime.alembic_config(settings)
    command.upgrade(cfg, BEFORE_QUEUE)
    with db.write_session() as s:
        for i, kind in ((1, ItemType.idea), (2, ItemType.idea), (3, ItemType.place), (4, ItemType.place)):
            s.add(_item(i, clock, kind))
    raw = sa.create_engine(settings.db_url)
    with raw.begin() as c:
        c.execute(
            sa.text("INSERT INTO digests VALUES (1, :t, :t, :t, :md, 'claude-sonnet-5-5', NULL)"),
            {"t": clock().strftime("%Y-%m-%d %H:%M:%S.%f"), "md": LEGACY},
        )
        for item_id, section in ((2, "goal"), (3, "top"), (4, "places"), (1, "top")):
            c.execute(sa.text("INSERT INTO digest_entries VALUES (1, :i, :s)"), {"i": item_id, "s": section})

    command.upgrade(cfg, "head")
    queue = _queue()
    assert queue == [
        (1, 3, DigestRole.pick, "Why tacos now.", "Book Friday.", None),
        (2, 1, DigestRole.pick, "Reason 1", "Action 1", None),
        (3, 2, DigestRole.new, "Reason 2", "Action 2", "Line for two."),
        (4, 4, DigestRole.new, "Reason 4", "Action 4", "Line for four."),
    ]
    view = digest.get_digest(1, llm_ready=True)
    assert view is not None and view.opening == "A week to ship."
    assert [p.item.id for p in view.top] == [3, 1, 2] and view.top[2].refill
    assert [(g.heading, [x.line for x in g.lines]) for g in view.groups] == [("Elsewhere", ["Line for four."])]

    command.downgrade(cfg, "-1")
    with raw.connect() as c:
        md = c.execute(sa.text("SELECT content_md FROM digests WHERE id = 1")).scalar_one()
    assert md.startswith("A week to ship.") and "**[Item 3](/items/3)**" in md and "(/items/4): Line for four." in md
    command.upgrade(cfg, "head")
    assert _queue() == queue
    raw.dispose()
