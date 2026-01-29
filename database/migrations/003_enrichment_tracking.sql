-- Migration 003: Enrichment tracking tables
-- Adds tables for cross-reference enrichment pipeline stage

-- Track enrichment runs (batch operations)
CREATE TABLE enrichment_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES background_jobs(id),
    strategy VARCHAR(50) NOT NULL,     -- 'cross_incident', 'llm_reextract', 'full'
    params JSONB DEFAULT '{}',
    total_incidents INTEGER DEFAULT 0,
    incidents_enriched INTEGER DEFAULT 0,
    fields_filled INTEGER DEFAULT 0,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'running'
);

-- Track every enrichment change for auditing/revert
CREATE TABLE enrichment_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES enrichment_runs(id),
    incident_id UUID NOT NULL REFERENCES incidents(id),
    field_name VARCHAR(100) NOT NULL,
    old_value TEXT,
    new_value TEXT,
    source_type VARCHAR(30) NOT NULL,  -- 'cross_incident', 'llm_reextract', 'article_merge'
    source_incident_id UUID REFERENCES incidents(id),  -- for cross_incident
    source_article_id UUID REFERENCES ingested_articles(id),  -- for llm
    confidence DECIMAL(3,2),
    applied BOOLEAN DEFAULT FALSE,     -- tracks if actually written to incident
    reverted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_enrichment_log_run ON enrichment_log(run_id);
CREATE INDEX idx_enrichment_log_incident ON enrichment_log(incident_id);
CREATE INDEX idx_enrichment_runs_status ON enrichment_runs(status);

-- Register pipeline stage
INSERT INTO pipeline_stages (name, slug, handler_class, default_order, is_active)
VALUES ('Enrichment', 'enrichment', 'backend.pipeline.stages.enrichment.EnrichmentStage', 110, TRUE)
ON CONFLICT (slug) DO NOTHING;

-- Grant permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON enrichment_runs TO incident_tracker_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON enrichment_log TO incident_tracker_app;

-- Record migration
INSERT INTO schema_migrations (version) VALUES ('003_enrichment_tracking');
