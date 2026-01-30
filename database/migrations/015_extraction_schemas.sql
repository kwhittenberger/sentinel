-- Migration 015: Flexible Extraction System
-- Adds extraction schemas, prompt testing infrastructure, quality monitoring,
-- custom field validation, and materialized view refresh configuration.
-- Part of Phase 3: Flexible Extraction System.

-- ============================================================================
-- 1. EXTRACTION SCHEMAS
-- ============================================================================

CREATE TABLE extraction_schemas (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain_id UUID REFERENCES event_domains(id),
    category_id UUID REFERENCES event_categories(id),
    schema_version INTEGER NOT NULL DEFAULT 1,
    name VARCHAR(100) NOT NULL,
    description TEXT,

    -- LLM Configuration
    system_prompt TEXT NOT NULL,
    user_prompt_template TEXT NOT NULL,
    model_name VARCHAR(50) DEFAULT 'claude-sonnet-4-5',
    temperature DECIMAL(3,2) DEFAULT 0.7,
    max_tokens INTEGER DEFAULT 4000,

    -- Schema Definition
    required_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    optional_fields JSONB DEFAULT '[]'::jsonb,
    field_definitions JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Validation Rules
    validation_rules JSONB DEFAULT '{}'::jsonb,
    confidence_thresholds JSONB DEFAULT '{}'::jsonb,

    -- Prompt Testing & Quality Metrics
    test_dataset_id UUID,
    quality_metrics JSONB DEFAULT '{}'::jsonb,
    min_quality_threshold DECIMAL(3,2) DEFAULT 0.80,

    -- Version Control
    git_commit_sha VARCHAR(40),
    previous_version_id UUID REFERENCES extraction_schemas(id),
    rollback_reason TEXT,

    -- Metadata
    is_active BOOLEAN DEFAULT TRUE,
    is_production BOOLEAN DEFAULT FALSE,
    deployed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    CHECK (schema_version > 0),
    CHECK (min_quality_threshold BETWEEN 0 AND 1)
);

-- Only one production version per domain/category
CREATE UNIQUE INDEX idx_extraction_schemas_production
ON extraction_schemas(domain_id, category_id)
WHERE is_production = TRUE AND is_active = TRUE;

CREATE INDEX idx_extraction_schemas_domain ON extraction_schemas(domain_id);
CREATE INDEX idx_extraction_schemas_category ON extraction_schemas(category_id);
CREATE INDEX idx_extraction_schemas_active ON extraction_schemas(is_active) WHERE is_active = TRUE;

-- Auto-update timestamp
CREATE TRIGGER update_extraction_schemas_timestamp
    BEFORE UPDATE ON extraction_schemas
    FOR EACH ROW
    EXECUTE FUNCTION update_case_timestamp();

-- ============================================================================
-- 2. PROMPT TESTING INFRASTRUCTURE
-- ============================================================================

