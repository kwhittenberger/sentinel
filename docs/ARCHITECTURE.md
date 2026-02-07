# Sentinel Architecture

This document describes the architecture of the Sentinel platform: its services,
data pipeline, data model layers, background processing, LLM integration, and
frontend structure.

---

## System Overview

Sentinel is an incident analysis and pattern detection platform. It ingests
articles from RSS feeds, uses LLM-powered extraction to produce structured
incident data, deduplicates results, applies confidence-based auto-approval,
and presents curated incidents through an interactive geographic dashboard.

**Primary users:**

- **Analysts** review curated incidents on the map dashboard, browse events and
  actors, and investigate patterns across jurisdictions.
- **Curators** review medium/low-confidence extractions in the curation queue,
  approve or reject them, and correct extracted fields.
- **Administrators** configure feeds, extraction prompts, incident types, event
  domains, approval thresholds, and LLM provider settings.

---

## Service Topology

Sentinel runs as seven Docker services plus an optional local frontend dev
server. All services are defined in `docker-compose.yml`.

```
+------------------+       +-----------------+       +-------------------+
|   frontend       |       |    backend      |       |    PostgreSQL     |
|   (Vite/React)   |------>|    (FastAPI)     |------>|    (postgres:16)  |
|   :5173          |       |    :8000        |       |    :5433          |
+------------------+       +--------+--------+       +-------------------+
                                    |                         ^
                                    | WebSocket (jobs)        |
                                    v                         |
                           +--------+--------+                |
                           |     Redis        |                |
                           |   (redis:7)      |                |
                           |   :6379          |                |
                           +--------+--------+                |
                                    ^                         |
                    +---------------+---------------+         |
                    |               |               |         |
           +--------+--+   +-------+---+   +-------+---+     |
           | celery     |   | celery     |   | celery     |   |
           | worker     |   | worker     |   | worker     |   |
           | default    |   | extraction |   | fetch      |   |
           | +enrichment|   | (conc=1)   |   | (conc=2)   |   |
           | (conc=2)   |   +-------+---+   +-------+---+     |
           +--------+--+           |               |          |
                    |              +-------+-------+          |
                    +--------------+       |                  |
                                   +-------+---+              |
                                   | celery     |             |
                                   | beat       +-------------+
                                   | (scheduler)|
                                   +------------+
```

### Services

| Service | Container | Purpose |
|---|---|---|
| **db** | `sentinel_db` | PostgreSQL 16 Alpine. Initialized from `database/schema.sql`. Port 5433 externally. |
| **redis** | `sentinel_redis` | Redis 7 Alpine. Celery broker and result backend. Port 6379. |
| **backend** | `sentinel_backend` | FastAPI app via uvicorn. REST API + WebSocket for job updates. Port 8000. |
| **celery-worker-default** | `sentinel_celery_worker_default` | Processes `default` and `enrichment` queues. Concurrency 2. |
| **celery-worker-extraction** | `sentinel_celery_worker_extraction` | Processes `extraction` queue (LLM calls). Concurrency 1 to manage API rate limits. |
| **celery-worker-fetch** | `sentinel_celery_worker_fetch` | Processes `fetch` queue (RSS fetching). Concurrency 2. |
| **celery-beat** | `sentinel_celery_beat` | Periodic task scheduler. Triggers scheduled fetches, cleanup, metrics, view refreshes. |
| **frontend** | `sentinel_frontend` | Vite dev server. Port 5173. Typically run outside Docker during development (`cd frontend && npm run dev` on port 5174). |

### Startup Modes

- **Full stack (Celery):** `./start-dev.sh` sets `USE_CELERY=true`. Backend delegates
  background work to Celery workers via Redis.
- **Backend-only (in-process):** `./start-backend.sh` sets `USE_CELERY=false`. The
  `JobExecutor` polls the `background_jobs` table and runs tasks in-process. This
  is the legacy fallback for environments without Redis.
