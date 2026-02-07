# Sentinel Codebase Audit

**Date:** 2026-02-07
**Scope:** Full codebase inventory and quality audit
**Type:** Documentation only (no code changes)

---

## Table of Contents

1. [Codebase Inventory](#codebase-inventory)
2. [Backend Issues](#backend-issues)
3. [Frontend Issues](#frontend-issues)
4. [Database Issues](#database-issues)
5. [Documentation Gaps](#documentation-gaps)
6. [Functionality Gaps](#functionality-gaps)
7. [Positive Findings](#positive-findings)

---

## Codebase Inventory

### Summary Statistics

| Layer | Files | Lines (approx) |
|-------|-------|-----------------|
| Backend (Python) | 62 | ~25,500 |
| Frontend (React/TS) | 40 | ~21,000 |
| Database (SQL) | 34 | schema + 33 migrations |
| Data Pipeline | 17 | ~3,500 |
| Scripts | 6 | — |
| Shell scripts | 3 | — |
| Data files | 14 | 400 incidents |

### Backend Structure

```
backend/
├── main.py                          # 6,280 lines — FastAPI routes, WebSocket, lifespan
├── database.py                      # 159 lines — AsyncPG connection pool
├── celery_app.py                    # 97 lines — Celery broker/backend config
├── jobs_ws.py                       # 158 lines — WebSocket broadcast manager
├── metrics.py                       # 154 lines — Pipeline metrics
├── models/                          # 569 lines total
│   ├── incident.py                  # IncidentCategory, SourceTier, CurationStatus, etc.
│   ├── curation.py                  # CurationQueueItem, RefinementBatch
│   ├── person.py                    # PersonRole, Person, IncidentActor
│   ├── jurisdiction.py              # Jurisdiction, JurisdictionCreate
│   └── source.py                    # Source, SourceCreate
├── services/                        # ~14,400 lines total (24 files)
│   ├── llm_extraction.py            # 611 lines — Article→incident extraction via Claude
│   ├── auto_approval.py             # 575 lines — Confidence-based auto-approval
│   ├── duplicate_detection.py       # 758 lines — URL, title, content, entity matching
│   ├── incident_creation_service.py # 782 lines — Incident creation from extracted data
│   ├── enrichment_service.py        # 812 lines — Post-extraction enrichment
│   ├── two_stage_extraction.py      # 874 lines — Two-stage extraction framework
│   ├── extraction_prompts.py        # 895 lines — Prompt templates
│   ├── actor_service.py             # 928 lines — Actor/person management
│   ├── prompt_testing.py            # 1,596 lines — Prompt testing framework
│   ├── incident_type_service.py     # 732 lines — Incident type management
│   ├── criminal_justice_service.py  # 705 lines — Case/charge tracking
│   ├── event_service.py             # 600 lines — Event creation, clustering
│   ├── pipeline_orchestrator.py     # 407 lines — Unified pipeline execution
│   ├── unified_pipeline.py          # 356 lines — Legacy pipeline (retained)
│   ├── event_clustering.py          # 446 lines — Clustering related incidents
│   ├── job_executor.py              # 470 lines — Legacy in-process job executor
│   ├── llm_provider.py              # 288 lines — Multi-LLM routing (Anthropic, Ollama)
│   ├── prompt_manager.py            # 647 lines — DB-backed prompt versioning
│   ├── llm_errors.py                # 261 lines — LLM error classification
│   ├── stage2_selector.py           # 474 lines — Two-stage selector
│   ├── generic_extraction.py        # 482 lines — Domain-agnostic extraction
│   ├── recidivism_service.py        # 298 lines — Criminal history tracking
│   ├── domain_service.py            # 331 lines — Domain management
│   ├── settings.py                  # 272 lines — Configuration management
│   └── circuit_breaker.py           # 110 lines — Fault tolerance
├── pipeline/stages/                 # ~1,594 lines total (11 files)
│   ├── extraction.py                # Article extraction via LLM
│   ├── auto_approval.py             # Confidence-based approval
│   ├── url_dedupe.py                # URL-based deduplication
│   ├── content_dedupe.py            # Text similarity dedup
│   ├── validation.py                # Schema validation
│   ├── enrichment.py                # Data enrichment
│   ├── classification.py            # Incident type classification
│   ├── entity_resolution.py         # Actor/jurisdiction linking
│   ├── cross_reference.py           # Related incident finding
│   ├── relevance.py                 # Domain relevance scoring
│   └── pattern_detection.py         # Pattern/anomaly detection
├── tasks/                           # ~1,070 lines total (6 files)
│   ├── extraction_tasks.py          # Celery extraction tasks
│   ├── enrichment_tasks.py          # Enrichment background jobs
│   ├── fetch_tasks.py               # RSS feed fetching
│   ├── scheduled_tasks.py           # Periodic tasks
│   ├── pipeline_tasks.py            # Pipeline execution
│   └── db.py                        # Database utility tasks
└── utils/                           # 355 lines
    ├── state_normalizer.py          # State abbreviation/name normalization
    └── geocoding.py                 # City coordinate lookup, caching
```

### Frontend Structure

```
frontend/src/
├── App.tsx                     # 1,416 lines — Main dashboard (map, filters, charts)
├── AdminPanel.tsx              # 369 lines — Admin navigation/routing
├── api.ts                      # 703 lines — 66 API client functions
├── types.ts                    # 893 lines — TypeScript interfaces
├── main.tsx                    # 10 lines — React entry point
├── IncidentBrowser.tsx         # 445 lines — Search/filter incidents
├── IncidentDetailView.tsx      # 521 lines — Detail view with actors, events
├── EventBrowser.tsx            # 663 lines — Event discovery with clustering
├── ActorBrowser.tsx            # 824 lines — Actor/person search
├── CaseManager.tsx             # 753 lines — Case management (RICO)
├── DomainManager.tsx           # 815 lines — Domain/category config
├── IncidentTypeManager.tsx     # 697 lines — Incident type CRUD
├── BatchProcessing.tsx         # 824 lines — Curation queue, bulk approval
├── QueueManager.tsx            # 826 lines — Queue status/management
├── SettingsPanel.tsx           # 1,166 lines — Admin settings
├── AnalyticsDashboard.tsx      # 322 lines — Pipeline metrics
├── ProsecutorDashboard.tsx     # 271 lines — Prosecutor analytics
├── RecidivismDashboard.tsx     # 380 lines — Criminal history analytics
├── ExtractionDetailView.tsx    # 416 lines — Extraction results
├── TwoStageExtractionView.tsx  # 475 lines — Two-stage extraction UI
├── PromptManager.tsx           # 557 lines — Prompt versioning
├── PromptTestRunner.tsx        # 2,106 lines — Prompt calibration suite
├── CalibrationReviewComponents.tsx # 667 lines — Model comparison
├── EnrichmentPanel.tsx         # 1,116 lines — Enrichment display
├── ExtractionSchemaManager.tsx # 491 lines — Schema config UI
├── DataSourcesPanel.tsx        # 311 lines — Source management
├── OperationsBar.tsx           # 720 lines — Top nav and operations
├── JobDashboard.tsx            # 371 lines — Background job monitoring
├── PipelineView.tsx            # 81 lines — Pipeline visualization
├── Charts.tsx                  # 276 lines — Chart utilities
├── ComparisonCharts.tsx        # 286 lines — Model comparison charts
├── ArticleAudit.tsx            # 369 lines — Article audit trail
├── HeatmapLayer.tsx            # 178 lines — Leaflet heatmap
├── QueueStatusBar.tsx          # 95 lines — Queue status indicator
├── SplitPane.tsx               # 183 lines — Responsive split layout
├── articleHighlight.tsx        # 121 lines — Text highlighting
├── DynamicExtractionFields.tsx # 234 lines — Dynamic field rendering
└── useJobWebSocket.ts          # 94 lines — WebSocket hook
```

### Database Structure

- **schema.sql** — Full schema definition (~60 tables/views)
- **33 migrations** (001-033) — Incremental schema changes
- **Key tables:** incidents, actors, events, cases, charges, ingested_articles, article_extractions, extraction_schemas, prompt_versions
- **Key views:** incidents_summary, curation_queue, actor_incident_history, recidivism_analysis (materialized), prosecutor_stats (materialized)

### Data Pipeline

```
data_pipeline/
├── sources/           # ICE, NewsAPI, The Trace fetchers
├── processors/        # Dedup, geocoding, normalization
├── importers/         # JSON, CSV importers
├── pipeline.py        # Main ETL orchestrator
├── cli.py             # Command-line interface
└── config.py          # Configuration
```

### Key Dependencies

**Python:** FastAPI, Celery, AsyncPG, Anthropic SDK, httpx, feedparser, pandas
**JavaScript:** React 19, Vite, TypeScript, Leaflet, Recharts, react-markdown

---

## Backend Issues

### B1 — HIGH: God file `main.py`

- **File:** `backend/main.py` (6,280 lines)
- All API routes in single file; should split into route modules (incidents, curation, admin, analytics, jobs, etc.)
- Contains 100+ route handlers mixing concerns

### B2 — HIGH: Truncated LLM responses parsed without validation

- **File:** `backend/services/llm_extraction.py`
- JSON extraction from markdown blocks duplicated 4+ times (lines ~104-114, ~217-224, ~360-367, ~489-496)
- Same pattern in `llm_provider.py`
- No JSON repair library used; truncated/malformed JSON fails silently with retry or manual review
- Two truncation limits: 20,000 chars for universal extraction (line 195), 15,000 chars for category extraction (line 315)

### B3 — HIGH: No timeout on LLM calls

- **File:** `backend/services/unified_pipeline.py`
- No timeout parameter used for LLM API calls — long articles can hang indefinitely
- Also affects `backend/tasks/fetch_tasks.py` where `feedparser.parse()` has no timeout (line ~51)

### B4 — HIGH: `datetime.utcnow()` used pervasively

- **Files:** `main.py` (20+ occurrences), `jobs_ws.py`, `prompt_manager.py`, `job_executor.py`, `enrichment_service.py`, `incident_creation_service.py`, `scheduled_tasks.py`, `db.py`, `fetch_tasks.py`
- `datetime.utcnow()` is deprecated since Python 3.12; should use `datetime.now(timezone.utc)`
- ~45 total occurrences across the codebase

### B5 — MEDIUM: Model name hardcoded

- **File:** `backend/services/llm_provider.py` (lines 55, 197, 240, 267)
- Model `claude-sonnet-4-20250514` hardcoded in 4 places — should be configurable via settings

### B6 — MEDIUM: Confidence thresholds spread across 4 config classes

- **File:** `backend/services/auto_approval.py` — 4 separate config dataclasses:
  - `ApprovalConfig` (line 29): auto_approve=0.85, review=0.50, reject=0.30
  - `EnforcementApprovalConfig` (line 57): auto_approve=0.90
  - `CrimeApprovalConfig` (line 70): auto_approve=0.85
  - `DomainApprovalConfig` (line 87): auto_approve=0.85
  - Additional DB defaults (lines 307-316) repeat same values
- **File:** `backend/services/duplicate_detection.py` (lines 19-22) — separate similarity thresholds
- No single source of truth across the codebase

### B7 — MEDIUM: Similarity threshold defaults without documentation

- **File:** `backend/services/duplicate_detection.py` (lines 19-22)
- Default thresholds: `title_similarity_threshold=0.75`, `content_similarity_threshold=0.85`, `name_similarity_threshold=0.7`
- Configurable via dataclass but defaults chosen without documented rationale

### B8 — MEDIUM: Settings loaded from DB on every call

- **File:** `backend/services/settings.py` (272 lines)
- No caching or TTL for settings queries — every API call that reads settings hits the database

### B9 — MEDIUM: Broad Exception catching

- **File:** `backend/services/job_executor.py` (lines 88, 104, 217, 275, 339, 395)
- 6 instances of `except Exception as e:` — catches all error types, swallows specific error information
- Also in `backend/services/settings.py` (lines ~250-258): `except Exception: pass` silently swallows all errors

### B10 — MEDIUM: Hardcoded coordinate lookup

- **File:** `backend/utils/geocoding.py` (201 lines)
- 139 cities with hardcoded coordinates (lines 11-165) — doesn't scale for new data
- No fallback to a geocoding API

### B11 — MEDIUM: Article text truncated at 15,000 chars

- **File:** `backend/pipeline/stages/extraction.py` (lines 76-77)
- `article_text[:15000]` with appended `[Article truncated due to length]`
- No strategy for what information is lost or prioritizing important content

### B12 — LOW: Error classification is type-based (acceptable)

- **File:** `backend/services/llm_errors.py` (261 lines)
- Error classification uses `isinstance()` checks against Anthropic/OpenAI exception types (lines 35-148, 151-251)
- This is reasonable; however, classification depends on SDK exception hierarchy which could change with SDK updates

### B13 — MEDIUM: Dangerous confidence default

- **File:** `backend/services/auto_approval.py` (lines ~475-481)
- Falls back to `1.0` (100% confidence) when `field_confidence` is missing
- Missing confidence data = treated as HIGH confidence; should default to `0.0`

### B14 — LOW: Inconsistent logging

- **Files:** Multiple services
- Some use `logger.warning()`, others `logger.error()` for similar severity
- No documented logging standards

### B15 — LOW: Connection pool not configurable

- **File:** `backend/database.py`
- Pool settings not configurable via environment variables
- Hardcoded fallback password `devpassword` in DATABASE_URL default (lines ~33-36)

### B16 — LOW: String substitution in prompts

- **File:** `backend/services/prompt_manager.py`
- Prompt rendering uses basic string substitution — no template escaping

### B17 — LOW: `Optional[str] = None` without normalization

- **Files:** Multiple services
- Empty string might be passed where `None` expected — no input normalization

### B18 — LOW: Large services candidates for splitting

- `criminal_justice_service.py` (705 lines) — many methods mixing case, charge, prosecution concerns
- `prompt_testing.py` (1,596 lines) — testing framework in single service

### B19 — LOW: Task retry policies hardcoded per-task

- **File:** `backend/tasks/extraction_tasks.py` (lines 177-179, 199-207) — `autoretry_for=(ConnectionError,)`, `retry_backoff=300`
- **File:** `backend/tasks/enrichment_tasks.py` (lines 118-120) — `retry_backoff=120`
- Retry policies exist per-task but with hardcoded values; not configurable via settings or environment

---

## Frontend Issues

### F1 — HIGH: 61 of 66 API functions lack error checking

- **File:** `frontend/src/api.ts` (703 lines)
- 66 exported API functions; only 5 check `response.ok`
- Error responses from the server are silently treated as valid data
- Functions that DO check: `fetchConnections` (line 127), and 4 functions in prompt-related endpoints (lines 644-698)

### F2 — HIGH: No error boundary on App or AdminPanel

- **File:** `frontend/src/App.tsx` (1,416 lines) — no error boundary; single component error crashes entire app
- **File:** `frontend/src/AdminPanel.tsx` (369 lines) — wraps 8+ complex child views without error boundary
- Only `HeatmapLayer.tsx` (line 63) has an error boundary

### F3 — HIGH: `Promise.all` without `.catch()`

- **File:** `frontend/src/App.tsx` (line 160)
- `Promise.all([fetchIncidents(filters), fetchStats(filters)]).then(...)` — no error handler
- Failed fetches leave loading spinner visible indefinitely

### F4 — MEDIUM: God component App.tsx

- **File:** `frontend/src/App.tsx` (1,416 lines)
- Map, filters, timeline, drawer, incident list all in one component
- 13+ separate state variables for drawer content alone — prop drilling

### F5 — MEDIUM: Unsafe `as any` casts

- **Files:** 48 total occurrences across 6 files
- `IncidentDetailView.tsx` (24 occurrences), `PromptTestRunner.tsx` (14), `ActorBrowser.tsx` (3), `HeatmapLayer.tsx` (3), `ExtractionSchemaManager.tsx` (2), `SettingsPanel.tsx` (2)
- Runtime errors if data shape differs from assumptions

### F6 — MEDIUM: Array `.map()` without null check

- **File:** `frontend/src/IncidentDetailView.tsx`
- `charges.map()` called on potentially null/undefined array
- Also: `ExtractionDetailView.tsx` assumes `data.incident`, `data.actors`, `data.events` exist

### F7 — MEDIUM: Race condition in BatchProcessing

- **File:** `frontend/src/BatchProcessing.tsx`
- `loadFullArticle()` doesn't abort previous requests; rapid item selection causes concurrent fetches with wrong data displayed
- Parallel state for `selectedItem` and `fullArticle` — sync issues

### F8 — MEDIUM: Timeline animation race condition

- **File:** `frontend/src/App.tsx` (lines ~402-414)
- `setIsPlaying` and `setTimelineDate` can create inconsistent state
- Play/pause button may show wrong state while animation continues briefly

### F9 — MEDIUM: Poll interval accumulation

- **File:** `frontend/src/QueueManager.tsx` (lines ~95-127)
- `pollCountRef` uses object mutation; interval polling could accumulate on component remount without proper cleanup

### F10 — MEDIUM: Missing keyboard navigation (WCAG)

- **File:** `frontend/src/SplitPane.tsx` (lines ~85-103)
- Divider has `role="separator"` but no keyboard navigation (Tab, Arrow key handlers)

### F11 — MEDIUM: Color-only marker differentiation

- **File:** `frontend/src/App.tsx` (lines ~337-341)
- Map markers use color-only differentiation (red/orange) — fails WCAG for colorblind users

### F12 — MEDIUM: ReactMarkdown allows HTML

- **File:** `frontend/src/articleHighlight.tsx` (lines ~95-130)
- `ReactMarkdown` allows HTML in user/LLM content — potential XSS vector

### F13 — MEDIUM: No extraction data schema validation

- **File:** `frontend/src/ExtractionDetailView.tsx`
- No schema validation on LLM extraction data before render
- Assumes specific structure from `extractedData`

### F14 — LOW: `loadIncidents` useCallback recreation

- **File:** `frontend/src/IncidentBrowser.tsx` (lines ~42-70)
- `useCallback` recreates on any filter change, triggering extra API calls via `useEffect`

### F15 — LOW: Silent WebSocket error swallowing

- **File:** `frontend/src/useJobWebSocket.ts` (line 58)
- `catch { }` — silently ignores all malformed message errors

### F16 — LOW: Magic numbers

- **File:** `frontend/src/QueueManager.tsx` (line ~163)
- `estimatedTime = batchSize * 2` with no explanation of the multiplier

### F17 — LOW: Type cast instead of proper interface

- **File:** `frontend/src/Charts.tsx` (lines ~24-31)
- `as Record<string, { state: string; ... }>` instead of proper interface definition

### F18 — LOW: URL date parameters not validated

- **File:** `frontend/src/App.tsx` (lines ~101-121)
- `date_start` from URL not validated as a valid date before use

### F19 — LOW: Non-null assertions on coordinates

- **File:** `frontend/src/App.tsx` (lines ~354-363)
- `incident.lat!` and `incident.lon!` — non-null assertions on potentially null values

### F20 — LOW: Success/error messages never auto-dismiss

- **File:** `frontend/src/BatchProcessing.tsx`
- UI messages persist indefinitely; user must manually close

### F21 — LOW: `Record<string, any>` loses type safety

- **File:** `frontend/src/api.ts` — `generatePromptImprovement` uses `Record<string, any>`

### F22 — LOW: Missing `aria-label` on interactive elements

- **Files:** Multiple components
- Interactive elements lack accessible labels for screen readers

---

## Database Issues

### D1 — HIGH: Three data models in tension

- **Legacy (schema.sql):** `persons`, `incident_persons`, enum-based types
- **Event-centric (migration 002+):** `actors`, `incident_actors`, `events` — first-class entities
- **Case-centric (migration 013+):** `cases`, `charges`, `dispositions` — legal domain
- Code must support all three simultaneously; significant duplication and ambiguity

### D2 — HIGH: Missing FK on `event_relationships.case_id`

- **File:** `database/migrations/011_event_relationships.sql` (line 40)
- `case_id UUID` column with comment "FK added when cases table exists" — but cases table exists (migration 013) and FK was never added
- Allows orphaned references

### D3 — HIGH: String-based FK for `relationship_type`

- **File:** `database/migrations/011_event_relationships.sql` (line 38)
- `relationship_type VARCHAR(50) NOT NULL REFERENCES relationship_types(name)`
- String-based FK instead of UUID — fragile, rename-risk, no proper cascade support

### D4 — MEDIUM: Duplicate entity tables `persons` vs `actors`

- `persons` defined in schema.sql; `actors` defined in migration 002
- Both store overlapping person/org data with different field sets
- No clear deprecation path documented

### D5 — MEDIUM: Schema drift between schema.sql and migrations

- `prompt_executions` defined in both schema.sql AND migration 002/006
- `task_metrics` / `task_metrics_aggregate` defined in schema.sql AND migration 024
- `rss_feeds` defined in schema.sql but dropped in migration 033
- Migrations use `IF NOT EXISTS` guards, preventing errors but indicating drift

### D6 — MEDIUM: Denormalized sanctuary fields

- **Table:** `incidents`
- `state_sanctuary_status`, `local_sanctuary_status`, `detainer_policy` duplicate data from `jurisdictions` table
- Sync risk if jurisdictions updated but incidents not refreshed

### D7 — MEDIUM: Two extraction pipelines without clear authority

- **Legacy:** `ingested_articles.extracted_data` (one-shot extraction)
- **Two-stage (migration 017):** `article_extractions` (Stage 1) + `schema_extraction_results` (Stage 2)
- Both pipelines active; `ingested_articles.extraction_pipeline` column distinguishes them but no documentation on when to use which

### D8 — MEDIUM: Custom field validation trigger disabled

- **File:** `database/migrations/028_category_required_fields.sql`
- `trigger_validate_custom_fields` disabled; validation moved to Python
- No coverage verification that Python validation is complete

### D9 — MEDIUM: Materialized views require manual REFRESH

- `recidivism_analysis` and `prosecutor_stats` configured in `materialized_view_refresh_config` table
- But no Celery task actually reads this config and performs the refresh
- Views can become stale without manual intervention

### D10 — LOW: CASCADE risk on `incident_persons`

- `ON DELETE CASCADE` on both FKs — deleting an incident cascades to `incident_persons`, which could cascade to `persons`
- Could cause unintended data loss on incident deletion

### D11 — LOW: Circular FK between `ingested_articles` and `article_extractions`

- `ingested_articles.latest_extraction_id` → `article_extractions.id`
- `article_extractions.article_id` → `ingested_articles.id`
- Deletion order matters; migration 022 handles this by nulling one side first

### D12 — LOW: Missing compound indexes for analytics

- `cases(domain_id, category_id, status)` — needed for filtered case queries
- `charges(case_id, status)` — needed for charge status lookups
- `incidents(domain_id, category_id, created_at DESC)` — needed for paginated browsing

### D13 — LOW: `incidents.curated_by` references phantom auth

- References `admin_users` table but no auth service code exists
- Table defined in schema.sql but unused

### D14 — LOW: `rss_feeds` create/drop conflict

- Defined in schema.sql; dropped in migration 033
- Running schema.sql after migrations re-creates the dropped table

---

## Documentation Gaps

| Gap | Current State | Needed |
|-----|---------------|--------|
| **API Documentation** | None | OpenAPI/Swagger spec or endpoint inventory with request/response examples |
| **Architecture Diagram** | None | Visual pipeline flow, service dependencies, data flow |
| **Data Dictionary** | None | Map business terms to DB columns, document enum values |
| **Deployment Guide** | Minimal in CLAUDE.md | Full Docker setup, env vars, port mappings, health checks |
| **Testing** | Zero test files | Unit tests for services, integration tests for pipeline, E2E for critical flows |
| **Contributing Guide** | None | Code standards, PR process, branch strategy |
| **Changelog** | None | Track breaking changes, new features, fixes |
| **Legacy vs Active** | Unclear in code | Document which tables/services are legacy vs. active |
| **Pipeline Selection** | Not documented | When to use legacy vs two-stage extraction |
| **Error Handling Strategy** | Inconsistent | Document expected error handling patterns per layer |

---

## Functionality Gaps

| Gap | Severity | Description |
|-----|----------|-------------|
| **No tests whatsoever** | CRITICAL | Zero test files in backend or frontend — no unit, integration, or E2E tests |
| **No authentication** | HIGH | `admin_users` table exists but no auth middleware, login flow, or session management |
| **No rate limiting** | MEDIUM | API endpoints have no rate limiting — vulnerable to abuse |
| **No health check endpoint** | MEDIUM | No `/health` or `/ready` endpoint for Docker/orchestration |
| **No input sanitization middleware** | MEDIUM | Validation happens per-endpoint; no centralized request validation |
| **No scheduled materialized view refresh** | MEDIUM | Views configured but no Celery task actually refreshes them |
| **No graceful shutdown** | LOW | Celery workers don't have graceful shutdown handling |
| **No backup/restore documentation** | LOW | No documented process for database backup and restore |

---

## Positive Findings

### Backend
- Well-structured service layer with clear separation of concerns
- Sophisticated pipeline architecture with pluggable stages
- Good use of asyncpg for async database operations
- Circuit breaker pattern for fault tolerance
- Multi-LLM provider abstraction with fallback support
- Database-backed prompt versioning with A/B testing

### Frontend
- Good use of React hooks and modern patterns
- Excellent TypeScript usage overall (types.ts is thorough)
- Good component composition and separation of concerns
- HeatmapLayer has proper error boundary (good pattern to replicate)
- SplitPane with localStorage persistence
- API layer well-organized with clear naming conventions

### Database
- Comprehensive schema with good normalization
- Full-text search with pg_trgm
- Extensible type system (outcome_types, victim_types, actor_role_types)
- Configurable pipeline stages per incident type
- Audit trails (enrichment_log, charge_history, migration_rollback_log)
- Partial indexes for query performance (idx_articles_extractable)

### Architecture
- Clear data pipeline: Fetch → Extract → Dedupe → Validate → Enrich → Classify → Resolve → Cross-Ref → Approve
- Category-aware extraction with domain-specific schemas
- Two-stage extraction for complex multi-domain articles
- Event-driven job monitoring via WebSocket
