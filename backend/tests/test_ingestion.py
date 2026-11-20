"""Unit + database tests for parsing, derivation and idempotent loading.

Payloads below are small SYNTHETIC TEST FIXTURES in the Jolpica response shape; they exist only to
test code paths and are never loaded by the application.
"""
from typing import Any

import pytest
from sqlalchemy import func, select

from app.ingestion.pipeline import ingest_race
from app.ingestion.transform import build_laps, parse_time_ms
from app.models import IngestionRun, Lap, PitStop, Race, Stint

DRIVERS = [f"d{i}" for i in range(6)]


def fmt(ms: float) -> str:
    total = round(ms)
    return f"{total // 60_000}:{(total % 60_000) / 1000:06.3f}"


def make_laps(n: int = 12, slow_laps: tuple[int, ...] = ()) -> list[dict[str, Any]]:
    out = []
    for lap in range(1, n + 1):
        base = 95_000 + lap * 20
        ms = base * 1.3 if lap in slow_laps else base
        out.append({"number": str(lap), "Timings": [
            {"driverId": d, "position": str(i + 1), "time": fmt(ms + i * 50)}
            for i, d in enumerate(DRIVERS)
        ]})
    return out


@pytest.mark.parametrize("text,expected", [
    ("1:35.123", 95123), ("23.456", 23456), ("1:02.3", 62300), ("", None), (None, None), ("abc", None),
])
def test_parse_time_ms(text: str | None, expected: int | None) -> None:
    assert parse_time_ms(text) == expected


def test_stints_tyre_age_and_in_out_laps() -> None:
    res = build_laps(make_laps(12), [{"driverId": "d0", "lap": "5", "stop": "1", "duration": "22.1"}])
    d0 = {r.lap_number: r for r in res.laps if r.driver_id == "d0"}
    assert [d0[n].tyre_age for n in (1, 5, 6, 7, 12)] == [1, 5, 1, 2, 7]
    assert d0[5].is_in_lap and d0[6].is_out_lap and d0[6].stint_number == 2
    assert not any(r.is_in_lap for r in res.laps if r.driver_id == "d1")
    stints = [s for s in res.stints if s["driver_id"] == "d0"]
    assert [(s["start_lap"], s["end_lap"]) for s in stints] == [(1, 5), (6, 12)]


def test_neutralised_laps_flagged_and_invalid_rejected() -> None:
    laps = make_laps(12, slow_laps=(7, 8))
    laps[2]["Timings"].append({"driverId": "d0", "position": "1", "time": "1:30.000"})  # duplicate
    laps[3]["Timings"][0]["time"] = "0:05.000"  # physically impossible
    res = build_laps(laps, [])
    assert res.rejected == 2
    flagged = {r.lap_number for r in res.laps if r.is_neutralised}
    assert flagged == {7, 8}


class FakeClient:
    """Stands in for the HTTP client; records call counts."""

    def __init__(self) -> None:
        self.calls = 0

    def results(self, season: int, rnd: int) -> list[dict[str, Any]]:
        self.calls += 1
        return [{"position": str(i + 1), "grid": str(i + 1), "status": "Finished", "laps": "12",
                 "Driver": {"driverId": d, "code": d.upper(), "givenName": "G", "familyName": d, "nationality": "X"},
                 "Constructor": {"constructorId": "team"}} for i, d in enumerate(DRIVERS)]

    def pitstops(self, season: int, rnd: int) -> list[dict[str, Any]]:
        return [{"driverId": "d0", "lap": "5", "stop": "1", "duration": "22.1"}]

    def laps(self, season: int, rnd: int) -> list[dict[str, Any]]:
        return make_laps(12)


ENTRY = {"season": "2024", "round": "1", "raceName": "Test GP", "date": "2024-03-02",
         "Circuit": {"circuitId": "testring", "circuitName": "Test Ring",
                     "Location": {"lat": "26.0", "long": "50.5", "locality": "X", "country": "Y"}}}


def test_ingest_loads_and_is_idempotent(session) -> None:  # type: ignore[no-untyped-def]
    client = FakeClient()
    assert ingest_race(session, client, ENTRY).status == "ok"  # type: ignore[arg-type]
    n_laps = session.scalar(select(func.count()).select_from(Lap))
    assert n_laps == 12 * len(DRIVERS)
    race = session.scalar(select(Race))
    assert race.has_laps and race.total_laps == 12
    assert session.scalar(select(func.count()).select_from(PitStop)) == 1

    assert ingest_race(session, client, ENTRY).status == "skipped"  # type: ignore[arg-type]
    assert client.calls == 1  # no re-fetch
    assert session.scalar(select(func.count()).select_from(Lap)) == n_laps

    assert ingest_race(session, client, ENTRY, force=True).status == "ok"  # type: ignore[arg-type]
    assert session.scalar(select(func.count()).select_from(Lap)) == n_laps  # replaced, not duplicated
    assert session.scalar(select(func.count()).select_from(Stint)) == len(DRIVERS) + 1


def test_failed_source_is_recorded_not_raised(session) -> None:  # type: ignore[no-untyped-def]
    class Empty(FakeClient):
        def laps(self, season: int, rnd: int) -> list[dict[str, Any]]:
            return []

    run = ingest_race(session, Empty(), ENTRY)  # type: ignore[arg-type]
    assert run.status == "failed"
    assert session.scalar(select(Race)).has_laps is False
    assert session.scalar(select(func.count()).select_from(IngestionRun)) >= 1
