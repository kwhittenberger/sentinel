# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Sentinel** — Incident analysis and pattern detection platform. Ingests articles via RSS, extracts structured incident data using LLM pipelines, and provides curation workflows, analytics, and geographic visualization.

The system supports configurable event domains and categories (e.g., Immigration, Criminal Justice, Civil Rights) with LLM-powered extraction, confidence-based auto-approval, and deduplication.

## Quick Start

```bash
# Start database
docker-compose up -d db

# Backend (in one terminal)
source .venv/bin/activate
cd backend && uvicorn main:app --reload --port 8000

# Frontend (in another terminal)
cd frontend && npm run dev
```

Access the dashboard at http://localhost:5173

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   React + Vite  │────▶│  FastAPI        │────▶│  PostgreSQL     │
│   (frontend/)   │     │  (backend/)     │     │  (docker)       │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                              │
                              ▼
                        ┌─────────────────┐
                        │  Claude Sonnet  │
                        │  (LLM Extract)  │
                        └─────────────────┘
```

### Backend (`backend/`)

- `main.py` - FastAPI routes for incidents, admin, analytics
- `database.py` - PostgreSQL connection pool
- `services/` - Business logic:
  - `llm_extraction.py` - Article-to-incident extraction via Claude
  - `auto_approval.py` - Confidence-based auto-approval
  - `duplicate_detection.py` - URL, title, content, entity matching
  - `unified_pipeline.py` - Orchestrates fetch → extract → dedupe → approve
  - `job_executor.py` - Background job processing
  - `settings.py` - Runtime configuration management

### Frontend (`frontend/src/`)

- `App.tsx` - Main dashboard with map, charts, filters
- `AdminPanel.tsx` - Admin navigation and routing
- `CurationQueue.tsx` - Review extracted articles
- `BatchProcessing.tsx` - Tiered confidence queue processing
- `IncidentBrowser.tsx` - Search/edit approved incidents
- `JobManager.tsx` - Background job monitoring
- `SettingsPanel.tsx` - Configuration UI
- `AnalyticsDashboard.tsx` - Pipeline metrics and funnels

### Database (`database/`)

- `schema.sql` - Full PostgreSQL schema
- `migrations/` - Incremental migrations

Key tables: `incidents`, `articles`, `curation_queue`, `persons`, `jurisdictions`, `background_jobs`

## Data Pipeline

1. **Fetch** - RSS feeds → `articles` table
2. **Extract** - Claude Sonnet analyzes article → `extracted_data` JSON
3. **Dedupe** - Check URL, title similarity, entity overlap
4. **Auto-Approve** - High confidence (≥85%) auto-approved
5. **Curation** - Human review for medium/low confidence
6. **Incident** - Approved items → `incidents` table

## Scripts

```bash
# Migrate JSON data to database (one-time)
python scripts/migrate_data.py

# Import crime tracker data
python scripts/import_crime_tracker.py

# Validate JSON schema (legacy data files)
python scripts/validate_schema.py
```

## Data Files

- `data/incidents/tier*.json` - Original incident data (backup/reference)
- `data/reference/sanctuary_jurisdictions.json` - Sanctuary policy classifications
- `data/methodology.json` - Source tier definitions

## Docker

```bash
# Start everything
docker-compose up -d

# Database only
docker-compose up -d db

# View logs
docker-compose logs -f

# Connect to database
docker exec -it sentinel_db psql -U sentinel -d sentinel
```

## Environment Variables

Copy `.env.example` to `.env` and configure:

```
DATABASE_URL=postgresql://sentinel:devpassword@localhost:5433/sentinel
ANTHROPIC_API_KEY=sk-ant-...
```

## Confidence Tiers

| Tier | Confidence | Action |
|------|------------|--------|
| HIGH | ≥ 85% | Auto-approve candidates |
| MEDIUM | 50-85% | Quick human review |
| LOW | < 50% | Full manual review |

## Incident Categories

**Enforcement** (higher scrutiny - 90% threshold):
- Focus: victim details, officer involvement, outcome severity
- Required: date, state, incident_type, victim_category, outcome_category

**Crime** (standard - 85% threshold):
- Focus: offender details, criminal history, deportation status
- Required: date, state, incident_type, immigration_status
