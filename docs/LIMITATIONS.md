# Limitations (read before trusting any number)

1. **No tyre compound data.** The only accessible source (Jolpica-F1) has none. The pace model sees lap, tyre age
   (laps since last stop, a lower bound), circuit, driver/team context and grid only. Compound pace offsets,
   degradation multipliers and stint limits in the optimizer are **editable assumptions**, not learned.
2. **No weather, track temperature or session data.** Only the Race session exists. Weather in the simulator is a
   hypothetical user scenario. Wet or interrupted races are only *detected* indirectly (abnormal-pace flag).
3. **Safety car / VSC / red flags are inferred** from field-median lap times, not from official race-control messages.
4. **Optimizer is single-car.** No traffic, undercut/overcut, track position, fuel, DRS or rival reaction. It is a
   model-based recommendation, not a team call, and has not been validated against real strategy outcomes.
5. **Pit loss** is estimated from recorded stop durations plus lap-time effects; stops absent from the source are not seen.
6. **Prediction accuracy is limited and reported honestly** (see MODEL_EVALUATION). Unseen circuits fall back to a
   global baseline and are flagged in the API (`unseen_circuit`). Few seasons ⇒ few circuits with ≥3 races.
7. **Monte Carlo is a sensitivity tool.** Noise terms are Gaussian; SC probability and timing are assumptions.
8. **Scale.** Single-process API, in-memory LRU caches, no auth or rate limiting. Fine for a portfolio/demo deployment, not production.
9. **Source availability.** Jolpica is community-run and rate-limited (observed HTTP 429); full-season ingestion takes
   many minutes and may need to be re-run (idempotent; raw responses are cached).
10. **Docker/PostgreSQL** paths are exercised in CI; see the acceptance report for what was verified locally.
