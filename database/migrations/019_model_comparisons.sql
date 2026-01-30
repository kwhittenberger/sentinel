-- Migration 019: Multi-model comparison testing
-- Enables side-by-side comparison of two LLM provider/model configurations
-- with multiple iterations per config for statistical significance.

CREATE TABLE prompt_test_comparisons (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    schema_id UUID NOT NULL REFERENCES extraction_schemas(id),
    dataset_id UUID NOT NULL REFERENCES prompt_test_datasets(id),
    config_a_provider VARCHAR(50) NOT NULL,
    config_a_model VARCHAR(200) NOT NULL,
    config_b_provider VARCHAR(50) NOT NULL,
    config_b_model VARCHAR(200) NOT NULL,
    iterations_per_config INTEGER NOT NULL DEFAULT 3,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','running','completed','failed')),
    progress INTEGER DEFAULT 0,
    total_iterations INTEGER DEFAULT 0,
    message TEXT,
    error TEXT,
    summary_stats JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

ALTER TABLE prompt_test_runs
    ADD COLUMN comparison_id UUID REFERENCES prompt_test_comparisons(id),
    ADD COLUMN iteration_number INTEGER,
    ADD COLUMN config_label VARCHAR(1) CHECK (config_label IN ('A','B'));

CREATE INDEX idx_comparisons_status ON prompt_test_comparisons(status);
CREATE INDEX idx_comparisons_created ON prompt_test_comparisons(created_at DESC);
CREATE INDEX idx_test_runs_comparison ON prompt_test_runs(comparison_id);
