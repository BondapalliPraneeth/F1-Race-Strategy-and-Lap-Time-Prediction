"""Feature engineering: DB rows -> modelling DataFrame. Feature definitions are versioned (FEATURE_SPEC)."""
import hashlib

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Lap, Race, Result

FEATURE_SPEC_VERSION = "v1"
NUMERIC = ["tyre_age", "lap_number", "race_progress", "grid", "season"]
CATEGORICAL = ["constructor_id", "driver_id"]
OPTIONAL_CATEGORICAL = ["compound"]  # used only when the data actually has it
TARGET = "delta_ms"  # lap time minus the circuit baseline (baseline fitted on training races only)


def load_laps(session: Session) -> pd.DataFrame:
    """All laps of fully ingested races, joined with race/circuit/result context."""
    q = (
        select(
            Lap.race_id, Race.season, Race.round, Race.circuit_id, Race.total_laps, Race.race_date,
            Lap.driver_id, Lap.lap_number, Lap.position, Lap.lap_time_ms, Lap.stint_number, Lap.tyre_age,
            Lap.is_in_lap, Lap.is_out_lap, Lap.is_neutralised, Lap.compound,
            Result.constructor_id, Result.grid,
        )
        .join(Race, Race.id == Lap.race_id)
        .join(Result, (Result.race_id == Lap.race_id) & (Result.driver_id == Lap.driver_id))
        .where(Race.has_laps)
    )
    df = pd.DataFrame(session.execute(q).all(), columns=[c.key for c in q.selected_columns])
    if df.empty:
        return df
    df["race_progress"] = df["lap_number"] / df["total_laps"]
    df["grid"] = df["grid"].fillna(20).astype(float)  # pit-lane starts are published as grid 0
    return df


def clean_laps(df: pd.DataFrame) -> pd.DataFrame:
    """Representative racing laps: drops lap 1, in/out laps, neutralised laps and missing times."""
    m = (
        df["lap_time_ms"].notna() & (df["lap_number"] > 1)
        & ~df["is_in_lap"] & ~df["is_out_lap"] & ~df["is_neutralised"]
    )
    out = df[m].copy()
    # Remove individual outliers (traffic/errors) beyond 107% of that driver's race median.
    med = out.groupby(["race_id", "driver_id"])["lap_time_ms"].transform("median")
    return out[out["lap_time_ms"] <= 1.07 * med].reset_index(drop=True)


def circuit_baselines(train: pd.DataFrame) -> dict[str, float]:
    """Median clean lap time per circuit — computed from TRAINING races only (no leakage)."""
    return train.groupby("circuit_id")["lap_time_ms"].median().to_dict()  # type: ignore[no-any-return]


def feature_columns(train: pd.DataFrame) -> tuple[list[str], list[str]]:
    cats = list(CATEGORICAL)
    for c in OPTIONAL_CATEGORICAL:
        if c in train and train[c].notna().mean() >= 0.5:
            cats.append(c)
    return list(NUMERIC), cats


def data_fingerprint(df: pd.DataFrame) -> str:
    """Stable hash of the training data (race ids, row count, lap-time sum) for reproducibility records."""
    key = f"{sorted(df['race_id'].unique().tolist())}|{len(df)}|{int(df['lap_time_ms'].sum())}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]
