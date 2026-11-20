"""Reproducible, leakage-safe training and evaluation on chronologically held-out races.

Protocol
  * Split by RACE (never by lap), ordered by date: the last ``test_races`` races are unseen test data.
  * Circuit baselines / category vocabularies are fitted on the training races only.
  * Three quantile models (p10, p50, p90) give a point estimate and an 80 % prediction interval.
  * Reported against two naive baselines on the same test laps.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.preprocessing import OrdinalEncoder
from sqlalchemy.orm import Session

from app.config import get_settings
from app.logging_setup import get_logger
from app.ml import features as F
from app.models import ModelVersion

log = get_logger("train")
QUANTILES = (0.1, 0.5, 0.9)
HYPERPARAMS: dict[str, Any] = {"max_iter": 300, "learning_rate": 0.05, "max_leaf_nodes": 31, "min_samples_leaf": 40,
                               "l2_regularization": 1.0}
SEED = 42


@dataclass
class Bundle:
    """Everything needed to predict, persisted as a single joblib artifact."""
    models: dict[float, HistGradientBoostingRegressor]
    encoder: OrdinalEncoder
    numeric: list[str]
    categorical: list[str]
    baselines: dict[str, float]
    global_baseline: float


def split_races(df: pd.DataFrame, test_races: int) -> tuple[list[int], list[int]]:
    order = (df.drop_duplicates("race_id").sort_values(["race_date", "round"])["race_id"].tolist())
    if len(order) < test_races + 3:
        raise ValueError(f"need at least {test_races + 3} ingested races, have {len(order)}")
    return order[:-test_races], order[-test_races:]


def _matrix(df: pd.DataFrame, b: Bundle) -> pd.DataFrame:
    X = df[b.numeric].astype(float).copy()
    if b.categorical:
        enc = b.encoder.transform(df[b.categorical].fillna("UNKNOWN").astype(str))
        for i, c in enumerate(b.categorical):
            X[c] = enc[:, i]
    return X


def baseline_for(b: Bundle, circuit_ids: pd.Series) -> np.ndarray:
    return circuit_ids.map(b.baselines).fillna(b.global_baseline).to_numpy(dtype=float)


def predict_ms(b: Bundle, df: pd.DataFrame) -> pd.DataFrame:
    """Returns p10/p50/p90 absolute lap-time predictions in ms (quantiles sorted to avoid crossing)."""
    X, base = _matrix(df, b), baseline_for(b, df["circuit_id"])
    q = np.sort(np.column_stack([b.models[k].predict(X) for k in QUANTILES]), axis=1) + base[:, None]
    return pd.DataFrame(q, columns=["p10", "p50", "p90"], index=df.index)


def fit(train: pd.DataFrame) -> Bundle:
    numeric, cats = F.feature_columns(train)
    baselines = F.circuit_baselines(train)
    enc = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
    if cats:
        enc.fit(train[cats].fillna("UNKNOWN").astype(str))
    b = Bundle({}, enc, numeric, cats, baselines, float(train["lap_time_ms"].median()))
    X = _matrix(train, b)
    y = train["lap_time_ms"].to_numpy(dtype=float) - baseline_for(b, train["circuit_id"])
    cat_mask = [c in cats for c in X.columns]
    for q in QUANTILES:
        m = HistGradientBoostingRegressor(loss="quantile", quantile=q, random_state=SEED,
                                          categorical_features=cat_mask if cats else None, **HYPERPARAMS)
        b.models[q] = m.fit(X, y)
    return b


def evaluate(b: Bundle, train: pd.DataFrame, test: pd.DataFrame) -> dict[str, Any]:
    all_test = test
    unseen_mask = ~all_test["circuit_id"].isin(b.baselines.keys())
    unseen_info: dict[str, Any] = {"n_laps": int(unseen_mask.sum()), "circuits": sorted(all_test.loc[unseen_mask, "circuit_id"].unique().tolist())}
    if unseen_mask.any():
        ye = all_test.loc[unseen_mask, "lap_time_ms"].to_numpy(dtype=float)
        unseen_info["mae_ms"] = float(np.mean(np.abs(predict_ms(b, all_test[unseen_mask])["p50"].to_numpy() - ye)))
        unseen_info["note"] = "no circuit history in training data: absolute pace is not identifiable; excluded from headline metrics"
    test = all_test[~unseen_mask]  # headline metrics: circuits with training history
    if test.empty:
        return {"n_test_laps": 0, "unseen_circuit_laps": unseen_info, "error": "no held-out laps at circuits seen in training"}
    y = test["lap_time_ms"].to_numpy(dtype=float)
    pred = predict_ms(b, test)
    err = pred["p50"].to_numpy() - y
    naive = baseline_for(b, test["circuit_id"])
    # Baseline 2: circuit median + linear tyre-age slope fitted on training data (no fuel/driver info).
    tr_delta = train["lap_time_ms"] - train["circuit_id"].map(b.baselines)
    slope, icpt = np.polyfit(train["tyre_age"].astype(float), tr_delta.astype(float), 1)
    naive_age = naive + icpt + slope * test["tyre_age"].to_numpy(dtype=float)
    mae = lambda e: float(np.mean(np.abs(e)))  # noqa: E731
    return {
        "n_test_laps": int(len(test)),
        "mae_ms": mae(err), "rmse_ms": float(np.sqrt(np.mean(err**2))), "bias_ms": float(err.mean()),
        "baseline_circuit_median_mae_ms": mae(naive - y),
        "baseline_circuit_median_plus_tyre_age_mae_ms": mae(naive_age - y),
        "interval_80_coverage": float(((y >= pred["p10"]) & (y <= pred["p90"])).mean()),
        "interval_80_mean_width_ms": float((pred["p90"] - pred["p10"]).mean()),
        "unseen_circuit_laps": unseen_info,
        "headline_scope": "held-out races, laps at circuits present in training data",
        "per_race_mae_ms": {int(r): mae(err[(test["race_id"] == r).to_numpy()]) for r in test["race_id"].unique()},
    }


def train_and_register(session: Session, test_races: int = 4, name: str = "laptime") -> ModelVersion:
    laps = F.load_laps(session)
    if laps.empty:
        raise ValueError("no ingested laps; run the ingestion first")
    train_ids, test_ids = split_races(laps, test_races)
    clean = F.clean_laps(laps)
    train, test = clean[clean["race_id"].isin(train_ids)], clean[clean["race_id"].isin(test_ids)]
    assert not set(train["race_id"]) & set(test["race_id"]), "train/test race overlap"
    bundle = fit(train)
    metrics = evaluate(bundle, train, test)
    metrics["n_train_laps"] = int(len(train))
    out = Path(get_settings().artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    session.query(ModelVersion).filter(ModelVersion.name == name).update({"is_active": False})
    mv = ModelVersion(
        name=name, is_active=True, artifact_path="", feature_spec={
            "version": F.FEATURE_SPEC_VERSION, "numeric": bundle.numeric, "categorical": bundle.categorical,
            "target": "lap_time_ms - circuit_baseline (train-only median)", "quantiles": list(QUANTILES),
            "cleaning": "excl. lap 1, in/out laps, neutralised laps, >107% of driver race median"},
        hyperparameters=HYPERPARAMS, train_races=[int(x) for x in train_ids], test_races=[int(x) for x in test_ids],
        metrics=metrics, data_fingerprint=F.data_fingerprint(train), random_seed=SEED)
    session.add(mv)
    session.flush()
    path = out / f"{name}_v{mv.id}.joblib"
    joblib.dump(bundle, path)
    mv.artifact_path = str(path)
    session.commit()
    log.info("model_registered", id=mv.id, mae=metrics["mae_ms"], baseline=metrics["baseline_circuit_median_mae_ms"])
    return mv


def load_bundle(mv: ModelVersion) -> Bundle:
    return joblib.load(mv.artifact_path)  # type: ignore[no-any-return]
