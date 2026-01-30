-- Migration 018: Add provider/model columns to prompt_test_runs for comparison testing
-- Allows running the same test suite with different providers and comparing results

ALTER TABLE prompt_test_runs
    ADD COLUMN IF NOT EXISTS provider_name VARCHAR(50),
    ADD COLUMN IF NOT EXISTS model_name VARCHAR(200);

CREATE INDEX IF NOT EXISTS idx_test_runs_provider ON prompt_test_runs(provider_name);
