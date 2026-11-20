"""Command line entry point: ``python -m app.cli <command>``.

Commands: migrate | ingest --season Y [--rounds 1 2 ...] [--force] | status
"""
import argparse
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from app.config import BACKEND_DIR, get_settings
from app.db import session_scope
from app.ingestion.jolpica import JolpicaClient
from app.ingestion.pipeline import ingest_season
from app.logging_setup import configure_logging
from app.models import Lap, Race


def migrate() -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")


def main(argv: list[str] | None = None) -> int:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    ap = argparse.ArgumentParser(prog="f1")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    ing = sub.add_parser("ingest")
    ing.add_argument("--season", type=int, required=True)
    ing.add_argument("--rounds", type=int, nargs="*")
    ing.add_argument("--force", action="store_true")
    tr = sub.add_parser("train")
    tr.add_argument("--test-races", type=int, default=4)
    sub.add_parser("status")
    args = ap.parse_args(argv)

    if args.cmd == "migrate":
        migrate()
    elif args.cmd == "ingest":
        client = JolpicaClient()
        with session_scope() as session:
            runs = ingest_season(session, client, args.season, args.rounds, args.force)
        for r in runs:
            print(f"{r.season} R{r.round:>2}  {r.status:<8} laps={r.laps_loaded} rejected={r.rows_rejected} {r.detail or ''}")
        if any(r.status == "failed" for r in runs):
            return 1
    elif args.cmd == "train":
        from app.ml.train import train_and_register

        with session_scope() as session:
            mv = train_and_register(session, test_races=args.test_races)
            m = mv.metrics
            print(f"model v{mv.id}: test MAE {m['mae_ms']:.0f} ms vs circuit-median baseline {m['baseline_circuit_median_mae_ms']:.0f} ms; "
                  f"80% interval coverage {m['interval_80_coverage']:.2f}; train races {len(mv.train_races)}, test races {len(mv.test_races)}")
    elif args.cmd == "status":
        with session_scope() as session:
            races = session.scalar(select(func.count()).select_from(Race).where(Race.has_laps))
            laps = session.scalar(select(func.count()).select_from(Lap))
            print(f"races with laps: {races}, laps: {laps}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
