"""Strategy configuration (validated with Pydantic).

Every parameter is either DATA-DERIVED (pit loss, lap-time noise) or a CONFIGURABLE ASSUMPTION
(compound profiles, safety-car behaviour, traffic). Assumptions are tagged so the API and UI can label them.
The only genuine regulation encoded is ``min_compounds_used`` (dry races require two different dry
compounds); the stop-count limits, stint limits and tyre-set counts are simplified, user-editable assumptions.
"""
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class CompoundProfile(BaseModel):
    offset_ms: float = Field(0, ge=-5000, le=5000, description="Per-lap pace offset vs the model's mean tyre (ASSUMPTION)")
    degradation_multiplier: float = Field(1.0, ge=0.2, le=4.0, description="Scales the learned age effect (ASSUMPTION)")
    max_stint_laps: int = Field(40, ge=5, le=100)


# Illustrative defaults. The ingested data source publishes NO compound information, so these are
# explicit hypotheses, shown as such in the UI, and are meant to be edited.
DEFAULT_COMPOUNDS: dict[str, CompoundProfile] = {
    "SOFT": CompoundProfile(offset_ms=-600, degradation_multiplier=1.8, max_stint_laps=20),
    "MEDIUM": CompoundProfile(offset_ms=0, degradation_multiplier=1.0, max_stint_laps=32),
    "HARD": CompoundProfile(offset_ms=450, degradation_multiplier=0.6, max_stint_laps=45),
}


class StrategyConfig(BaseModel):
    total_laps: int = Field(ge=10, le=100)
    pit_loss_ms: float = Field(ge=5_000, le=60_000, description="Total time lost by one stop vs staying out")
    pit_loss_std_ms: float = Field(1_200, ge=0, le=15_000)
    compounds: dict[str, CompoundProfile] = Field(default_factory=lambda: {k: v.model_copy() for k, v in DEFAULT_COMPOUNDS.items()})
    available_sets: dict[str, int | None] = Field(default_factory=dict, description="Max stints per compound; missing/None = unlimited")
    min_compounds_used: int = Field(2, ge=1, le=3, description="FIA dry-race rule is 2; configurable for wet scenarios")
    max_stops: int = Field(3, ge=0, le=4)
    min_stint_laps: int = Field(5, ge=1, le=30)
    inlap_penalty_ms: float = Field(0, ge=0, le=10_000, description="Extra in-lap loss beyond pit_loss (ASSUMPTION)")
    outlap_penalty_ms: float = Field(0, ge=0, le=10_000, description="Extra out-lap loss beyond pit_loss (ASSUMPTION)")
    traffic_penalty_ms: float = Field(0, ge=0, le=5_000, description="Per-lap traffic cost after a stop (ASSUMPTION)")
    traffic_laps: int = Field(0, ge=0, le=10)
    window_tolerance_ms: float = Field(1_500, ge=0, description="Pit window = laps within this of the optimum")
    top_k: int = Field(8, ge=1, le=30)

    @field_validator("compounds")
    @classmethod
    def _non_empty(cls, v: dict[str, CompoundProfile]) -> dict[str, CompoundProfile]:
        if not v:
            raise ValueError("at least one compound is required")
        return v

    @model_validator(mode="after")
    def _feasible(self) -> "StrategyConfig":
        if self.min_compounds_used > len(self.compounds):
            raise ValueError("min_compounds_used exceeds the number of compounds configured")
        if self.min_stint_laps * 1 > self.total_laps:
            raise ValueError("min_stint_laps exceeds race distance")
        return self


class SafetyCarScenario(BaseModel):
    mode: Literal["none", "random", "fixed"] = "none"
    probability: float = Field(0.5, ge=0, le=1, description="mode=random: chance of one SC period in the race")
    start_lap: int | None = Field(None, ge=2, description="mode=fixed")
    duration_laps: int = Field(4, ge=1, le=15)
    slowdown_factor: float = Field(1.45, ge=1.05, le=3.0, description="SC lap time vs racing lap (ASSUMPTION)")
    pit_loss_factor: float = Field(0.55, ge=0.1, le=1.0, description="Share of pit loss paid when stopping under SC (ASSUMPTION)")
    vsc: bool = Field(False, description="Virtual SC: milder slowdown and smaller pit discount")


class WeatherWindow(BaseModel):
    start_lap: int = Field(ge=1)
    end_lap: int = Field(ge=1)
    slowdown_pct: float = Field(8.0, ge=0, le=60, description="HYPOTHETICAL lap-time increase (e.g. rain)")

    @model_validator(mode="after")
    def _order(self) -> "WeatherWindow":
        if self.end_lap < self.start_lap:
            raise ValueError("end_lap must be >= start_lap")
        return self


class StintPlan(BaseModel):
    compound: str
    laps: int = Field(ge=1)


class Strategy(BaseModel):
    stints: list[StintPlan]

    @property
    def pit_laps(self) -> list[int]:
        out, acc = [], 0
        for s in self.stints[:-1]:
            acc += s.laps
            out.append(acc)
        return out

    @property
    def label(self) -> str:
        return " → ".join(f"{s.compound[0]}{s.laps}" for s in self.stints)
