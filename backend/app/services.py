"""Service layer shared by the API: model loading (cached), race context, pace tables."""
from typing import Any

import numpy as np
import pandas as pd
from cachetools import LRUCache, cached
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ml import train as T
from app.models import ModelVersion, Race, Result


class NotFoundError(Exception):
    pass


class UnavailableError(Exception):
    """Required data or model is not present (e.g. nothing ingested / no trained model)."""


_bundles: LRUCache[int, T.Bundle] = LRUCache(maxsize=4)
_pace: LRUCache[tuple, tuple[np.ndarray, float]] = LRUCache(maxsize=256)


def active_model(session: Session) -> ModelVersion:
    mv = session.scalar(select(ModelVersion).where(ModelVersion.name == "laptime", ModelVersion.is_active).order_by(ModelVersion.id.desc()))
    if mv is None:
        raise UnavailableError("No trained model is registered. Run `python -m app.cli train` after ingesting data.")
    return mv


def bundle_for(mv: ModelVersion) -> T.Bundle:
    if mv.id not in _bundles:
        _bundles[mv.id] = T.load_bundle(mv)
    return _bundles[mv.id]


def get_race(session: Session, race_id: int) -> Race:
    race = session.get(Race, race_id)
    if race is None:
        raise NotFoundError(f"race {race_id} not found")
    return race


def driver_context(session: Session, race: Race, driver_id: str) -> Result:
    res = session.scalar(select(Result).where(Result.race_id == race.id, Result.driver_id == driver_id))
    if res is None:
        raise NotFoundError(f"driver {driver_id} did not take part in race {race.id}")
    return res


def feature_frame(race: Race, res: Result, laps: list[int], ages: list[int], total_laps: int) -> pd.DataFrame:
    return pd.DataFrame({
        "circuit_id": race.circuit_id, "season": float(race.season), "constructor_id": res.constructor_id, "driver_id": res.driver_id,
        "grid": float(res.grid if res.grid else 20), "lap_number": [float(x) for x in laps], "tyre_age": [float(x) for x in ages],
        "race_progress": [x / total_laps for x in laps], "compound": None,
    })


def pace_table(session: Session, race: Race, driver_id: str, total_laps: int) -> tuple[np.ndarray, float, ModelVersion]:
    """Predicted p50 lap time for every (lap, tyre age) pair, plus a per-lap noise sigma from the p10-p90 band."""
    mv = active_model(session)
    key = (mv.id, race.id, driver_id, total_laps)
    if key not in _pace:
        res = driver_context(session, race, driver_id)
        laps, ages = np.meshgrid(np.arange(1, total_laps + 1), np.arange(1, total_laps + 1), indexing="ij")
        df = feature_frame(race, res, laps.ravel().tolist(), ages.ravel().tolist(), total_laps)
        pred = T.predict_ms(bundle_for(mv), df)
        table = pred["p50"].to_numpy().reshape(total_laps, total_laps)
        valid = (ages <= laps).ravel()
        sigma = float(((pred["p90"] - pred["p10"]).to_numpy()[valid]).mean() / 2.563)
        _pace[key] = (table, sigma)
    table, sigma = _pace[key]
    return table, sigma, mv


def split_label(mv: ModelVersion, race_id: int) -> str:
    if race_id in mv.test_races:
        return "held_out_test"
    if race_id in mv.train_races:
        return "training"
    return "not_in_model_data"


def model_summary(mv: ModelVersion) -> dict[str, Any]:
    return {"id": mv.id, "name": mv.name, "created_at": mv.created_at.isoformat() if mv.created_at else None,
            "is_active": mv.is_active, "feature_spec": mv.feature_spec, "hyperparameters": mv.hyperparameters,
            "n_train_races": len(mv.train_races), "n_test_races": len(mv.test_races), "test_races": mv.test_races,
            "metrics": mv.metrics, "data_fingerprint": mv.data_fingerprint, "random_seed": mv.random_seed}


__all__ = ["cached"]
