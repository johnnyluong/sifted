from __future__ import annotations

import sqlalchemy as sa
from sqlmodel import SQLModel, col, select

from alembic import command
from sift import db, digest, runtime
from sift.config import Settings
from sift.domain import Channel, DigestRole, ItemStatus, ItemType, LinkState, Source
from sift.items import queries
from sift.llm.schemas import ProductCard
from sift.models import DigestEntry, Import, ImportLink, Item
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


def _old_items(row: dict[str, object]) -> sa.Insert:
    """An insert of only these columns, so model defaults for columns a migration adds later stay out."""
    items = SQLModel.metadata.tables["items"]
    return sa.insert(sa.table("items", *(sa.column(k, items.c[k].type) for k in row)))


def _queue() -> list[tuple[int, int, DigestRole, str | None, str | None, str | None]]:
    with db.read_session() as s:
        rows = s.exec(select(DigestEntry).order_by(col(DigestEntry.position))).all()
    return [(e.position, e.item_id, e.role, e.why, e.next_action, e.line) for e in rows]


def test_old_digests_become_queues_and_round_trip(settings: Settings, clock: Clock) -> None:
    settings.data_dir.mkdir(parents=True)
    db.configure(settings.db_url)
    cfg = runtime.alembic_config(settings)
    command.upgrade(cfg, BEFORE_QUEUE)
    raw = sa.create_engine(settings.db_url)
    with raw.begin() as c:
        kinds = ((1, ItemType.idea), (2, ItemType.idea), (3, ItemType.place), (4, ItemType.place))
        rows = [_item(i, clock, kind).model_dump(exclude_none=True, exclude={"wishlist"}) for i, kind in kinds]
        c.execute(_old_items(rows[0]), rows)
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

    command.downgrade(cfg, BEFORE_QUEUE)
    with raw.connect() as c:
        md = c.execute(sa.text("SELECT content_md FROM digests WHERE id = 1")).scalar_one()
    assert md.startswith("A week to ship.") and "**[Item 3](/items/3)**" in md and "(/items/4): Line for four." in md
    command.upgrade(cfg, "head")
    assert _queue() == queue
    raw.dispose()


BEFORE_WISHLIST = "228878c93883"


def test_wishlist_migration_backfills_product_cards_and_round_trips(settings: Settings, clock: Clock) -> None:
    settings.data_dir.mkdir(parents=True)
    db.configure(settings.db_url)
    cfg = runtime.alembic_config(settings)
    command.upgrade(cfg, BEFORE_WISHLIST)
    raw = sa.create_engine(settings.db_url)
    product = _item(1, clock, ItemType.product).model_dump(exclude_none=True, exclude={"wishlist"})
    product["details"] = {"name": "Jacket", "what_it_is": "A rain jacket", "price": "$90", "link": None}
    with raw.begin() as c:
        c.execute(_old_items(product), [product])

    def columns() -> set[str]:
        with raw.connect() as c:
            return {r[1] for r in c.execute(sa.text("PRAGMA table_info(items)"))}

    command.upgrade(cfg, "head")
    detail = queries.get_item(1, llm_ready=True)
    assert detail is not None and isinstance(detail.card, ProductCard)
    assert detail.card.details.wishlist is False and detail.wishlist is False

    command.downgrade(cfg, BEFORE_WISHLIST)
    assert not {"wishlist", "wishlist_override"} & columns()
    with raw.connect() as c:
        details = c.execute(sa.text("SELECT details FROM items WHERE id = 1")).scalar_one()
    assert "wishlist" not in details

    command.upgrade(cfg, "head")
    assert {"wishlist", "wishlist_override"} <= columns()
    raw.dispose()


BEFORE_SETTLED = "931548f27344"


def test_settled_marker_migration_keeps_processed_at_only_on_settled_posts(settings: Settings, clock: Clock) -> None:
    settings.data_dir.mkdir(parents=True)
    db.configure(settings.db_url)
    cfg = runtime.alembic_config(settings)
    command.upgrade(cfg, BEFORE_SETTLED)
    stale, settled_at = clock(), clock.advance(hours=1)
    scored = {"scored_at": stale, "relevance_score": 70, "threshold_decision": "keep"}
    cases: dict[int, dict[str, object]] = {
        1: {"status": ItemStatus.queued, "processed_at": stale},
        2: {"status": ItemStatus.failed, "processed_at": stale, "failure_kind": "llm_failed"},
        3: {"status": ItemStatus.archived, "processed_at": stale},
        4: {"status": ItemStatus.kept, "processed_at": stale, **scored},
        5: {"status": ItemStatus.kept, "decided_at": settled_at, **scored},
        6: {"status": ItemStatus.kept, "wishlist": True, "decided_at": settled_at},
    }
    raw = sa.create_engine(settings.db_url)
    with raw.begin() as c:
        for i, fields in cases.items():
            row = {**_item(i, clock, ItemType.idea).model_dump(exclude_none=True), **fields}
            c.execute(_old_items(row), [row])

    command.upgrade(cfg, "head")
    with db.read_session() as s:
        marks = {r.id: r.processed_at for r in s.exec(select(Item)).all()}
    assert marks == {1: None, 2: None, 3: None, 4: stale, 5: settled_at, 6: settled_at}
    command.downgrade(cfg, BEFORE_SETTLED)
    command.upgrade(cfg, "head")
    raw.dispose()


BEFORE_DETACH = "7e2b0c4d9a13"


def test_a_released_link_can_lose_its_post_and_round_trips(settings: Settings, clock: Clock) -> None:
    settings.data_dir.mkdir(parents=True)
    db.configure(settings.db_url)
    cfg = runtime.alembic_config(settings)
    command.upgrade(cfg, BEFORE_DETACH)
    with db.write_session() as s:
        s.add(_item(1, clock, ItemType.idea))
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
        assert imp.id is not None
        for code, item_id in (("M1", 1), ("M2", None)):
            state = LinkState.released if item_id else LinkState.found
            url = f"https://www.instagram.com/reel/{code}/"
            s.add(
                ImportLink(
                    import_id=imp.id,
                    source=Source.instagram,
                    canonical_id=code,
                    clean_url=url,
                    url=url,
                    state=state,
                    item_id=item_id,
                    released_at=clock() if item_id else None,
                )
            )

    def links() -> list[tuple[str, LinkState, int | None, object]]:
        with db.read_session() as s:
            rows = s.exec(select(ImportLink).order_by(col(ImportLink.canonical_id))).all()
            return [(r.canonical_id, r.state, r.item_id, r.released_at) for r in rows]

    command.upgrade(cfg, "head")
    with db.write_session() as s:
        s.exec(sa.update(ImportLink).values(item_id=None))
    assert links() == [("M1", LinkState.released, None, clock()), ("M2", LinkState.found, None, None)]

    command.downgrade(cfg, "-1")
    assert links() == [("M1", LinkState.skipped, None, clock()), ("M2", LinkState.found, None, None)]
    command.upgrade(cfg, "head")
