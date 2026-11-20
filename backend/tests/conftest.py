"""Test fixtures. TEST_DATABASE_URL selects the DB (CI uses PostgreSQL; default is in-memory SQLite)."""
import os

os.environ.setdefault("OMP_NUM_THREADS", "2")  # tiny models: avoid OpenMP oversubscription slowing the suite
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "2")
from collections.abc import Iterator  # noqa: E402

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base


@pytest.fixture
def session() -> Iterator[Session]:
    url = os.environ.get("TEST_DATABASE_URL", "sqlite://")
    if url.startswith("sqlite"):
        engine = create_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    Base.metadata.drop_all(engine)
    engine.dispose()
