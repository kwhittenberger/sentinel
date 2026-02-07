-- Migration: Add prompt tracking and analytics tables
-- Description: Enables LLM prompt versioning, A/B testing, and token usage tracking

-- ============================================================================
-- PROMPT MANAGEMENT TABLES
-- ============================================================================

-- Prompts with versioning and A/B testing support
CREATE TABLE IF NOT EXISTS prompts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Identity
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) NOT NULL,
    description TEXT,
    prompt_type VARCHAR(50) NOT NULL,  -- extraction, classification, entity_resolution, pattern_detection, summarization, analysis

    -- Optional incident type association (for type-specific prompts)
    incident_type_id UUID REFERENCES incident_types(id),

    -- Prompt content
    system_prompt TEXT NOT NULL,
    user_prompt_template TEXT NOT NULL,
    output_schema JSONB,  -- JSON schema for expected output

    -- Versioning
    version INTEGER NOT NULL DEFAULT 1,
    parent_version_id UUID REFERENCES prompts(id),  -- Links to previous version
    status VARCHAR(20) NOT NULL DEFAULT 'draft',  -- draft, active, testing, deprecated, archived

    -- Model configuration
    model_name VARCHAR(100) DEFAULT 'claude-sonnet-4-20250514',
    max_tokens INTEGER DEFAULT 2000,
    temperature DECIMAL(3, 2) DEFAULT 0.0,

    -- A/B testing
    traffic_percentage INTEGER DEFAULT 100 CHECK (traffic_percentage >= 0 AND traffic_percentage <= 100),
    ab_test_group VARCHAR(50),  -- e.g., 'control', 'variant_a', 'variant_b'

    -- Audit
    -- NOTE: admin_users has no auth implementation. This FK is a placeholder. See audit D13.
    created_by UUID REFERENCES admin_users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    activated_at TIMESTAMP WITH TIME ZONE,  -- When status changed to 'active'

    -- Ensure unique active prompts per type/incident_type
    UNIQUE(slug, version)
);

CREATE INDEX idx_prompts_type ON prompts(prompt_type);
CREATE INDEX idx_prompts_status ON prompts(status);
CREATE INDEX idx_prompts_incident_type ON prompts(incident_type_id);
CREATE INDEX idx_prompts_slug ON prompts(slug);
CREATE INDEX idx_prompts_ab_group ON prompts(ab_test_group) WHERE ab_test_group IS NOT NULL;

-- Prompt execution tracking for analytics and A/B testing
CREATE TABLE IF NOT EXISTS prompt_executions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Which prompt was used
    prompt_id UUID NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,

    -- Context
    article_id UUID REFERENCES ingested_articles(id),  -- Optional link to article
    incident_id UUID REFERENCES incidents(id),  -- Optional link to incident
    -- NOTE: admin_users has no auth implementation. This FK is a placeholder. See audit D13.
    user_id UUID REFERENCES admin_users(id),  -- Optional user who triggered this

    -- Input
    input_text_length INTEGER,  -- Length of input text in characters
    input_hash VARCHAR(64),  -- SHA256 hash for deduplication

    -- Execution metrics
    success BOOLEAN NOT NULL,
    latency_ms INTEGER,  -- Time to complete in milliseconds
    input_tokens INTEGER,  -- From Claude API usage
    output_tokens INTEGER,  -- From Claude API usage

    -- Output quality
    confidence_score DECIMAL(3, 2),  -- Overall confidence from extraction (0.00-1.00)
    result_data JSONB,  -- Extracted data (for quality analysis)
    error_message TEXT,  -- If success=false

    -- A/B testing
    ab_variant VARCHAR(50),  -- Which variant was served

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT valid_confidence CHECK (confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1))
);

CREATE INDEX idx_prompt_executions_prompt ON prompt_executions(prompt_id);
CREATE INDEX idx_prompt_executions_article ON prompt_executions(article_id);
CREATE INDEX idx_prompt_executions_created ON prompt_executions(created_at DESC);
CREATE INDEX idx_prompt_executions_success ON prompt_executions(success);
CREATE INDEX idx_prompt_executions_ab_variant ON prompt_executions(ab_variant) WHERE ab_variant IS NOT NULL;

