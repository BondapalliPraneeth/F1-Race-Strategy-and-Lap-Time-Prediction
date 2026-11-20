"""Pure functions: parse, validate and derive fields from raw Jolpica payloads (no I/O)."""
import re
import statistics
from dataclasses import dataclass, field
from typing import Any

_TIME_RE = re.compile(r"^(?:(\d+):)?(\d{1,2})\.(\d{1,3})$")
MIN_LAP_MS, MAX_LAP_MS = 40_000, 400_000  # physical sanity bounds for any F1 lap (incl. red-flag laps)
NEUTRALISED_RATIO = 1.15  # field-median lap this much slower than the race's green pace => SC/VSC/incident


def parse_time_ms(text: str | None) -> int | None:
    """'1:35.123' -> 95123; '23.456' -> 23456; invalid/missing -> None."""
    if not text:
        return None
    m = _TIME_RE.match(text.strip())
    if not m:
        return None
    minutes, secs, frac = m.groups()
    return int(minutes or 0) * 60_000 + int(secs) * 1000 + int(frac.ljust(3, "0"))


@dataclass
class LapRow:
    driver_id: str
    lap_number: int
    position: int | None
    lap_time_ms: int | None
    stint_number: int = 1
    tyre_age: int = 1
    is_in_lap: bool = False
    is_out_lap: bool = False
    is_neutralised: bool = False


@dataclass
class TransformResult:
    laps: list[LapRow] = field(default_factory=list)
    stints: list[dict[str, Any]] = field(default_factory=list)
    rejected: int = 0


def build_laps(raw_laps: list[dict[str, Any]], pit_stops: list[dict[str, Any]]) -> TransformResult:
    """Validate raw lap timings and derive stint / tyre-age / in-out-lap / neutralisation fields.

    Tyre age is *laps since the driver's last pit stop* (or race start). It does not know about
    used tyres fitted at a stop, so it is a lower bound on true tyre age.
    """
    res = TransformResult()
    stops: dict[str, list[int]] = {}
    for p in pit_stops:
        stops.setdefault(p["driverId"], []).append(int(p["lap"]))
    for v in stops.values():
        v.sort()

    seen: set[tuple[str, int]] = set()
    for lap in raw_laps:
        n = int(lap["number"])
        for t in lap["Timings"]:
            drv = t["driverId"]
            ms = parse_time_ms(t.get("time"))
            if (drv, n) in seen or n < 1 or (ms is not None and not MIN_LAP_MS <= ms <= MAX_LAP_MS):
                res.rejected += 1
                continue
            seen.add((drv, n))
            pos = int(t["position"]) if str(t.get("position", "")).isdigit() else None
            stop_laps = stops.get(drv, [])
            # A stop recorded on lap L is made at the end of lap L: L is the in-lap, L+1 the out-lap.
            stint = 1 + sum(1 for s in stop_laps if s < n)
            start = 1 + max([s for s in stop_laps if s < n], default=0)
            res.laps.append(
                LapRow(drv, n, pos, ms, stint, n - start + 1, n in stop_laps, (n - 1) in stop_laps)
            )

    _flag_neutralised(res.laps)

    by_drv: dict[str, list[LapRow]] = {}
    for r in res.laps:
        by_drv.setdefault(r.driver_id, []).append(r)
    for drv, rows in by_drv.items():
        for sn in sorted({r.stint_number for r in rows}):
            sl = [r.lap_number for r in rows if r.stint_number == sn]
            res.stints.append(
                {"driver_id": drv, "stint_number": sn, "start_lap": min(sl), "end_lap": max(sl)}
            )
    return res


def _flag_neutralised(laps: list[LapRow]) -> None:
    by_lap: dict[int, list[int]] = {}
    for r in laps:
        if r.lap_time_ms is not None and r.lap_number > 1 and not (r.is_in_lap or r.is_out_lap):
            by_lap.setdefault(r.lap_number, []).append(r.lap_time_ms)
    field_med = {n: statistics.median(v) for n, v in by_lap.items() if len(v) >= 5}
    if len(field_med) < 5:
        return
    ordered = sorted(field_med.values())
    reference = statistics.median(ordered[: max(3, len(ordered) // 2)])  # fastest half = green-flag pace
    slow = {n for n, m in field_med.items() if m > NEUTRALISED_RATIO * reference}
    for r in laps:
        if r.lap_number in slow:
            r.is_neutralised = True
