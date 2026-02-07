# CLAUDE.md — Sentinel

This file provides project-specific guidance for this codebase. For universal workflow rules, see the root `../CLAUDE.md`.

---

## Project Context

- **Product:** Incident analysis and pattern detection platform — RSS ingestion, LLM-powered entity extraction, curation workflows, analytics, geographic visualization
- **Stack:** Python (FastAPI, Celery), React (Vite, TypeScript), PostgreSQL, Redis
- **Architecture:** Data pipeline: Fetch → Extract → Dedupe → Auto-Approve → Curate → Incident
- **Deploy:** Docker Compose (db, redis, backend, celery workers, beat)
- **Key integrations:** Claude Sonnet (LLM extraction), RSS feeds, Celery (background processing)

## Build & Run

```bash
# Start all services (db, redis, backend, celery workers, beat)
./start-dev.sh

# Frontend (separate terminal)
cd frontend && npm run dev

# Backend-only (no Celery workers)
./start-backend.sh

# Check service status / stop
./start-dev.sh status
./start-dev.sh stop

# Docker
docker-compose up -d              # Start everything
docker-compose up -d db           # Database only
docker exec -it sentinel_db psql -U sentinel -d sentinel

# Scripts
python scripts/migrate_data.py          # Migrate JSON → DB (one-time)
python scripts/import_crime_tracker.py  # Import crime tracker data
```

Dashboard: http://localhost:5174

## Architecture

### Key Directories

```
backend/
├── main.py                     # FastAPI routes
├── database.py                 # PostgreSQL connection pool
└── services/
    ├── llm_extraction.py       # Article→incident extraction via Claude
    ├── auto_approval.py        # Confidence-based auto-approval
    ├── duplicate_detection.py  # URL, title, content, entity matching
    ├── unified_pipeline.py     # Fetch → Extract → Dedupe → Approve
    ├── job_executor.py         # Background job processing
    └── settings.py             # Runtime config

frontend/src/
├── App.tsx                     # Main dashboard (map, charts, filters)
├── AdminPanel.tsx              # Admin navigation/routing
├── CurationQueue.tsx           # Review extracted articles
├── BatchProcessing.tsx         # Tiered confidence queue
├── IncidentBrowser.tsx         # Search/edit approved incidents
├── JobManager.tsx              # Background job monitoring
└── AnalyticsDashboard.tsx      # Pipeline metrics/funnels

database/
├── schema.sql                  # Full PostgreSQL schema
└── migrations/                 # Incremental migrations
```

### Key Design Decisions

- **LLM-powered extraction:** Claude Sonnet analyzes articles to produce structured incident data with confidence scores
- **Confidence-based auto-approval:** High confidence (>=85%) items auto-approved; medium/low go to human curation
- **Configurable event domains:** Supports multiple categories (Immigration, Criminal Justice, Civil Rights) with per-category extraction rules

## Session Continuity

**At session start:** Read `docs/WORK-LOG.md` to understand current state.
**At session end:** Update it with accomplishments, in-progress work, blockers, and next steps.

## Audit & Known Issues

See [`docs/CODEBASE-AUDIT.md`](docs/CODEBASE-AUDIT.md) for the full codebase audit (2026-02-07).
Action items tracked in [`tasks/todo.md`](tasks/todo.md).

### Known Architectural Decisions

- **Persons vs Actors:** Two entity models coexist. `persons` (schema.sql) is legacy; `actors` (migration 002) is preferred for new code. Both are in use.
- **Legacy vs Two-Stage Extraction:** Check `ingested_articles.extraction_pipeline` column. Legacy = one-shot via `extracted_data`. Two-stage = `article_extractions` (Stage 1) + `schema_extraction_results` (Stage 2). Two-stage is preferred for new work.
- **Three data layers:** Legacy person-centric, event-centric (actors/events), and case-centric (cases/charges/dispositions) all coexist. Code must handle all three.

## Domain-Specific Rules

### Confidence Tiers

| Tier | Confidence | Action |
|------|------------|--------|
| HIGH | >= 85% | Auto-approve candidates |
| MEDIUM | 50-85% | Quick human review |
| LOW | < 50% | Full manual review |

### Incident Categories

- **Enforcement** (higher scrutiny — 90% threshold): Focus on victim details, officer involvement, outcome severity. Required: date, state, incident_type, victim_category, outcome_category
- **Crime** (standard — 85% threshold): Focus on offender details, criminal history, deportation status. Required: date, state, incident_type, immigration_status

### Environment

Copy `.env.example` to `.env`. Key vars: `DATABASE_URL`, `ANTHROPIC_API_KEY`.
Logs go to `.logs/` directory.

Key tables: `incidents`, `ingested_articles`, `article_extractions`, `actors`, `events`, `cases`, `charges`, `curation_queue`, `jurisdictions`, `background_jobs`
