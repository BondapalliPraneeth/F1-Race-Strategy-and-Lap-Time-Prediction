# Strategy Engine

Code: `backend/app/strategy/engine.py`, `config.py`. The engine answers *"for this driver in this race, which pit
laps and tyre sequence minimise predicted race time?"*

## Inputs

1. **Pace table** `pace[lap, age]` – the model's p50 lap time for every (lap number, tyre age) pair, built once per
   (race, driver, model) and cached. The model never sees compounds (the source has none).
2. **`StrategyConfig`** (Pydantic, validated) – race length, pit loss, compound profiles, stop limits, minimum stint,
   optional penalties. See `config.py` for bounds and descriptions.

## Algorithm

For each admissible **compound sequence** (e.g. MEDIUM→HARD, SOFT→MEDIUM→HARD) the engine solves the pit-lap
placement **exactly** with dynamic programming:

* `stint_cost_table` gives the cost of a stint of `n` laps starting on lap `s` on compound `c`
  (prefix sums of the adjusted pace: `pace + offset_ms + (age-effect × degradation_multiplier)`).
* `_optimise_sequence` runs a DP over (stint index, laps used) choosing stint lengths between `min_stint_laps` and
  the compound's `max_stint_laps`, adding `pit_loss_ms` (+ optional in/out-lap and traffic penalties) per stop.
* `evaluate` scores a user-supplied plan with the same cost model, so the optimum and a manual plan are comparable.
* Sequences are filtered by `_valid_sequence` (≤ `max_stops`, ≥ `min_compounds_used` distinct compounds,
  per-compound set limits). Top `top_k` plans by total time are returned.

Because the DP is exact per sequence and the sequence space is tiny (3 compounds, ≤ 4 stints), the result is the
global optimum *under the model and assumptions* – not a heuristic. Typical latency: ≈ 1 s per request.

## Pit windows

`pit_windows` reports, per stop, the laps whose total time is within `window_tolerance_ms` (default 1.5 s) of the
optimum with the other stops re-optimised. It tells you how flexible the call is, not just the single best lap.

## Explanation and infeasibility

Each recommendation carries a plain-language explanation computed from the actual numbers (total time, stop count and pit-loss share, best alternative with one fewer/more stop, margin to the runner-up, pit windows). `InfeasibleError` (optimiser) and `feasibility_issues` (simulator plans) give human-readable reasons when no plan exists, and the API answers 422.

## What is real, data-derived or assumed

| Item | Status |
|---|---|
| Two different dry compounds required | **Real regulation**, editable |
| Pit loss | **Data-derived** (median recorded stop cost for the circuit) or user override |
| Lap-time vs tyre-age shape | **Learned** from historical laps (age = laps since last stop) |
| Compound offsets, degradation multipliers, max stint | **Assumption** (no compound data) |
| Stop-count cap, minimum stint, traffic/in/out-lap penalties, tyre-set limits | **Assumption** |

Every response lists the assumptions used so the UI can label them. The output is a *model-based recommendation*, not
what a team would do: no tyre-set inventory, traffic, fuel load, undercut/overcut interaction or live state is modelled.
