"""Tyre-compound / weather / safety-car enrichment from the Mendeley "Multi-Season Formula 1 Lap Dataset" (CC BY 4.0).

The dataset is FastF1-derived: one Parquet file per race session (2022-2025) with, for every driver lap, the tyre
compound, true tyre life, fresh/used flag, air/track temperature, humidity, wind, rainfall and safety-car / virtual
safety-car labels derived from race-control messages. This module

* downloads the files (``fetch_dataset``; sha256 of every file is verified against the Mendeley listing), and
* joins them onto the laps ingested from Jolpica by (season, race name, driver code, lap number)
  (``ingest_directory``), filling ``laps.compound/tyre_life/fresh_tyre/sc_state``, ``stints.compound`` and ``weather``.

Nothing is invented: a lap that is not present in the dataset keeps NULL tyre fields, and a race that cannot be
matched is reported as unmatched. Lap times are NOT taken from this dataset, only the extra columns.
"""
import hashlib
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
from sqlalchemy import bindparam, delete, select, update
from sqlalchemy.orm import Session

from app.logging_setup import get_logger
from app.models import Driver, IngestionRun, Lap, Race, Stint, Weather

log = get_logger("tyres")

SOURCE = "mendeley-fastf1"
DATASET_ID = "djr8rnjtjp"
LISTING_URL = f"https://data.mendeley.com/api/datasets/{DATASET_ID}/files"
VALID_COMPOUNDS = {"SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"}
REQUIRED_COLUMNS = {"Driver", "LapNumber", "Compound", "TyreLife", "Year", "EventName", "TrackTemp", "AirTemp", "Rainfall"}
USER_AGENT = "f1-strategy-lab-tyre-fetch/1.0"


# --------------------------------------------------------------------------- download
def fetch_dataset(dest: Path, timeout: float = 60.0, progress: Callable[[str], None] | None = None) -> list[Path]:
    """Download every race Parquet file of the dataset into ``dest`` (skips files already present with the right hash)."""
    dest.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": USER_AGENT}
    out: list[Path] = []
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as http:
        first = http.get(LISTING_URL, params={"version": 1})
        first.raise_for_status()
        folders = sorted({f["folder_id"] for f in first.json()})  # the root listing is capped; each race sits in its own folder
        seen: set[str] = set()
        for fid in folders:
            r = http.get(LISTING_URL, params={"folder_id": fid, "version": 1})
            r.raise_for_status()
            for f in r.json():
                if not f["filename"].endswith(".parquet") or f["id"] in seen:
                    continue
                seen.add(f["id"])
                target = dest / f"{f['id']}.parquet"
                want = f["content_details"]["sha256_hash"]
                if not (target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == want):
                    body = http.get(f["content_details"]["download_url"]).content
                    if hashlib.sha256(body).hexdigest() != want:
                        raise ValueError(f"checksum mismatch for {f['filename']}")
                    target.write_bytes(body)
                out.append(target)
                if progress:
                    progress(f"{len(out)} files")
    (dest / "SOURCE.json").write_text(json.dumps({
        "dataset": "Multi-Season Formula 1 Lap Dataset with Race-Control-Based Safety Car Labels (2022-2025)",
        "mendeley_id": DATASET_ID, "licence": "CC BY 4.0", "files": len(out)}, indent=2))
    return out


# --------------------------------------------------------------------------- matching
def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"grand prix|\bcity\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def match_race(session: Session, season: int, event: str, taken: set[int]) -> Race | None:
    races = session.scalars(select(Race).where(Race.season == season, Race.has_laps)).all()
    key = _norm(event)
    for r in races:
        if r.id not in taken and _norm(r.name) == key:
            return r
    # Encoding damage (e.g. "S�o Paulo") can break exact matching: accept a unique fuzzy candidate only.
    cands = [r for r in races if r.id not in taken and (key in _norm(r.name) or _norm(r.name) in key
                                                         or _squeeze(key) == _squeeze(_norm(r.name)))]
    return cands[0] if len(cands) == 1 else None


def _squeeze(s: str) -> str:
    return re.sub(r"[aeiou]", "", s)


def clean_compound(v: Any) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip().upper()
    return s if s in VALID_COMPOUNDS else None


@dataclass
class TyreReport:
    races_matched: int = 0
    laps_updated: int = 0
    unmatched_events: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)


def _read(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"missing columns {sorted(missing)}")
    return df


