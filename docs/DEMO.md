# Demo Scenario and Walkthrough

A reproducible scenario using real data: **2024 Las Vegas Grand Prix, Charles Leclerc** (race id depends on your DB;
the UI selectors find it by name; the screenshots in `docs/screenshots/` were produced by `frontend/scripts/screenshots.mjs`).

## Prepare (≈ 20–40 min, mostly polite rate-limited downloads)

```bash
cd backend
export F1_DATABASE_URL=sqlite:///data/dev.db
python -m app.cli migrate
python -m app.cli ingest --season 2023
python -m app.cli ingest --season 2024
python -m app.cli train --test-races 4      # Las Vegas 2024 is a held-out test race
uvicorn app.main:app --port 8000 &
cd ../frontend && npm ci && npm run dev
```

## Walkthrough

1. **Race Analysis** – choose 2024 → Las Vegas GP → Race. Tick Leclerc and another driver: lap-time and position charts
   (badge *ACTUAL*, source: laps table), pit stops list.
2. **Lap-Time Prediction** – lap 20, tyre age 5 → p50 and 80 % interval (*PREDICTED*, "held-out test race" notice).
   The lower chart shows predicted vs actual for every clean lap (MAE 0.665 s, 45 laps for this driver).
3. **Tyre Degradation** – regression of lap time on tyre age from real laps; note the tyre-age caveat and the missing compound data.
4. **Strategy Optimizer** – leave pit loss blank (data-derived: 24.2 s, median of 55 recorded stops), click *Find optimal
   strategy*: recommended 1-stop M32→S18, pit window laps 30–32, explanation, 7 alternatives, and the actual strategy
   (stops on laps 9, 31) for comparison. Edit the compound profile (assumption) and re-run to see sensitivity.
5. **What-If Simulation** – enter `MEDIUM:25, HARD:25` vs `SOFT:15, HARD:35`, 2,000 simulations, random safety car,
   optional weather window: mean/p5/p95, win probability, histogram (*SIMULATED*). Same seed ⇒ same result.
6. **Model & Data** – active model version, split, metrics, baselines, data availability (no compounds/weather).

Error and empty states to try: stop the API (banner), run before training (503 message), simulation laps that do not sum
to the race distance (inline validation), the weather panel (explicit "not available from source").

## Automated version

`frontend/e2e/journey.spec.ts` runs this journey in Playwright against the real API (CI seeds from a synthetic fixture
pushed through the real ingestion and training code, so CI needs no network).
