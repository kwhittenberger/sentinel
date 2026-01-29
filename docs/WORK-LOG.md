# Work Log - Generic Event Tracking System

## Session: 2026-01-29

### Context
Implementing the Generic Event Tracking System plan from `docs/plans/generic-event-tracking-system.md`.
Phase 1 (Foundation) complete, now implementing Phase 2 (Cases & Legal Tracking).

### Prior Work (This Session)
- Committed multi-LLM provider support (Ollama + Claude routing) — commit `1acb9d9`
- All 7 LLM call sites refactored to use `LLMRouter` with per-stage config and fallback

### Phase 1 Status: COMPLETE
- [x] Migration 009: Event taxonomy — domains, categories, incidents schema extensions, seed data
- [x] Migration 010: Actor roles — configurable role_type_id replacing fixed enum
- [x] Migration 011: Event relationships — typed relationships with cycle detection
- [x] Migration 012: Validation script — read-only integrity checks
- [x] DomainService backend — `backend/services/domain_service.py`
- [x] Domain/category API endpoints in `backend/main.py`
- [x] DomainManager frontend — `frontend/src/DomainManager.tsx` + AdminPanel integration

### Phase 2: Cases & Legal Tracking — COMPLETE
- [x] Migration 013: Cases system — `database/migrations/013_cases_system.sql`
  - cases table (case_number, case_type, jurisdiction, court_name, status, custom_fields)
  - charges table (per-charge tracking with level, class, severity, sentencing fields)
  - charge_history table (audit trail: filed/amended/reduced/dismissed/convicted/acquitted)
  - case_jurisdictions table (multi-jurisdiction with filing/transferred/appellate/concurrent roles)
  - external_system_ids table (cross-system ID mapping with confidence scoring)
  - case_incidents table (links incidents to cases with role semantics)
  - case_actors table (links actors to cases with role_type_id)
  - Auto-update timestamp triggers, indexes, grants
- [x] Migration 014: Prosecutorial tracking — `database/migrations/014_prosecutorial_tracking.sql`
  - prosecutorial_actions table (9 action types with reasoning/legal_basis)
  - prosecutor_action_charges junction table (links actions to affected charges)
  - bail_decisions table (risk assessment, prosecution/defense positions, outcome)
  - dispositions table (granular sentencing: jail, probation, financial, community service, treatment, compliance)
  - prosecutor_stats materialized view (conviction rate, avg sentence, data completeness)
  - Auto-update triggers, indexes, grants
- [x] CriminalJusticeService — `backend/services/criminal_justice_service.py`
  - Full CRUD for cases, charges, charge_history
  - Prosecutorial actions, bail decisions, dispositions
  - Case linking (incidents, actors)
  - Prosecutor stats with materialized view refresh
  - Singleton pattern with get_criminal_justice_service()
- [x] API endpoints — 22 new endpoints in `backend/main.py`
  - Cases: GET/POST /api/admin/cases, GET/PUT /api/admin/cases/{id}
  - Charges: GET/POST /api/admin/cases/{id}/charges, PUT /api/admin/charges/{id}
  - Charge history: GET /api/admin/cases/{id}/charge-history, POST /api/admin/charge-history
  - Prosecutorial: GET /api/admin/cases/{id}/prosecutorial-actions, POST /api/admin/prosecutorial-actions
  - Bail: GET /api/admin/cases/{id}/bail-decisions, POST /api/admin/bail-decisions
  - Dispositions: GET /api/admin/cases/{id}/dispositions, POST /api/admin/dispositions
  - Case linking: GET/POST /api/admin/cases/{id}/incidents, GET/POST /api/admin/cases/{id}/actors
  - Prosecutor stats: GET /api/admin/prosecutor-stats, POST /api/admin/prosecutor-stats/refresh
- [x] CaseManager UI — `frontend/src/CaseManager.tsx`
  - Split-view with case list and detail panel
  - Filters: status, type, search
  - Detail tabs: Details, Charges, History, Incidents, Actors
  - Create case and charge modals
  - Charge status color coding, violent crime badges
- [x] ProsecutorDashboard UI — `frontend/src/ProsecutorDashboard.tsx`
  - Summary cards (prosecutors, total cases, avg conviction rate, dismissals)
  - Prosecutor table with sortable stats
  - Detail view: case outcomes grid, key metrics, outcome distribution bar
  - Materialized view refresh button
- [x] AdminPanel integration — added Cases and Prosecutors nav items under Data section
- [x] TypeScript compiles clean
- [x] Python syntax validated

### Files Created (Phase 2)
- `database/migrations/013_cases_system.sql`
- `database/migrations/014_prosecutorial_tracking.sql`
- `backend/services/criminal_justice_service.py`
- `frontend/src/CaseManager.tsx`
- `frontend/src/ProsecutorDashboard.tsx`

### Files Modified (Phase 2)
- `backend/main.py` — 22 new API endpoints
- `backend/services/__init__.py` — exported CriminalJusticeService
- `frontend/src/AdminPanel.tsx` — added cases/prosecutors views and nav items

### Commits
- `0fca7da` — Phase 1 + Phase 2 (event taxonomy, cases, prosecutorial tracking)

