# Limitations (read before trusting any number)

1. **Tyre data is a community FastF1-derived dataset, 2022–2025 only.** Compound, true tyre life, weather and safety-car labels come from a Mendeley
   dataset (CC BY 4.0), not an official feed. 2021, Miami 2023 and Spanish GP 2025 have none; those laps fall back to laps-since-stop and no compound.
2. **Compound does not improve lap-time accuracy** (ablation: 793 ms without vs 806 ms with), and the model's compound effect is *confounded* by strategy
   and fuel load (it predicts SOFT slower than HARD at equal age). The optimiser therefore applies no extra compound pace offsets; only stint limits come from real stints.
   Hand-set compound offsets/multipliers remain available as labelled what-ifs.
3. **Tyre-set history is not modelled.** `TyreLife` captures used-set age, but the number of sets available per compound is not known.
4. **Wet and interrupted races are excluded from training** (rain/wet tyres on > 10 % of laps or abnormal pace). The model is a dry-race model; no wet-strategy support.
5. **Safety car / VSC labels come from race-control messages for 2022–2025**; earlier seasons use the pace heuristic. Red flags are not labelled.
6. **Optimizer is single-car.** No traffic, undercut/overcut, track position, fuel, DRS or rival reaction. Pit-loss is a per-circuit median of recorded stops; traffic and
   safety-car slowdown factors are assumptions. It is a model-based recommendation, not a team call, and has not been validated against real strategy outcomes.
7. **Prediction accuracy is reported honestly** (see MODEL_EVALUATION): four dry 2025 test races, small-sample coverage, and numbers that are not comparable with the earlier
   wet-race-dominated v5 results. Unseen circuits fall back to a global baseline and are flagged (`unseen_circuit`).
8. **Monte Carlo is a sensitivity tool.** Noise terms are Gaussian; safety-car timing and weather windows are scenarios, not forecasts.
9. **Dataset access is fragile.** The Mendeley file-listing endpoint is undocumented and the dataset is a single-author derivative; `fetch-tyres` verifies sha256 hashes,
   and manual download plus `ingest-tyres --dir` is the fallback. Jolpica is community-run and rate-limited (HTTP 429); ingestion is idempotent and cached.
10. **Scale.** Single-process API, in-memory caches, no auth or rate limiting. Fine for a portfolio/demo deployment, not production.
11. **Docker/PostgreSQL** paths are exercised in CI; see the acceptance report for what was verified locally. The tyre-enrichment path is covered by unit tests on a synthetic
    dataset with the real column layout; the e2e seed database has no tyre data.
