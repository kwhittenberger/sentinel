# Sentinel API Reference

**Base URL:** `http://localhost:8000`
**Total endpoints:** 120 (118 REST + 1 WebSocket + 1 health check)

---

## Table of Contents

- [Health](#health)
- [Incidents (Public)](#incidents-public) -- 6 endpoints
- [Curation Queue](#curation-queue) -- 18 endpoints
- [Admin Incidents](#admin-incidents) -- 8 endpoints
- [Jobs](#jobs) -- 9 endpoints (+ 1 WebSocket)
- [Settings & Config](#settings--config) -- 18 endpoints
- [Feeds](#feeds) -- 6 endpoints
- [Domains & Categories](#domains--categories) -- 7 endpoints
- [Types & Prompts](#types--prompts) -- 14 endpoints
- [Events & Actors](#events--actors) -- 15 endpoints
- [Analytics](#analytics) -- 5 endpoints
- [Extraction & Pipeline](#extraction--pipeline) -- 16 endpoints
- [Cases & Legal](#cases--legal) -- 17 endpoints
- [Testing & Calibration](#testing--calibration) -- 13 endpoints
- [Recidivism](#recidivism) -- 10 endpoints
- [Curl Examples](#curl-examples)

---

## Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |

---

## Incidents (Public)

Read-only endpoints for the dashboard.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/incidents` | List incidents with filters |
| GET | `/api/incidents/{incident_id}` | Get single incident with sources, actors, events |
| GET | `/api/incidents/{incident_id}/connections` | Get connected incidents via shared events |
| GET | `/api/stats` | Summary statistics (totals, by-tier, by-state, pipeline stats) |
| GET | `/api/filters` | Available filter options (states, categories, date range) |
| GET | `/api/domains-summary` | Event domains with categories for dropdowns |

**Key query params for `GET /api/incidents`:**

| Param | Type | Description |
|-------|------|-------------|
| `tiers` | string | Comma-separated tier numbers |
| `states` | string | Comma-separated state codes |
| `category` | string | `enforcement` or `crime` |
| `date_start` / `date_end` | string | Date range (YYYY-MM-DD) |
| `search` | string | Full-text search across notes, names, descriptions |
| `event_id` | string | Filter to incidents linked to an event |
| `death_only` | bool | Only fatal outcomes |
| `gang_affiliated` | bool | Filter by gang affiliation |

**Response:** `{ "incidents": [...], "total": int }`

---

## Curation Queue

Article ingestion, review, extraction, and approval workflows.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/status` | Data status (tier counts, sources, data files) |
| POST | `/api/admin/pipeline/fetch` | Fetch data from sources |
| POST | `/api/admin/pipeline/process` | Process existing data (validate, normalize, dedupe) |
| POST | `/api/admin/pipeline/run` | Run full pipeline (fetch + process + save) |
| GET | `/api/admin/queue` | List curation queue items |
| GET | `/api/admin/queue/tiered` | Queue items grouped by confidence tier |
| GET | `/api/admin/queue/extraction-status` | Queue breakdown by extraction/pipeline stage |
| GET | `/api/admin/queue/{article_id}` | Single queue item with full details |
| GET | `/api/admin/queue/{article_id}/suggestions` | AI suggestions for low-confidence fields |
| GET | `/api/admin/articles/audit` | Article audit with extraction quality analysis |
| POST | `/api/admin/queue/submit` | Submit article for curation |
| POST | `/api/admin/queue/bulk-approve` | Bulk approve articles in a confidence tier |
| POST | `/api/admin/queue/bulk-reject` | Bulk reject articles in a confidence tier |
| POST | `/api/admin/queue/bulk-reject-by-criteria` | Reject by IDs, relevance, or confidence threshold |
| POST | `/api/admin/queue/auto-approve` | Evaluate pending articles against approval thresholds |
| POST | `/api/admin/queue/triage` | Quick triage on queue items for relevance |
| POST | `/api/admin/queue/batch-extract` | Run LLM extraction on queue items |
| POST | `/api/admin/queue/{article_id}/extract-universal` | Run universal extraction on a single article |
| POST | `/api/admin/queue/{article_id}/approve` | Approve article and create incident |
| POST | `/api/admin/queue/{article_id}/reject` | Reject article with reason |
| POST | `/api/admin/reset-pipeline-data` | Nuclear reset: delete all pipeline data |
| POST | `/api/admin/backfill-actors-events` | Backfill actors/events for existing incidents |

**Approve article request body:**

```json
{
  "overrides": { "city": "Houston", "state": "TX" },
  "force_create": false,
  "link_to_existing_id": null
}
```

**Reject article request body:**

```json
{ "reason": "Not an incident article" }
```

---

## Admin Incidents

CRUD, export, and relationship management for approved incidents.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/incidents` | Paginated incident list with filters |
| GET | `/api/admin/incidents/{incident_id}` | Single incident for editing (with sources, actors, events) |
| GET | `/api/admin/incidents/{incident_id}/articles` | Ingested articles linked to an incident |
| GET | `/api/admin/incidents/{incident_id}/relationships` | Incident relationships |
| GET | `/api/admin/incidents/export` | Export incidents (JSON or CSV) |
| PUT | `/api/admin/incidents/{incident_id}` | Update incident fields |
| DELETE | `/api/admin/incidents/{incident_id}` | Soft or hard delete (`?hard_delete=true`) |
| POST | `/api/admin/incidents/relationships` | Create relationship between two incidents |

**Key query params for `GET /api/admin/incidents`:**

| Param | Type | Description |
|-------|------|-------------|
| `category` | string | `enforcement` or `crime` |
| `state` | string | State code |
| `search` | string | Text search |
| `page` / `page_size` | int | Pagination (default 1/50) |

---

## Jobs

Background job management and real-time monitoring.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/jobs` | List background jobs |
| GET | `/api/admin/jobs/{job_id}` | Get job status and details |
| POST | `/api/admin/jobs` | Create a background job |
| DELETE | `/api/admin/jobs/{job_id}` | Cancel a pending/running job |
| DELETE | `/api/admin/jobs/{job_id}/delete` | Hard-delete a terminal-state job |
| POST | `/api/admin/jobs/{job_id}/retry` | Retry a failed job |
| POST | `/api/admin/jobs/{job_id}/unstick` | Reset a stale running job |
| WS | `/ws/jobs` | Real-time job status WebSocket stream |
| GET | `/api/metrics/overview` | Queue and worker stats (Celery inspect) |
| GET | `/api/metrics/task-performance` | Per-task performance stats |

**Create job request body:**

```json
{
  "job_type": "batch_extract",
  "params": { "limit": 50 }
}
```

**Job types:** `fetch`, `process`, `batch_extract`, `batch_enrich`, `cross_reference_enrich`, `full_pipeline`

---

## Settings & Config

Application settings, duplicate detection, auto-approval, LLM provider config.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/settings` | Get all application settings |
| GET | `/api/admin/settings/auto-approval` | Auto-approval settings |
| PUT | `/api/admin/settings/auto-approval` | Update auto-approval settings |
| GET | `/api/admin/settings/duplicate` | Duplicate detection settings |
| PUT | `/api/admin/settings/duplicate` | Update duplicate detection settings |
| GET | `/api/admin/settings/pipeline` | Pipeline settings |
| PUT | `/api/admin/settings/pipeline` | Update pipeline settings |
| GET | `/api/admin/settings/event-clustering` | Event clustering settings |
| PUT | `/api/admin/settings/event-clustering` | Update event clustering settings |
| GET | `/api/admin/settings/llm` | LLM provider settings |
| PUT | `/api/admin/settings/llm` | Update LLM provider settings |
| GET | `/api/admin/duplicates/config` | Duplicate detection config |
| POST | `/api/admin/duplicates/check` | Check if an article is a duplicate |
| GET | `/api/admin/auto-approval/config` | Auto-approval config |
| PUT | `/api/admin/auto-approval/config` | Update auto-approval config |
| POST | `/api/admin/auto-approval/evaluate` | Evaluate an article for auto-approval |
| GET | `/api/admin/llm-extraction/status` | LLM extraction service availability |
| POST | `/api/admin/llm-extraction/extract` | Extract incident data from article text |
| GET | `/api/admin/pipeline/config` | Unified pipeline config/stats |
| POST | `/api/admin/pipeline/process-article` | Process single article through pipeline |
| GET | `/api/admin/llm/providers` | LLM provider availability status |
| GET | `/api/admin/llm/models` | Available models per provider |

---

## Feeds

RSS feed / data source management.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/feeds` | List all data sources |
| POST | `/api/admin/feeds` | Create a new feed |
| PUT | `/api/admin/feeds/{feed_id}` | Update a feed |
| DELETE | `/api/admin/feeds/{feed_id}` | Delete a feed |
| POST | `/api/admin/feeds/{feed_id}/fetch` | Manually fetch a specific feed |
| POST | `/api/admin/feeds/{feed_id}/toggle` | Enable or disable a feed |

**Create feed request body:**

```json
{
  "name": "Example News RSS",
  "url": "https://example.com/feed.xml",
  "source_type": "news",
  "tier": 3,
  "interval_minutes": 60
}
```

---

## Domains & Categories

Event domain and category configuration.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/domains` | List event domains |
| POST | `/api/admin/domains` | Create a domain |
| GET | `/api/admin/domains/{slug}` | Get domain by slug |
| PUT | `/api/admin/domains/{slug}` | Update a domain |
| GET | `/api/admin/domains/{slug}/categories` | List categories in a domain |
| POST | `/api/admin/domains/{slug}/categories` | Create category in a domain |
| GET | `/api/admin/categories/{category_id}` | Get category with field definitions |
| PUT | `/api/admin/categories/{category_id}` | Update a category |

---

## Types & Prompts

Incident type configuration and LLM prompt versioning.

### Incident Types

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/types` | List incident types |
| GET | `/api/admin/types/{type_id}` | Get type with fields and pipeline config |
| POST | `/api/admin/types` | Create incident type |
| PUT | `/api/admin/types/{type_id}` | Update incident type |
| GET | `/api/admin/types/{type_id}/fields` | Get field definitions |
| POST | `/api/admin/types/{type_id}/fields` | Create field definition |

### Prompts

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/prompts` | List prompts |
| GET | `/api/admin/prompts/{prompt_id}` | Get prompt with version history |
| POST | `/api/admin/prompts` | Create prompt |
| PUT | `/api/admin/prompts/{prompt_id}` | Update prompt (creates new version) |
| POST | `/api/admin/prompts/{prompt_id}/activate` | Activate a prompt version |
| GET | `/api/admin/prompts/{prompt_id}/executions` | Prompt execution statistics |
| GET | `/api/admin/prompts/token-usage` | Token usage and cost summary |

---

## Events & Actors

Event tracking, actor management, merge tools, and legacy person endpoints.

### Events

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/events` | List events with filters |
| GET | `/api/events/suggestions` | AI-suggested event groupings |
| GET | `/api/events/{event_id}` | Get event with linked incidents and actors |
| POST | `/api/events` | Create an event |
| POST | `/api/events/{event_id}/incidents` | Link incident to event |
| DELETE | `/api/events/{event_id}/incidents/{incident_id}` | Unlink incident from event |

### Actors

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/actors` | List or search actors |
| GET | `/api/actors/merge-suggestions` | Suggested duplicate actors |
| GET | `/api/actors/{actor_id}` | Actor with incident history and relations |
| GET | `/api/actors/{actor_id}/similar` | Find similar actors (trigram matching) |
| POST | `/api/actors` | Create an actor |
| PUT | `/api/actors/{actor_id}` | Update an actor |
| POST | `/api/actors/merge` | Merge duplicate actors |
| POST | `/api/actors/{actor_id}/incidents` | Link actor to incident |

### Persons (Legacy)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/persons` | List persons (stub) |
| GET | `/api/persons/{person_id}` | Get person details (stub) |

---

## Analytics

Dashboard and pipeline analytics.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/stats/comparison` | Enforcement vs. crime comparison by state |
| GET | `/api/stats/sanctuary` | Sanctuary policy correlation analysis |
| GET | `/api/admin/analytics/overview` | Admin dashboard overview (incidents + queue) |
| GET | `/api/admin/analytics/conversion` | Ingestion-to-approval conversion funnel |
| GET | `/api/admin/analytics/sources` | Analytics by source (approval rate, confidence) |
| GET | `/api/admin/analytics/geographic` | Analytics by state |

---

## Extraction & Pipeline

Pipeline orchestration, enrichment, extraction schemas, and two-stage extraction.

### Pipeline

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/pipeline/stages` | List available pipeline stages |
| POST | `/api/admin/pipeline/execute` | Execute configurable pipeline on an article |

### Enrichment

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/enrichment/stats` | Missing field counts and enrichment summary |
| GET | `/api/admin/enrichment/candidates` | Preview enrichable incidents |
| POST | `/api/admin/enrichment/run` | Start enrichment job |
| GET | `/api/admin/enrichment/runs` | Enrichment run history |
| GET | `/api/admin/enrichment/log/{incident_id}` | Enrichment audit log for an incident |
| POST | `/api/admin/enrichment/revert/{log_id}` | Revert a specific enrichment change |

### Extraction Schemas

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/extraction-schemas` | List extraction schemas |
| GET | `/api/admin/extraction-schemas/{schema_id}` | Get schema details |
| POST | `/api/admin/extraction-schemas` | Create schema |
| PUT | `/api/admin/extraction-schemas/{schema_id}` | Update schema |
| POST | `/api/admin/extraction-schemas/{schema_id}/extract` | Run extraction against a schema |
| GET | `/api/admin/extraction-schemas/{schema_id}/quality` | Production quality metrics |
| POST | `/api/admin/extraction-schemas/{schema_id}/deploy` | Deploy schema to production |
| POST | `/api/admin/extraction-schemas/{schema_id}/rollback` | Rollback to previous version |

### Two-Stage Extraction

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/admin/two-stage/extract-stage1` | Run Stage 1 comprehensive extraction |
| POST | `/api/admin/two-stage/extract-stage2` | Run Stage 2 schema extractions |
| POST | `/api/admin/two-stage/extract-full` | Full two-stage pipeline (Stage 1 + 2) |
| POST | `/api/admin/two-stage/reextract` | Re-run Stage 2 without re-running Stage 1 |
| GET | `/api/admin/two-stage/status/{article_id}` | Extraction pipeline status for article |
| GET | `/api/admin/two-stage/extractions/{extraction_id}` | Stage 1 extraction with Stage 2 results |
| POST | `/api/admin/two-stage/batch-extract` | Batch two-stage pipeline with circuit breaker |

---

## Cases & Legal

Criminal justice case tracking, charges, bail, dispositions, prosecutor stats.

### Cases

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/cases` | List cases with filters |
| POST | `/api/admin/cases` | Create a case |
| GET | `/api/admin/cases/{case_id}` | Get case by ID |
| PUT | `/api/admin/cases/{case_id}` | Update a case |

### Charges

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/cases/{case_id}/charges` | List charges for a case |
| POST | `/api/admin/cases/{case_id}/charges` | Create a charge |
| PUT | `/api/admin/charges/{charge_id}` | Update a charge |
| GET | `/api/admin/cases/{case_id}/charge-history` | Charge history for a case |
| POST | `/api/admin/charge-history` | Record a charge history event |

### Prosecutorial & Bail

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/cases/{case_id}/prosecutorial-actions` | List prosecutorial actions |
| POST | `/api/admin/prosecutorial-actions` | Create prosecutorial action |
| GET | `/api/admin/cases/{case_id}/bail-decisions` | List bail decisions |
| POST | `/api/admin/bail-decisions` | Create bail decision |

### Dispositions

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/cases/{case_id}/dispositions` | List dispositions |
| POST | `/api/admin/dispositions` | Create disposition |

### Case Linking

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/cases/{case_id}/incidents` | Incidents linked to a case |
| POST | `/api/admin/cases/{case_id}/incidents` | Link incident to case |
| GET | `/api/admin/cases/{case_id}/actors` | Actors linked to a case |
| POST | `/api/admin/cases/{case_id}/actors` | Link actor to case |

### Prosecutor Stats

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/prosecutor-stats` | Prosecutor performance stats |
| POST | `/api/admin/prosecutor-stats/refresh` | Refresh materialized view |

---

## Testing & Calibration

Prompt testing, model comparison, calibration workflows.

### Test Datasets & Cases

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/prompt-tests/datasets` | List test datasets |
| POST | `/api/admin/prompt-tests/datasets` | Create test dataset |
| GET | `/api/admin/prompt-tests/datasets/{dataset_id}` | Get test dataset |
| GET | `/api/admin/prompt-tests/datasets/{dataset_id}/cases` | List test cases in dataset |
| POST | `/api/admin/prompt-tests/cases` | Create test case |

### Test Runs

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/prompt-tests/runs` | List test runs |
| GET | `/api/admin/prompt-tests/runs/{run_id}` | Get test run details |
| POST | `/api/admin/prompt-tests/run` | Execute a test suite |

### Model Comparisons

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/prompt-tests/comparisons` | List comparisons |
| GET | `/api/admin/prompt-tests/comparisons/{id}` | Get comparison |
| GET | `/api/admin/prompt-tests/comparisons/{id}/runs` | Get comparison runs |
| POST | `/api/admin/prompt-tests/comparisons` | Create and run comparison |

### Calibration

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/admin/prompt-tests/calibrations` | Create and run calibration |
| POST | `/api/admin/prompt-tests/pipeline-calibrations` | Create pipeline calibration |
| GET | `/api/admin/prompt-tests/calibrations/{id}/articles` | List calibration articles |
| POST | `/api/admin/prompt-tests/calibrations/{id}/articles/{article_id}/review` | Review calibration article |
| POST | `/api/admin/prompt-tests/calibrations/{id}/save-dataset` | Save calibration as test dataset |
| POST | `/api/admin/prompt-tests/generate-prompt-improvement` | Generate prompt improvement suggestions |

---

## Recidivism

Recidivism analytics and import saga management.

### Analytics

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/recidivism/summary` | Recidivism analytics summary |
| GET | `/api/admin/recidivism/actors` | List recidivist actors |
| GET | `/api/admin/recidivism/actors/{actor_id}` | Full recidivism profile |
| GET | `/api/admin/recidivism/actors/{actor_id}/history` | Actor incident history |
| GET | `/api/admin/recidivism/actors/{actor_id}/indicator` | Recidivism indicator |
| GET | `/api/admin/recidivism/actors/{actor_id}/lifecycle` | Defendant lifecycle |
| POST | `/api/admin/recidivism/refresh` | Refresh recidivism materialized view |

### Import Sagas

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/import-sagas` | List import sagas |
| POST | `/api/admin/import-sagas` | Create import saga |
| PUT | `/api/admin/import-sagas/{saga_id}` | Update import saga |

---

## Curl Examples

### Fetch incidents with filters

```bash
curl 'http://localhost:8000/api/incidents?category=crime&states=TX,CA&date_start=2025-01-01&death_only=true'
```

### Get queue stats (extraction status breakdown)

```bash
curl http://localhost:8000/api/admin/queue/extraction-status
```

### Approve an article

```bash
curl -X POST http://localhost:8000/api/admin/queue/{article_id}/approve \
  -H 'Content-Type: application/json' \
  -d '{"overrides": {"city": "Houston"}, "force_create": false}'
```

### Reject an article

```bash
curl -X POST http://localhost:8000/api/admin/queue/{article_id}/reject \
  -H 'Content-Type: application/json' \
  -d '{"reason": "Not an incident report"}'
```

### Create an incident (via article approval pipeline)

```bash
# Submit article, then approve it to create an incident:
# Step 1: Submit
curl -X POST http://localhost:8000/api/admin/queue/submit \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://example.com/article",
    "title": "Example Incident",
    "content": "Full article text...",
    "source_name": "Example News",
    "run_extraction": true
  }'

# Step 2: Approve (creates incident)
curl -X POST http://localhost:8000/api/admin/queue/{article_id}/approve \
  -H 'Content-Type: application/json' \
  -d '{}'
```

### Create a background job

```bash
curl -X POST http://localhost:8000/api/admin/jobs \
  -H 'Content-Type: application/json' \
  -d '{"job_type": "batch_extract", "params": {"limit": 25}}'
```

### Run batch two-stage extraction

```bash
curl -X POST http://localhost:8000/api/admin/two-stage/batch-extract \
  -H 'Content-Type: application/json' \
  -d '{"limit": 20}'
```

### Export incidents as CSV

```bash
curl 'http://localhost:8000/api/admin/incidents/export?format=csv&category=crime' \
  -o incidents.csv
```
