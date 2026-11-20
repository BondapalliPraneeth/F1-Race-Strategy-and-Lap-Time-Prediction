# Model Evaluation (real results)

Evaluated on **held-out future races** (chronological split). Numbers come from `model_versions.metrics` of the
active model **v6**, trained on the author's local database; regenerate with `python -m app.cli train`.

**Data**: 109 races with laps (2021–2025; Jolpica-F1 lap times) enriched with tyre compound, true tyre life, weather and
safety-car labels from the Mendeley FastF1-derived dataset (2022–2025, 90 of them matched; 2021, Miami 2023 and Spanish 2025 have no tyre data).
Compound is present on 78 % of training laps. Train: 90 races (85,866 clean laps); calibration: 2025 Singapore, United States, Mexico City;
**test: 2025 São Paulo, Las Vegas, Qatar, Abu Dhabi** (3,822 laps).
11 training races were excluded as wet/abnormal (rain or wet tyres on > 10 % of laps, or median pace > 1.06 × circuit reference).

| Metric (test laps) | Model v6 | Baseline: circuit median | Baseline: + tyre age |
|---|---|---|---|
| MAE | **806 ms** | 1,541 ms | 1,562 ms |
| RMSE | 978 ms | – | – |
| Bias (pred − actual) | +218 ms | – | – |
| 80 % interval coverage | **0.80** (target 0.80) | – | – |
| Mean interval width | 2,494 ms | – | – |

Per-race MAE: São Paulo 916 ms, Las Vegas 1,110 ms, Qatar 609 ms, Abu Dhabi 653 ms.

## Interpretation (honest)

* **These numbers are NOT comparable with the earlier v5 results (MAE 3,034 ms).** The test races are different (2025 instead of 2024),
  and the 2024 test set contained a wet, red-flagged São Paulo race (8.2 s MAE) that dominated v5's headline. All four 2025 test races
  were normal-pace. The circuit-median baseline itself dropped from 3,281 ms to 1,541 ms, so the fair statement is
  **the model beats the baseline by ≈ 48 % on these four races**, not that the model became 4× better.
* **Compound does not improve accuracy.** Ablation on the same split and training laps without the compound feature: MAE **793 ms**
  (vs 806 ms with it). The gain over the baseline comes from true tyre life, driver/team/lap/race-progress context and the cleaner training set.
* **Compound effects in the model are confounded.** At equal tyre age the model predicts SOFT *slower* than HARD (≈ 0.5 s at lap 10, tyre age 3 on a 2025 Las Vegas lap).
  That is an association caused by strategy (which compound is run when, and by whom), not tyre physics. The optimiser therefore uses the model's pace with
  offset 0 / multiplier 1 and takes compound *limits* (max stint) from real stints, and the UI says so.
* Negative conformal quantile (−80 ms): calibration races were slightly over-covered, so intervals were tightened a little.
  80 % coverage on four races is a small-sample result, not a guarantee.
* Four test races at four circuits. Wet races are excluded from training and would be reported in a separate stratum (none in this test set).

## Reproduce
```bash
cd backend && F1_DATABASE_URL=sqlite:///data/dev.db .venv/Scripts/python -m app.cli train --test-races 4
```
Unit tests assert on synthetic data with a known generating process that the model beats baselines on unseen races,
recovers the true degradation slope, learns a known compound offset, is deterministic, and that conformal calibration improves coverage under shift.