- **Docker Compose:** `docker-compose up -d` starts everything including frontend.

---

## Data Pipeline Flow

Articles flow through the system in a series of stages. Each stage can run
synchronously (via the unified pipeline) or asynchronously (via Celery tasks).

```
                          RSS Feeds
                              |
                              v
                   +--------------------+
                   |   1. FETCH         |   Celery: fetch queue
                   |   (fetch_tasks)    |   Scheduled: hourly via beat
                   |                    |   Reads sources table, parses
                   |                    |   RSS via feedparser, stores
                   |                    |   new articles in
                   |                    |   ingested_articles
                   +--------+-----------+
                            |
                            v
                   +--------------------+
                   |   2. ENRICH        |   Celery: enrichment queue
                   |   (enrichment_     |   Fetches full article content
                   |    tasks)          |   via HTTP when RSS snippet is
                   |                    |   too short (<500 chars).
                   |                    |   Extracts text from HTML.
                   +--------+-----------+
                            |
                            v
                   +--------------------+
                   |   3. EXTRACT       |   Celery: extraction queue
                   |   (extraction_     |   LLM-powered extraction.
                   |    tasks)          |   Two modes:
                   |                    |     Legacy: single LLM call
                   |                    |     Two-stage: Stage 1 + Stage 2
                   +--------+-----------+
                            |
                            v
                   +--------------------+
                   |   4. DEDUPLICATE   |   In unified_pipeline
                   |   (duplicate_      |   Four strategies checked
                   |    detection)      |   in order:
                   |                    |     1. URL match
                   |                    |     2. Title similarity
                   |                    |     3. Content fingerprint
                   |                    |     4. Entity match
                   +--------+-----------+
                            |
                            v
                   +--------------------+
                   |   5. AUTO-APPROVE  |   In unified_pipeline
                   |   (auto_approval)  |   Confidence-based triage:
                   |                    |     >= 85%: auto-approve
                   |                    |     50-85%: needs_review
                   |                    |     < 50%: auto-reject
                   |                    |   Category-specific thresholds
                   |                    |   (enforcement: 90%)
                   +--------+-----------+
                            |
                  +---------+---------+
                  |         |         |
                  v         v         v
            auto_approve  review  auto_reject
                  |         |
                  v         v
           +-----------+  +-------------+
           | INCIDENT  |  | CURATION    |
           | (created) |  | QUEUE       |
           +-----------+  | (human      |
                          |  review)    |
                          +------+------+
                                 |
                           approve/reject
                                 |
                                 v
                          +-----------+
                          | INCIDENT  |
                          | (created) |
                          +-----------+
```

### Full Pipeline Task

The `run_full_pipeline` Celery task chains all three I/O stages sequentially:
Fetch -> Enrich -> Extract. The deduplication and auto-approval stages run
inline within the extraction step via `UnifiedPipeline.process_single()`.

---

## Two Extraction Pipelines

The system supports two extraction pipelines. The active pipeline for an article
is recorded in `ingested_articles.extraction_pipeline` (`'legacy'` or `'two_stage'`).

### Legacy Pipeline (One-Shot)

A single LLM call extracts all structured fields from the article text. The
result is stored in `ingested_articles.extracted_data` (JSONB column).

```
Article Text --> LLM (single call) --> extracted_data (JSONB)
```

- Implemented in `services/llm_extraction.py` (`LLMExtractor.extract()`)
- Uses prompts from `services/extraction_prompts.py` or database-backed prompts
  via `PromptManager`
- Supports category-aware extraction (enforcement vs crime prompts)

### Two-Stage Pipeline (Preferred)

Two sequential LLM calls produce a richer, more flexible extraction.

