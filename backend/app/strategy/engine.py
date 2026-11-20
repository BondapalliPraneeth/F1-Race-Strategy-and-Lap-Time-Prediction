"""Deterministic pit-stop strategy optimizer.

Input: a pace table ``pace[lap-1, age-1]`` (predicted ms for a given race lap on tyres of a given age)
plus a StrategyConfig. For every feasible compound sequence the best pit laps are found EXACTLY with
dynamic programming over stint boundaries; sequences are then ranked by predicted total race time.
"""
from dataclasses import dataclass
from itertools import product

import numpy as np

from app.strategy.config import Strategy, StrategyConfig, StintPlan

INF = float("inf")


class InfeasibleError(ValueError):
    """No strategy satisfies the configured constraints."""


@dataclass
class Ranked:
    strategy: Strategy
    total_ms: float
    pit_windows: list[dict[str, int]]


def adjusted_lap_times(pace: np.ndarray, profile_offset: float, mult: float) -> np.ndarray:
    """Compound-adjusted pace table. age effect = pace[l, age] - pace[l, 1]; scaled by ``mult``."""
    ref = pace[:, :1]
    return pace + profile_offset + (mult - 1.0) * (pace - ref)


def stint_cost_table(adj: np.ndarray) -> np.ndarray:
    """cost[s, e] (1-based inclusive laps s..e) = sum of lap times if a fresh set is fitted for lap s."""
    n = adj.shape[0]
    cost = np.full((n + 2, n + 2), INF)
    for s in range(1, n + 1):
        ages = np.arange(0, n - s + 1)
        laps = np.arange(s - 1, n)
        cs = np.cumsum(adj[laps, ages])
        cost[s, s : n + 1] = cs
    return cost


PaceInput = np.ndarray | dict[str, np.ndarray]


def pace_for(pace: PaceInput, compound: str) -> np.ndarray:
    """A single pace table is shared by all compounds (profiles then supply the differences); a dict holds one
    model-predicted table per compound (used when the model learned the compound effect from real tyre data)."""
    return pace[compound] if isinstance(pace, dict) else pace


def _tables(pace: PaceInput, cfg: StrategyConfig) -> dict[str, np.ndarray]:
    n = cfg.total_laps
    return {c: stint_cost_table(adjusted_lap_times(pace_for(pace, c)[:n, :n], p.offset_ms, p.degradation_multiplier))
            for c, p in cfg.compounds.items()}


def _extra(cfg: StrategyConfig, j: int, k: int) -> float:
    """Per-stint extras: stop cost paid when STARTING stint j>0, in-lap penalty when ending stint j<k."""
    x = 0.0
    if j > 0:
        x += cfg.pit_loss_ms + cfg.outlap_penalty_ms + cfg.traffic_penalty_ms * cfg.traffic_laps
    if j < k:
        x += cfg.inlap_penalty_ms
    return x


def _optimise_sequence(seq: tuple[str, ...], costs: dict[str, np.ndarray], cfg: StrategyConfig) -> tuple[float, list[int]] | None:
    n, k = cfg.total_laps, len(seq) - 1
    best = np.full((k + 1, n + 1), INF)  # best[j, e]: stints 0..j cover laps 1..e
    arg = np.zeros((k + 1, n + 1), dtype=int)
    for j, comp in enumerate(seq):
        cost, maxlen = costs[comp], cfg.compounds[comp].max_stint_laps
        extra = _extra(cfg, j, k)
        for e in range(1, n + 1):
            lo = 1 if j == 0 else 2
            for s in range(max(lo, e - maxlen + 1), e - cfg.min_stint_laps + 2):
                prev = 0.0 if j == 0 else best[j - 1, s - 1]
                if j == 0 and s != 1:
                    continue
                v = prev + cost[s, e] + extra
                if v < best[j, e]:
                    best[j, e], arg[j, e] = v, s
    if not np.isfinite(best[k, n]):
        return None
    bounds, e = [], n
    for j in range(k, -1, -1):
        s = int(arg[j, e])
        bounds.append((s, e))
        e = s - 1
    bounds.reverse()
    return float(best[k, n]), [b[1] for b in bounds[:-1]]


def evaluate(strategy: Strategy, costs: dict[str, np.ndarray], cfg: StrategyConfig) -> float:
    """Deterministic total time of an explicit strategy (used for what-if and windows)."""
    k, s, total = len(strategy.stints) - 1, 1, 0.0
    for j, st in enumerate(strategy.stints):
        e = s + st.laps - 1
        if e > cfg.total_laps:
            return INF
        total += costs[st.compound][s, e] + _extra(cfg, j, k)
        s = e + 1
    return total if s - 1 == cfg.total_laps else INF


def _valid_sequence(seq: tuple[str, ...], cfg: StrategyConfig) -> bool:
    if len(set(seq)) < cfg.min_compounds_used:
        return False
    for c, cap in cfg.available_sets.items():
        if cap is not None and seq.count(c) > cap:
            return False
    return True


