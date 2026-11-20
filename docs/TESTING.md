# Testing

| Layer | Location | Tooling | What it covers |
|---|---|---|---|
| Unit / ingestion | `backend/tests/test_ingestion.py` | pytest, respx (HTTP mocked at the network boundary) | pagination, 429 back-off, time parsing, stint/tyre-age derivation, duplicates, idempotent re-ingest, failure recording |
| ML | `tests/test_ml.py` | pytest | cleaning, features, chronological split (no leakage), training, determinism with seed, registry, abnormal-race flag, conformal calibration |
| Strategy | `tests/test_strategy.py` | pytest | DP vs brute-force on hand-built pace tables, constraints, infeasible cases, pit windows, Monte Carlo reproducibility, common random numbers, SC/weather effects |
| Tyre / weather enrichment | `tests/test_tyres.py` | pytest | synthetic dataset in the real Mendeley column layout: join, idempotence, true tyre life, SC stats, wet-race detection, model learns a known compound effect, per-compound optimiser |
| API / DB | `tests/test_api.py` | FastAPI TestClient on a DB filled by the real ingestion pipeline from a synthetic source fixture | all routes, validation, pagination, empty/error states (503, 404, 422) |
| Frontend components | `frontend/src/**/*.test.tsx` | vitest + Testing Library (fetch stubbed) | empty state, validation, backend-error display, plan parser, chart labelling |
| End to end | `frontend/e2e/journey.spec.ts` | Playwright (chromium) against real API + built UI | full journey A→E, input validation, weather empty state, injected 503 error, simulation sum validation |
| Static | CI | ruff, mypy (pydantic plugin), oxlint, tsc | |

Tests use a **synthetic fixture only as test input** (never as application data). The E2E database is created by running
the real ingestion and training code on that fixture (`backend/scripts/seed_e2e.py`).

## Run

```bash
cd backend && .venv/Scripts/python -m pytest -q          # ~3 min (ML tests dominate)
cd backend && TEST_DATABASE_URL=postgresql+psycopg://... pytest   # same suite on PostgreSQL
cd frontend && npm test                                   # vitest
cd frontend && npm run e2e                                # needs API on :8000 (see playwright.config.ts)
```

Last local results are recorded in `docs/ACCEPTANCE_REPORT.md`.

Note: the first Playwright run after a cold API start can time out on the model's first pace-table computation (observed twice locally against the real-data database); a re-run passes. CI retries once.
