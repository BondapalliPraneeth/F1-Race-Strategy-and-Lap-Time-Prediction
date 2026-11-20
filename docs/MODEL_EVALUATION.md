# Model Evaluation (real results)

Evaluated on **held-out future races** (chronological split). Numbers below come from `model_versions.metrics` of the
active model **v3** trained on the author's local database; regenerate with `python -m app.cli train`.

**Data**: 48 races with laps (2022: 2 races, 2023: 22, 2024: 24), 52,749 laps from Jolpica-F1. Train: 41 races
(38,829 clean laps); calibration: 2024 Singapore, United States, Mexico City; **test: 2024 São Paulo, Las Vegas, Qatar, Abu Dhabi** (3,377 laps).
(Ingesting 2022/2021 was throttled by the source with HTTP 429, so only 2 early-2022 races were loaded.)

| Metric (test laps) | Model v3 | Baseline: circuit median | Baseline: + tyre age |
|---|---|---|---|
| MAE | **3,008 ms** | 3,245 ms | 3,278 ms |
| RMSE | 4,491 ms | – | – |
| Bias (pred − actual) | −1,693 ms | – | – |
| 80 % interval coverage | **0.64** (target 0.80) | – | – |
| Mean interval width | 5,913 ms | – | – |

Per-race MAE: São Paulo **8,230 ms**, Las Vegas 674 ms, Qatar 2,201 ms, Abu Dhabi 692 ms.

## Interpretation (honest)

* The model beats both naive baselines overall, but the headline is dominated by **São Paulo 2024, a wet,
  red-flagged race**. On the three dry races MAE is 0.7–2.2 s, and the wet race inflates MAE, bias (the model predicts
  dry pace) and under-coverage. Without weather data this cannot be fixed, only detected.
* The abnormal-pace flag did **not** trigger here: it needs ≥ 3 races per circuit and only two full seasons are
  loaded. Stratified metrics (`strata`) will populate once ≥ 3 seasons are ingested.
* Coverage 0.64 < 0.80: conformal calibration raised coverage (earlier uncalibrated model: 0.43 on the same kind of
  split) but calibration races are dry and the test set contains a wet race, so shift remains.
* Gains over the circuit-median baseline are modest (≈ 7 %) because pace within a race is largely explained by
  circuit and by driver/car, and the missing compound/weather information is exactly what drives lap-to-lap variance.
* Adding tyre age to the median baseline does not help on its own (3,278 vs 3,245 ms), consistent with age
  being a noisy lower bound without compound data; the model's gain comes from driver/team/lap/progress interactions.

## Reproduce
```bash
cd backend && F1_DATABASE_URL=sqlite:///data/dev.db .venv/Scripts/python -m app.cli train --test-races 4
```
Unit tests assert on synthetic data with a known generating process that the model beats baselines on unseen races,
recovers the true degradation slope, is deterministic, and that conformal calibration improves coverage under shift.
