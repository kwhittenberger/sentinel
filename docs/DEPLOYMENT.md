# Deployment Guide

This guide covers setting up and running the Sentinel incident analysis platform in development and production-like environments.

---

## Prerequisites

| Requirement | Version | Purpose |
|-------------|---------|---------|
| Docker & Docker Compose | 20.10+ / v2+ | Database, Redis, and containerized services |
| Python | 3.11+ | Backend API and Celery workers |
| Node.js | 20+ | Frontend dev server |
| Git | 2.x | Source control |

Optional:

- **Anthropic API key** -- Required for LLM-powered article extraction
- **News API key** -- Required only for the data pipeline's news source fetcher
- **Ollama** -- Alternative local LLM provider (if configured)

---

## Quick Start

```bash
# 1. Clone and enter the project
git clone <repo-url> sentinel
cd sentinel

# 2. Create environment file
cp .env.example .env
# Edit .env and set at minimum: ANTHROPIC_API_KEY

# 3. Create Python virtual environment
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 4. Start database and Redis
docker-compose up -d db redis

# 5. Start all services (backend, Celery workers, beat scheduler)
./start-dev.sh

# 6. Start frontend (separate terminal)
cd frontend && npm install && npm run dev
```

Dashboard: http://localhost:5174
Backend API: http://localhost:8000

---

## Environment Variables

Copy `.env.example` to `.env`. All variables and their purposes:

### Required

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://sentinel:sentinel@localhost:5433/sentinel` | PostgreSQL connection string. Port 5433 maps to container's 5432. |
| `POSTGRES_PASSWORD` | `sentinel` | Password for the PostgreSQL `sentinel` user. Used by Docker and connection strings. |
| `ANTHROPIC_API_KEY` | _(none)_ | Anthropic API key for Claude-powered article extraction. Without this, LLM extraction is unavailable. |

### Redis / Celery

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection for caching and Celery result backend. |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Message broker URL for Celery task queue. |
| `USE_CELERY` | `false` | Set to `true` to enable Celery task dispatch. When `false`, background tasks run synchronously. `start-dev.sh` sets this to `true` automatically. |

### Celery Retry Policies (all optional)

These control retry behavior for background tasks. Defaults are sensible for development.

| Variable | Default | Description |
|----------|---------|-------------|
| `CELERY_FETCH_MAX_RETRIES` | `5` | Max retries for article fetch tasks |
| `CELERY_FETCH_RETRY_BACKOFF` | `60` | Base backoff (seconds) between fetch retries |
| `CELERY_FETCH_RETRY_BACKOFF_MAX` | `600` | Maximum backoff cap for fetch retries |
| `CELERY_EXTRACT_MAX_RETRIES` | `3` | Max retries for single-article extraction |
| `CELERY_EXTRACT_RETRY_BACKOFF` | `300` | Backoff (seconds) for extraction retries |
| `CELERY_EXTRACT_MANUAL_RETRY_BASE` | `60` | Base delay for manual extraction retries |
| `CELERY_BATCH_EXTRACT_MAX_RETRIES` | `2` | Max retries for batch extraction |
| `CELERY_BATCH_EXTRACT_RETRY_BACKOFF` | `300` | Backoff for batch extraction retries |
| `CELERY_BATCH_EXTRACT_MANUAL_RETRY_BASE` | `120` | Base delay for manual batch retries |
| `CELERY_BATCH_ENRICH_MAX_RETRIES` | `3` | Max retries for batch enrichment |
| `CELERY_BATCH_ENRICH_RETRY_BACKOFF` | `120` | Backoff for batch enrichment retries |
| `CELERY_ENRICH_MAX_RETRIES` | `2` | Max retries for single enrichment |
| `CELERY_ENRICH_RETRY_BACKOFF` | `300` | Backoff for enrichment retries |
| `CELERY_PIPELINE_MAX_RETRIES` | `1` | Max retries for full pipeline runs |
| `CELERY_PIPELINE_RETRY_BACKOFF` | `600` | Backoff for pipeline retries |

### LLM Providers

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://192.168.1.228:11434/v1` | Ollama API endpoint for local LLM inference (optional alternative to Anthropic) |

### Geocoding

| Variable | Default | Description |
|----------|---------|-------------|
| `GEOCODING_API_ENABLED` | `false` | Enable Nominatim API fallback for cities not in the local lookup table. Set to `true` to resolve unknown city coordinates via the public API. |

### Application

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | `development` | Runtime environment identifier. Affects logging verbosity and error detail in responses. |
| `NEWS_API_KEY` | _(none)_ | API key for the News API data source (optional; only needed if using News API feeds). |

