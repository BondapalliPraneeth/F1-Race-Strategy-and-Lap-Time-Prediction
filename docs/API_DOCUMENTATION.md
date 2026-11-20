# API Documentation

Base path `/api`. Interactive OpenAPI: `http://localhost:8000/docs` (Swagger) and `/openapi.json`.
Every response that carries numbers says what they are via `kind`: `actual` (from the database), `predicted`
(model output), `simulated` (Monte Carlo / hypothetical).

## Conventions

| Topic | Behaviour |
|---|---|
| Pagination | `page` (≥1), `page_size` (races ≤100, laps ≤500); response `{items,total,page,page_size}` |
| Errors | `{"detail": ...}`; 404 unknown race/driver, 422 validation/infeasible (field-level list or `message`+`issues`), 503 no trained model |
| Request id | every response has `X-Request-ID`; latency is logged with structlog |
| Times | all durations in milliseconds (`*_ms`) |

## Endpoints

| Method | Path | Purpose | Notes |
|---|---|---|---|
| GET | `/health` | liveness + DB status | `database: up/down` |
| GET | `/seasons` | seasons with ingested laps and race counts | empty list when DB empty |
| GET | `/races?season=&page=&page_size=` | paginated races | only races with laps |
| GET | `/races/{id}` | race detail, drivers, data availability, model split | |
| GET | `/races/{id}/laps?driver_id=` | paginated actual laps | `kind: actual` |
| GET | `/races/{id}/compare?drivers=a&drivers=b` | up to 6 drivers' lap series | |
| GET | `/races/{id}/pit-stops` | recorded stops | |
| GET | `/races/{id}/weather` | per-lap air/track temperature, humidity, rain (2022–2025); otherwise `available:false` + reason | no fabricated data |
| GET | `/races/{id}/strategy-context` | data-derived compound profiles (p90 real stint lengths), safety-car statistics, weather summary, `model_uses_compound` | feeds optimizer/simulator defaults in the UI |
| GET | `/races/{id}/degradation` | regression of lap time on tyre age | actual-data analysis |
| GET | `/models`, `/models/active` | registry: metrics, split, seed, fingerprint | |
| POST | `/predict/laptime` | single lap p50 + 80 % interval | 503 without model |
| GET | `/races/{id}/predict-vs-actual?driver_id=` | per-lap predicted vs actual | marks train/test split |
| POST | `/strategy/optimize` | DP-optimal strategy, alternatives, pit windows, explanation | |
| POST | `/strategy/simulate` | Monte Carlo comparison of 1–8 plans | `n_sims ≤ 20000`, seeded |

## Examples

```bash
curl -s localhost:8000/api/seasons
curl -s -X POST localhost:8000/api/predict/laptime -H 'content-type: application/json' \
  -d '{"race_id":1,"driver_id":"max_verstappen","lap_number":20,"tyre_age":12}'
```
```json
{"kind":"predicted","predicted_ms":92431.0,"interval_80_ms":[91650.0,93390.0],"model_version":2,
 "split":"test","compound_used_by_model":false,"actual_ms":92510,"error_ms":-79.0,"unseen_circuit":false}
```
(illustrative shape; real values depend on your database and model)

Optimise:
```bash
curl -s -X POST localhost:8000/api/strategy/optimize -H 'content-type: application/json' \
  -d '{"race_id":1,"driver_id":"max_verstappen","params":{"max_stops":2,"min_stint_laps":8}}'
```
Returns `recommended` and `alternatives` (stints, pit laps, total_ms), `pit_windows`, `explanation[]`, the effective
`config` (including the data-derived `pit_loss_estimate` and whether it was overridden) and `compute_seconds`.

Simulate:
```json
{"race_id":1,"driver_id":"max_verstappen","n_sims":2000,"seed":42,
 "strategies":[[{"compound":"MEDIUM","laps":25},{"compound":"HARD","laps":32}]],
 "safety_car":{"mode":"random","probability":0.4,"duration_laps":4},
 "weather":[{"start_lap":20,"end_lap":30,"slowdown_pct":3}]}
```
Plan lap totals must equal the race distance and obey the config limits; otherwise 422 lists each issue.
