"""Monte Carlo race simulation.

Per simulation: deterministic strategy lap times (from the pace table) + stochastic terms:
  * lap noise      ~ N(0, lap_sigma)           lap_sigma derived from the model's p10-p90 interval
  * stint offset   ~ N(0, stint_sigma)         persistent per-stint pace variation
  * pit loss       ~ N(pit_loss, pit_std)      truncated at 50 % of the mean
  * safety car     random/fixed period; laps slowed, stops inside it pay a discounted pit loss
  * weather        hypothetical lap-time multipliers over user-chosen lap windows
All strategies share the SAME random draws (common random numbers), so differences between strategies are
not Monte Carlo noise and win probabilities are directly comparable. Fully reproducible via ``seed``.
"""
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.strategy.config import SafetyCarScenario, Strategy, StrategyConfig, WeatherWindow
from app.strategy.engine import adjusted_lap_times

MAX_SIMS = 20_000


@dataclass
class Draws:
    lap_noise: np.ndarray       # (S, N)
    stint_noise: np.ndarray     # (S, 5)
    pit_z: np.ndarray           # (S, 5)
    sc_active: np.ndarray       # (S,) bool
    sc_start: np.ndarray        # (S,) int lap
    sc_len: np.ndarray          # (S,) int


def make_draws(n_sims: int, n_laps: int, sc: SafetyCarScenario, lap_sigma: float, stint_sigma: float, seed: int) -> Draws:
    rng = np.random.default_rng(seed)
    if sc.mode == "none":
        active, start = np.zeros(n_sims, bool), np.zeros(n_sims, int)
        rng.random(n_sims)
    elif sc.mode == "fixed":
        if sc.start_lap is None:
            raise ValueError("safety car mode 'fixed' requires start_lap")
        active, start = np.ones(n_sims, bool), np.full(n_sims, sc.start_lap)
    else:
        active = rng.random(n_sims) < sc.probability
        start = rng.integers(2, max(3, n_laps - sc.duration_laps), n_sims)
    return Draws(rng.normal(0, lap_sigma, (n_sims, n_laps)), rng.normal(0, stint_sigma, (n_sims, 5)),
                 rng.standard_normal((n_sims, 5)), active, start, np.full(n_sims, sc.duration_laps))


def simulate_strategy(pace: np.ndarray, strategy: Strategy, cfg: StrategyConfig, sc: SafetyCarScenario,
                      weather: list[WeatherWindow], d: Draws) -> np.ndarray:
    """Returns total race time (ms) per simulation, shape (S,)."""
    n = cfg.total_laps
    pace = pace[:n, :n]
    base = np.zeros(n)
    stint_idx = np.zeros(n, dtype=int)
    lap = 0
    for j, st in enumerate(strategy.stints):
        p = cfg.compounds[st.compound]
        adj = adjusted_lap_times(pace, p.offset_ms, p.degradation_multiplier)
        for age in range(st.laps):
            base[lap] = adj[lap, age]
            stint_idx[lap] = min(j, 4)
            lap += 1
    if lap != n:
        raise ValueError(f"strategy covers {lap} laps but race has {n}")
    for w in weather:
        base[w.start_lap - 1 : min(w.end_lap, n)] *= 1 + w.slowdown_pct / 100

    times = base[None, :] + d.lap_noise + d.stint_noise[:, stint_idx]
    laps_idx = np.arange(1, n + 1)[None, :]
    in_sc = d.sc_active[:, None] & (laps_idx >= d.sc_start[:, None]) & (laps_idx < (d.sc_start + d.sc_len)[:, None])
    slow = 1 + (sc.slowdown_factor - 1) * (0.5 if sc.vsc else 1.0)
    times = np.where(in_sc, times * slow, times)

    total = times.sum(axis=1)
    discount = 1 - (1 - sc.pit_loss_factor) * (0.5 if sc.vsc else 1.0)
    for i, pit_lap in enumerate(strategy.pit_laps):
        loss = np.maximum(cfg.pit_loss_ms + cfg.pit_loss_std_ms * d.pit_z[:, min(i, 4)], 0.5 * cfg.pit_loss_ms)
        loss = loss + cfg.outlap_penalty_ms + cfg.inlap_penalty_ms + cfg.traffic_penalty_ms * cfg.traffic_laps
        total += np.where(in_sc[:, pit_lap - 1], loss * discount, loss)
    return total


def summarise(totals: np.ndarray) -> dict[str, float]:
    p = np.percentile(totals, [5, 25, 50, 75, 95])
    return {"mean_ms": float(totals.mean()), "median_ms": float(p[2]), "std_ms": float(totals.std()),
            "p5_ms": float(p[0]), "p25_ms": float(p[1]), "p75_ms": float(p[3]), "p95_ms": float(p[4])}


def run_comparison(pace: np.ndarray, strategies: list[Strategy], cfg: StrategyConfig, sc: SafetyCarScenario,
                   weather: list[WeatherWindow], n_sims: int, seed: int, lap_sigma_ms: float, stint_sigma_ms: float = 150.0) -> dict[str, Any]:
    if not 1 <= n_sims <= MAX_SIMS:
        raise ValueError(f"n_sims must be within 1..{MAX_SIMS}")
    d = make_draws(n_sims, cfg.total_laps, sc, lap_sigma_ms, stint_sigma_ms, seed)
    totals = np.vstack([simulate_strategy(pace, s, cfg, sc, weather, d) for s in strategies])
    winners = totals.argmin(axis=0)
    out = []
    lo, hi = float(totals.min()), float(totals.max())
    edges = np.linspace(lo, hi, 31)
    for i, s in enumerate(strategies):
        hist, _ = np.histogram(totals[i], bins=edges)
        out.append({"label": s.label, "stints": [x.model_dump() for x in s.stints], "pit_laps": s.pit_laps,
                    **summarise(totals[i]), "win_probability": float((winners == i).mean()),
                    "histogram": {"edges_ms": edges.tolist(), "counts": hist.tolist()}})
    return {"n_sims": n_sims, "seed": seed, "sc_hit_rate": float(d.sc_active.mean()), "strategies": out}