def enrich_race(session: Session, race: Race, df: pd.DataFrame) -> int:
    """Apply one dataset race frame to an ingested race. Returns the number of laps updated."""
    codes = {c: d for c, d in session.execute(select(Driver.code, Driver.driver_id)).all() if c}
    df = df.copy()
    df["driver_id"] = df["Driver"].map(codes)
    df = df[df["driver_id"].notna() & df["LapNumber"].notna()]
    df["lap"] = df["LapNumber"].astype(int)
    df = df.drop_duplicates(["driver_id", "lap"])
    df["compound"] = df["Compound"].map(clean_compound)
    sc = df["IsSafetyCar"].fillna(0).astype(int) if "IsSafetyCar" in df else pd.Series(0, index=df.index)
    vsc = df["IsVSC"].fillna(0).astype(int) if "IsVSC" in df else pd.Series(0, index=df.index)
    df["sc_state"] = (sc > 0).astype(int) + 2 * ((vsc > 0) & (sc == 0)).astype(int)

    records: list[Any] = df.to_dict("records")
    rows: list[dict[str, Any]] = [{
        "b_driver": r["driver_id"], "b_lap": int(r["lap"]), "v_compound": r["compound"],
        "v_life": None if pd.isna(r["TyreLife"]) else int(r["TyreLife"]),
        "v_fresh": None if pd.isna(r.get("FreshTyre")) else bool(r["FreshTyre"]),
        "v_sc": int(r["sc_state"])} for r in records]
    stmt = (update(Lap).where(Lap.race_id == race.id, Lap.driver_id == bindparam("b_driver"), Lap.lap_number == bindparam("b_lap"))
            .values(compound=bindparam("v_compound"), tyre_life=bindparam("v_life"), fresh_tyre=bindparam("v_fresh"),
                    sc_state=bindparam("v_sc")))
    n = 0
    if rows:
        session.connection().execute(stmt, rows)
        n = len(rows)
        # Official SC/VSC labels override the pace heuristic where they say the lap was neutralised.
        neutral = [{"b_driver": r["b_driver"], "b_lap": r["b_lap"]} for r in rows if r["v_sc"] > 0]
        if neutral:
            session.connection().execute(
                update(Lap).where(Lap.race_id == race.id, Lap.driver_id == bindparam("b_driver"),
                                  Lap.lap_number == bindparam("b_lap")).values(is_neutralised=True), neutral)

    # Stint compound = most common lap compound inside the stint (stints come from the pit-stop records).
    laps = session.execute(select(Lap.driver_id, Lap.stint_number, Lap.compound).where(Lap.race_id == race.id)).all()
    votes: dict[tuple[str, int], Counter[str]] = {}
    for drv, sn, comp in laps:
        if comp and sn is not None:
            votes.setdefault((drv, sn), Counter())[comp] += 1
    for (drv, sn), c in votes.items():
        session.execute(update(Stint).where(Stint.race_id == race.id, Stint.driver_id == drv, Stint.stint_number == sn)
                        .values(compound=c.most_common(1)[0][0], compound_source=SOURCE))

    # Weather: one row per lap, robust to per-driver sampling (median; rain if any driver's sample says rain).
    session.execute(delete(Weather).where(Weather.race_id == race.id))
    g = df.groupby("lap")
    wx = pd.DataFrame({
        "air": g["AirTemp"].median(), "track": g["TrackTemp"].median(),
        "hum": g["Humidity"].median() if "Humidity" in df else None,
        "wind": g["WindSpeed"].median() if "WindSpeed" in df else None,
        "rain": g["Rainfall"].max()})
    for lap, r in wx.iterrows():
        session.add(Weather(race_id=race.id, lap_number=int(str(lap)), air_temp_c=_f(r["air"]), track_temp_c=_f(r["track"]),
                            rainfall=None if pd.isna(r["rain"]) else bool(r["rain"]), humidity_pct=_f(r["hum"]),
                            wind_speed_ms=_f(r["wind"]), source=SOURCE))
    return n


def _f(v: Any) -> float | None:
    return None if v is None or pd.isna(v) else float(v)


def ingest_directory(session: Session, directory: Path) -> TyreReport:
    """Enrich every already-ingested race that a dataset file in ``directory`` (recursive) matches."""
    report = TyreReport()
    taken: set[int] = set()
    for path in sorted([*directory.rglob("*.parquet"), *directory.rglob("*.csv")]):
        try:
            df = _read(path)
        except Exception as exc:  # unreadable or foreign file: record, keep going
            report.skipped_files.append(f"{path.name}: {exc}")
            continue
        if df.empty:
            continue
        year, event = int(df["Year"].iloc[0]), str(df["EventName"].iloc[0])
        if "test" in event.lower() or "pre-season" in event.lower():
            continue  # pre-season testing is not a race
        race = match_race(session, year, event, taken)
        if race is None:
            report.unmatched_events.append(f"{year} {event}")
            continue
        taken.add(race.id)
        n = enrich_race(session, race, df)
        session.add(IngestionRun(source=SOURCE, season=race.season, round=race.round, status="ok", laps_loaded=n,
                                 detail=f"{event}: compound/tyre life/weather/SC labels"))
        session.commit()
        report.races_matched += 1
        report.laps_updated += n
        log.info("tyres_enriched", season=race.season, round=race.round, laps=n)
    return report
