"""Engine and session factory."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from scoredclub.db.models import Base

_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def get_engine(database_url: str) -> Engine:
    global _engine, _session_factory
    if _engine is None or str(_engine.url) != database_url:
        if _engine is not None:
            _engine.dispose()
        url = make_url(database_url)
        connect_args: dict = {}
        if url.drivername.startswith("sqlite"):
            if url.database not in (None, ":memory:"):
                Path(url.database).parent.mkdir(parents=True, exist_ok=True)
            # Allow use across threads (background job runner opens its own session).
            connect_args["check_same_thread"] = False
        _engine = create_engine(database_url, future=True, connect_args=connect_args)
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_session(database_url: str) -> Session:
    get_engine(database_url)
    assert _session_factory is not None
    return _session_factory()


def init_db(database_url: str) -> None:
    Base.metadata.create_all(get_engine(database_url))