---

## Service Architecture

Sentinel runs as seven cooperating services:

```
                    +----------+
                    | Frontend |  :5173 (Vite dev) / :5174 (npm run dev)
                    +----+-----+
                         |
                    +----v-----+
                    | Backend  |  :8000 (FastAPI/Uvicorn)
                    +----+-----+
                         |
              +----------+----------+
              |                     |
        +-----v------+       +-----v------+
        | PostgreSQL  |       |   Redis    |
        |   :5433     |       |   :6379    |
        +-------------+       +-----+------+
                                    |
                    +---------------+---------------+
                    |               |               |
              +-----v-----+  +-----v-----+  +-----v-----+
              |  Worker:   |  |  Worker:   |  |  Worker:   |
              |  default   |  | extraction |  |   fetch    |
              +------------+  +------------+  +------------+
                                    |
                              +-----v-----+
                              | Celery    |
                              | Beat      |
                              +-----------+
```

### Service Details

| Service | Container | Port | Description |
|---------|-----------|------|-------------|
| **PostgreSQL** | `sentinel_db` | 5433 (host) -> 5432 (container) | Primary data store. Postgres 16 Alpine. Data persisted in `sentinel_data` volume. |
| **Redis** | `sentinel_redis` | 6379 | Celery message broker and result backend. Redis 7 Alpine. Data persisted in `sentinel_redis_data` volume. |
| **Backend** | `sentinel_backend` | 8000 | FastAPI application. Serves the REST API. Hot-reloads in dev mode. |
| **Worker: default** | `sentinel_celery_worker_default` | -- | Processes `default` and `enrichment` queues. Concurrency: 2. |
| **Worker: extraction** | `sentinel_celery_worker_extraction` | -- | Processes `extraction` queue (LLM calls). Concurrency: 1 (rate-limited to avoid API throttling). |
| **Worker: fetch** | `sentinel_celery_worker_fetch` | -- | Processes `fetch` queue (RSS/article download). Concurrency: 2. |
| **Celery Beat** | `sentinel_celery_beat` | -- | Periodic task scheduler. Triggers scheduled fetches and maintenance tasks. |
| **Frontend** | `sentinel_frontend` | 5173 | Vite dev server (React/TypeScript). Proxies API calls to backend. |

### Healthchecks

| Service | Healthcheck | Interval |
|---------|-------------|----------|
| PostgreSQL | `pg_isready -U sentinel -d sentinel` | 10s (5 retries, 5s timeout) |
| Redis | `redis-cli ping` | 10s (5 retries, 5s timeout) |

The backend and Celery workers depend on database health before starting. Celery workers additionally depend on Redis health.

---

## Database Setup

### Initial Schema

On first `docker-compose up`, the database container automatically runs `database/schema.sql` (mounted at `/docker-entrypoint-initdb.d/01_schema.sql`). This creates all tables, indexes, views, materialized views, functions, and triggers.

This only runs when the `sentinel_data` volume is empty (first boot). To re-initialize:

```bash
# WARNING: Destroys all data
docker-compose down -v   # Remove volumes
docker-compose up -d db  # Recreate from schema.sql
```

### Migrations

Incremental migrations live in `database/migrations/` (001 through 035). The `schema.sql` file is the canonical, post-migration schema. If you are starting fresh from `schema.sql`, no migrations are needed.

For existing databases that need incremental updates, apply migrations in order:

```bash
docker exec -it sentinel_db psql -U sentinel -d sentinel -f /path/to/migration.sql
```

Migration state is tracked in the `schema_migrations` table.

### Seed Data

`schema.sql` includes seed data for `incident_types` (21 types across enforcement and crime categories). All other reference data (event domains, categories, outcome types, victim types) is created at runtime via the application.

### Data Import Scripts

```bash
# Migrate legacy JSON data into the database (one-time)
python scripts/migrate_data.py

# Import crime tracker dataset
python scripts/import_crime_tracker.py
```

### Direct Database Access

```bash
docker exec -it sentinel_db psql -U sentinel -d sentinel
```

---

## Development Mode

### Option A: start-dev.sh (recommended)

Runs all backend services natively (outside Docker) for fast iteration with hot-reload:

```bash
./start-dev.sh          # Start everything
./start-dev.sh status   # Check service status
./start-dev.sh stop     # Stop non-Docker services
```

This script:
1. Starts `db` and `redis` via Docker Compose (if not already running)
2. Activates the `.venv` Python virtual environment
3. Loads `.env` variables
4. Starts uvicorn on port 8000 with `--reload`
5. Starts three Celery workers (default, extraction, fetch)
6. Starts Celery Beat scheduler