```
Article Text
     |
     v
+------------------+
| Stage 1 (IR)     |   Comprehensive entity/event extraction.
| article_          |   Produces a reusable intermediate
|   extractions     |   representation: entities, events,
|                   |   legal data, quotes, classification.
+--------+---------+
         |
         v
+------------------+
| Stage 2 (Schema) |   Domain-specific schema extraction.
| schema_extraction |   Multiple schemas run against the
|   _results        |   Stage 1 IR + original text.
|                   |   Each produces per-category output.
+--------+---------+
         |
         v
+------------------+
| Stage 2 Selector |   Selects best result using domain
| (stage2_selector)|   priority + confidence scoring.
|                  |   Merges complementary schemas about
|                  |   the same entity. Prevents cross-
|                  |   contamination between entities.
+------------------+
```

- Stage 1: `services/two_stage_extraction.py` (`run_stage1()`)
- Stage 2: `services/two_stage_extraction.py` (`run_stage2()`)
- Selection: `services/stage2_selector.py` (`select_and_merge_stage2()`)
- Schema routing uses classification confidence from Stage 1 (threshold: 0.3)
- Domain priority ordering: Immigration (100) > Criminal Justice (50) > Civil Rights (25)

---

## Three Data Layers

The database has three coexisting data models, each introduced at a different
phase of development. All three are active; code must handle all of them.

### Layer 1: Person-Centric (Legacy)

```
incidents ---< incident_persons >--- persons
```

- Tables: `persons`, `incident_persons`
- Original model from initial development
- Persons have roles (victim, offender, witness, officer)
- Still referenced by import scripts and actor migration logic
- **Not recommended for new code**

### Layer 2: Event-Centric (Active, Preferred)

```
event_domains ---< event_categories
                        |
incidents ---< incident_actors >--- actors
    |                                  |
    +---< incident_events >--- events  +---< actor_relations
```

- Tables: `actors`, `incident_actors`, `events`, `incident_events`,
  `actor_relations`, `actor_role_types`, `event_domains`, `event_categories`
- Introduced in migration 002, extended through migrations 009-010
- Actors are typed: person, organization, agency, group
- Roles are extensible via `actor_role_types` table
- Events support domain/category taxonomy (`event_domains` -> `event_categories`)
- **Preferred for all new code**

### Layer 3: Case-Centric (Active)

```
cases ---< charges ---< charge_history
  |                         |
  +---< dispositions        +--- bail_decisions
  |
  +---< case_incidents >--- incidents
  |
  +---< case_actors >--- actors
  |
  +---< prosecutorial_actions
  |
  +---< case_jurisdictions >--- jurisdictions
```

- Tables: `cases`, `charges`, `charge_history`, `dispositions`,
  `case_incidents`, `case_actors`, `prosecutorial_actions`, `bail_decisions`,
  `case_jurisdictions`
- Introduced in migration 013
- Legal case lifecycle tracking: charges -> prosecution -> disposition
- Links cases to both incidents and actors
- Supports recidivism analysis and prosecutor dashboards

---

## Key Service Dependencies

The backend services form a layered dependency graph. Services are singletons
accessed via `get_*()` factory functions.

```
unified_pipeline
  +-- duplicate_detection    (URL, title, content, entity matching)
  +-- llm_extraction         (legacy one-shot extraction)
  |     +-- llm_provider     (LLM router: Anthropic / Ollama)
  |     +-- prompt_manager   (database-backed prompts, optional)
  |     +-- extraction_prompts (hardcoded prompt templates)
  +-- auto_approval          (confidence-based triage)
  |     +-- thresholds       (configurable threshold constants)
  |     +-- incident_type_service (DB-backed thresholds, optional)
  +-- two_stage_extraction   (Stage 1 + Stage 2 pipeline)
  |     +-- llm_provider
  |     +-- extraction_prompts
  +-- stage2_selector        (domain-priority merge of Stage 2 results)
  +-- pipeline_orchestrator  (configurable stage runner, optional)

enrichment_service           (cross-reference + targeted re-extraction)
  +-- llm_provider

domain_service               (event domain/category CRUD)
incident_type_service        (incident type CRUD + approval thresholds)
incident_creation_service    (creates incidents from approved extractions)
actor_service                (actor CRUD + deduplication)
event_service                (event CRUD + clustering)
criminal_justice_service     (case/charge/disposition CRUD)
recidivism_service           (recidivism analysis queries)
settings                     (in-memory config with cache TTL)
circuit_breaker              (LLM call protection)
```

