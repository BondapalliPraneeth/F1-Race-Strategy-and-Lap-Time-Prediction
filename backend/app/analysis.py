"""Data-derived analytics: pit-loss estimation and tyre degradation (all computed from stored laps)."""
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ml import features as F
from app.models import Lap, PitStop, Race

DEFAULT_PIT_LOSS_MS = 22_000.0


def estimate_pit_loss(session: Session, circuit_id: str) -> dict[str, Any]:
    """Time lost per stop = (in-lap + out-lap) - 2 x the driver's median clean lap around the stop.

    Uses stops at this circuit; falls back to all circuits, then to a documented default if no data.
    Stops under neutralised laps are excluded because they are artificially cheap.
    """
    def collect(circuit: str | None) -> list[float]:
        q = select(Lap.race_id, Lap.driver_id, Lap.lap_number, Lap.lap_time_ms, Lap.is_in_lap, Lap.is_out_lap,
                   Lap.is_neutralised).join(Race, Race.id == Lap.race_id).where(Race.has_laps)
        if circuit:
            q = q.where(Race.circuit_id == circuit)
        df = pd.DataFrame(session.execute(q).all(), columns=["race_id", "driver_id", "lap", "ms", "in", "out", "neu"])
        if df.empty:
            return []
        losses: list[float] = []
        for (_, _), g in df.groupby(["race_id", "driver_id"]):
            g = g.set_index("lap")
            clean = g[~g["in"] & ~g["out"] & ~g["neu"] & g["ms"].notna() & (g.index > 1)]
            if len(clean) < 8:
                continue
            ref = clean["ms"].median()
            for lap in g.index[g["in"]]:
                if lap + 1 in g.index and not g.loc[[lap, lap + 1], "neu"].any() and g.loc[[lap, lap + 1], "ms"].notna().all():
                    losses.append(float(g.loc[lap, "ms"] + g.loc[lap + 1, "ms"] - 2 * ref))
        return [x for x in losses if 5_000 <= x <= 60_000]

    for scope, circuit in (("circuit", circuit_id), ("all_circuits", None)):
        vals = collect(circuit)
        if len(vals) >= 8:
            return {"pit_loss_ms": float(np.median(vals)), "std_ms": float(np.std(vals)), "n_stops": len(vals), "scope": scope,
                    "method": "median(in-lap + out-lap - 2 x median clean lap)"}
    return {"pit_loss_ms": DEFAULT_PIT_LOSS_MS, "std_ms": 1500.0, "n_stops": 0, "scope": "default_assumption",
            "method": "no usable stops in database; documented default"}


def recorded_pit_durations(session: Session, race_id: int) -> list[int]:
    return [d for (d,) in session.execute(select(PitStop.duration_ms).where(PitStop.race_id == race_id)).all() if d]


