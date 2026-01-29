-- Migration 008: Add LLM provider tracking columns
-- Adds provider_name and model_name to prompt_executions for multi-provider support

-- Add provider tracking columns to prompt_executions
ALTER TABLE prompt_executions
    ADD COLUMN IF NOT EXISTS provider_name VARCHAR(50),
    ADD COLUMN IF NOT EXISTS model_name VARCHAR(100);

-- Index for provider-based queries
CREATE INDEX IF NOT EXISTS idx_prompt_executions_provider
    ON prompt_executions(provider_name)
    WHERE provider_name IS NOT NULL;

-- Provider performance comparison view
CREATE OR REPLACE VIEW provider_performance AS
SELECT
    pe.provider_name,
    pe.model_name,
    p.prompt_type,
    COUNT(*) as total_executions,
    COUNT(*) FILTER (WHERE pe.success) as successful,
    ROUND(
        COUNT(*) FILTER (WHERE pe.success) * 100.0 / NULLIF(COUNT(*), 0),
        2
    ) as success_rate_pct,
    ROUND(AVG(pe.latency_ms)::numeric, 0) as avg_latency_ms,
    ROUND(AVG(pe.confidence_score)::numeric, 3) as avg_confidence,
    SUM(pe.input_tokens) as total_input_tokens,
    SUM(pe.output_tokens) as total_output_tokens,
    MIN(pe.created_at) as first_seen,
    MAX(pe.created_at) as last_seen
FROM prompt_executions pe
JOIN prompts p ON pe.prompt_id = p.id
WHERE pe.provider_name IS NOT NULL
  AND pe.created_at >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY pe.provider_name, pe.model_name, p.prompt_type
ORDER BY total_executions DESC;

COMMENT ON VIEW provider_performance IS 'Performance comparison across LLM providers (last 30 days)';
