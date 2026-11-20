"""HTTP API. Every endpoint reads PostgreSQL via SQLAlchemy or runs the real model/optimizer/simulator."""
import time
from typing import Annotated, Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import analysis, services
from app.db import get_session
from app.ml import features as F
from app.ml import train as T
from app.models import Lap, ModelVersion, PitStop, Race, Result, Stint, Weather
from app.schemas import OptimizeRequest, PredictRequest, SimulateRequest, StrategyParams
from app.strategy import engine as E
from app.strategy import simulate as S
from app.strategy.config import Strategy, StrategyConfig, StintPlan

router = APIRouter(prefix="/api")
Db = Annotated[Session, Depends(get_session)]


def _paginate(session: Session, q: Any, page: int, size: int, mapper: Any) -> dict[str, Any]:
    total = session.scalar(select(func.count()).select_from(q.order_by(None).subquery()))
    rows = session.execute(q.limit(size).offset((page - 1) * size)).all()
    return {"items": [mapper(r) for r in rows], "total": total, "page": page, "page_size": size}


@router.get("/health")
def health(session: Db) -> dict[str, Any]:
    session.execute(text("select 1"))
    return {"status": "ok", "database": "up",
            "races_with_laps": session.scalar(select(func.count()).select_from(Race).where(Race.has_laps)),
            "active_model": session.scalar(select(ModelVersion.id).where(ModelVersion.is_active).order_by(ModelVersion.id.desc()))}


@router.get("/seasons")
def seasons(session: Db) -> list[dict[str, Any]]:
    q = select(Race.season, func.count()).where(Race.has_laps).group_by(Race.season).order_by(Race.season.desc())
    return [{"season": s, "races": n} for s, n in session.execute(q).all()]


@router.get("/races")
def races(session: Db, season: int | None = None, page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100)) -> dict[str, Any]:
    q = select(Race).where(Race.has_laps).order_by(Race.season.desc(), Race.round)
    if season:
        q = q.where(Race.season == season)
    total = session.scalar(select(func.count()).select_from(q.order_by(None).subquery()))
    rows = session.scalars(q.limit(page_size).offset((page - 1) * page_size)).all()
    return {"items": [_race(r) for r in rows], "total": total, "page": page, "page_size": page_size}


def _race(r: Race) -> dict[str, Any]:
    return {"id": r.id, "season": r.season, "round": r.round, "name": r.name, "circuit_id": r.circuit_id, "circuit": r.circuit.name,
            "country": r.circuit.country, "date": r.race_date.isoformat() if r.race_date else None, "total_laps": r.total_laps,
            "sessions": [{"key": "race", "label": "Race", "available": True}]}


@router.get("/races/{race_id}")
def race_detail(race_id: int, session: Db) -> dict[str, Any]:
    race = services.get_race(session, race_id)
    drivers = session.execute(select(Result, func.count(Lap.id)).outerjoin(Lap, (Lap.race_id == Result.race_id) & (Lap.driver_id == Result.driver_id))
                              .where(Result.race_id == race_id).group_by(Result.id).order_by(Result.position.is_(None), Result.position)).all()
    has_weather = bool(session.scalar(select(func.count()).select_from(Weather).where(Weather.race_id == race_id)))
    has_compound = bool(session.scalar(select(func.count()).select_from(Lap).where(Lap.race_id == race_id, Lap.compound.is_not(None))))
    mv = session.scalar(select(ModelVersion).where(ModelVersion.is_active).order_by(ModelVersion.id.desc()))
    return {**_race(race), "data_availability": {"laps": True, "pit_stops": True, "weather": has_weather, "tyre_compound": has_compound},
            "data_source": "Jolpica-F1 (Ergast-compatible API)", "model_split": services.split_label(mv, race_id) if mv else None,
            "drivers": [{"driver_id": r.driver_id, "code": r.driver.code, "name": f"{r.driver.given_name} {r.driver.family_name}",
                         "constructor_id": r.constructor_id, "grid": r.grid, "position": r.position, "status": r.status, "laps": n} for r, n in drivers]}


