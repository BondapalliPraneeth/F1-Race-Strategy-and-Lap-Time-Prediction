# Deployment

## Local (no Docker)

```bash
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt -r requirements-dev.txt   # Linux/mac: .venv/bin/pip
export F1_DATABASE_URL=sqlite:///data/dev.db            # or a PostgreSQL URL
python -m app.cli migrate
python -m app.cli ingest --season 2024                 # one season per call; slow, polite, cached; re-runnable
python -m app.cli train --test-races 4
uvicorn app.main:app --port 8000
cd ../frontend && npm ci && npm run dev                 # http://localhost:5173 (proxies /api)
```

## Docker Compose

```bash
cp .env.example .env
docker compose up --build            # db (postgres 16), backend (runs migrations), frontend on :8080
docker compose --profile tools run --rm ingest    # load data into PostgreSQL
docker compose --profile tools run --rm train     # train + register a model
```
Open http://localhost:8080. nginx serves the SPA and proxies `/api` to the backend.

## Configuration (environment, prefix `F1_`)

| Variable | Meaning |
|---|---|
| `F1_DATABASE_URL` | SQLAlchemy URL (`postgresql+psycopg://…` or `sqlite:///…`) |
| `F1_ARTIFACTS_DIR` | where model artifacts are stored (mount a volume) |
| `F1_LOG_LEVEL`, `F1_LOG_JSON` | logging |
| `POSTGRES_*` | compose database credentials (`.env.example`) |

Secrets are never committed; `.env` is git-ignored.

## Operations notes

* Migrations run at backend container start (`python -m app.cli migrate`).
* Model artifacts are files plus a `model_versions` row (the newest trained version becomes active).
* Health: `GET /api/health`. Logs are structured (JSON when `F1_LOG_JSON=true`).
* CI (`.github/workflows/ci.yml`): lint/type/test on PostgreSQL, frontend build/test, Playwright E2E, compose smoke test.
