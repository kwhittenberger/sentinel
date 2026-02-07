-- Migration 035: Add compound indexes for analytics queries
-- Addresses audit item 7.1: common analytics queries lack compound indexes,
-- forcing PostgreSQL to combine single-column indexes via bitmap scans.
-- Date: 2026-02-06

-- == Incidents table ==

-- State + date range queries (e.g., "incidents in California this month")
CREATE INDEX IF NOT EXISTS idx_incidents_state_date
    ON incidents(state, date);

-- Type-filtered date range queries (e.g., "all shootings in 2025")
CREATE INDEX IF NOT EXISTS idx_incidents_type_date
    ON incidents(incident_type_id, date);

-- Outcome analysis queries (e.g., "fatalities over time")
CREATE INDEX IF NOT EXISTS idx_incidents_outcome_date
    ON incidents(outcome_type_id, date);

-- Admin queue filtering (e.g., "pending curation sorted by newest")
CREATE INDEX IF NOT EXISTS idx_incidents_curation_created
    ON incidents(curation_status, created_at);

-- == Ingested articles table ==
-- Note: schema uses source_name (not source_domain) and status (not processing_status)
-- and fetched_at (not ingested_at). Indexes adapted to actual column names.

-- Source performance analytics (e.g., "articles per source over time")
CREATE INDEX IF NOT EXISTS idx_ingested_source_fetched
    ON ingested_articles(source_name, fetched_at);

-- Pipeline monitoring (e.g., "pending articles by ingest time")
CREATE INDEX IF NOT EXISTS idx_ingested_status_fetched
    ON ingested_articles(status, fetched_at);

-- == Curation queue support ==
-- curation_queue is a VIEW over ingested_articles filtered by status IN ('pending','in_review')
-- and ordered by relevance_score DESC, fetched_at DESC.
-- A compound index on those columns accelerates the view's query plan.
CREATE INDEX IF NOT EXISTS idx_ingested_curation_queue
    ON ingested_articles(status, relevance_score DESC, fetched_at DESC)
    WHERE status IN ('pending', 'in_review');

-- == Join tables ==
-- incident_actors and incident_events already have indexes on incident_id
-- (idx_incident_actors_incident, idx_incident_events_incident from migration 002).
-- actors and events are linked via these join tables, not direct FK columns,
-- so no additional incident_id indexes are needed.
