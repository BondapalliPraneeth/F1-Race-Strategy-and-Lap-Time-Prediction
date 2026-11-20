"""Tyre / weather / safety-car enrichment tests.

The dataset files here are SYNTHETIC (test-only) but have exactly the real Mendeley/FastF1 column layout. They are
joined onto fixture races ingested through the real pipeline, then the real training code and optimiser run on them.
"""
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import analysis, services
from app.config import get_settings
from app.ingestion import tyres
from app.ingestion.pipeline import ingest_race
from app.ingestion.transform import parse_time_ms
from app.ml import features as F
from app.ml.train import train_and_register
from app.models import Lap, Race, Stint, Weather
from app.strategy import engine as E
from app.strategy.config import CompoundProfile, StrategyConfig
from tests.test_api import DRIVERS, FixtureSource, entry, fmt

OFFSET = {"SOFT": -600.0, "MEDIUM": 0.0, "HARD": 400.0}
CYCLE = ["MEDIUM", "HARD", "SOFT"]


def comp_of(driver: str, stint: int) -> str:
    return CYCLE[(DRIVERS.index(driver) + stint - 1) % 3]


class TyreFixtureSource(FixtureSource):
    """Fixture race whose lap times really depend on the compound being run (so a model can learn it)."""

    def laps(self, season: int, rnd: int) -> list[dict[str, Any]]:
        out = super().laps(season, rnd)
        for lap in out:
            n = int(lap["number"])
            for t in lap["Timings"]:
                stint = 1 + sum(1 for s in self.pits[t["driverId"]] if s < n)
                ms = parse_time_ms(t["time"]) or 0
                t["time"] = fmt(ms + OFFSET[comp_of(t["driverId"], stint)])
        return out


def dataset_frame(session: Session, race: Race, sc_laps: tuple[int, ...] = (), rain: bool = False) -> pd.DataFrame:
    rows = []
    for lap in session.scalars(select(Lap).where(Lap.race_id == race.id)):
        stint = lap.stint_number or 1
        rows.append({
            "Driver": lap.driver_id.upper(), "LapNumber": float(lap.lap_number), "Compound": comp_of(lap.driver_id, stint),
            "TyreLife": float((lap.tyre_age or 1) + (3 if stint > 1 else 0)), "FreshTyre": stint == 1,
            "Year": race.season, "EventName": race.name, "AirTemp": 25.0 + lap.lap_number * 0.01, "TrackTemp": 38.0, "Humidity": 50.0,
            "WindSpeed": 2.0, "Rainfall": rain, "IsSafetyCar": int(lap.lap_number in sc_laps), "IsVSC": 0})
    return pd.DataFrame(rows)


@pytest.fixture
def enriched(session: Session, tmp_path: Path) -> tuple[Session, Path, tyres.TyreReport]:
    for rnd in range(1, 9):
        assert ingest_race(session, TyreFixtureSource(rnd), entry(rnd)).status == "ok"  # type: ignore[arg-type]
    d = tmp_path / "data"
    d.mkdir()
    races = session.scalars(select(Race).order_by(Race.round)).all()
    for race in races:
        dataset_frame(session, race, sc_laps=(10, 11, 12) if race.round in (2, 4) else ()).to_csv(d / f"event={race.round}.csv", index=False)
    pd.DataFrame({"Driver": ["X"]}).to_csv(d / "broken.csv", index=False)  # foreign file: reported, not a crash
    extra = dataset_frame(session, races[0])
    extra["EventName"] = "Nonexistent Grand Prix"
    extra.to_csv(d / "unmatched.csv", index=False)
    return session, d, tyres.ingest_directory(session, d)


def test_enrichment_fills_compound_tyre_life_weather_and_labels(enriched: Any) -> None:
    session, _, rep = enriched
    assert rep.races_matched == 8 and rep.laps_updated == 8 * len(DRIVERS) * 40
    assert any("Nonexistent" in u for u in rep.unmatched_events) and any("broken" in s for s in rep.skipped_files)
    race1 = session.scalar(select(Race).where(Race.round == 1))
    assert race1 is not None
    lap = session.scalar(select(Lap).where(Lap.driver_id == "d0", Lap.lap_number == 30, Lap.race_id == race1.id))
    assert lap is not None and lap.compound in OFFSET and lap.tyre_life is not None and lap.sc_state == 0
    wx = session.scalar(select(Weather).where(Weather.race_id == race1.id, Weather.lap_number == 5))
    assert wx is not None and wx.source == tyres.SOURCE
    stint = session.scalar(select(Stint).where(Stint.race_id == race1.id, Stint.driver_id == "d0", Stint.stint_number == 1))
    assert stint is not None and stint.compound == comp_of("d0", 1) and stint.compound_source == tyres.SOURCE
    race2 = session.scalar(select(Race).where(Race.round == 2))
    assert race2 is not None
    sc_lap = session.scalar(select(Lap).where(Lap.race_id == race2.id, Lap.driver_id == "d1", Lap.lap_number == 11))
    assert sc_lap is not None and sc_lap.sc_state == 1 and sc_lap.is_neutralised  # official SC label marks the lap neutralised


