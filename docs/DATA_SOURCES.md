# Data Sources

Two sources are combined. Neither is redistributed in this repository (`backend/data/` is git-ignored); you build your own copy with the CLI.

## 1. Jolpica-F1 (Ergast-compatible) — laps, results, pit stops

* Base URL: `https://api.jolpi.ca/ergast/f1` (community-run successor to the Ergast API; free, no key).
* Endpoints: `/{season}.json`, `/{season}/{round}/results.json`, `/pitstops.json`, `/laps.json`; max 100 rows per request, `offset` followed.
* HTTP 429 handled with exponential back-off; minimum 0.35 s between requests; every response cached under `backend/data/raw_cache`.
* Provides: schedule, circuits, classification, grid, per-lap times and positions, pit-stop lap and duration. Seasons 2021–2025 are loaded here.

## 2. Mendeley Data — "Multi-Season Formula 1 Lap Dataset with Race-Control-Based Safety Car Labels (2022-2025)"

* Dataset `djr8rnjtjp`, DOI [10.17632/djr8rnjtjp.1](https://doi.org/10.17632/djr8rnjtjp.1), author Tanvinur Rahman Siam (Chittagong University of Engineering & Technology),
  licence **CC BY 4.0**. Derived from FastF1 public timing data. Cite it if you reuse results.
* One Parquet file per race session. Used columns: `Compound`, `TyreLife`, `FreshTyre`, `AirTemp`, `TrackTemp`, `Humidity`, `WindSpeed`, `Rainfall`,
  `IsSafetyCar`, `IsVSC` (labels parsed from official race-control messages).
* Lap **times are not taken from it** — only the extra columns, joined to Jolpica laps by (season, normalised event name, driver code, lap number).
* Commands: `python -m app.cli fetch-tyres` (downloads and verifies the sha256 of each file against the Mendeley listing), then
  `python -m app.cli ingest-tyres --dir data/tyre_cache`. The listing endpoint is not a documented API; if it changes, download the files manually
  from the dataset page and point `--dir` at them.
* Coverage achieved: 90 of 109 ingested races matched. Unmatched: all 17 races of 2021 (dataset starts in 2022), Miami 2023 and Spanish GP 2025 (no matching file in the dataset). Unmatched races keep NULL tyre/weather fields — nothing is imputed.
  Unmatched races keep NULL tyre/weather fields — nothing is imputed.
* Treated as untrusted input: columns are validated, unreadable or foreign files are reported and skipped, compounds are restricted to SOFT/MEDIUM/HARD/INTERMEDIATE/WET.

| Now available | Still not available |
|---|---|
| Compound per lap and per stint, true tyre life, fresh/used flag | Tyre-set inventory (used-set history only via `TyreLife`) |
| Air/track temperature, humidity, wind, rainfall (per lap, 2022–2025) | Telemetry, qualifying/practice laps, track evolution |
| Official safety-car and virtual-safety-car labels | Red-flag labels, traffic/gaps |

## Evaluated and not usable

| Source | Result |
|---|---|
| OpenF1 (`api.openf1.org`) | HTTP 401 for historical endpoints from this environment |
| F1 live-timing static feed | HTTP 401 |
| FastF1 directly | depends on the same restricted feeds; the Mendeley dataset is a FastF1-derived export instead |

## Derived fields

| Field | Method | Caveat |
|---|---|---|
| `stint_number` | from recorded pit-stop laps | stops missing from the source are not detected |
| `tyre_age` (model feature) | dataset `TyreLife` when present, else laps since last stop | 2021, Miami 2023 and Spanish 2025 fall back to the lower bound |
| `stints.compound` | most common lap compound in the stint | `compound_source = mendeley-fastf1` |
| `is_neutralised` | official SC/VSC label when present, else field-median lap > 1.15 × green-flag pace | heuristic outside 2022–2025 |
| wet race | rain or wet tyres on > 10 % of laps (when weather exists) or median pace > 1.06 × circuit reference | excluded from training |
| rejected rows | unparsable, duplicate or implausible (outside 40–400 s) times | counted in `ingestion_runs` |

## Real regulations vs data vs assumptions

| Item | Status |
|---|---|
| At least two different dry compounds in a dry race (FIA Sporting Regulations) | **Real rule** — `min_compounds_used = 2`, editable |
| Max stint length per compound | **Data-derived** — 90th percentile of real stints (circuit if enough stints there, else all circuits); assumption if the model has no compound data |
| Compound pace offsets / degradation multipliers | **Model-learned** when the model uses compound (offset 0 / multiplier 1 on top); otherwise editable assumptions |
| Safety-car frequency and duration shown in the UI | **Data-derived** from official labels (circuit scope if ≥ 4 races there); the simulator scenario itself is a what-if |
| Pit-lane time loss | **Data-derived** per circuit (median over recorded stops) |
| Weather windows in the simulation | **Hypothetical** user scenario (historical weather is shown beside it) |
| Traffic penalty, SC slowdown factor, tyre-set availability | **Assumption** |

No unofficial team assets, logos or private data are included.