@router.get("/races/{race_id}/laps")
def laps(race_id: int, session: Db, driver_id: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    services.get_race(session, race_id)
    q = select(Lap).where(Lap.race_id == race_id).order_by(Lap.driver_id, Lap.lap_number)
    if driver_id:
        q = q.where(Lap.driver_id == driver_id)
    total = session.scalar(select(func.count()).select_from(q.order_by(None).subquery()))
    rows = session.scalars(q.limit(page_size).offset((page - 1) * page_size)).all()
    return {"items": [_lap(x) for x in rows], "total": total, "page": page, "page_size": page_size, "kind": "actual"}


def _lap(x: Lap) -> dict[str, Any]:
    return {"driver_id": x.driver_id, "lap_number": x.lap_number, "position": x.position, "lap_time_ms": x.lap_time_ms, "stint_number": x.stint_number,
            "tyre_age": x.tyre_age, "is_in_lap": x.is_in_lap, "is_out_lap": x.is_out_lap, "is_neutralised": x.is_neutralised, "compound": x.compound}


@router.get("/races/{race_id}/compare")
def compare(race_id: int, session: Db, drivers: Annotated[list[str], Query(min_length=1, max_length=6)]) -> dict[str, Any]:
    services.get_race(session, race_id)
    out = []
    for d in drivers:
        rows = session.scalars(select(Lap).where(Lap.race_id == race_id, Lap.driver_id == d).order_by(Lap.lap_number)).all()
        if not rows:
            raise HTTPException(404, f"no laps for driver {d} in race {race_id}")
        stints = session.scalars(select(Stint).where(Stint.race_id == race_id, Stint.driver_id == d).order_by(Stint.stint_number)).all()
        clean = [x.lap_time_ms for x in rows if x.lap_time_ms and not (x.is_in_lap or x.is_out_lap or x.is_neutralised) and x.lap_number > 1]
        out.append({"driver_id": d, "laps": [_lap(x) for x in rows],
                    "stints": [{"stint_number": s.stint_number, "start_lap": s.start_lap, "end_lap": s.end_lap, "compound": s.compound} for s in stints],
                    "median_clean_lap_ms": float(np.median(clean)) if clean else None, "n_clean_laps": len(clean)})
    return {"kind": "actual", "source": "laps table (Jolpica-F1)", "drivers": out}


@router.get("/races/{race_id}/pit-stops")
def pit_stops(race_id: int, session: Db) -> dict[str, Any]:
    services.get_race(session, race_id)
    rows = session.scalars(select(PitStop).where(PitStop.race_id == race_id).order_by(PitStop.lap)).all()
    return {"kind": "actual", "items": [{"driver_id": p.driver_id, "stop_number": p.stop_number, "lap": p.lap, "duration_ms": p.duration_ms} for p in rows]}


@router.get("/races/{race_id}/weather")
def weather(race_id: int, session: Db) -> dict[str, Any]:
    services.get_race(session, race_id)
    rows = session.scalars(select(Weather).where(Weather.race_id == race_id).order_by(Weather.lap_number)).all()
    return {"kind": "actual", "available": bool(rows), "items": [{"lap_number": w.lap_number, "air_temp_c": w.air_temp_c, "track_temp_c": w.track_temp_c,
                                                                  "rainfall": w.rainfall, "source": w.source} for w in rows],
            "reason": None if rows else "The configured data source (Jolpica-F1) does not publish weather; no weather has been ingested."}


@router.get("/models")
def models(session: Db) -> list[dict[str, Any]]:
    return [services.model_summary(m) for m in session.scalars(select(ModelVersion).order_by(ModelVersion.id.desc())).all()]


@router.get("/models/active")
def active_model(session: Db) -> dict[str, Any]:
    return services.model_summary(services.active_model(session))


@router.post("/predict/laptime")
def predict(req: PredictRequest, session: Db) -> dict[str, Any]:
    race = services.get_race(session, req.race_id)
    res = services.driver_context(session, race, req.driver_id)
    mv = services.active_model(session)
    df = services.feature_frame(race, res, [req.lap_number], [req.tyre_age], race.total_laps or 60)
    p = T.predict_ms(services.bundle_for(mv), df).iloc[0]
    actual = session.scalar(select(Lap).where(Lap.race_id == race.id, Lap.driver_id == req.driver_id, Lap.lap_number == req.lap_number))
    comparable = bool(actual and actual.lap_time_ms and actual.tyre_age == req.tyre_age and not (actual.is_in_lap or actual.is_out_lap or actual.is_neutralised))
    return {"kind": "predicted", "predicted_ms": float(p["p50"]), "interval_80_ms": [float(p["p10"]), float(p["p90"])],
            "model_version": mv.id, "split": services.split_label(mv, race.id),
            "compound_used_by_model": "compound" in mv.feature_spec["categorical"],
            "actual_ms": actual.lap_time_ms if comparable else None,
            "error_ms": float(p["p50"] - actual.lap_time_ms) if comparable and actual else None,
            "actual_note": None if comparable else "no comparable clean actual lap at this lap/tyre age",
            "unseen_circuit": race.circuit_id not in services.bundle_for(mv).baselines}


@router.get("/races/{race_id}/predict-vs-actual")
def predict_vs_actual(race_id: int, driver_id: str, session: Db) -> dict[str, Any]:
    race = services.get_race(session, race_id)
    res = services.driver_context(session, race, driver_id)
    mv = services.active_model(session)
    laps_df = F.load_laps(session)
    d = laps_df[(laps_df.race_id == race_id) & (laps_df.driver_id == driver_id)]
    c = F.clean_laps(d) if not d.empty else d
    if c.empty:
        return {"kind": "predicted", "available": False, "reason": "no clean laps for this driver", "points": []}
    df = services.feature_frame(race, res, c["lap_number"].tolist(), c["tyre_age"].tolist(), race.total_laps or 60)
    p = T.predict_ms(services.bundle_for(mv), df)
    err = p["p50"].to_numpy() - c["lap_time_ms"].to_numpy()
    return {"kind": "predicted_vs_actual", "available": True, "model_version": mv.id, "split": services.split_label(mv, race_id),
            "mae_ms": float(np.abs(err).mean()), "n": int(len(c)),
            "interval_80_coverage": float(((c["lap_time_ms"].to_numpy() >= p["p10"].to_numpy()) & (c["lap_time_ms"].to_numpy() <= p["p90"].to_numpy())).mean()),
            "points": [{"lap_number": int(l), "tyre_age": int(a), "actual_ms": float(y), "p10": float(lo), "p50": float(m), "p90": float(hi)}
                       for l, a, y, lo, m, hi in zip(c["lap_number"], c["tyre_age"], c["lap_time_ms"], p["p10"], p["p50"], p["p90"], strict=True)]}


@router.get("/races/{race_id}/degradation")
def degradation(race_id: int, driver_id: str, session: Db) -> dict[str, Any]:
    race = services.get_race(session, race_id)
    out = analysis.degradation(session, race_id, driver_id)
    out.update(kind="actual_derived", source="laps table; OLS fuel correction + per-stint regression")
    if out["available"]:
        try:
            n = race.total_laps or 50
            table, _, mv = services.pace_table(session, race, driver_id, n)
            mid = max(n // 2, 2)
            curve = [{"tyre_age": a, "predicted_ms": float(table[mid - 1, a - 1])} for a in range(1, min(mid, 40) + 1)]
            out["model_curve"] = {"kind": "predicted", "at_lap": mid, "model_version": mv.id, "points": curve}
        except services.UnavailableError as e:
            out["model_curve"] = {"kind": "predicted", "available": False, "reason": str(e)}
    return out


# ------------------------------------------------------------------ strategy
def build_config(session: Session, race: Race, p: StrategyParams) -> tuple[StrategyConfig, dict[str, Any]]:
    est = analysis.estimate_pit_loss(session, race.circuit_id)
    data = p.model_dump(exclude_none=True)
    data.setdefault("total_laps", race.total_laps or 50)
    data.setdefault("pit_loss_ms", est["pit_loss_ms"])
    data.setdefault("pit_loss_std_ms", est["std_ms"])
    data["pit_loss_ms"] = max(5_000, min(60_000, data["pit_loss_ms"]))
    try:
        return StrategyConfig(**data), {"pit_loss_estimate": est, "pit_loss_overridden": p.pit_loss_ms is not None}
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False, include_context=False)) from e