### Phase 3: Flexible Extraction System — COMPLETE
- [x] Migration 015: Extraction schemas — `database/migrations/015_extraction_schemas.sql`
  - extraction_schemas table (domain/category-scoped LLM configs, version control, quality metrics)
  - prompt_test_datasets, prompt_test_cases, prompt_test_runs tables
  - extraction_quality_samples table (production monitoring)
  - Custom field validation trigger on incidents
  - Materialized view refresh configuration table
  - Seed data: prosecution extraction schema
  - Indexes, constraints, grants
- [x] GenericExtractionService — `backend/services/generic_extraction.py`
  - Schema CRUD (list, get, create, update)
  - Production schema lookup by domain/category
  - Schema-driven LLM extraction via LLMRouter
  - Field validation, weighted confidence scoring, cross-field validation
  - Quality sample recording and review
  - Production quality monitoring with degradation detection
- [x] PromptTestingService — `backend/services/prompt_testing.py`
  - Test dataset and test case CRUD
  - Test run execution: per-case LLM extraction, field comparison, precision/recall/F1
  - Deploy-to-production workflow with quality gate
  - Rollback to previous version
  - Fuzzy value matching (string similarity, numeric tolerance)
- [x] API endpoints — 18 new endpoints in `backend/main.py`
  - Extraction schemas: GET/POST/PUT /api/admin/extraction-schemas, GET quality, POST extract/deploy/rollback
  - Prompt tests: GET/POST datasets, GET cases, GET/POST runs, POST execute
- [x] ExtractionSchemaManager UI — `frontend/src/ExtractionSchemaManager.tsx`
  - Split-view schema list with domain filter
  - Detail panel: configuration, quality metrics, fields, prompts
  - Create/edit modals with domain/category/model selection
  - Production/Active/Inactive status badges
- [x] PromptTestRunner UI — `frontend/src/PromptTestRunner.tsx`
  - Two tabs: Datasets and Test Runs
  - Dataset management with test case list (importance badges, field counts)
  - Test run results with precision/recall/F1 metrics
  - Create dataset, add test case, and run test modals
- [x] AdminPanel integration — added Extraction section (Schemas, Prompt Tests nav items)
- [x] TypeScript compiles clean
- [x] Python syntax validated

### Phase 4: Advanced Analytics — COMPLETE
- [x] Migration 016: Recidivism tracking — `database/migrations/016_recidivism_analytics.sql`
  - actor_incident_history view (windowed: incident_number, days_since_last, total_for_actor)
  - recidivism_analysis materialized view (aggregated stats, incident/outcome progression arrays)
  - calculate_recidivism_indicator() function (heuristic-v1, with disclaimers)
  - defendant_lifecycle_timeline view (12-phase CJ lifecycle)
  - import_sagas table (multi-step ETL orchestration with status machine)
  - staging_incidents, staging_actors tables (validation, dedup, comparison tracking)
  - migration_rollback_log table
  - Materialized view refresh config for recidivism_analysis
  - Grants for all tables/views
- [x] RecidivismService — `backend/services/recidivism_service.py`
  - Actor incident history, recidivism stats, full profile
  - Recidivism indicator calculation via SQL function
  - Defendant lifecycle timeline
  - Analytics summary (totals, averages)
  - Materialized view refresh
  - Import saga CRUD (list, create, update with status machine)
- [x] API endpoints — 10 new endpoints in `backend/main.py`
  - Recidivism: GET summary, GET actors, GET actor profile/history/indicator/lifecycle
  - POST recidivism refresh
  - Import sagas: GET/POST/PUT
- [x] RecidivismDashboard UI — `frontend/src/RecidivismDashboard.tsx`
  - Summary cards (repeat offenders, avg incidents, max, avg days between)
  - Actor list with incident count badges and gap/span columns
  - Detail panel: indicator badge (color-coded score, disclaimer), stats grid
  - Incident progression tag display
  - Two tabs: Incident History (timeline cards) and Lifecycle Timeline (phase list)
  - Min incidents filter, refresh button
- [x] AdminPanel integration — added Recidivism nav item under Data section
- [x] TypeScript compiles clean
- [x] Python syntax validated

### Files Created (Phase 3)
- `database/migrations/015_extraction_schemas.sql`
- `backend/services/generic_extraction.py`
- `backend/services/prompt_testing.py`
- `frontend/src/ExtractionSchemaManager.tsx`
- `frontend/src/PromptTestRunner.tsx`

### Files Created (Phase 4)
- `database/migrations/016_recidivism_analytics.sql`
- `backend/services/recidivism_service.py`
- `frontend/src/RecidivismDashboard.tsx`

### Files Modified (Phase 3 + 4)
- `backend/main.py` — 28 new API endpoints (18 Phase 3 + 10 Phase 4)
- `backend/services/__init__.py` — exported Phase 3+4 services
- `frontend/src/AdminPanel.tsx` — added Extraction section + Recidivism nav

### Status: ALL PHASES COMPLETE
Phases 1-4 fully implemented. Phases 5-7 (ML, Cross-Domain, Public API) are future aspirational items.