---

## Background Processing

### Celery Queue Topology

Four queues isolate different workload types:

| Queue | Workers | Concurrency | Tasks |
|---|---|---|---|
| `default` | celery-worker-default | 2 | `run_full_pipeline`, `cleanup_stale_jobs`, `aggregate_metrics`, `refresh_materialized_views` |
| `extraction` | celery-worker-extraction | 1 | `run_process` (single article), `run_batch_extract` |
| `fetch` | celery-worker-fetch | 2 | `run_fetch`, `scheduled_fetch` |
| `enrichment` | celery-worker-default | 2 | `run_batch_enrich`, `run_enrichment` |

Extraction uses concurrency 1 to respect LLM API rate limits.

### Celery Beat Schedule

| Schedule | Task | Purpose |
|---|---|---|
| Every hour (:00) | `scheduled_fetch` | Pull new articles from RSS feeds |
| Every 15 minutes | `cleanup_stale_jobs` | Detect and retry/fail stale running jobs |
| Every 5 minutes | `aggregate_metrics` | Roll up `task_metrics` into 5-minute buckets |
| Every 6 hours (:30) | `refresh_materialized_views` | Refresh `prosecutor_stats` and `recidivism_analysis` views |

### Retry Policies

Each task category has independently configurable retry parameters via
environment variables:

| Task Category | Max Retries | Initial Backoff | Max Backoff |
|---|---|---|---|
| Fetch (RSS) | 5 | 60s | 600s |
| Extract (single) | 3 | 300s | 1800s |
| Extract (batch) | 2 | 300s | 1800s |
| Enrich (batch) | 3 | 120s | 600s |
| Enrich (cross-ref) | 2 | 300s | 1800s |
| Full pipeline | 1 | 600s | 1800s |

### Reliability Settings

- `task_acks_late = True` -- ACK only after task completes
- `worker_prefetch_multiplier = 1` -- one task at a time per worker process
- `task_reject_on_worker_lost = True` -- re-queue on worker crash

### Legacy Job Executor

When `USE_CELERY=false`, the `JobExecutor` (in `services/job_executor.py`) runs
in-process within the FastAPI server. It polls the `background_jobs` table for
pending jobs and executes them sequentially. This is deprecated but retained for
environments without Redis.

### WebSocket Job Updates

`JobUpdateManager` (in `jobs_ws.py`) maintains WebSocket connections to frontend
clients and broadcasts job status snapshots every 2 seconds. Immediate
notifications are sent on job creation and cancellation.

---

## LLM Integration

### Provider Architecture

`LLMRouter` (in `services/llm_provider.py`) abstracts LLM calls behind a
unified interface with automatic fallback.

```
LLMRouter
  +-- AnthropicProvider    Anthropic Claude (via anthropic SDK)
  +-- OllamaProvider       Local Ollama (via OpenAI-compatible API)
```

- **Primary provider:** Anthropic Claude (`claude-sonnet-4-20250514` default)
- **Fallback:** Configurable; Anthropic can fall back to Ollama and vice versa
- **Model config:** Runtime-configurable via `SettingsService` -> `LLMSettings`
- **Timeout:** 120s default (`LLM_API_TIMEOUT_SECONDS` env var)
- **Error handling:** `LLMError` hierarchy with `ErrorCategory` (transient,
  partial, permanent). Only transient/partial errors trigger fallback; permanent
  errors (auth, invalid request) re-raise immediately.

### LLM Call Flow

```
Service (extraction, enrichment, triage)
     |
     v
LLMRouter.call(system_prompt, user_message, provider, model)
     |
     +---> Primary Provider.call()
     |         |
     |         +---> Success: return LLMResponse
     |         |
     |         +---> Transient error: try fallback
     |
     +---> Fallback Provider.call()
               |
               +---> Success: return LLMResponse
               +---> Failure: raise LLMError
```