def test_enrichment_is_idempotent(enriched: Any) -> None:
    session, d, _ = enriched
    before = session.query(Weather).count()
    tyres.ingest_directory(session, d)
    assert session.query(Weather).count() == before  # weather replaced, not duplicated


def test_true_tyre_life_replaces_laps_since_stop(enriched: Any) -> None:
    session, _, _ = enriched
    df = F.load_laps(session)
    assert (df[df.stint_number == 2].tyre_age >= 4).all()  # fixture adds 3 laps of used-tyre age on stint 2


def test_sc_statistics_and_weather_summary(enriched: Any) -> None:
    session, _, _ = enriched
    sc = analysis.sc_statistics(session, "c_b")
    assert sc["available"] and sc["n_races"] == 4 and sc["scope"] == "circuit"
    assert sc["sc_probability"] == pytest.approx(2 / 4) and sc["sc_mean_laps_per_period"] == 3.0  # laps 10-12 in 2 of the 4 races at c_b
    race1 = session.scalar(select(Race).where(Race.round == 1))
    assert race1 is not None
    wx = analysis.weather_summary(session, race1.id)
    assert wx["available"] and wx["rain_lap_share"] == 0 and wx["track_temp_c"]["mean"] == pytest.approx(38.0)


def test_wet_races_detected_from_weather_and_tyres() -> None:
    df = pd.DataFrame({"race_id": [1] * 10 + [2] * 10, "rain": [True] * 5 + [False] * 5 + [False] * 10,
                       "compound": ["SOFT"] * 10 + ["INTERMEDIATE"] * 5 + ["SOFT"] * 5})
    assert F.wet_races(df) == {1, 2}
    assert F.wet_races(df.assign(rain=False, compound="SOFT")) == set()


def test_model_learns_compound_effect_and_pace_tables_follow(enriched: Any, tmp_path: Path) -> None:
    session, _, _ = enriched
    get_settings().artifacts_dir = tmp_path / "artifacts"
    services._bundles.clear()  # caches are keyed by model id, which repeats across throw-away test databases
    services._pace.clear()
    mv = train_and_register(session, test_races=2)
    assert "compound" in mv.feature_spec["categorical"] and services.model_uses_compound(mv)
    assert "ablation_without_compound" in mv.metrics
    race = session.scalar(select(Race).where(Race.round == 8))
    assert race is not None
    tables, _, _ = services.pace_tables(session, race, "d3", 40, ["SOFT", "MEDIUM", "HARD"])
    assert isinstance(tables, dict)
    assert tables["HARD"][20, 4] - tables["SOFT"][20, 4] > 500  # known law: SOFT is 1000 ms/lap faster than HARD
    prof = analysis.compound_profiles(session, "c_a", 40, model_learns_compound=True)
    assert prof["source"] == "data" and set(prof["profiles"]) == {"SOFT", "MEDIUM", "HARD"}
    assert all(p["offset_ms"] == 0 and p["degradation_multiplier"] == 1 for p in prof["profiles"].values())
    assert analysis.compound_profiles(session, "c_a", 40, model_learns_compound=False)["source"] == "assumption"


def test_optimiser_uses_per_compound_tables() -> None:
    n = 30
    base = np.full((n, n), 90_000.0)
    soft = base - 800 + 150 * np.arange(n)[None, :]   # fast but wears quickly
    hard = base + 300 + 10 * np.arange(n)[None, :]    # slow but durable
    cfg = StrategyConfig(total_laps=n, pit_loss_ms=20_000, min_stint_laps=5, max_stops=2,
                         compounds={"SOFT": CompoundProfile(max_stint_laps=30), "HARD": CompoundProfile(max_stint_laps=30)})
    stints = E.optimise({"SOFT": soft, "HARD": hard}, cfg)[0].strategy.stints
    assert len(stints) >= 2 and "SOFT" in {s.compound for s in stints}
    # a single shared table cannot distinguish the compounds: dict-of-identical-tables == single table
    assert E.optimise(base, cfg)[0].total_ms == pytest.approx(E.optimise({"SOFT": base, "HARD": base}, cfg)[0].total_ms)


def test_echoed_data_profiles_are_not_a_user_override(enriched: Any, tmp_path: Path) -> None:
    from app.api.routes import build_config
    from app.schemas import StrategyParams

    session, _, _ = enriched
    get_settings().artifacts_dir = tmp_path / "artifacts"
    services._bundles.clear()
    services._pace.clear()
    train_and_register(session, test_races=2)
    race = session.scalar(select(Race).where(Race.round == 8))
    assert race is not None
    cfg, meta = build_config(session, race, StrategyParams())
    assert meta["compound_profile_source"] == "data"
    echoed = {k: v.model_dump() for k, v in cfg.compounds.items()}
    assert build_config(session, race, StrategyParams(compounds=echoed))[1]["compound_profile_source"] == "data"
    echoed["SOFT"]["max_stint_laps"] += 1
    assert build_config(session, race, StrategyParams(compounds=echoed))[1]["compound_profile_source"] == "user"
