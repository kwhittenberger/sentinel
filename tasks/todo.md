# Sentinel — Prioritized Action Items

Source: [`docs/CODEBASE-AUDIT.md`](../docs/CODEBASE-AUDIT.md)

---

## CRITICAL

- [ ] **Add tests** — Zero test files exist. Start with unit tests for `auto_approval.py`, `duplicate_detection.py`, `llm_extraction.py`. Then integration tests for the pipeline. Then E2E for curation workflow.

## HIGH Priority

### Backend
- [x] **Split `main.py` (6,280 lines)** into route modules — extracted to `routes/incidents.py`, `routes/curation.py`, `routes/settings.py`, `routes/domains.py`, `routes/admin_incidents.py`, `routes/jobs.py`, `routes/feeds.py`, `routes/types_prompts.py`, `routes/events_actors.py`, `routes/analytics.py`, `routes/cases.py`, `routes/extraction.py`, `routes/testing.py`, `routes/recidivism.py`
- [ ] **Replace `datetime.utcnow()`** with `datetime.now(timezone.utc)` — 45+ occurrences across 10+ files
- [ ] **Add timeouts to LLM calls** in `unified_pipeline.py` and `llm_extraction.py`
- [ ] **Fix confidence default** in `auto_approval.py` (~line 479): change fallback from `1.0` to `0.0` when `field_confidence` is missing

### Frontend
- [x] **Add `response.ok` checks** to 61 API functions in `api.ts` that lack error handling
- [x] **Add error boundaries** to `App.tsx` and `AdminPanel.tsx` (replicate `HeatmapLayer.tsx` pattern)
- [x] **Add `.catch()` handler** to `Promise.all` in `App.tsx` (line 160)

### Database
- [x] **Add FK constraint** on `event_relationships.case_id` → `cases(id) ON DELETE SET NULL` — migration 034 already handles this
- [x] **Document legacy vs active models** — `persons` vs `actors`, legacy vs two-stage extraction — documented in schema.sql header and CLAUDE.md

## MEDIUM Priority

### Backend
- [ ] **Make LLM model configurable** — remove hardcoded `claude-sonnet-4-20250514` from `llm_provider.py` (4 occurrences); use settings
- [ ] **Centralize confidence thresholds** — single source of truth instead of spread across `auto_approval.py` and `duplicate_detection.py`
- [ ] **Add settings caching** with TTL in `settings.py` to avoid DB hit on every call
- [ ] **Narrow Exception catches** in `job_executor.py` (6 instances) and `settings.py`
- [ ] **Extract JSON parsing helper** — deduplicate markdown→JSON extraction across 4+ files in `llm_extraction.py`
- [ ] **Document similarity thresholds** in `duplicate_detection.py` (title=0.75, content=0.85, name=0.7)

### Frontend
- [x] **Extract App.tsx** — split into smaller components (map, filters, timeline, drawer)
- [ ] **Fix race condition** in `BatchProcessing.tsx` — abort previous fetch on new selection
- [ ] **Fix timeline race condition** in `App.tsx` (lines ~402-414)
- [x] **Add extraction data validation** before render in `ExtractionDetailView.tsx`
- [x] **Add null checks** before `.map()` calls on `charges` in `IncidentDetailView.tsx`
- [ ] **Fix poll interval cleanup** in `QueueManager.tsx` on remount
- [ ] **Disable HTML** in ReactMarkdown in `articleHighlight.tsx`
- [ ] **Add keyboard navigation** to `SplitPane.tsx` separator (WCAG)
- [x] **Add non-color marker differentiation** for map markers in `App.tsx`

### Database
- [x] **Add compound indexes** for analytics — migration 035 adds compound indexes for incidents and ingested_articles; cases/charges indexes deferred
- [ ] **Create Celery task** to refresh `recidivism_analysis` and `prosecutor_stats` materialized views
- [ ] **Migrate `relationship_type`** from VARCHAR(50) FK to UUID-based FK — string FK `REFERENCES relationship_types(name)` exists (migration 011); converting to UUID FK requires coordinated changes in `domain_service.py`, `admin_incidents.py`, and the cycle detection trigger
- [x] **Resolve schema drift** between schema.sql and migrations — schema.sql rewritten as canonical post-migration (001–035) state

## LOW Priority

### Backend
- [ ] **Remove hardcoded `devpassword`** from `database.py` DATABASE_URL fallback
- [ ] **Standardize logging levels** across services
- [ ] **Make connection pool configurable** via environment in `database.py`
- [ ] **Make Celery retry policies configurable** per task type
- [ ] **Add geocoding API fallback** for cities not in hardcoded lookup

### Frontend
- [x] **Reduce `as any` casts** — 48 occurrences across 6 files; add proper interfaces
- [x] **Add loading/error states** to components (ExtractionDetailView, IncidentDetailView)
- [ ] **Auto-dismiss success/error messages** in `BatchProcessing.tsx`
- [x] **Log WebSocket errors** in dev mode instead of swallowing in `useJobWebSocket.ts`
- [ ] **Validate URL date parameters** in `App.tsx`
- [x] **Add `aria-label`** to interactive elements

### Database
- [ ] **Review CASCADE behavior** on `incident_persons` — consider RESTRICT
- [x] **Audit `admin_users` table** — documented as placeholder; no auth exists (see D13 comments in schema.sql and migrations 002, 006)
- [ ] **Add data dictionary** — map business terms to DB columns

### Documentation
- [ ] **Create API documentation** — at minimum, endpoint inventory with examples
- [ ] **Create architecture diagram** — pipeline flow, service dependencies
- [ ] **Create deployment guide** — full Docker setup, env vars, health checks
- [ ] **Create contributing guide** — code standards, PR process
- [ ] **Document extraction pipeline selection** — when legacy vs two-stage
