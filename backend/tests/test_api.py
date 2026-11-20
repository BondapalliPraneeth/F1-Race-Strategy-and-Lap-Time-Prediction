"""API + integration tests: ingestion -> training -> prediction -> optimisation -> simulation through HTTP.

The race data is a SYNTHETIC FIXTURE (known degradation law) loaded through the real ingestion pipeline; it exists
only inside the test database.
"""
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import db
from app.config import get_settings
from app.ingestion.pipeline import ingest_race
from app.ml.train import train_and_register
from app.models import Base

DRIVERS = [f"d{i}" for i in range(8)]
N_LAPS = 40


def fmt(ms: float) -> str:
    t = round(ms)
    return f"{t // 60_000}:{(t % 60_000) / 1000:06.3f}"


class FixtureSource:
    def __init__(self, rnd: int) -> None:
        self.rnd = rnd
        self.circuit_base = 90_000 if rnd % 2 else 80_000
        self.pits = {d: [12 + 2 * i, 28 + i] if i % 2 else [16 + i] for i, d in enumerate(DRIVERS)}
        self.rng = np.random.default_rng(rnd)

    def results(self, season: int, rnd: int) -> list[dict[str, Any]]:
        return [{"position": str(i + 1), "grid": str(i + 1), "status": "Finished", "laps": str(N_LAPS),
                 "Driver": {"driverId": d, "code": d.upper(), "givenName": "Test", "familyName": d, "nationality": "X"},
                 "Constructor": {"constructorId": f"team{i // 2}"}} for i, d in enumerate(DRIVERS)]

    def pitstops(self, season: int, rnd: int) -> list[dict[str, Any]]:
        return [{"driverId": d, "lap": str(lap), "stop": str(k + 1), "duration": "22.5"} for d, laps in self.pits.items() for k, lap in enumerate(laps)]

    def laps(self, season: int, rnd: int) -> list[dict[str, Any]]:
        out = []
        for lap in range(1, N_LAPS + 1):
            timings = []
            for i, d in enumerate(DRIVERS):
                stops = self.pits[d]
                age = lap - max([s for s in stops if s < lap], default=0)
                t = self.circuit_base + i * 80 + 55 * age - 9 * lap + self.rng.normal(0, 120)
                if lap in stops:
                    t += 9_000
                if lap - 1 in stops:
                    t += 11_000
                timings.append({"driverId": d, "position": str(i + 1), "time": fmt(t)})
            out.append({"number": str(lap), "Timings": timings})
        return out


