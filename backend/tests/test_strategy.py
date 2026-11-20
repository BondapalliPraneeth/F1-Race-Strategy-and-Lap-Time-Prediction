"""Strategy optimizer and Monte Carlo tests on a controlled analytic pace table (test-only)."""
from itertools import product

import numpy as np
import pytest

from app.strategy import engine as E
from app.strategy import simulate as S
from app.strategy.config import CompoundProfile, SafetyCarScenario, StintPlan, Strategy, StrategyConfig, WeatherWindow


def pace_table(n: int, base: float = 90_000, deg: float = 60, fuel: float = 10) -> np.ndarray:
    p = np.full((n, n), np.nan)
    for lap in range(1, n + 1):
        for age in range(1, lap + 1):
            p[lap - 1, age - 1] = base - fuel * lap + deg * age
    # ages beyond the lap number are impossible; keep finite so cumulative sums stay valid
    for lap in range(1, n + 1):
        for age in range(lap + 1, n + 1):
            p[lap - 1, age - 1] = base - fuel * lap + deg * age
    return p


def cfg(n: int = 24, **kw) -> StrategyConfig:  # type: ignore[no-untyped-def]
    comps = {"S": CompoundProfile(offset_ms=-500, degradation_multiplier=2.0, max_stint_laps=12),
             "H": CompoundProfile(offset_ms=300, degradation_multiplier=0.7, max_stint_laps=30)}
    base = dict(total_laps=n, pit_loss_ms=20_000, compounds=comps, max_stops=2, min_stint_laps=3)
    base.update(kw)
    return StrategyConfig(**base)


def brute_force(pace: np.ndarray, c: StrategyConfig) -> float:
    costs = E._tables(pace[: c.total_laps, : c.total_laps], c)
    best, n = float("inf"), c.total_laps
    names = list(c.compounds)
    for stops in range(c.max_stops + 1):
        for seq in product(names, repeat=stops + 1):
            if not E._valid_sequence(seq, c):
                continue
            for cuts in product(range(1, n), repeat=stops):
                if list(cuts) != sorted(set(cuts)):
                    continue
                b = [0, *cuts, n]
                st = Strategy(stints=[StintPlan(compound=s, laps=b[i + 1] - b[i]) for i, s in enumerate(seq)])
                if E.feasibility_issues(st, c):
                    continue
                best = min(best, E.evaluate(st, costs, c))
    return best


def test_dp_matches_brute_force() -> None:
    c = cfg(24)
    p = pace_table(24)
    ranked = E.optimise(p, c)
    assert ranked[0].total_ms == pytest.approx(brute_force(p, c), rel=1e-9)


def test_results_sorted_feasible_and_cover_race() -> None:
    c = cfg(24)
    ranked = E.optimise(pace_table(24), c)
    assert [r.total_ms for r in ranked] == sorted(r.total_ms for r in ranked)
    for r in ranked:
        assert E.feasibility_issues(r.strategy, c) == []
        assert sum(s.laps for s in r.strategy.stints) == 24
        assert len({s.compound for s in r.strategy.stints}) >= 2


def test_higher_pit_loss_means_fewer_stops_and_more_degradation_more_stops() -> None:
    n = 40
    cheap = E.optimise(pace_table(n, deg=150), cfg(n, pit_loss_ms=15_000, max_stops=3))[0]
    costly = E.optimise(pace_table(n, deg=150), cfg(n, pit_loss_ms=50_000, max_stops=3))[0]
    assert len(costly.strategy.stints) <= len(cheap.strategy.stints)
    low_deg = E.optimise(pace_table(n, deg=10), cfg(n, max_stops=3))[0]
    high_deg = E.optimise(pace_table(n, deg=250), cfg(n, max_stops=3))[0]
    assert len(high_deg.strategy.stints) >= len(low_deg.strategy.stints)


def test_constraints_enforced() -> None:
    c = cfg(24, available_sets={"S": 0})
    assert all(s.compound != "S" for r in E.optimise(pace_table(24), cfg(24, min_compounds_used=1, available_sets={"S": 0})) for s in r.strategy.stints)
    with pytest.raises(E.InfeasibleError):
        E.optimise(pace_table(24), c)  # needs 2 compounds but S unavailable and only H left
    bad = Strategy(stints=[StintPlan(compound="H", laps=24)])
    assert any("different compounds" in i for i in E.feasibility_issues(bad, cfg(24)))
    long = Strategy(stints=[StintPlan(compound="S", laps=20), StintPlan(compound="H", laps=4)])
    assert any("exceeds its max" in i for i in E.feasibility_issues(long, cfg(24)))


def test_config_validation() -> None:
    with pytest.raises(ValueError):
        StrategyConfig(total_laps=5, pit_loss_ms=20_000)
    with pytest.raises(ValueError):
        StrategyConfig(total_laps=50, pit_loss_ms=100)
    with pytest.raises(ValueError):
        StrategyConfig(total_laps=50, pit_loss_ms=20_000, min_compounds_used=3, compounds={"S": CompoundProfile()})