-- ============================================================================
-- ANALYTICS VIEWS
-- ============================================================================

-- Prompt performance summary
CREATE OR REPLACE VIEW prompt_performance AS
SELECT
    p.id,
    p.name,
    p.slug,
    p.version,
    p.prompt_type,
    p.status,
    p.ab_test_group,
    COUNT(pe.id) as total_executions,
    COUNT(pe.id) FILTER (WHERE pe.success) as successful_executions,
    COUNT(pe.id) FILTER (WHERE NOT pe.success) as failed_executions,
    ROUND(
        COUNT(pe.id) FILTER (WHERE pe.success)::DECIMAL / NULLIF(COUNT(pe.id), 0) * 100,
        2
    ) as success_rate_pct,
    AVG(pe.latency_ms) as avg_latency_ms,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY pe.latency_ms) as median_latency_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY pe.latency_ms) as p95_latency_ms,
    AVG(pe.input_tokens) as avg_input_tokens,
    AVG(pe.output_tokens) as avg_output_tokens,
    SUM(pe.input_tokens) as total_input_tokens,
    SUM(pe.output_tokens) as total_output_tokens,
    AVG(pe.confidence_score) as avg_confidence,
    MIN(pe.created_at) as first_execution,
    MAX(pe.created_at) as last_execution
FROM prompts p
LEFT JOIN prompt_executions pe ON p.id = pe.prompt_id
GROUP BY p.id, p.name, p.slug, p.version, p.prompt_type, p.status, p.ab_test_group;

-- Token usage by day
CREATE OR REPLACE VIEW token_usage_by_day AS
SELECT
    DATE(pe.created_at) as date,
    p.slug,
    p.version,
    p.prompt_type,
    COUNT(pe.id) as executions,
    SUM(pe.input_tokens) as total_input_tokens,
    SUM(pe.output_tokens) as total_output_tokens,
    SUM(pe.input_tokens + pe.output_tokens) as total_tokens,
    AVG(pe.confidence_score) as avg_confidence
FROM prompt_executions pe
JOIN prompts p ON pe.prompt_id = p.id
WHERE pe.created_at >= CURRENT_DATE - INTERVAL '90 days'
GROUP BY DATE(pe.created_at), p.slug, p.version, p.prompt_type
ORDER BY date DESC, total_tokens DESC;

-- A/B test comparison
CREATE OR REPLACE VIEW ab_test_comparison AS
SELECT
    p.slug,
    p.prompt_type,
    pe.ab_variant,
    COUNT(pe.id) as executions,
    COUNT(pe.id) FILTER (WHERE pe.success) as successful,
    ROUND(
        COUNT(pe.id) FILTER (WHERE pe.success)::DECIMAL / NULLIF(COUNT(pe.id), 0) * 100,
        2
    ) as success_rate_pct,
    AVG(pe.latency_ms) as avg_latency_ms,
    AVG(pe.confidence_score) as avg_confidence,
    AVG(pe.input_tokens + pe.output_tokens) as avg_total_tokens
FROM prompt_executions pe
JOIN prompts p ON pe.prompt_id = p.id
WHERE pe.ab_variant IS NOT NULL
  AND pe.created_at >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY p.slug, p.prompt_type, pe.ab_variant
ORDER BY p.slug, pe.ab_variant;

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Update timestamp trigger for prompts
CREATE TRIGGER update_prompts_timestamp
    BEFORE UPDATE ON prompts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Function to get active prompt for a type
CREATE OR REPLACE FUNCTION get_active_prompt(
    p_prompt_type VARCHAR,
    p_incident_type_id UUID DEFAULT NULL,
    p_slug VARCHAR DEFAULT NULL
)
RETURNS UUID AS $$
DECLARE
    v_prompt_id UUID;