-- Golden test datasets
CREATE TABLE prompt_test_datasets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(200) NOT NULL,
    description TEXT,
    domain_id UUID REFERENCES event_domains(id),
    category_id UUID REFERENCES event_categories(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Wire up the FK from extraction_schemas.test_dataset_id
ALTER TABLE extraction_schemas
    ADD CONSTRAINT fk_extraction_schemas_test_dataset
    FOREIGN KEY (test_dataset_id) REFERENCES prompt_test_datasets(id);

-- Individual test cases
CREATE TABLE prompt_test_cases (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dataset_id UUID NOT NULL REFERENCES prompt_test_datasets(id) ON DELETE CASCADE,
    article_text TEXT NOT NULL,
    expected_extraction JSONB NOT NULL,
    importance VARCHAR(20) DEFAULT 'medium'
        CHECK (importance IN ('critical', 'high', 'medium', 'low')),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_test_cases_dataset ON prompt_test_cases(dataset_id);

-- Test run results
CREATE TABLE prompt_test_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    schema_id UUID NOT NULL REFERENCES extraction_schemas(id) ON DELETE CASCADE,
    dataset_id UUID NOT NULL REFERENCES prompt_test_datasets(id),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'running'
        CHECK (status IN ('running', 'passed', 'failed', 'error')),

    -- Aggregate metrics
    total_cases INTEGER,
    passed_cases INTEGER,
    failed_cases INTEGER,
    precision DECIMAL(5,4),
    recall DECIMAL(5,4),
    f1_score DECIMAL(5,4),

    -- Cost tracking
    total_input_tokens BIGINT,
    total_output_tokens BIGINT,
    estimated_cost DECIMAL(10,4),

    results JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_test_runs_schema ON prompt_test_runs(schema_id);
CREATE INDEX idx_test_runs_status ON prompt_test_runs(status);

-- ============================================================================
-- 3. PRODUCTION QUALITY MONITORING
-- ============================================================================

CREATE TABLE extraction_quality_samples (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    schema_id UUID NOT NULL REFERENCES extraction_schemas(id),
    article_id UUID NOT NULL REFERENCES ingested_articles(id),
    extracted_data JSONB,
    confidence DECIMAL(3,2),
    human_reviewed BOOLEAN DEFAULT FALSE,
    review_passed BOOLEAN,
    review_corrections JSONB,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_quality_samples_schema ON extraction_quality_samples(schema_id);
CREATE INDEX idx_quality_samples_reviewed ON extraction_quality_samples(human_reviewed);

-- ============================================================================
-- 4. CUSTOM FIELD VALIDATION TRIGGER
-- (Already created in migration 009 — no-op here, kept for documentation)
-- ============================================================================

-- ============================================================================
-- 5. MATERIALIZED VIEW REFRESH CONFIGURATION
-- ============================================================================

CREATE TABLE materialized_view_refresh_config (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    view_name VARCHAR(100) NOT NULL UNIQUE,
    refresh_interval_minutes INTEGER NOT NULL DEFAULT 60,
    staleness_tolerance_minutes INTEGER NOT NULL DEFAULT 120,
    last_refresh_at TIMESTAMPTZ,
    last_refresh_duration_ms INTEGER,
    last_refresh_status VARCHAR(20) DEFAULT 'pending'
        CHECK (last_refresh_status IN ('pending', 'running', 'success', 'failed')),
    is_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO materialized_view_refresh_config
    (view_name, refresh_interval_minutes, staleness_tolerance_minutes)
VALUES
    ('prosecutor_stats', 60, 120);

-- ============================================================================
-- 6. SEED DATA: Example extraction schema for prosecution tracking
-- ============================================================================

INSERT INTO extraction_schemas (
    domain_id,
    category_id,
    name,
    description,
    system_prompt,
    user_prompt_template,
    required_fields,
    optional_fields,
    field_definitions,
    is_production
) VALUES (
    (SELECT id FROM event_domains WHERE slug = 'criminal_justice'),
    (SELECT id FROM event_categories WHERE slug = 'prosecution'),
    'Prosecutorial Decision Extraction',
    'Extract prosecutor decisions, charge changes, and plea bargains from news articles',
    'You are analyzing news articles about criminal prosecutions. Extract structured data about prosecutorial decisions, charges, plea bargains, and case outcomes.',
    E'Extract the following information from this article about a prosecution:\n\n{article_text}\n\nProvide structured data including: prosecutor name, defendant name, original charges, amended charges, plea offer, disposition, sentence.',
    '["prosecutor_name", "defendant_name", "charges", "disposition"]'::jsonb,
    '["original_charges", "amended_charges", "plea_offer", "plea_accepted", "sentence", "reasoning"]'::jsonb,
    '{
        "prosecutor_name": {"type": "string", "description": "Name of prosecuting attorney"},
        "defendant_name": {"type": "string", "description": "Name of defendant"},
        "charges": {"type": "array", "description": "List of charges"},
        "original_charges": {"type": "array", "description": "Original charges filed"},
        "amended_charges": {"type": "array", "description": "Charges after amendment"},
        "plea_offer": {"type": "object", "description": "Details of plea bargain offered"},
        "plea_accepted": {"type": "boolean", "description": "Whether plea was accepted"},
        "disposition": {"type": "string", "description": "Case outcome: convicted, acquitted, dismissed, plea"},
        "sentence": {"type": "object", "description": "Sentencing details"},
        "reasoning": {"type": "string", "description": "Stated reasoning for decisions"}
    }'::jsonb,
    TRUE
);

-- ============================================================================
-- 7. GRANTS
-- ============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON extraction_schemas TO sentinel;
GRANT SELECT, INSERT, UPDATE, DELETE ON prompt_test_datasets TO sentinel;
GRANT SELECT, INSERT, UPDATE, DELETE ON prompt_test_cases TO sentinel;
GRANT SELECT, INSERT, UPDATE, DELETE ON prompt_test_runs TO sentinel;
GRANT SELECT, INSERT, UPDATE, DELETE ON extraction_quality_samples TO sentinel;
GRANT SELECT, INSERT, UPDATE, DELETE ON materialized_view_refresh_config TO sentinel;
