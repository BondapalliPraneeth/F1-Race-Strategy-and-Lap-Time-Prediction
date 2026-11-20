"""Idempotent ingestion: fetch -> validate/derive -> load into the database in one transaction per race."""
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ingestion.jolpica import JolpicaClient, SourceError
from app.ingestion.transform import build_laps, parse_time_ms
from app.logging_setup import get_logger
from app.models import Circuit, Driver, IngestionRun, Lap, PitStop, Race, Result, Stint

log = get_logger("ingest")
SOURCE = "jolpica"


def _upsert_race(session: Session, entry: dict) -> Race:
    c = entry["Circuit"]
    loc = c.get("Location", {})
    circuit = session.get(Circuit, c["circuitId"]) or Circuit(circuit_id=c["circuitId"], name=c["circuitName"])
    circuit.name = c["circuitName"]
    circuit.locality, circuit.country = loc.get("locality"), loc.get("country")
    circuit.lat = float(loc["lat"]) if loc.get("lat") else None
    circuit.lon = float(loc["long"]) if loc.get("long") else None
    session.add(circuit)
    season, rnd = int(entry["season"]), int(entry["round"])
    race = session.scalar(select(Race).where(Race.season == season, Race.round == rnd))
    if race is None:
        race = Race(season=season, round=rnd, name=entry["raceName"], circuit_id=circuit.circuit_id)
        session.add(race)
    race.name = entry["raceName"]
    race.circuit_id = circuit.circuit_id
    race.race_date = date.fromisoformat(entry["date"]) if entry.get("date") else None
    session.flush()
    return race


def ingest_race(session: Session, client: JolpicaClient, entry: dict, force: bool = False) -> IngestionRun:
    """Ingest one race. Re-running without ``force`` is a no-op (no duplicate rows)."""
    season, rnd = int(entry["season"]), int(entry["round"])
    race = _upsert_race(session, entry)
    session.commit()  # keep the race row even if the data fetch below fails
    if race.has_laps and not force:
        run = IngestionRun(source=SOURCE, season=season, round=rnd, status="skipped", detail="already ingested")
        session.add(run)
        session.commit()
        return run
    try:
        results = client.results(season, rnd)
        pits = client.pitstops(season, rnd)
        raw_laps = client.laps(season, rnd)
        if not raw_laps or not results:
            raise SourceError("no lap or result data published for this race")
        t = build_laps(raw_laps, pits)

        for model in (Lap, PitStop, Stint, Result):
            session.execute(delete(model).where(model.race_id == race.id))
        for r in results:
            d = r["Driver"]
            drv = session.get(Driver, d["driverId"]) or Driver(
                driver_id=d["driverId"], given_name=d["givenName"], family_name=d["familyName"]
            )
            drv.code, drv.nationality = d.get("code"), d.get("nationality")
            session.add(drv)
        session.flush()
        for r in results:
            session.add(Result(
                race_id=race.id, driver_id=r["Driver"]["driverId"], constructor_id=r["Constructor"]["constructorId"],
                grid=int(r["grid"]) if str(r.get("grid", "")).isdigit() else None,
                position=int(r["position"]) if str(r.get("position", "")).isdigit() else None,
                status=r.get("status"), laps_completed=int(r["laps"]) if str(r.get("laps", "")).isdigit() else None,
            ))
        known = {r["Driver"]["driverId"] for r in results}
        for p in pits:
            if p["driverId"] in known:
                session.add(PitStop(race_id=race.id, driver_id=p["driverId"], stop_number=int(p["stop"]),
                                    lap=int(p["lap"]), duration_ms=parse_time_ms(p.get("duration"))))
        rows = [x for x in t.laps if x.driver_id in known]
        session.add_all(Lap(race_id=race.id, **x.__dict__) for x in rows)
        session.add_all(Stint(race_id=race.id, **s) for s in t.stints if s["driver_id"] in known)
        race.total_laps = max((x.lap_number for x in rows), default=None)
        race.has_laps = True
        run = IngestionRun(source=SOURCE, season=season, round=rnd, status="ok",
                           laps_loaded=len(rows), rows_rejected=t.rejected)
        session.add(run)
        session.commit()
        log.info("ingested", season=season, round=rnd, laps=len(rows), rejected=t.rejected)
        return run
    except Exception as exc:
        session.rollback()
        run = IngestionRun(source=SOURCE, season=season, round=rnd, status="failed", detail=str(exc)[:1000])
        session.add(run)
        session.commit()
        log.error("ingest_failed", season=season, round=rnd, error=str(exc))
        return run


def ingest_season(session: Session, client: JolpicaClient, season: int, rounds: list[int] | None = None,
                  force: bool = False) -> list[IngestionRun]:
    today = date.today().isoformat()
    out = []
    for entry in client.schedule(season):
        if rounds and int(entry["round"]) not in rounds:
            continue
        if entry.get("date", "9999") > today:
            continue  # future race
        out.append(ingest_race(session, client, entry, force=force))
    return out
