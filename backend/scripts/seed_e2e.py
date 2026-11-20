"""Seed a database for the Playwright E2E suite.

Uses the SYNTHETIC test fixture (known degradation law) pushed through the REAL ingestion + training code, so CI needs
no network. It is for automated tests only — the dev/demo database is loaded from real Jolpica-F1 data (`app.cli ingest`).
Usage: F1_DATABASE_URL=sqlite:///e2e.db python scripts/seed_e2e.py
"""
from sqlalchemy.orm import Session

from app.cli import migrate
from app.db import get_engine
from app.ingestion.pipeline import ingest_race
from app.ml.train import train_and_register
from tests.test_api import FixtureSource, entry

if __name__ == "__main__":
    migrate()
    with Session(get_engine()) as s:
        for rnd in range(1, 9):
            ingest_race(s, FixtureSource(rnd), entry(rnd))  # type: ignore[arg-type]
        mv = train_and_register(s, test_races=2)
        print("seeded; model", mv.id)