### Prompt Management

Two prompt sources, with database taking priority when available:

1. **Hardcoded prompts** (`services/extraction_prompts.py`): Stage 1 schema,
   triage schema, universal extraction schema, category-specific prompts.
2. **Database-backed prompts** (`services/prompt_manager.py`): Stored in the
   `prompts` table with versioning, A/B testing, and execution tracking.
   Queried by the `PromptManager` service.

---

## Database

### Connection Management

`database.py` manages an `asyncpg` connection pool:

- Pool size: 2-10 connections (configurable via `DB_POOL_MIN_SIZE`, `DB_POOL_MAX_SIZE`)
- JSON/JSONB codecs registered on each connection
- 60-second command timeout
- Context managers: `get_connection()`, `get_transaction()`
- Helper functions: `fetch()`, `fetchrow()`, `fetchval()`, `execute()`, `executemany()`

### Key Tables

| Table | Layer | Purpose |
|---|---|---|
| `incidents` | Core | Approved incidents with location, type, source, outcome |
| `ingested_articles` | Pipeline | Raw articles from RSS feeds with extraction status |
| `article_extractions` | Pipeline | Stage 1 intermediate representations (two-stage) |
| `schema_extraction_results` | Pipeline | Stage 2 per-schema outputs (two-stage) |
| `curation_queue` | Pipeline | Articles awaiting human review |
| `sources` | Core | RSS feeds and other data sources |
| `actors` | Layer 2 | Typed entities (person, org, agency, group) |
| `events` | Layer 2 | Discrete events linked to incidents |
| `cases` | Layer 3 | Legal cases with charges and dispositions |
| `background_jobs` | System | Job queue for background processing |
| `task_metrics` | System | Per-task performance metrics |
| `event_domains` | Taxonomy | Top-level domain groupings (Immigration, CJ, CR) |
| `event_categories` | Taxonomy | Hierarchical categories within domains |
| `incident_types` | Core | Typed incident classifications with severity weights |
| `jurisdictions` | Core | States/counties with sanctuary policy data |
| `prompts` | Config | Database-backed LLM prompts with versioning |

### Materialized Views

Two materialized views provide pre-computed analytics, refreshed every 6 hours:

- `prosecutor_stats` -- Aggregated prosecution metrics by jurisdiction
- `recidivism_analysis` -- Repeat offender analysis across incidents

### Extensions

- `uuid-ossp` -- UUID generation
- `pg_trgm` -- Fuzzy text search (trigram matching)

---

## Frontend Architecture

### Stack

- **Framework:** React 18 with TypeScript
- **Build:** Vite
- **Map:** Leaflet with OpenStreetMap tiles
- **Charts:** Recharts
- **Styling:** CSS files (no Tailwind, no component library)

### Application Structure

The app has two main modes: the **map dashboard** (default) and the **admin panel**.

```
App.tsx (map dashboard)
  +-- useIncidentData        (data fetching, filters, domain state)
  +-- useIncidentSelection   (selected incident, detail loading)
  +-- useTimelinePlayback    (date-based animation)
  +-- useKeyboardNavigation  (arrow key incident cycling)
  +-- IncidentMap            (Leaflet map with markers)
  +-- IncidentListSidebar    (filterable incident list)
  +-- IncidentDetailDrawer   (selected incident details)
  +-- StatsBar               (aggregate statistics)
  +-- TimelineControls       (playback controls)
  +-- Charts                 (Recharts visualizations)
  +-- MapLegend / HeatmapLayer / StreetViewPanel / EventBanner

AdminPanel.tsx (admin views)
  +-- PipelineView           (pipeline monitoring, job control)
  +-- IncidentBrowser        (search, edit, manage incidents)
  +-- AnalyticsDashboard     (pipeline metrics, funnels)
  +-- IncidentTypeManager    (incident type CRUD)
  +-- PromptManager          (prompt editing and testing)
  +-- PromptTestRunner       (A/B prompt testing)
  +-- DomainManager          (event domain/category config)
  +-- EventBrowser           (event search and detail)
  +-- ActorBrowser           (actor search and detail)
  +-- CaseManager            (case/charge/disposition management)
  +-- ProsecutorDashboard    (prosecution analytics)
  +-- RecidivismDashboard    (recidivism analysis)
  +-- SettingsPanel          (system configuration)
  +-- QueueStatusBar         (curation queue stats)
```

