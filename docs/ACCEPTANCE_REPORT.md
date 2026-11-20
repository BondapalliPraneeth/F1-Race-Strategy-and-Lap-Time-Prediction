# Acceptance Report

Status legend: **Done** = implemented and verified; **Partial** = works with a stated limit; **Not done**.
Test status reflects runs on the author's Windows machine (and Docker Desktop) on 2026-11-20. GitHub Actions has **not yet run** (nothing pushed).

| Feature | Implementation Status | Test Status | Evidence |
|---|---|---|---|
| Ingestion from Jolpica (paging, back-off, cache, idempotent, audit) | Done | pytest `test_ingestion.py` pass; real run loaded 85 races / 92k laps | `docs/DATA_SOURCES.md`, `ingestion_runs` |
| Real tyre-compound / weather / SC data | Done for 2022–2025 (Mendeley FastF1-derived dataset, CC BY 4.0; 90 of 109 races matched) | `test_tyres.py` (7 tests, synthetic data in the real column layout); real enrichment run | `DATA_SOURCES.md` |
| PostgreSQL schema + Alembic | Done | `test_db.py`; migration applied on PostgreSQL 16 in Docker; 36 API/ingestion/strategy + 9 ML tests pass on PG | `DATABASE_SCHEMA.md` |
| Feature building, chronological split, no leakage | Done | `test_ml.py` | `MODEL_METHODOLOGY.md` |
| Lap-time model with uncertainty, versioned registry | Done | `test_ml.py` (beats baselines on synthetic, deterministic, calibration) | model v6 in `model_versions` |
| Real-data accuracy | Done – MAE 806 ms vs 1,541 ms baseline on 4 dry 2025 races, coverage 0.80; compound adds no accuracy (ablation 793 ms) | metrics measured on held-out races | `MODEL_EVALUATION.md` |
| Abnormal (wet) race detection | Done – rainfall/wet-tyre share from real weather plus the pace rule; 11 training races excluded | `test_tyres.py` unit test | `MODEL_EVALUATION.md` |
| Tyre degradation analysis (C) | Done (true tyre life, by real compound) | `test_degradation_recovers_fixture_slope` | screenshot 03 |
| Pit optimizer, exact DP, windows, explanations (D) | Done; compound stint limits data-derived, pace from model | `test_strategy.py` (DP vs brute force, constraints) | `STRATEGY_ENGINE.md`, screenshot 04 |
| Monte Carlo what-if (E) | Done; not validated against real outcomes | `test_strategy.py` (seed, CRN, SC, weather) | `SIMULATION_METHODOLOGY.md` |
| REST API, validation, pagination, errors | Done | `test_api.py` | `API_DOCUMENTATION.md` |
| React dashboard, loading/error/empty states, labels | Done | vitest 21 pass; Playwright 4/4 pass on seeded DB | screenshots 01–06 |
| Playwright full journey on real-data DB | Done – the plan is derived from the race length shown by the app | 4/4 pass on both seeded and real-data DBs | `TESTING.md` |
| Accessibility | Partial – labels, roles, alerts, keyboard-usable forms; no automated a11y audit | manual / role-based locators | – |
| Docker Compose | Done | `compose build`, `up`, `/api/health` via nginx on :8080 verified locally | `DEPLOYMENT.md` |
| CI workflow | Written; **unverified on GitHub** | components verified locally (ruff, mypy, pytest, vitest, build, Playwright, compose) | `.github/workflows/ci.yml` |
| Performance measured | Done | local, SQLite, laptop | below |
| 12 docs, diagrams, demo, screenshots | Done | – | `docs/` |

## Last local results
* Backend: 54 tests passed (backend, SQLite). ruff and mypy clean.
* Frontend: vitest 21 passed; oxlint warnings only (3); production build OK.
* E2E: 4 passed (seeded DB).

## Measured performance (real data, 2021–2024, local)
list/laps ≈ 0.3 s · prediction ≈ 0.35–0.45 s · degradation ≈ 0.27 s warm · optimise ≈ 1.5–2.5 s · simulate 5k–20k runs ≈ 0.6–0.7 s · training ≈ 1–2 min · ingestion ≈ 1 min/race when not throttled (HTTP 429 slowed earlier runs).
