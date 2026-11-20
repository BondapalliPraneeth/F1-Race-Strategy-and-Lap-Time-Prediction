"""ML pipeline tests on a SYNTHETIC generator with a known law (test-only; never used by the app).

They verify mechanics — chronological split, no train/test leakage, determinism, calibration of the
uncertainty interval, and that the model recovers a known tyre-degradation effect. Real-data accuracy
is reported separately by the evaluation run (MODEL_EVALUATION.md).
"""
import numpy as np
import pandas as pd
import pytest

from app.ml import features as F
from app.ml import train as T

BASE = {"c1": 92_000, "c2": 78_000}
DEG_MS_PER_LAP = 40


def synthetic(n_races: int = 9, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for r in range(n_races):
        circuit = "c1" if r % 2 == 0 else "c2"
        for d in range(8):
            skill = d * 60
            for lap in range(2, 51):
                age = (lap - 1) % 20 + 1
                t = BASE[circuit] + skill + DEG_MS_PER_LAP * age - 8 * lap + rng.normal(0, 150)
                rows.append(dict(race_id=r + 1, season=2024, round=r + 1, circuit_id=circuit, total_laps=50,
                                 race_date=pd.Timestamp("2024-03-01") + pd.Timedelta(days=14 * r), driver_id=f"d{d}",
                                 lap_number=lap, position=d + 1, lap_time_ms=t, stint_number=1 + (lap - 1) // 20,
                                 tyre_age=age, is_in_lap=False, is_out_lap=False, is_neutralised=False,
                                 compound=None, constructor_id=f"t{d // 2}", grid=d + 1.0, race_progress=lap / 50))
    return pd.DataFrame(rows)


def test_split_is_chronological_and_disjoint() -> None:
    df = synthetic()
    train_ids, test_ids = T.split_races(df, 3)
    assert not set(train_ids) & set(test_ids)
    assert test_ids == [7, 8, 9] and max(train_ids) < min(test_ids)


def test_split_rejects_too_little_data() -> None:
    with pytest.raises(ValueError):
        T.split_races(synthetic(4), 3)


def test_baselines_use_training_races_only() -> None:
    df = synthetic()
    train = df[df.race_id <= 6]
    poisoned = df.copy()
    poisoned.loc[poisoned.race_id > 6, "lap_time_ms"] += 50_000  # change test data only
    assert F.circuit_baselines(train) == F.circuit_baselines(poisoned[poisoned.race_id <= 6])
    b = T.fit(train)
    p1 = T.predict_ms(b, df[df.race_id > 6])
    p2 = T.predict_ms(b, poisoned[poisoned.race_id > 6])
    pd.testing.assert_frame_equal(p1, p2)  # predictions cannot depend on test targets


def test_model_beats_baselines_on_unseen_races_with_calibrated_interval() -> None:
    df = synthetic()
    train_ids, test_ids = T.split_races(df, 3)
    train, test = df[df.race_id.isin(train_ids)], df[df.race_id.isin(test_ids)]
    b = T.fit(train)
    m = T.evaluate(b, train, test)
    assert m["mae_ms"] < 0.5 * m["baseline_circuit_median_mae_ms"]
    assert 0.65 <= m["interval_80_coverage"] <= 0.95
    assert m["unseen_circuit_laps"]["n_laps"] == 0


def test_model_recovers_known_tyre_degradation_and_is_deterministic() -> None:
    df = synthetic()
    b1, b2 = T.fit(df), T.fit(df)
    probe = df[(df.race_id == 1) & (df.driver_id == "d0")].copy()
    lo, hi = probe.copy(), probe.copy()
    lo["tyre_age"], hi["tyre_age"] = 2, 18
    slope = (T.predict_ms(b1, hi)["p50"] - T.predict_ms(b1, lo)["p50"]).mean() / 16
    assert slope == pytest.approx(DEG_MS_PER_LAP, rel=0.35)
    pd.testing.assert_frame_equal(T.predict_ms(b1, probe), T.predict_ms(b2, probe))


def test_unseen_circuit_falls_back_without_crashing() -> None:
    df = synthetic()
    b = T.fit(df)
    x = df.head(5).copy()
    x["circuit_id"] = "new_circuit"
    out = T.predict_ms(b, x)
    assert out.notna().all().all() and (out["p10"] <= out["p90"]).all()


def test_clean_laps_filters() -> None:
    df = synthetic(3)
    df.loc[df.index[:5], "is_neutralised"] = True
    df.loc[df.index[5:10], "lap_time_ms"] = np.nan
    assert len(F.clean_laps(df)) <= len(df) - 10
