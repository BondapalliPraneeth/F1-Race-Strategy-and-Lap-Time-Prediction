"""Pydantic request schemas (inputs are validated at the API boundary)."""
from pydantic import BaseModel, Field, model_validator

from app.strategy.config import CompoundProfile, SafetyCarScenario, StintPlan, WeatherWindow

COMPOUNDS = {"SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"}


class PredictRequest(BaseModel):
    race_id: int = Field(ge=1)
    driver_id: str = Field(min_length=1, max_length=64)
    lap_number: int = Field(ge=1, le=100)
    tyre_age: int = Field(ge=1, le=100)
    compound: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "PredictRequest":
        if self.tyre_age > self.lap_number:
            raise ValueError("tyre_age cannot exceed lap_number")
        if self.compound is not None and self.compound.upper() not in COMPOUNDS:
            raise ValueError(f"compound must be one of {sorted(COMPOUNDS)}")
        return self


class StrategyParams(BaseModel):
    """User-editable strategy parameters; omitted fields take data-derived or documented defaults."""
    pit_loss_ms: float | None = Field(None, ge=5_000, le=60_000)
    pit_loss_std_ms: float | None = Field(None, ge=0, le=15_000)
    compounds: dict[str, CompoundProfile] | None = None
    available_sets: dict[str, int | None] = Field(default_factory=dict)
    min_compounds_used: int = Field(2, ge=1, le=3)
    max_stops: int = Field(3, ge=0, le=4)
    min_stint_laps: int = Field(5, ge=1, le=30)
    inlap_penalty_ms: float = Field(0, ge=0, le=10_000)
    outlap_penalty_ms: float = Field(0, ge=0, le=10_000)
    traffic_penalty_ms: float = Field(0, ge=0, le=5_000)
    traffic_laps: int = Field(0, ge=0, le=10)
    window_tolerance_ms: float = Field(1_500, ge=0, le=20_000)
    top_k: int = Field(8, ge=1, le=30)
    total_laps: int | None = Field(None, ge=10, le=100)


class OptimizeRequest(BaseModel):
    race_id: int = Field(ge=1)
    driver_id: str = Field(min_length=1, max_length=64)
    params: StrategyParams = Field(default_factory=lambda: StrategyParams())


class SimulateRequest(BaseModel):
    race_id: int = Field(ge=1)
    driver_id: str = Field(min_length=1, max_length=64)
    params: StrategyParams = Field(default_factory=lambda: StrategyParams())
    strategies: list[list[StintPlan]] = Field(min_length=1, max_length=8)
    safety_car: SafetyCarScenario = Field(default_factory=lambda: SafetyCarScenario())
    weather: list[WeatherWindow] = Field(default_factory=list, max_length=5)
    n_sims: int = Field(2000, ge=1, le=20_000)
    seed: int = Field(42, ge=0)