BEGIN
    -- Try to find type-specific prompt first (if incident_type_id provided)
    IF p_incident_type_id IS NOT NULL THEN
        SELECT id INTO v_prompt_id
        FROM prompts
        WHERE prompt_type = p_prompt_type
          AND incident_type_id = p_incident_type_id
          AND status = 'active'
          AND (p_slug IS NULL OR slug = p_slug)
        ORDER BY version DESC
        LIMIT 1;

        IF v_prompt_id IS NOT NULL THEN
            RETURN v_prompt_id;
        END IF;
    END IF;

    -- Fall back to generic prompt (no incident_type_id)
    SELECT id INTO v_prompt_id
    FROM prompts
    WHERE prompt_type = p_prompt_type
      AND incident_type_id IS NULL
      AND status = 'active'
      AND (p_slug IS NULL OR slug = p_slug)
    ORDER BY version DESC
    LIMIT 1;

    RETURN v_prompt_id;
END;
$$ LANGUAGE plpgsql;

-- Function to calculate cost estimate (approximation based on Claude pricing)
CREATE OR REPLACE FUNCTION estimate_cost_usd(
    p_input_tokens BIGINT,
    p_output_tokens BIGINT,
    p_model VARCHAR DEFAULT 'claude-sonnet-4-20250514'
)
RETURNS DECIMAL AS $$
DECLARE
    v_input_price_per_mtok DECIMAL;
    v_output_price_per_mtok DECIMAL;
BEGIN
    -- Pricing as of Jan 2025 (update as needed)
    CASE p_model
        WHEN 'claude-sonnet-4-20250514' THEN
            v_input_price_per_mtok := 3.00;   -- $3 per million input tokens
            v_output_price_per_mtok := 15.00;  -- $15 per million output tokens
        WHEN 'claude-opus-4-5-20251101' THEN
            v_input_price_per_mtok := 15.00;
            v_output_price_per_mtok := 75.00;
        WHEN 'claude-haiku-3-5-20241022' THEN
            v_input_price_per_mtok := 1.00;
            v_output_price_per_mtok := 5.00;
        ELSE
            v_input_price_per_mtok := 3.00;  -- Default to Sonnet pricing
            v_output_price_per_mtok := 15.00;
    END CASE;

    RETURN ROUND(
        (p_input_tokens::DECIMAL / 1000000.0 * v_input_price_per_mtok) +
        (p_output_tokens::DECIMAL / 1000000.0 * v_output_price_per_mtok),
        4
    );
END;
$$ LANGUAGE plpgsql;

-- Cost summary view
CREATE OR REPLACE VIEW token_cost_summary AS
SELECT
    p.slug,
    p.version,
    p.model_name,
    COUNT(pe.id) as executions,
    SUM(pe.input_tokens) as total_input_tokens,
    SUM(pe.output_tokens) as total_output_tokens,
    estimate_cost_usd(
        SUM(pe.input_tokens),
        SUM(pe.output_tokens),
        p.model_name
    ) as estimated_cost_usd
FROM prompt_executions pe
JOIN prompts p ON pe.prompt_id = p.id
WHERE pe.created_at >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY p.slug, p.version, p.model_name
ORDER BY estimated_cost_usd DESC;

-- ============================================================================
-- SEED DATA (Example prompts)
-- ============================================================================

-- Note: Actual prompts will be loaded from extraction_prompts.py via API
-- This is just a placeholder to show the structure

COMMENT ON TABLE prompts IS 'LLM prompt configurations with versioning and A/B testing';
COMMENT ON TABLE prompt_executions IS 'Tracks every LLM prompt execution for analytics and cost monitoring';
COMMENT ON VIEW prompt_performance IS 'Aggregated performance metrics per prompt version';
COMMENT ON VIEW token_usage_by_day IS 'Daily token usage and costs by prompt type';
COMMENT ON VIEW ab_test_comparison IS 'A/B test performance comparison';
COMMENT ON VIEW token_cost_summary IS 'Cost estimates by prompt (last 30 days)';
