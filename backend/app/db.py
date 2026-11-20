"""SQLAlchemy engine/session management with connection pooling."""
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None


def make_engine(url: str) -> Engine:
    s = get_settings()
    if url.startswith("sqlite"):
        return create_engine(url)
    return create_engine(url, pool_size=s.db_pool_size, max_overflow=s.db_max_overflow, pool_pre_ping=True)


def get_engine() -> Engine:
    global _engine, _factory
    if _engine is None:
        _engine = make_engine(get_settings().database_url)
        _factory = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def set_engine(engine: Engine) -> None:
    """Override the global engine (tests, CLI)."""
    global _engine, _factory
    _engine = engine
    _factory = sessionmaker(engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    get_engine()
    assert _factory is not None
    with _factory() as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    get_engine()
    assert _factory is not None
    with _factory() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
