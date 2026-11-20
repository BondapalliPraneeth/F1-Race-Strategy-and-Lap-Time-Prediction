# Data Sources

## Used: Jolpica-F1 (Ergast-compatible)

* Base URL: `https://api.jolpi.ca/ergast/f1` (community-run successor to the Ergast API; free, no key).
* Endpoints: `/{season}.json` (schedule), `/{season}/{round}/results.json`, `/pitstops.json`, `/laps.json`.
* Paging: maximum 100 rows per request; the client follows `offset`.
* Rate limiting: HTTP 429 is handled with exponential back-off; a minimum interval between requests (default 0.35 s) is enforced.
* Caching: each response is stored as JSON under `backend/data/raw_cache` so re-ingestion is offline and cheap.
* Licence/etiquette: it is a public community API — the client identifies itself generically and throttles. No data is
  redistributed in this repository (`backend/data/` is git-ignored); you build your own copy with the CLI.

| Provides | Does **not** provide |
|---|---|
| Race schedule, circuits, classification, grid, status | Tyre compounds |
| Per-lap times and positions for every driver | Weather, track temperature, rainfall |
| Pit stop lap and pit-lane duration | Qualifying/practice lap data, car telemetry |
| Seasons back to 1950 (laps from ~1996) | Safety-car/VSC periods (inferred heuristically) |

## Evaluated and rejected

| Source | Result | Consequence |
|---|---|---|
| OpenF1 (`api.openf1.org`) | HTTP 401 for historical endpoints from this environment (restricted access) | no compounds/weather/sessions |
| F1 live-timing static feed | HTTP 401 | same |
| FastF1 | depends on the same restricted feeds; not used | — |

**Therefore:** only the **Race** session exists in the app, the weather table is empty, compound is NULL, and the
optimizer's compound characteristics are explicit, editable *assumptions*. The code is structured so a tyre/weather
source can be added: `stints.compound_source`, `laps.compound` and the optional `compound` feature
(`OPTIONAL_CATEGORICAL` in `features.py`, used automatically once ≥ 50 % of laps have it) already exist.

## Derived fields (how they are computed)

| Field | Method | Caveat |
|---|---|---|
| `stint_number`, `tyre_age` | from recorded pit-stop laps | lower bound of real tyre age |
| `is_in_lap` / `is_out_lap` | lap of / after a recorded stop | stops missing from the source are not detected |
| `is_neutralised` | field-median lap > 1.15 × the race's green-flag pace | heuristic; may miss slow VSC laps or flag rain |
| rejected rows | unparsable, duplicate or implausible (outside 40 s – 400 s) times | counted in `ingestion_runs` |

## Real regulations vs assumptions

| Item | Status |
|---|---|
| At least two different dry-tyre compounds must be used in a dry race (FIA Sporting Regulations) | **Real** — encoded as `min_compounds_used = 2` and editable |
| Compound pace offsets, degradation multipliers, maximum stint lengths | **Assumption** — shown in the UI with an `ASSUMPTION` badge |
| Pit-lane time loss | **Data-derived** per circuit (median over recorded stops); user override allowed |
| Safety-car slowdown factor, pit-loss discount under SC, probability | **Assumption** |
| Weather windows in simulation | **Hypothetical** user scenario |
| Number of tyre sets available | Not modelled (optional `available_sets` limit exists, default unlimited) |

No unofficial team assets, logos or private data are included.
