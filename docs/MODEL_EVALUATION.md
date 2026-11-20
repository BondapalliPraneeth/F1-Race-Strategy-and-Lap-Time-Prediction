# Model Evaluation (real results)

Evaluated on **held-out future races** (chronological split). Numbers below come from `model_versions.metrics` of the
active model **v4** trained on the author's local database; regenerate with `python -m app.cli train`.

**Data**: 85 races with laps (2021–2024, some 2021/2022 rounds unavailable from the source), 92,337 laps from Jolpica-F1.
Train: 73 races (68,984 clean laps); calibration: 2024 Singapore, United States, Mexico City; **test: 2024 São Paulo, Las Vegas, Qatar, Abu Dhabi** (3,377 laps).
Four training races were excluded by the abnormal-pace rule.

| Metric (test laps) | Model v4 | Baseline: circuit median | Baseline: + tyre age |
|---|---|---|---|
| MAE | **3,034 ms** | 3,281 ms | 3,299 ms |
| RMSE | 4,493 ms | – | – |
| Bias (pred − actual) | −1,758 ms | – | – |
| 80 % interval coverage | **0.65** (target 0.80) | – | – |
| Mean interval width | 5,088 ms | – | – |

Per-race MAE: São Paulo **8,236 ms**, Las Vegas 770 ms, Qatar 1,992 ms, Abu Dhabi 857 ms.

## Interpretation (honest)

* The model beats both naive baselines (≈ 7.5 % lower MAE), but the headline is dominated by **São Paulo 2024, a wet,
  red-flagged race**. On the three dry races MAE is 0.8–2.0 s. Without weather data this cannot be fixed, only detected.
* The abnormal-pace flag excluded 4 training races but did **not** flag São Paulo 2024 itself (it is not in the strata,
  `strata: {}`), so the rule is a coarse proxy that misses this case. I did not tune the threshold on the test race, to avoid leakage.
* Coverage 0.65 < 0.80: conformal calibration helps (an earlier uncalibrated model reached 0.43 on a similar split) but
  the calibration races are dry and the test set contains a wet race, so shift remains.
* Adding tyre age to the median baseline does not help on its own (3,299 vs 3,281 ms): without compound data, age is a
  noisy lower bound. The model's gain comes from driver/team/lap/progress interactions.
* More data (46 → 85 races) barely changed test MAE (3,008 → 3,034 ms): the error is dominated by the wet race, not by sample size.

## Reproduce
```bash
cd backend && F1_DATABASE_URL=sqlite:///data/dev.db .venv/Scripts/python -m app.cli train --test-races 4
```
Unit tests assert on synthetic data with a known generating process that the model beats baselines on unseen races,
recovers the true degradation slope, is deterministic, and that conformal calibration improves coverage under shift.
