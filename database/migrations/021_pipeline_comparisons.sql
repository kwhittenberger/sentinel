-- Migration 021: Pipeline-level comparisons
-- Allow schema_id to be NULL and add pipeline comparison support

-- Allow schema_id to be NULL for pipeline-level comparisons
ALTER TABLE prompt_test_comparisons
    ALTER COLUMN schema_id DROP NOT NULL;

-- Add comparison_type column
ALTER TABLE prompt_test_comparisons
    ADD COLUMN comparison_type VARCHAR(20) DEFAULT 'schema'
        CHECK (comparison_type IN ('schema', 'pipeline'));

-- Extend comparison_articles with full pipeline results
ALTER TABLE comparison_articles
    ADD COLUMN config_a_stage1 JSONB,
    ADD COLUMN config_b_stage1 JSONB,
    ADD COLUMN config_a_stage2_results JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN config_b_stage2_results JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN config_a_total_tokens INTEGER,
    ADD COLUMN config_b_total_tokens INTEGER,
    ADD COLUMN config_a_total_latency_ms INTEGER,
    ADD COLUMN config_b_total_latency_ms INTEGER;

GRANT ALL ON ALL TABLES IN SCHEMA public TO sentinel;
