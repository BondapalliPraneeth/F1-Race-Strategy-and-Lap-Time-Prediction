"""Database tests: the Alembic migration produces the schema the models declare, with its constraints and indexes."""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.cli import BACKEND_DIR
from app.models import Base, Circuit, Lap, Race


@pytest.fixture
def migrated_engine(tmp_path: Path):  # type: ignore[no-untyped-def]
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    yield engine
    engine.dispose()


def test_migration_creates_every_model_table_and_expected_indexes(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    insp = inspect(migrated_engine)
    assert set(Base.metadata.tables) <= set(insp.get_table_names())
    lap_idx = {tuple(i["column_names"]) for i in insp.get_indexes("laps")}
    assert ("race_id", "lap_number") in lap_idx
    lap_unique = {tuple(u["column_names"]) for u in insp.get_unique_constraints("laps")}
    assert ("race_id", "driver_id", "lap_number") in lap_unique
    race_unique = {tuple(u["column_names"]) for u in insp.get_unique_constraints("races")}
    assert ("season", "round") in race_unique


def test_duplicate_race_and_lap_rejected(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    with Session(migrated_engine) as s:
        s.add(Circuit(circuit_id="c", name="C"))
        s.add(Race(season=2024, round=1, name="A", circuit_id="c"))
        s.commit()
        s.add(Race(season=2024, round=1, name="B", circuit_id="c"))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
        assert s.query(Lap).count() == 0
