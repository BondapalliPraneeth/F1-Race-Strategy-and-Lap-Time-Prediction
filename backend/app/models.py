"""ORM models. See DATABASE_SCHEMA.md for the rationale behind each table and index."""
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

PK = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    pass


class Circuit(Base):
    __tablename__ = "circuits"
    circuit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    locality: Mapped[str | None] = mapped_column(String(128))
    country: Mapped[str | None] = mapped_column(String(64))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)


class Driver(Base):
    __tablename__ = "drivers"
    driver_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str | None] = mapped_column(String(8))
    given_name: Mapped[str] = mapped_column(String(64))
    family_name: Mapped[str] = mapped_column(String(64))
    nationality: Mapped[str | None] = mapped_column(String(64))


class Race(Base):
    __tablename__ = "races"
    __table_args__ = (
        UniqueConstraint("season", "round", name="uq_race_season_round"),
        Index("ix_races_circuit", "circuit_id"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    season: Mapped[int] = mapped_column(Integer, index=True)
    round: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(128))
    circuit_id: Mapped[str] = mapped_column(ForeignKey("circuits.circuit_id"))
    race_date: Mapped[date | None] = mapped_column(Date)
    total_laps: Mapped[int | None] = mapped_column(Integer)
    has_laps: Mapped[bool] = mapped_column(Boolean, default=False)
    circuit: Mapped[Circuit] = relationship()


class Result(Base):
    __tablename__ = "results"
    __table_args__ = (UniqueConstraint("race_id", "driver_id", name="uq_result_race_driver"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    race_id: Mapped[int] = mapped_column(ForeignKey("races.id", ondelete="CASCADE"), index=True)
    driver_id: Mapped[str] = mapped_column(ForeignKey("drivers.driver_id"))
    constructor_id: Mapped[str | None] = mapped_column(String(64))
    grid: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String(64))
    laps_completed: Mapped[int | None] = mapped_column(Integer)
    driver: Mapped[Driver] = relationship()


class Lap(Base):
    __tablename__ = "laps"
    __table_args__ = (
        UniqueConstraint("race_id", "driver_id", "lap_number", name="uq_lap_race_driver_lap"),
        Index("ix_laps_race_lap", "race_id", "lap_number"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    race_id: Mapped[int] = mapped_column(ForeignKey("races.id", ondelete="CASCADE"))
    driver_id: Mapped[str] = mapped_column(ForeignKey("drivers.driver_id"))
    lap_number: Mapped[int] = mapped_column(Integer)
    position: Mapped[int | None] = mapped_column(Integer)
    lap_time_ms: Mapped[int | None] = mapped_column(Integer)
    # Derived during ingestion from pit-stop records (not provided by the source):
    stint_number: Mapped[int | None] = mapped_column(Integer)
    tyre_age: Mapped[int | None] = mapped_column(Integer)  # laps run in this stint, 1-based
    is_in_lap: Mapped[bool] = mapped_column(Boolean, default=False)
    is_out_lap: Mapped[bool] = mapped_column(Boolean, default=False)
    is_neutralised: Mapped[bool] = mapped_column(Boolean, default=False)  # heuristic SC/VSC/incident flag
    compound: Mapped[str | None] = mapped_column(String(16))  # NULL unless a tyre source provided it


class PitStop(Base):
    __tablename__ = "pit_stops"
    __table_args__ = (UniqueConstraint("race_id", "driver_id", "stop_number", name="uq_pit_race_driver_stop"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    race_id: Mapped[int] = mapped_column(ForeignKey("races.id", ondelete="CASCADE"), index=True)
    driver_id: Mapped[str] = mapped_column(ForeignKey("drivers.driver_id"))
    stop_number: Mapped[int] = mapped_column(Integer)
    lap: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)  # pit-lane time as published


class Stint(Base):
    __tablename__ = "stints"
    __table_args__ = (UniqueConstraint("race_id", "driver_id", "stint_number", name="uq_stint"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    race_id: Mapped[int] = mapped_column(ForeignKey("races.id", ondelete="CASCADE"), index=True)
    driver_id: Mapped[str] = mapped_column(ForeignKey("drivers.driver_id"))
    stint_number: Mapped[int] = mapped_column(Integer)
    start_lap: Mapped[int] = mapped_column(Integer)
    end_lap: Mapped[int] = mapped_column(Integer)
    compound: Mapped[str | None] = mapped_column(String(16))
    compound_source: Mapped[str | None] = mapped_column(String(32))


class Weather(Base):
    """Populated only when a weather-capable source is reachable; otherwise empty (never fabricated)."""

    __tablename__ = "weather"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    race_id: Mapped[int] = mapped_column(ForeignKey("races.id", ondelete="CASCADE"), index=True)
    lap_number: Mapped[int | None] = mapped_column(Integer)
    air_temp_c: Mapped[float | None] = mapped_column(Float)
    track_temp_c: Mapped[float | None] = mapped_column(Float)
    rainfall: Mapped[bool | None] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(32))


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (Index("ix_ingest_season_round", "season", "round"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32))
    season: Mapped[int] = mapped_column(Integer)
    round: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))  # ok | skipped | failed
    laps_loaded: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str | None] = mapped_column(String(1024))
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    artifact_path: Mapped[str] = mapped_column(String(512))
    feature_spec: Mapped[dict] = mapped_column(JSON)
    hyperparameters: Mapped[dict] = mapped_column(JSON)
    train_races: Mapped[list] = mapped_column(JSON)
    test_races: Mapped[list] = mapped_column(JSON)
    metrics: Mapped[dict] = mapped_column(JSON)
    data_fingerprint: Mapped[str] = mapped_column(String(64))
    random_seed: Mapped[int] = mapped_column(Integer)
