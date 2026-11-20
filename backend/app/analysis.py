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