def _ols(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = max(len(y) - X.shape[1], 1)
    cov = np.linalg.pinv(X.T @ X) * (resid @ resid / dof)
    return beta, np.sqrt(np.clip(np.diag(cov), 0, None))


def degradation(session: Session, race_id: int, driver_id: str) -> dict[str, Any]:
    """Tyre degradation from actual laps.

    1. Race-level regression  lap_time ~ driver_fixed_effect + fuel_slope*lap + deg_slope*tyre_age  identifies the
       fuel/track-evolution slope separately from tyre age because different drivers are on different ages at the
       same lap.
    2. For the chosen driver, each stint's fuel-corrected laps are regressed on tyre age -> degradation slope
       (ms/lap) with a standard error. Stints with <5 laps or a CI spanning zero are flagged uncertain.
    Compound is not published by the source; it is reported as null when absent.
    """
    df = F.load_laps(session, race_id)
    clean = F.clean_laps(df) if not df.empty else df
    if clean.empty or driver_id not in set(clean["driver_id"]):
        return {"available": False, "reason": "no clean laps for this driver/race", "stints": [], "fuel_slope_ms_per_lap": None}
    drivers = sorted(clean["driver_id"].unique())
    D = np.column_stack([(clean["driver_id"] == d).to_numpy(float) for d in drivers])
    X = np.column_stack([D, clean["lap_number"].to_numpy(float), clean["tyre_age"].to_numpy(float)])
    beta, se = _ols(X, clean["lap_time_ms"].to_numpy(float))
    fuel, fuel_se = float(beta[-2]), float(se[-2])
    pooled, pooled_se = float(beta[-1]), float(se[-1])

    mine = clean[clean["driver_id"] == driver_id]
    stints = []
    all_stints = df[(df["driver_id"] == driver_id)].groupby("stint_number")
    for sn_raw, g_all in all_stints:
        sn = int(str(sn_raw))
        g = mine[mine["stint_number"] == sn].sort_values("tyre_age")
        entry: dict[str, Any] = {"stint_number": int(sn), "start_lap": int(g_all["lap_number"].min()), "end_lap": int(g_all["lap_number"].max()),
                                 "compound": None if g_all["compound"].isna().all() else str(g_all["compound"].dropna().iloc[0]),
                                 "n_clean_laps": int(len(g)), "points": []}
        if len(g) >= 2:
            corrected = g["lap_time_ms"].to_numpy(float) - fuel * g["lap_number"].to_numpy(float)
            entry["points"] = [{"tyre_age": int(a), "lap_number": int(n), "lap_time_ms": float(t), "fuel_corrected_ms": float(c)}
                               for a, n, t, c in zip(g["tyre_age"], g["lap_number"], g["lap_time_ms"], corrected, strict=True)]
        if len(g) >= 5:
            A = np.column_stack([np.ones(len(g)), g["tyre_age"].to_numpy(float)])
            b, s = _ols(A, corrected)
            entry.update(slope_ms_per_lap=float(b[1]), slope_se=float(s[1]), intercept_ms=float(b[0]))
            entry["uncertain"] = bool(abs(b[1]) < 1.96 * s[1])
            entry["uncertainty_reason"] = "slope not statistically distinguishable from zero" if entry["uncertain"] else None
        else:
            entry.update(slope_ms_per_lap=None, slope_se=None, intercept_ms=None, uncertain=True,
                         uncertainty_reason=f"only {len(g)} clean laps (need >= 5)")
        stints.append(entry)
    return {"available": True, "fuel_slope_ms_per_lap": fuel, "fuel_slope_se": fuel_se, "pooled_degradation_ms_per_lap": pooled,
            "pooled_degradation_se": pooled_se, "stints": stints,
            "notes": ["Compound is not provided by the ingested source; stints are labelled by number only."
                      if all(s["compound"] is None for s in stints) else "Compounds from tyre source."]}


# ------------------------------------------------------------------ tyre / weather / safety-car statistics (real source data)
DRY_COMPOUNDS = ("SOFT", "MEDIUM", "HARD")
MIN_LAPS_PER_COMPOUND = 30
MIN_STINTS_FOR_CIRCUIT_SCOPE = 8


def _wet_race_ids(session: Session) -> set[int]:
    """Races with measured rain, or wet/intermediate tyres, on more than 10 % of laps (same rule as training)."""
    from sqlalchemy import case, func

    from app.models import Weather

    wx = session.execute(select(Weather.race_id, func.avg(case((Weather.rainfall.is_(True), 1.0), else_=0.0))).group_by(Weather.race_id)).all()
    wet = {int(r) for r, share in wx if share is not None and share > F.WET_SHARE}
    tyre = session.execute(select(Lap.race_id, func.avg(case((Lap.compound.in_(["INTERMEDIATE", "WET"]), 1.0), else_=0.0)))
                           .where(Lap.compound.is_not(None)).group_by(Lap.race_id)).all()
    return wet | {int(r) for r, share in tyre if share is not None and share > F.WET_SHARE}


def compound_profiles(session: Session, circuit_id: str, total_laps: int, model_learns_compound: bool) -> dict[str, Any]:
    """Compounds and stint limits measured from real dry-race stints.

    Returns ``{"source": "data"|"assumption", "profiles": {...}, "evidence": {...}}``. When the model was trained with the
    compound feature, pace offsets and degradation come from the model itself (profile offset 0 / multiplier 1); the data
    only sets which compounds exist and how long a stint on each has realistically run (90th percentile of observed
    stint lengths at this circuit, or across all circuits when the circuit has too few stints).
    """
    from app.models import Stint

    q = (select(Stint.race_id, Stint.compound, Stint.start_lap, Stint.end_lap, Race.circuit_id)
         .join(Race, Race.id == Stint.race_id).where(Stint.compound.is_not(None)))
    df = pd.DataFrame(session.execute(q).all(), columns=["race_id", "compound", "start", "end", "circuit_id"])
    if df.empty or not model_learns_compound:
        return {"source": "assumption", "profiles": None, "evidence": {"reason": "no tyre data in database" if df.empty
                                                                         else "model was trained without the compound feature"}}
    df = df[~df["race_id"].isin(_wet_race_ids(session)) & df["compound"].isin(DRY_COMPOUNDS)]
    df["length"] = df["end"] - df["start"] + 1
    profiles: dict[str, dict[str, Any]] = {}
    evidence: dict[str, Any] = {}
    for comp in DRY_COMPOUNDS:
        here, anywhere = df[(df["compound"] == comp) & (df["circuit_id"] == circuit_id)], df[df["compound"] == comp]
        scope, d = ("circuit", here) if len(here) >= MIN_STINTS_FOR_CIRCUIT_SCOPE else ("all_circuits", anywhere)
        if len(d) < MIN_STINTS_FOR_CIRCUIT_SCOPE:
            continue
        p90 = float(np.percentile(d["length"], 90))
        profiles[comp] = {"offset_ms": 0.0, "degradation_multiplier": 1.0, "max_stint_laps": int(max(10, min(70, round(p90), total_laps)))}
        evidence[comp] = {"scope": scope, "n_stints": int(len(d)), "median_stint_laps": float(d["length"].median()), "p90_stint_laps": p90,
                          "longest_stint_laps": int(d["length"].max())}
    if len(profiles) < 2:
        return {"source": "assumption", "profiles": None, "evidence": {"reason": "fewer than two dry compounds with enough stints"}}
    return {"source": "data", "profiles": profiles, "evidence": evidence}


def sc_statistics(session: Session, circuit_id: str) -> dict[str, Any]:
    """Safety-car / VSC frequency from race-control labels (circuit scope if >= 4 labelled races there, else all circuits)."""
    q = (select(Lap.race_id, Lap.lap_number, Lap.sc_state, Race.circuit_id).join(Race, Race.id == Lap.race_id)
         .where(Lap.sc_state.is_not(None)))
    df = pd.DataFrame(session.execute(q).all(), columns=["race_id", "lap", "sc", "circuit_id"])
    if df.empty:
        return {"available": False, "reason": "no race-control safety-car labels in the database"}
    per = df.groupby(["race_id", "lap"])["sc"].agg(lambda s: 1 if (s == 1).any() else (2 if (s == 2).any() else 0)).reset_index()
    per = per.merge(df.drop_duplicates("race_id")[["race_id", "circuit_id"]], on="race_id")
    scope = "circuit" if per[per.circuit_id == circuit_id]["race_id"].nunique() >= 4 else "all_circuits"
    d = per[per.circuit_id == circuit_id] if scope == "circuit" else per
    n_races = int(d["race_id"].nunique())

    def periods(state: int) -> list[int]:
        out: list[int] = []
        for _, g in d.groupby("race_id"):
            laps = sorted(g.loc[g["sc"] == state, "lap"].tolist())
            run = 0
            for i, lap in enumerate(laps):
                run = run + 1 if i and lap == laps[i - 1] + 1 else 1
                if i + 1 == len(laps) or laps[i + 1] != lap + 1:
                    out.append(run)
        return out

    sc_p, vsc_p = periods(1), periods(2)
    sc_races = int(d.loc[d["sc"] == 1, "race_id"].nunique())
    vsc_races = int(d.loc[d["sc"] == 2, "race_id"].nunique())
    return {"available": True, "scope": scope, "n_races": n_races,
            "sc_probability": sc_races / n_races, "vsc_probability": vsc_races / n_races,
            "sc_mean_laps_per_period": float(np.mean(sc_p)) if sc_p else None, "vsc_mean_laps_per_period": float(np.mean(vsc_p)) if vsc_p else None,
            "source": "race-control messages (Mendeley FastF1 dataset)"}


def weather_summary(session: Session, race_id: int) -> dict[str, Any]:
    from app.models import Weather

    rows = session.execute(select(Weather.air_temp_c, Weather.track_temp_c, Weather.humidity_pct, Weather.rainfall, Weather.source)
                           .where(Weather.race_id == race_id)).all()
    if not rows:
        return {"available": False, "reason": "no weather rows for this race (source does not cover it)"}
    df = pd.DataFrame(rows, columns=["air", "track", "hum", "rain", "source"])
    return {"available": True, "source": str(df["source"].iloc[0]), "n_laps": int(len(df)),
            "air_temp_c": {"min": float(df["air"].min()), "mean": float(df["air"].mean()), "max": float(df["air"].max())},
            "track_temp_c": {"min": float(df["track"].min()), "mean": float(df["track"].mean()), "max": float(df["track"].max())},
            "humidity_pct_mean": None if df["hum"].isna().all() else float(df["hum"].mean()),
            "rain_lap_share": float(df["rain"].fillna(False).astype(bool).mean())}