@router.post("/strategy/optimize")
def optimize(req: OptimizeRequest, session: Db) -> dict[str, Any]:
    race = services.get_race(session, req.race_id)
    cfg, meta = build_config(session, race, req.params)
    t0 = time.perf_counter()
    table, sigma, mv = services.pace_table(session, race, req.driver_id, cfg.total_laps)
    try:
        ranked = E.optimise(table, cfg)
    except E.InfeasibleError as e:
        raise HTTPException(422, str(e)) from e
    elapsed = time.perf_counter() - t0
    actual = _actual_strategy(session, race, req.driver_id, cfg)
    return {"kind": "predicted", "model_version": mv.id, "split": services.split_label(mv, race.id), "config": cfg.model_dump(), **meta,
            "lap_sigma_ms": sigma, "compute_seconds": round(elapsed, 3),
            "recommended": _ranked(ranked[0]), "alternatives": [_ranked(r) for r in ranked[1:]], "explanation": E.explain(ranked, cfg),
            "actual_strategy": actual,
            "assumption_notes": ["Compound pace/degradation are configurable assumptions (source has no tyre data).",
                                 "Only the 'at least two compounds' rule reflects an FIA dry-race regulation; all other limits are simplified."]}


def _ranked(r: E.Ranked) -> dict[str, Any]:
    return {"label": r.strategy.label, "stints": [s.model_dump() for s in r.strategy.stints], "pit_laps": r.strategy.pit_laps,
            "predicted_total_ms": r.total_ms, "pit_windows": r.pit_windows}