def feasibility_issues(strategy: Strategy, cfg: StrategyConfig) -> list[str]:
    issues = []
    if sum(s.laps for s in strategy.stints) != cfg.total_laps:
        issues.append(f"stints cover {sum(s.laps for s in strategy.stints)} laps, race is {cfg.total_laps}")
    seq = tuple(s.compound for s in strategy.stints)
    for c in seq:
        if c not in cfg.compounds:
            issues.append(f"unknown compound {c}")
    if issues:
        return issues
    if len(set(seq)) < cfg.min_compounds_used:
        issues.append(f"must use at least {cfg.min_compounds_used} different compounds")
    for s in strategy.stints:
        if s.laps < cfg.min_stint_laps:
            issues.append(f"{s.compound} stint of {s.laps} laps is below the minimum {cfg.min_stint_laps}")
        if s.laps > cfg.compounds[s.compound].max_stint_laps:
            issues.append(f"{s.compound} stint of {s.laps} laps exceeds its max {cfg.compounds[s.compound].max_stint_laps}")
    for c, cap in cfg.available_sets.items():
        if cap is not None and seq.count(c) > cap:
            issues.append(f"only {cap} set(s) of {c} available")
    if len(seq) - 1 > cfg.max_stops:
        issues.append(f"{len(seq) - 1} stops exceeds max_stops={cfg.max_stops}")
    return issues


def pit_windows(strategy: Strategy, costs: dict[str, np.ndarray], cfg: StrategyConfig, optimum: float) -> list[dict[str, int]]:
    """For each stop, the range of laps that stay within tolerance of the optimum with other stops fixed."""
    windows = []
    laps = [s.laps for s in strategy.stints]
    for i in range(len(laps) - 1):
        ok = []
        for shift in range(-15, 16):
            a, b = laps[i] + shift, laps[i + 1] - shift
            if a < 1 or b < 1:
                continue
            trial = Strategy(stints=[StintPlan(compound=s.compound, laps=a if m == i else b if m == i + 1 else s.laps)
                                     for m, s in enumerate(strategy.stints)])
            if feasibility_issues(trial, cfg):
                continue
            if evaluate(trial, costs, cfg) - optimum <= cfg.window_tolerance_ms:
                ok.append(sum(laps[: i + 1]) + shift)
        optimum_lap = sum(laps[: i + 1])
        windows.append({"stop": i + 1, "optimal_lap": optimum_lap, "earliest": min(ok or [optimum_lap]), "latest": max(ok or [optimum_lap])})
    return windows


def optimise(pace: PaceInput, cfg: StrategyConfig) -> list[Ranked]:
    if any(t.shape[0] < cfg.total_laps for t in (pace.values() if isinstance(pace, dict) else [pace])):
        raise ValueError("pace table shorter than race distance")
    costs = _tables(pace, cfg)
    names = list(cfg.compounds)
    out: list[Ranked] = []
    for stops in range(cfg.max_stops + 1):
        for seq in product(names, repeat=stops + 1):
            if not _valid_sequence(seq, cfg):
                continue
            res = _optimise_sequence(seq, costs, cfg)
            if res is None:
                continue
            total, pits = res
            bounds = [0, *pits, cfg.total_laps]
            strat = Strategy(stints=[StintPlan(compound=c, laps=bounds[i + 1] - bounds[i]) for i, c in enumerate(seq)])
            out.append(Ranked(strat, total, []))
    if not out:
        raise InfeasibleError("no feasible strategy under the configured constraints (check stint limits and compound rules)")
    out.sort(key=lambda r: r.total_ms)
    out = out[: cfg.top_k]
    out[0].pit_windows = pit_windows(out[0].strategy, costs, cfg, out[0].total_ms)
    return out


def explain(ranked: list[Ranked], cfg: StrategyConfig, note: str = "Compound pace and degradation multipliers are configurable assumptions, not learned from data.") -> list[str]:
    """Plain-language reasons, computed from the actual numbers (no canned text about results)."""
    best = ranked[0]
    lines = [f"Best strategy {best.strategy.label} has the lowest predicted race time of {len(ranked)} ranked candidates "
             f"({best.total_ms / 1000:.1f} s)."]
    n_stops = len(best.strategy.stints) - 1
    lines.append(f"It uses {n_stops} stop(s) at a configured pit loss of {cfg.pit_loss_ms / 1000:.1f} s each "
                 f"({n_stops * cfg.pit_loss_ms / 1000:.1f} s total).")
    for other_stops in (n_stops - 1, n_stops + 1):
        alt = next((r for r in ranked if len(r.strategy.stints) - 1 == other_stops), None)
        if alt:
            d = (alt.total_ms - best.total_ms) / 1000
            lines.append(f"Best {other_stops}-stop alternative {alt.strategy.label} is {d:.1f} s slower.")
    if len(ranked) > 1:
        lines.append(f"Margin to runner-up {ranked[1].strategy.label}: {(ranked[1].total_ms - best.total_ms) / 1000:.2f} s.")
    for w in best.pit_windows:
        lines.append(f"Stop {w['stop']}: optimum lap {w['optimal_lap']}; within {cfg.window_tolerance_ms / 1000:.1f} s of optimum "
                     f"for laps {w['earliest']}–{w['latest']}.")
    lines.append(note)
    return lines