def test_windows_contain_optimum_and_explanation_uses_numbers() -> None:
    c = cfg(30, max_stops=2)
    ranked = E.optimise(pace_table(30), c)
    for w in ranked[0].pit_windows:
        assert w["earliest"] <= w["optimal_lap"] <= w["latest"]
    text = " ".join(E.explain(ranked, c))
    assert ranked[0].strategy.label in text and "assumptions" in text


def test_pit_laps_property() -> None:
    s = Strategy(stints=[StintPlan(compound="S", laps=10), StintPlan(compound="H", laps=14)])
    assert s.pit_laps == [10] and s.label == "S10 → H14"


# ---------------------------------------------------------------- Monte Carlo
def setup_sim(n: int = 24):  # type: ignore[no-untyped-def]
    c = cfg(n)
    p = pace_table(n)
    best = E.optimise(p, c)[0]
    return c, p, best


def test_zero_noise_equals_deterministic_total() -> None:
    c, p, best = setup_sim()
    c = c.model_copy(update={"pit_loss_std_ms": 0})
    res = S.run_comparison(p, [best.strategy], c, SafetyCarScenario(), [], 50, 1, lap_sigma_ms=0, stint_sigma_ms=0)
    assert res["strategies"][0]["mean_ms"] == pytest.approx(best.total_ms)
    assert res["strategies"][0]["std_ms"] == pytest.approx(0, abs=1e-6)


def test_reproducible_with_seed_and_different_across_seeds() -> None:
    c, p, best = setup_sim()
    a = S.run_comparison(p, [best.strategy], c, SafetyCarScenario(), [], 500, 7, 400)
    b = S.run_comparison(p, [best.strategy], c, SafetyCarScenario(), [], 500, 7, 400)
    d = S.run_comparison(p, [best.strategy], c, SafetyCarScenario(), [], 500, 8, 400)
    assert a == b and a["strategies"][0]["mean_ms"] != d["strategies"][0]["mean_ms"]


def test_percentiles_ordered_and_win_probabilities_sum_to_one() -> None:
    c, p, _ = setup_sim()
    ranked = E.optimise(p, c)
    res = S.run_comparison(p, [r.strategy for r in ranked[:4]], c, SafetyCarScenario(), [], 2000, 3, 400)
    assert sum(s["win_probability"] for s in res["strategies"]) == pytest.approx(1.0)
    for s in res["strategies"]:
        assert s["p5_ms"] <= s["p25_ms"] <= s["median_ms"] <= s["p75_ms"] <= s["p95_ms"]
        assert sum(s["histogram"]["counts"]) == 2000


def test_best_deterministic_strategy_wins_most_often() -> None:
    c, p, _ = setup_sim()
    ranked = E.optimise(p, c)
    res = S.run_comparison(p, [r.strategy for r in ranked[:3]], c, SafetyCarScenario(), [], 3000, 3, 300)
    assert res["strategies"][0]["win_probability"] == max(s["win_probability"] for s in res["strategies"])


def test_safety_car_and_weather_effects() -> None:
    c, p, best = setup_sim()
    c = c.model_copy(update={"pit_loss_std_ms": 0})
    run = lambda sc, w=(): S.run_comparison(p, [best.strategy], c, sc, list(w), 200, 1, 0, 0)["strategies"][0]["mean_ms"]  # noqa: E731
    green = run(SafetyCarScenario())
    sc_mid = run(SafetyCarScenario(mode="fixed", start_lap=3, duration_laps=3))
    assert sc_mid > green - 1  # slow laps cost time (unless a stop is discounted)
    pit = best.strategy.pit_laps[0]
    sc_pit = SafetyCarScenario(mode="fixed", start_lap=pit, duration_laps=3, slowdown_factor=1.05, pit_loss_factor=0.3)
    assert run(sc_pit) < run(SafetyCarScenario(mode="fixed", start_lap=pit, duration_laps=3, slowdown_factor=1.05, pit_loss_factor=1.0))
    assert run(SafetyCarScenario(), [WeatherWindow(start_lap=5, end_lap=10, slowdown_pct=10)]) > green


def test_invalid_simulation_inputs() -> None:
    c, p, best = setup_sim()
    with pytest.raises(ValueError):
        S.run_comparison(p, [best.strategy], c, SafetyCarScenario(), [], 0, 1, 100)
    with pytest.raises(ValueError):
        S.run_comparison(p, [best.strategy], c, SafetyCarScenario(mode="fixed"), [], 10, 1, 100)
    with pytest.raises(ValueError):
        S.run_comparison(p, [Strategy(stints=[StintPlan(compound="H", laps=5)])], c, SafetyCarScenario(), [], 10, 1, 100)