### API Layer

`frontend/src/api.ts` provides typed fetch wrappers for all backend endpoints.
All requests go through a central `fetchJSON<T>()` function that:

- Checks `response.ok` and throws `ApiError` with status and detail on failure
- Returns typed JSON responses
- Uses `/api` as the base path (proxied to backend via Vite config)

### State Management

No external state library. State is managed through:

- **Custom hooks** (`useIncidentData`, `useIncidentSelection`, `useTimelinePlayback`,
  `useKeyboardNavigation`) encapsulate data fetching and derived state
- **URL params** for filter persistence (date range, states, categories)
- **localStorage** for user preferences (dark mode, collapsed stats)
- **WebSocket** for real-time job status updates

### Error Handling

- `ErrorBoundary` component wraps major sections to prevent full-page crashes
- API errors surface as `ApiError` instances with HTTP status and server detail
- Loading and error states are handled per-component

---

## Backend Route Modules

API routes are organized into 14 modules registered in `routes/__init__.py`:

| Module | Prefix | Responsibility |
|---|---|---|
| `incidents` | `/api/incidents` | Public incident queries, stats, filters |
| `curation` | `/api/curation` | Curation queue: review, approve, reject |
| `admin_incidents` | `/api/admin/incidents` | Admin CRUD for incidents |
| `jobs` | `/api/jobs` | Background job management, WebSocket |
| `settings` | `/api/settings` | Runtime configuration CRUD |
| `feeds` | `/api/feeds` | RSS feed/source management |
| `domains` | `/api/domains` | Event domain/category CRUD |
| `types_prompts` | `/api/types`, `/api/prompts` | Incident type and prompt management |
| `events_actors` | `/api/events`, `/api/actors` | Event and actor queries |
| `analytics` | `/api/analytics` | Pipeline metrics, dashboards |
| `extraction` | `/api/extraction` | Extraction management, two-stage ops |
| `cases` | `/api/cases` | Case/charge/disposition CRUD |
| `testing` | `/api/testing` | Prompt testing endpoints |
| `recidivism` | `/api/recidivism` | Recidivism analysis queries |

---

## Configuration

### Environment Variables

Key variables (see `.env.example`):

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude |
| `USE_DATABASE` | Enable database connection (`true`/`false`) |
| `USE_CELERY` | Use Celery workers vs in-process executor |
| `REDIS_URL` / `CELERY_BROKER_URL` | Redis connection for Celery |
| `OLLAMA_BASE_URL` | Ollama server URL (default: `http://localhost:11434/v1`) |
| `LLM_API_TIMEOUT_SECONDS` | LLM call timeout (default: 120) |
| `DB_POOL_MIN_SIZE` / `DB_POOL_MAX_SIZE` | Connection pool sizing |
| `SETTINGS_CACHE_TTL` | Settings cache TTL in seconds (default: 60) |

### Runtime Settings

The `SettingsService` manages runtime configuration in memory with a cache:

- **Auto-approval settings:** Confidence thresholds, required fields, severity gates
- **Duplicate detection settings:** Similarity thresholds, strategy toggles
- **LLM settings:** Default model, per-stage model/provider overrides, fallback config
- **Category-specific overrides:** Enforcement (90% threshold), Crime (85%), Domain (85%)

Settings can be overridden per-incident-type via the `incident_types.approval_thresholds`
JSONB column.
