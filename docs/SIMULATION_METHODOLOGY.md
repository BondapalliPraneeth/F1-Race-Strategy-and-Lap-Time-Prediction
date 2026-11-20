# Simulation Methodology (Workflow E)

Code: `backend/app/strategy/simulate.py`. All simulation output is **simulated / hypothetical** and labelled so in the UI.

## Model

For each of `n_sims` (≤ 20,000) runs and each strategy:

```
total = Σ_laps [ base(lap) + lap_noise + stint_noise(stint) ] × SC/VSC factor  +  Σ_stops pit_loss
```

| Term | Distribution / rule | Origin |
|---|---|---|
| `base(lap)` | strategy lap times from the pace table, compound profile, and weather multiplier | model + assumption |
| `lap_noise` | N(0, σ) with σ derived from the model's p10–p90 interval | data-derived |
| `stint_noise` | N(0, 150 ms) persistent per stint | assumption |
| pit loss | N(μ, σ) truncated at 0.5 μ; μ from recorded stops (or override) | data-derived |
| safety car | `none`, `fixed` (start lap given) or `random` (probability, start uniform, duration) | scenario assumption |
| VSC | half the SC slowdown and half the pit-loss discount | assumption |
| SC pit discount | stops made under SC pay `pit_loss_factor` × loss | assumption |
| weather | user-defined lap windows with a % slowdown | **hypothetical** scenario |

## Variance-reduction and reproducibility

* **Common random numbers**: all strategies share the same draw matrix, so differences are not Monte Carlo noise and
  `win_probability` (share of runs in which a strategy is fastest) is directly comparable.
* Fully seeded (`seed` in request and response): same request → identical output (tested).
* Output: mean, median, std, p5/p25/p75/p95, win probability, 30-bin histogram, SC hit rate.

## Interpreting results

A strategy with a lower mean but a fatter right tail can be *riskier*; compare p95 and win probability, not only the mean.
Safety-car timing is the dominant uncertainty and is not learned from data (the source has no SC flags); treat the SC
parameters as sensitivity knobs. Validation of the simulator against real race outcomes is **not** performed – see LIMITATIONS.