def entry(rnd: int) -> dict[str, Any]:
    return {"season": "2024", "round": str(rnd), "raceName": f"Fixture GP {rnd}", "date": f"2024-{3 + rnd // 3:02d}-{1 + (rnd % 3) * 9:02d}",
            "Circuit": {"circuitId": "c_a" if rnd % 2 else "c_b", "circuitName": "Alpha" if rnd % 2 else "Beta",
                        "Location": {"lat": "1", "long": "2", "locality": "L", "country": "C"}}}


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Any:
    tmp: Path = tmp_path_factory.mktemp("api")
    settings = get_settings()
    settings.artifacts_dir = tmp / "artifacts"
    engine = create_engine(f"sqlite:///{tmp / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db.set_engine(engine)
    with Session(engine) as s:
        for rnd in range(1, 9):
            assert ingest_race(s, FixtureSource(rnd), entry(rnd)).status == "ok"  # type: ignore[arg-type]
        train_and_register(s, test_races=2)
    from app.main import create_app

    return TestClient(create_app())


def test_health_and_listing(client: TestClient) -> None:
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["races_with_laps"] == 8 and h["active_model"] == 1
    assert client.get("/api/seasons").json() == [{"season": 2024, "races": 8}]
    page = client.get("/api/races", params={"season": 2024, "page_size": 3}).json()
    assert page["total"] == 8 and len(page["items"]) == 3 and page["items"][0]["sessions"][0]["key"] == "race"


def test_race_detail_and_data_availability(client: TestClient) -> None:
    r = client.get("/api/races/8").json()
    assert len(r["drivers"]) == 8 and r["data_availability"]["weather"] is False and r["data_availability"]["tyre_compound"] is False
    assert r["model_split"] == "held_out_test"
    assert client.get("/api/races/999").status_code == 404


def test_laps_pagination_and_compare(client: TestClient) -> None:
    p = client.get("/api/races/1/laps", params={"driver_id": "d0", "page_size": 15, "page": 3}).json()
    assert p["total"] == N_LAPS and len(p["items"]) == 10 and p["kind"] == "actual"
    c = client.get("/api/races/1/compare", params=[("drivers", "d0"), ("drivers", "d3")]).json()
    assert [d["driver_id"] for d in c["drivers"]] == ["d0", "d3"] and len(c["drivers"][0]["laps"]) == N_LAPS
    assert client.get("/api/races/1/compare", params={"drivers": "nobody"}).status_code == 404
    assert client.get("/api/races/1/laps", params={"page_size": 5000}).status_code == 422


def test_weather_empty_state_is_explicit(client: TestClient) -> None:
    w = client.get("/api/races/1/weather").json()
    assert w["available"] is False and "does not publish weather" in w["reason"]


def test_prediction_uses_trained_model_and_reports_uncertainty(client: TestClient) -> None:
    body = {"race_id": 7, "driver_id": "d0", "lap_number": 20, "tyre_age": 4}
    p = client.post("/api/predict/laptime", json=body).json()
    lo, hi = p["interval_80_ms"]
    assert lo <= p["predicted_ms"] <= hi and p["kind"] == "predicted" and p["model_version"] == 1
    assert p["actual_ms"] is not None and abs(p["error_ms"]) < 3000
    assert p["compound_used_by_model"] is False
    older = client.post("/api/predict/laptime", json={**body, "tyre_age": 15}).json()["predicted_ms"]
    assert older > p["predicted_ms"]  # degradation learned from data


def test_prediction_input_validation(client: TestClient) -> None:
    base = {"race_id": 7, "driver_id": "d0", "lap_number": 5, "tyre_age": 5}
    assert client.post("/api/predict/laptime", json={**base, "tyre_age": 9}).status_code == 422
    assert client.post("/api/predict/laptime", json={**base, "compound": "PURPLE"}).status_code == 422
    assert client.post("/api/predict/laptime", json={**base, "driver_id": "ghost"}).status_code == 404
    assert client.post("/api/predict/laptime", json={**base, "lap_number": 0}).status_code == 422


def test_predict_vs_actual(client: TestClient) -> None:
    r = client.get("/api/races/8/predict-vs-actual", params={"driver_id": "d2"}).json()
    assert r["available"] and r["split"] == "held_out_test" and r["mae_ms"] < 3000 and len(r["points"]) > 20


def test_degradation_recovers_fixture_slope(client: TestClient) -> None:
    d = client.get("/api/races/3/degradation", params={"driver_id": "d1"}).json()
    assert d["available"] and d["kind"] == "actual_derived"
    assert d["fuel_slope_ms_per_lap"] == pytest.approx(-9, abs=4)
    fitted = [s for s in d["stints"] if s["slope_ms_per_lap"] is not None]
    assert fitted and d["pooled_degradation_ms_per_lap"] == pytest.approx(55, abs=8)
    assert all(abs(s["slope_ms_per_lap"] - 55) < 3.5 * s["slope_se"] + 5 for s in fitted)  # truth inside the CI
    assert d["model_curve"]["kind"] == "predicted"
    assert all(s["compound"] is None for s in d["stints"]) and "not provided" in d["notes"][0]


def test_optimize_returns_feasible_ranked_strategy(client: TestClient) -> None:
    r = client.post("/api/strategy/optimize", json={"race_id": 8, "driver_id": "d0", "params": {"max_stops": 2}}).json()
    assert r["kind"] == "predicted" and r["pit_loss_estimate"]["n_stops"] > 0
    assert r["pit_loss_estimate"]["pit_loss_ms"] == pytest.approx(20_000, rel=0.15)  # 9 s + 11 s injected in fixture
    rec = r["recommended"]
    assert sum(s["laps"] for s in rec["stints"]) == N_LAPS and len({s["compound"] for s in rec["stints"]}) >= 2
    totals = [rec["predicted_total_ms"]] + [a["predicted_total_ms"] for a in r["alternatives"]]
    assert totals == sorted(totals) and r["explanation"] and rec["pit_windows"]
    assert r["actual_strategy"]["completed_full_distance"] and r["actual_strategy"]["pit_laps"]


def test_optimize_validation_and_infeasible(client: TestClient) -> None:
    assert client.post("/api/strategy/optimize", json={"race_id": 8, "driver_id": "d0", "params": {"pit_loss_ms": 10}}).status_code == 422
    r = client.post("/api/strategy/optimize", json={"race_id": 8, "driver_id": "d0", "params": {
        "compounds": {"SOFT": {"max_stint_laps": 5}, "HARD": {"max_stint_laps": 5}}, "max_stops": 1}})
    assert r.status_code == 422 and "no feasible" in r.json()["detail"]


def test_simulation_what_if(client: TestClient) -> None:
    opt = client.post("/api/strategy/optimize", json={"race_id": 8, "driver_id": "d0", "params": {"max_stops": 2}}).json()
    best = opt["recommended"]["stints"]
    alt = [{"compound": "SOFT", "laps": 10}, {"compound": "MEDIUM", "laps": 15}, {"compound": "HARD", "laps": 15}]
    body = {"race_id": 8, "driver_id": "d0", "params": {"max_stops": 2}, "strategies": [best, alt], "n_sims": 1500, "seed": 5,
            "safety_car": {"mode": "random", "probability": 0.6, "duration_laps": 4}}
    r = client.post("/api/strategy/simulate", json=body).json()
    assert r["kind"] == "simulated" and r["scenario"]["hypothetical"] is True and r["n_sims"] == 1500
    s0, s1 = r["strategies"]
    assert s0["win_probability"] + s1["win_probability"] == pytest.approx(1.0)
    assert s0["p5_ms"] <= s0["median_ms"] <= s0["p95_ms"] and 0 < r["sc_hit_rate"] < 1
    again = client.post("/api/strategy/simulate", json=body).json()
    assert {k: v for k, v in again.items() if k != "compute_seconds"} == {k: v for k, v in r.items() if k != "compute_seconds"}  # same seed -> identical
    bad = {**body, "strategies": [[{"compound": "SOFT", "laps": 40}]]}
    assert client.post("/api/strategy/simulate", json=bad).status_code == 422
    assert client.post("/api/strategy/simulate", json={**body, "n_sims": 10**7}).status_code == 422


def test_full_journey_select_predict_optimise_simulate(client: TestClient) -> None:
    """The headline workflow from the brief, via the API."""
    race = client.get("/api/races", params={"season": 2024}).json()["items"][-1]
    rid, drv = race["id"], client.get(f"/api/races/{race['id']}").json()["drivers"][1]["driver_id"]
    laps = client.get(f"/api/races/{rid}/laps", params={"driver_id": drv}).json()
    assert laps["total"] > 0
    pred = client.post("/api/predict/laptime", json={"race_id": rid, "driver_id": drv, "lap_number": 10, "tyre_age": 10}).json()
    assert pred["predicted_ms"] > 0
    opt = client.post("/api/strategy/optimize", json={"race_id": rid, "driver_id": drv, "params": {"max_stops": 2}}).json()
    sim = client.post("/api/strategy/simulate", json={"race_id": rid, "driver_id": drv, "params": {"max_stops": 2},
                                                      "strategies": [opt["recommended"]["stints"]], "n_sims": 500}).json()
    assert sim["strategies"][0]["mean_ms"] == pytest.approx(opt["recommended"]["predicted_total_ms"], rel=0.05)


def test_models_endpoint_exposes_real_metrics(client: TestClient) -> None:
    m = client.get("/api/models/active").json()
    assert m["metrics"]["n_test_laps"] > 0 and m["n_test_races"] == 2 and set(m["test_races"]).isdisjoint(range(1, 7))
    assert m["metrics"]["mae_ms"] < m["metrics"]["baseline_circuit_median_mae_ms"]