def _actual_strategy(session: Session, race: Race, driver_id: str, cfg: StrategyConfig) -> dict[str, Any]:
    stints = session.scalars(select(Stint).where(Stint.race_id == race.id, Stint.driver_id == driver_id).order_by(Stint.stint_number)).all()
    laps = session.scalars(select(Lap).where(Lap.race_id == race.id, Lap.driver_id == driver_id)).all()
    complete = len(laps) == cfg.total_laps and all(x.lap_time_ms for x in laps)
    return {"kind": "actual", "pit_laps": [s.end_lap for s in stints[:-1]], "stint_lengths": [s.end_lap - s.start_lap + 1 for s in stints],
            "completed_full_distance": complete, "actual_total_ms": sum(x.lap_time_ms for x in laps) if complete else None}


@router.post("/strategy/simulate")
def simulate(req: SimulateRequest, session: Db) -> dict[str, Any]:
    race = services.get_race(session, req.race_id)
    cfg, meta = build_config(session, race, req.params)
    table, sigma, mv = services.pace_table(session, race, req.driver_id, cfg.total_laps)
    strategies = [Strategy(stints=s) for s in req.strategies]
    issues = {st.label: E.feasibility_issues(st, cfg) for st in strategies}
    bad = {k: v for k, v in issues.items() if v}
    if bad:
        raise HTTPException(422, {"message": "infeasible strategy", "issues": bad})
    t0 = time.perf_counter()
    try:
        res = S.run_comparison(table, strategies, cfg, req.safety_car, req.weather, req.n_sims, req.seed, sigma)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    costs = E._tables(table[: cfg.total_laps, : cfg.total_laps], cfg)
    for entry, st in zip(res["strategies"], strategies, strict=True):
        entry["deterministic_ms"] = E.evaluate(st, costs, cfg)
    return {"kind": "simulated", "model_version": mv.id, "lap_sigma_ms": sigma, "compute_seconds": round(time.perf_counter() - t0, 3),
            "scenario": {"safety_car": req.safety_car.model_dump(), "weather": [w.model_dump() for w in req.weather], "hypothetical": True},
            **meta, **res}
