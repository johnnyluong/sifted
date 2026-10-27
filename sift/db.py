from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import DateTime, TypeDecorator
from sqlmodel import Session

_engine: Engine | None = None


class UTCDateTime(TypeDecorator[datetime]):
    """SQLite drops tzinfo, so values are stored as naive UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime written to a UTCDateTime column")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


def configure(db_url: str) -> Engine:
    global _engine
    engine = create_engine(db_url, connect_args={"check_same_thread": False, "timeout": 10})

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: Any, _record: Any) -> None:
        # Hand transaction control to the "begin" hook below (the pysqlite recipe).
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        for pragma in ("journal_mode=WAL", "busy_timeout=5000", "foreign_keys=ON", "synchronous=NORMAL"):
            cur.execute(f"PRAGMA {pragma}")
        cur.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn: Any) -> None:
        write = conn.get_execution_options().get("sift_write", False)
        # WAL: a deferred read-then-write gets SQLITE_BUSY at once, bypassing busy_timeout.
        conn.exec_driver_sql("BEGIN IMMEDIATE" if write else "BEGIN")

    if _engine is not None:
        _engine.dispose()
    _engine = engine
    return engine


def engine() -> Engine:
    if _engine is None:
        raise RuntimeError("sift.db.configure() was not called")
    return _engine


@contextmanager
def read_session() -> Iterator[Session]:
    with Session(engine(), expire_on_commit=False) as s:
        yield s


@contextmanager
def write_session() -> Iterator[Session]:
    bind = engine().execution_options(sift_write=True)
    with Session(bind, expire_on_commit=False) as s, s.begin():
        yield s