All logs go to `.logs/` directory:
- `.logs/backend.log`
- `.logs/worker-default.log`
- `.logs/worker-extraction.log` (not created by the script name, but logged)
- `.logs/celery-beat.log`

Frontend must be started separately:

```bash
cd frontend && npm run dev
```

### Option B: start-backend.sh

Runs only the backend API server (no Celery workers). Useful for frontend-only development or when background processing is not needed:

```bash
./start-backend.sh
```

Sets `USE_CELERY=true` but does not start workers, so tasks will be queued but not processed.

### Option C: Full Docker Compose

Runs everything in containers. Slower iteration (no hot-reload on backend volume changes without rebuild), but closest to production:

```bash
docker-compose up -d
```

Frontend available at http://localhost:5173, backend at http://localhost:8000.

---

## Monitoring

### Health Endpoint

The backend exposes a health endpoint (check specific route in `backend/main.py`) at the API root.

### Job Dashboard

The frontend includes a **Job Manager** (`/admin/jobs`) that shows:
- Active, completed, and failed background jobs
- Job progress, retry counts, and error messages
- Celery task IDs for correlation with worker logs

### Logs

Development logs are written to `.logs/`:

| File | Contents |
|------|----------|
| `.logs/backend.log` | Uvicorn/FastAPI request logs and application errors |
| `.logs/worker-default.log` | Default + enrichment queue task execution |
| `.logs/worker-extraction.log` | LLM extraction task execution |
| `.logs/celery-beat.log` | Periodic task scheduling |

Docker Compose logs:

```bash
docker-compose logs -f backend         # Follow backend logs
docker-compose logs -f celery-worker-extraction  # Follow extraction worker
docker-compose logs --tail=100 db      # Last 100 lines from database
```

### Pipeline Metrics

The `task_metrics` and `task_metrics_aggregate` tables track per-task execution metrics (duration, success rate, items processed). The **Analytics Dashboard** (`/admin/analytics`) visualizes pipeline throughput and funnel metrics.

### Materialized Views

Two materialized views require periodic refresh:

- `prosecutor_stats` -- Aggregated prosecutorial action statistics
- `recidivism_analysis` -- Actor recidivism patterns

Refresh configuration is stored in `materialized_view_refresh_config`. To manually refresh:

```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY prosecutor_stats;
REFRESH MATERIALIZED VIEW CONCURRENTLY recidivism_analysis;
```

---

## Troubleshooting

### Port 5433 already in use

Another PostgreSQL instance is running on port 5433. Either stop it or change the port mapping in `docker-compose.yml`:

```yaml
ports:
  - "5434:5432"  # Change host port
```

Update `DATABASE_URL` in `.env` to match.

### Port 8000 already in use

```bash
# Find what's using it
ss -tlnp | grep ':8000 '

# Kill it
./start-dev.sh stop
```

### Celery workers not processing tasks

1. Verify Redis is running: `docker-compose ps redis`
2. Check `USE_CELERY=true` in your `.env`
3. Check worker logs in `.logs/worker-*.log`
4. Verify the correct queues: workers must be listening on `default`, `enrichment`, `extraction`, and `fetch`

### LLM extraction returning errors

1. Verify `ANTHROPIC_API_KEY` is set in `.env`
2. Check `.logs/worker-extraction.log` for rate limit or authentication errors
3. The extraction worker has concurrency=1 to avoid API throttling. If you see 429 errors, increase retry backoff values.

### Database schema out of sync

If `schema.sql` and migrations have drifted:

```bash
# Nuclear option: recreate from canonical schema
docker-compose down -v
docker-compose up -d db
```

For incremental fixes, check `database/migrations/` for unapplied migrations and run them in order.

### Docker Compose "no such service"

Ensure you are running from the project root (where `docker-compose.yml` lives):

```bash
cd /path/to/sentinel
docker-compose up -d db redis
```

### Frontend can't reach backend

1. Check backend is running on port 8000: `curl http://localhost:8000/`
2. If using Docker Compose for frontend, ensure `VITE_API_URL=http://localhost:8000` is set
3. Check browser console for CORS errors -- the backend must allow the frontend origin

### "relation does not exist" errors

The database was likely started without `schema.sql` being applied. Verify the volume mount:

```bash
docker exec -it sentinel_db psql -U sentinel -d sentinel -c '\dt'
```

If tables are missing, recreate the database (see "Database schema out of sync" above).
