"""Feature engineering: DB rows -> modelling DataFrame. Feature definitions are versioned (FEATURE_SPEC)."""
import hashlib

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Lap, Race, Result, Weather

FEATURE_SPEC_VERSION = "v1"
NUMERIC = ["tyre_age", "lap_number", "race_progress", "grid", "season"]
CATEGORICAL = ["constructor_id", "driver_id"]
OPTIONAL_CATEGORICAL = ["compound"]  # used only when the data actually has it
TARGET = "delta_ms"  # lap time minus the circuit baseline (baseline fitted on training races only)


def load_laps(session: Session, race_id: int | None = None) -> pd.DataFrame:
    """Laps of fully ingested races (optionally one race), joined with race/circuit/result context."""
    q = (
        select(
            Lap.race_id, Race.season, Race.round, Race.circuit_id, Race.total_laps, Race.race_date,
            Lap.driver_id, Lap.lap_number, Lap.position, Lap.lap_time_ms, Lap.stint_number, Lap.tyre_age,
            Lap.is_in_lap, Lap.is_out_lap, Lap.is_neutralised, Lap.compound, Lap.tyre_life, Lap.sc_state,
            Result.constructor_id, Result.grid, Weather.rainfall.label("rain"), Weather.track_temp_c, Weather.air_temp_c,
        )
        .join(Race, Race.id == Lap.race_id)
        .join(Result, (Result.race_id == Lap.race_id) & (Result.driver_id == Lap.driver_id))
        .outerjoin(Weather, (Weather.race_id == Lap.race_id) & (Weather.lap_number == Lap.lap_number))
        .where(Race.has_laps)
    )
    if race_id is not None:
        q = q.where(Lap.race_id == race_id)
    df = pd.DataFrame(session.execute(q).all(), columns=[c.key for c in q.selected_columns])
    if df.empty:
        return df
    # True tyre age (incl. laps on a used set) from the tyre source where available, else laps since the last stop.
    df["tyre_age"] = df["tyre_life"].fillna(df["tyre_age"]).astype(float)
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


def feature_columns(train: pd.DataFrame, use_optional: bool = True) -> tuple[list[str], list[str]]:
    cats = list(CATEGORICAL)
    for c in OPTIONAL_CATEGORICAL if use_optional else []:
        if c in train and train[c].notna().mean() >= 0.5:
            cats.append(c)
    return list(NUMERIC), cats


def data_fingerprint(df: pd.DataFrame) -> str:
    """Stable hash of the training data (race ids, row count, lap-time sum) for reproducibility records."""
    key = f"{sorted(df['race_id'].unique().tolist())}|{len(df)}|{int(df['lap_time_ms'].sum())}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


ABNORMAL_PACE_RATIO = 1.06


def race_pace_ratio(df: pd.DataFrame, reference: dict[str, float]) -> pd.Series:
    """Per race: median clean lap / reference circuit pace. ~1.0 for a normal dry race; wet/red-flag-affected races are well above.

    The weather table is empty (the data source publishes none), so this ratio is the only data-derived signal of
    abnormal race conditions. It is used (a) to exclude such races from TRAINING and (b) to stratify reported metrics.
    """
    med = df.groupby("race_id")["lap_time_ms"].median()
    circ = df.drop_duplicates("race_id").set_index("race_id")["circuit_id"]
    ref = circ.map(reference)
    return (med / ref).dropna()


def reference_pace(df: pd.DataFrame, min_races: int = 2) -> dict[str, float]:
    """Median of per-race median lap times per circuit (robust to a few wet races); circuits with < min_races are skipped."""
    per_race = df.groupby(["circuit_id", "race_id"])["lap_time_ms"].median().reset_index()
    g = per_race.groupby("circuit_id")["lap_time_ms"]
    counts = g.count().to_dict()
    return {str(c): float(v) for c, v in g.median().items() if counts[c] >= min_races}


WET_SHARE = 0.10


def wet_races(df: pd.DataFrame) -> set[int]:
    """Races where the weather feed reports rain, or wet-weather tyres were used, on more than 10 % of laps."""
    out: set[int] = set()
    if "rain" in df:
        share = df.assign(r=df["rain"].fillna(False).astype(bool)).groupby("race_id")["r"].mean()
        out |= {int(i) for i in share[share > WET_SHARE].index}
    if "compound" in df:
        wetc = df.assign(w=df["compound"].isin(["INTERMEDIATE", "WET"])).groupby("race_id")["w"].mean()
        out |= {int(i) for i in wetc[wetc > WET_SHARE].index}
    return out


def abnormal_pace_races(df: pd.DataFrame, reference: dict[str, float]) -> list[int]:
    """Races to exclude from training / report separately: pace far off the circuit reference OR measured wet conditions."""
    r = race_pace_ratio(df, reference)
    return sorted({int(i) for i in r[r > ABNORMAL_PACE_RATIO].index} | wet_races(df))
