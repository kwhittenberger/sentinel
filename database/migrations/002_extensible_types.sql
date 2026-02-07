-- Migration: 002_extensible_types.sql
-- Transforms the incident tracker into a fully extensible, database-driven system
-- with dynamic incident types, AI prompt versioning, and first-class actors/events

-- ============================================================================
-- ENUM TYPES
-- ============================================================================

-- Prompt types for different AI tasks
CREATE TYPE prompt_type AS ENUM (
    'extraction',        -- Article → incident data
    'classification',    -- Relevance/category detection
    'entity_resolution', -- Person/org matching
    'pattern_detection', -- Cluster/trend detection
    'summarization',     -- Content summarization
    'analysis'           -- General analysis
);

CREATE TYPE prompt_status AS ENUM ('draft', 'active', 'testing', 'deprecated', 'archived');

-- Field types for custom field definitions
CREATE TYPE field_type AS ENUM (
    'string', 'text', 'integer', 'decimal', 'boolean',
    'date', 'datetime', 'enum', 'array', 'reference'
);

-- Actor types
CREATE TYPE actor_type AS ENUM ('person', 'organization', 'agency', 'group');

-- Actor roles in incidents
CREATE TYPE actor_role AS ENUM (
    'victim', 'offender', 'witness', 'officer',
    'arresting_agency', 'reporting_agency',
    'bystander', 'organizer', 'participant'
);

-- Actor relationship types
CREATE TYPE actor_relation_type AS ENUM (
    'alias_of', 'member_of', 'affiliated_with',
    'employed_by', 'family_of', 'associated_with'
);

-- ============================================================================
-- PROMPT MANAGEMENT TABLES
-- ============================================================================

-- Central prompt storage with versioning
CREATE TABLE prompts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) NOT NULL,
    description TEXT,
    prompt_type prompt_type NOT NULL,
    incident_type_id UUID REFERENCES incident_types(id) ON DELETE SET NULL,  -- NULL = global

    -- Content
    system_prompt TEXT NOT NULL,
    user_prompt_template TEXT NOT NULL,  -- Supports {{variable}} substitution
    output_schema JSONB,  -- Expected response schema

    -- Versioning
    version INTEGER NOT NULL DEFAULT 1,
    parent_version_id UUID REFERENCES prompts(id) ON DELETE SET NULL,
    status prompt_status DEFAULT 'draft',

    -- Model config
    model_name VARCHAR(100) DEFAULT 'claude-sonnet-4-20250514',
    max_tokens INTEGER DEFAULT 2000,
    temperature DECIMAL(2,1) DEFAULT 0.0,

    -- A/B testing
    traffic_percentage INTEGER DEFAULT 100 CHECK (traffic_percentage >= 0 AND traffic_percentage <= 100),
    ab_test_group VARCHAR(50),

    -- Audit
    -- NOTE: admin_users has no auth implementation. This FK is a placeholder. See audit D13.
    created_by UUID REFERENCES admin_users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    activated_at TIMESTAMPTZ,

    UNIQUE(slug, version)
);

CREATE INDEX idx_prompts_slug ON prompts(slug);
CREATE INDEX idx_prompts_type ON prompts(prompt_type);
CREATE INDEX idx_prompts_status ON prompts(status);
CREATE INDEX idx_prompts_incident_type ON prompts(incident_type_id);
CREATE INDEX idx_prompts_active ON prompts(status, prompt_type) WHERE status = 'active';

-- Track prompt executions for analytics
CREATE TABLE prompt_executions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    prompt_id UUID NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
    article_id UUID REFERENCES ingested_articles(id) ON DELETE SET NULL,
    incident_id UUID REFERENCES incidents(id) ON DELETE SET NULL,

    -- Execution metrics
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_ms INTEGER,
    success BOOLEAN NOT NULL DEFAULT TRUE,
    error_message TEXT,

    -- Results
    confidence_score DECIMAL(3,2),
    result_data JSONB,
    ab_variant VARCHAR(50),

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_prompt_executions_prompt ON prompt_executions(prompt_id);
CREATE INDEX idx_prompt_executions_article ON prompt_executions(article_id);
CREATE INDEX idx_prompt_executions_created ON prompt_executions(created_at DESC);
CREATE INDEX idx_prompt_executions_success ON prompt_executions(prompt_id, success);

-- ============================================================================
-- ENHANCED INCIDENT TYPES
-- ============================================================================

-- Add new columns to incident_types for full configurability
ALTER TABLE incident_types ADD COLUMN IF NOT EXISTS slug VARCHAR(50);
ALTER TABLE incident_types ADD COLUMN IF NOT EXISTS display_name VARCHAR(100);
ALTER TABLE incident_types ADD COLUMN IF NOT EXISTS icon VARCHAR(50);
ALTER TABLE incident_types ADD COLUMN IF NOT EXISTS color VARCHAR(7);
ALTER TABLE incident_types ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
ALTER TABLE incident_types ADD COLUMN IF NOT EXISTS parent_type_id UUID REFERENCES incident_types(id) ON DELETE SET NULL;
ALTER TABLE incident_types ADD COLUMN IF NOT EXISTS pipeline_config JSONB DEFAULT '{}';
ALTER TABLE incident_types ADD COLUMN IF NOT EXISTS approval_thresholds JSONB DEFAULT '{}';
ALTER TABLE incident_types ADD COLUMN IF NOT EXISTS validation_rules JSONB DEFAULT '[]';
ALTER TABLE incident_types ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- Create unique constraint on slug
CREATE UNIQUE INDEX IF NOT EXISTS idx_incident_types_slug ON incident_types(slug) WHERE slug IS NOT NULL;

-- Update existing types with slugs
UPDATE incident_types SET slug = lower(replace(replace(name, ' ', '_'), '-', '_')) WHERE slug IS NULL;

-- Custom field definitions per type
CREATE TABLE field_definitions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_type_id UUID NOT NULL REFERENCES incident_types(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    field_type field_type NOT NULL,
    description TEXT,

    -- Configuration
    enum_values TEXT[],  -- For enum fields
    reference_table VARCHAR(100),  -- For reference fields
    default_value TEXT,

    -- Validation
    required BOOLEAN DEFAULT FALSE,
    min_value DECIMAL,
    max_value DECIMAL,
    pattern VARCHAR(255),  -- Regex pattern for validation

    -- LLM hints
    extraction_hint TEXT,  -- Hint for LLM extraction

    -- Display
    display_order INTEGER DEFAULT 0,
    show_in_list BOOLEAN DEFAULT TRUE,
    show_in_detail BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(incident_type_id, name)
);

CREATE INDEX idx_field_definitions_type ON field_definitions(incident_type_id);
CREATE INDEX idx_field_definitions_order ON field_definitions(incident_type_id, display_order);

-- ============================================================================
-- EVENTS TABLE
-- ============================================================================

-- Events: Parent groupings of related incidents
CREATE TABLE events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(500) NOT NULL,
    slug VARCHAR(100),
    description TEXT,
    event_type VARCHAR(100),  -- protest_series, enforcement_operation, crime_spree, etc.

    -- Temporal bounds
    start_date DATE NOT NULL,
    end_date DATE,
    ongoing BOOLEAN DEFAULT FALSE,

    -- Geographic scope
    primary_state VARCHAR(50),
    primary_city VARCHAR(100),
    geographic_scope VARCHAR(50),  -- local, regional, statewide, national
    latitude DECIMAL(10, 7),
    longitude DECIMAL(10, 7),

    -- AI-generated analysis
    ai_analysis JSONB,
    ai_summary TEXT,

    -- Metadata
    tags TEXT[],
    external_ids JSONB,  -- References to external systems

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_events_dates ON events(start_date, end_date);
CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_state ON events(primary_state);
CREATE INDEX idx_events_slug ON events(slug) WHERE slug IS NOT NULL;
CREATE INDEX idx_events_tags ON events USING gin(tags);

-- ============================================================================
-- ACTORS TABLE
-- ============================================================================

-- Actors: First-class entities (persons, orgs, agencies)
CREATE TABLE actors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    canonical_name VARCHAR(500) NOT NULL,
    actor_type actor_type NOT NULL,
    aliases TEXT[],

    -- Person-specific fields
    date_of_birth DATE,
    date_of_death DATE,
    gender VARCHAR(20),
    nationality VARCHAR(100),
    immigration_status VARCHAR(100),
    prior_deportations INTEGER DEFAULT 0,

    -- Organization-specific fields
    organization_type VARCHAR(100),  -- law_enforcement, advocacy, media, etc.
    parent_org_id UUID REFERENCES actors(id) ON DELETE SET NULL,
    is_government_entity BOOLEAN DEFAULT FALSE,
    is_law_enforcement BOOLEAN DEFAULT FALSE,
    jurisdiction VARCHAR(100),  -- For agencies: federal, state, local

    -- Profile
    description TEXT,
    profile_data JSONB,  -- Additional structured data
    external_ids JSONB,  -- ICE detainee number, court case IDs, etc.

    -- Entity resolution
    confidence_score DECIMAL(3,2),  -- Confidence in entity resolution
    merged_from UUID[],  -- IDs of actors merged into this one
    is_merged BOOLEAN DEFAULT FALSE,  -- Soft delete for merged records

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_actors_type ON actors(actor_type);
CREATE INDEX idx_actors_name ON actors(canonical_name);
CREATE INDEX idx_actors_name_trgm ON actors USING gin(canonical_name gin_trgm_ops);
CREATE INDEX idx_actors_aliases ON actors USING gin(aliases);
CREATE INDEX idx_actors_immigration ON actors(immigration_status) WHERE immigration_status IS NOT NULL;
CREATE INDEX idx_actors_law_enforcement ON actors(is_law_enforcement) WHERE is_law_enforcement = TRUE;

-- ============================================================================
-- RELATIONSHIP TABLES
-- ============================================================================

-- Incident ↔ Event relationship
CREATE TABLE incident_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    is_primary_event BOOLEAN DEFAULT FALSE,
    sequence_number INTEGER,  -- Order within the event
    assigned_by VARCHAR(20) DEFAULT 'manual',  -- 'manual' or 'ai'
    assignment_confidence DECIMAL(3,2),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(incident_id, event_id)
);

CREATE INDEX idx_incident_events_incident ON incident_events(incident_id);
CREATE INDEX idx_incident_events_event ON incident_events(event_id);

-- Incident ↔ Actor relationship (replaces incident_persons)
CREATE TABLE incident_actors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    actor_id UUID NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
    role actor_role NOT NULL,
    role_detail TEXT,  -- Additional role context
    is_primary BOOLEAN DEFAULT FALSE,
    sequence_number INTEGER,  -- Order for multiple actors in same role
    assigned_by VARCHAR(20) DEFAULT 'manual',  -- 'manual' or 'ai'
    assignment_confidence DECIMAL(3,2),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(incident_id, actor_id, role)
);

CREATE INDEX idx_incident_actors_incident ON incident_actors(incident_id);
CREATE INDEX idx_incident_actors_actor ON incident_actors(actor_id);
CREATE INDEX idx_incident_actors_role ON incident_actors(role);

-- Actor ↔ Actor relationships
CREATE TABLE actor_relations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    actor_id UUID NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
    related_actor_id UUID NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
    relation_type actor_relation_type NOT NULL,
    confidence DECIMAL(3,2),
    start_date DATE,
    end_date DATE,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT no_self_relation CHECK (actor_id != related_actor_id),
    UNIQUE(actor_id, related_actor_id, relation_type)
);

CREATE INDEX idx_actor_relations_actor ON actor_relations(actor_id);
CREATE INDEX idx_actor_relations_related ON actor_relations(related_actor_id);
CREATE INDEX idx_actor_relations_type ON actor_relations(relation_type);

-- ============================================================================
-- ENHANCED INCIDENT RELATIONS
-- ============================================================================

-- Add new relation types to existing enum (if not exists)
DO $$ BEGIN
    ALTER TYPE relation_type ADD VALUE IF NOT EXISTS 'same_event';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TYPE relation_type ADD VALUE IF NOT EXISTS 'caused_by';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TYPE relation_type ADD VALUE IF NOT EXISTS 'response_to';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TYPE relation_type ADD VALUE IF NOT EXISTS 'involves_same_actor';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TYPE relation_type ADD VALUE IF NOT EXISTS 'escalation_of';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Add new columns to incident_relations
ALTER TABLE incident_relations ADD COLUMN IF NOT EXISTS source VARCHAR(20) DEFAULT 'manual';  -- 'manual' or 'ai'
ALTER TABLE incident_relations ADD COLUMN IF NOT EXISTS suggested_by_prompt_id UUID REFERENCES prompts(id) ON DELETE SET NULL;
ALTER TABLE incident_relations ADD COLUMN IF NOT EXISTS verified BOOLEAN DEFAULT FALSE;
ALTER TABLE incident_relations ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;
-- NOTE: admin_users has no auth implementation. This FK is a placeholder. See audit D13.
ALTER TABLE incident_relations ADD COLUMN IF NOT EXISTS verified_by UUID REFERENCES admin_users(id) ON DELETE SET NULL;

-- ============================================================================
-- PIPELINE CONFIGURATION
-- ============================================================================

-- Available pipeline stages
CREATE TABLE pipeline_stages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    handler_class VARCHAR(200) NOT NULL,  -- Python class path
    default_order INTEGER NOT NULL,
    config_schema JSONB,  -- JSON Schema for stage config
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Per-type pipeline configuration
CREATE TABLE incident_type_pipeline_config (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_type_id UUID NOT NULL REFERENCES incident_types(id) ON DELETE CASCADE,
    pipeline_stage_id UUID NOT NULL REFERENCES pipeline_stages(id) ON DELETE CASCADE,
    enabled BOOLEAN DEFAULT TRUE,
    execution_order INTEGER,  -- Override default order
    stage_config JSONB DEFAULT '{}',  -- Stage-specific configuration
    prompt_id UUID REFERENCES prompts(id) ON DELETE SET NULL,  -- Optional prompt override
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(incident_type_id, pipeline_stage_id)
);

CREATE INDEX idx_pipeline_config_type ON incident_type_pipeline_config(incident_type_id);
CREATE INDEX idx_pipeline_config_stage ON incident_type_pipeline_config(pipeline_stage_id);

-- ============================================================================
-- SEED DATA
-- ============================================================================

-- Seed default pipeline stages
INSERT INTO pipeline_stages (name, slug, handler_class, default_order, description) VALUES
    ('URL Deduplication', 'url_dedupe', 'backend.pipeline.stages.URLDedupeStage', 10, 'Check for duplicate URLs'),
    ('Content Deduplication', 'content_dedupe', 'backend.pipeline.stages.ContentDedupeStage', 20, 'Check for duplicate content via similarity'),
    ('Relevance Check', 'relevance', 'backend.pipeline.stages.RelevanceStage', 30, 'AI relevance scoring'),
    ('Type Classification', 'classification', 'backend.pipeline.stages.ClassificationStage', 40, 'Classify incident type'),
    ('Data Extraction', 'extraction', 'backend.pipeline.stages.ExtractionStage', 50, 'Extract structured data via LLM'),
    ('Entity Resolution', 'entity_resolution', 'backend.pipeline.stages.EntityResolutionStage', 60, 'Match/create actors'),
    ('Validation', 'validation', 'backend.pipeline.stages.ValidationStage', 70, 'Validate extracted data'),
    ('Auto-Approval', 'auto_approval', 'backend.pipeline.stages.AutoApprovalStage', 80, 'Evaluate for auto-approval'),
    ('Pattern Detection', 'pattern_detection', 'backend.pipeline.stages.PatternDetectionStage', 90, 'Detect patterns and clusters'),
    ('Cross-Reference', 'cross_reference', 'backend.pipeline.stages.CrossReferenceStage', 100, 'Link to related incidents/events')
ON CONFLICT (slug) DO NOTHING;

-- Seed default prompts for existing categories
INSERT INTO prompts (name, slug, prompt_type, system_prompt, user_prompt_template, status)
SELECT
    'Enforcement Extraction',
    'enforcement_extraction',
    'extraction'::prompt_type,
    'You are extracting data about violent incidents involving ICE/CBP agents.

Focus on: victim details, officer involvement, outcome severity, location.
This tracks enforcement actions that harmed non-immigrants (protesters, journalists, bystanders, US citizens).

Key entities to extract:
- victim_name, victim_age, victim_category
- officer_involved, agency (ICE/CBP)
- outcome_category (death, serious_injury, minor_injury, no_injury, unknown)

Higher scrutiny is required for enforcement incidents. Be conservative with confidence scores.

For each field you extract, provide a confidence score from 0.0 to 1.0:
- 1.0: Explicitly stated in the text
- 0.7-0.9: Strongly implied or inferrable
- 0.4-0.6: Partially mentioned or uncertain
- 0.1-0.3: Weak inference
- 0.0: Not found or pure guess

Always return valid JSON matching the expected schema.',
    'You are extracting data about an enforcement incident involving ICE/CBP agents.

Focus on extracting:
- victim_name, victim_age, victim_category (who was harmed)
- officer_involved, agency (who caused the harm)
- outcome_category (severity of harm)
- Location and date details

Victim categories: detainee, enforcement_target, protester, journalist, bystander, us_citizen_collateral, officer, multiple

For each field you extract, provide a confidence score from 0.0 to 1.0.

ARTICLE TEXT:
{{article_text}}

Extract the incident data and return as JSON.',
    'active'::prompt_status
WHERE NOT EXISTS (SELECT 1 FROM prompts WHERE slug = 'enforcement_extraction');

INSERT INTO prompts (name, slug, prompt_type, system_prompt, user_prompt_template, status)
SELECT
    'Crime Extraction',
    'crime_extraction',
    'extraction'::prompt_type,
    'You are extracting data about crimes committed by individuals with immigration status issues.

Focus on: offender details, criminal history, prior deportations, gang affiliation, ICE detainer status.

Key entities to extract:
- offender_name, offender_age, offender_nationality
- offender_immigration_status (undocumented, visa overstay, DACA, TPS, etc.)
- prior_deportations
- gang_affiliated, gang_name
- ice_detainer_status

For each field you extract, provide a confidence score from 0.0 to 1.0:
- 1.0: Explicitly stated in the text
- 0.7-0.9: Strongly implied or inferrable
- 0.4-0.6: Partially mentioned or uncertain
- 0.1-0.3: Weak inference
- 0.0: Not found or pure guess

Always return valid JSON matching the expected schema.',
    'You are extracting data about a crime committed by an individual with immigration status issues.

Focus on extracting:
- offender_name, offender_age, offender_nationality
- offender_immigration_status (undocumented, visa overstay, etc.)
- prior_deportations (number if mentioned)
- gang_affiliated, gang_name
- ice_detainer_status
- incident_type (the crime committed)

For each field you extract, provide a confidence score from 0.0 to 1.0.

ARTICLE TEXT:
{{article_text}}

Extract the incident data and return as JSON.',
    'active'::prompt_status
WHERE NOT EXISTS (SELECT 1 FROM prompts WHERE slug = 'crime_extraction');

INSERT INTO prompts (name, slug, prompt_type, system_prompt, user_prompt_template, status)
SELECT
    'General Classification',
    'general_classification',
    'classification'::prompt_type,
    'You are a precise classification assistant. Your role is to:
1. Read articles about potential immigration-related incidents
2. Determine if the article is relevant
3. Classify as either "enforcement" (ICE/CBP action) or "crime" (crime by immigrant)
4. Provide confidence scores

Be conservative with relevance - only mark as relevant if clearly related.',
    'Analyze this article and classify it:

ARTICLE TEXT:
{{article_text}}

Return JSON with:
- is_relevant: boolean
- relevance_reason: string
- category: "enforcement" or "crime" (if relevant)
- category_confidence: 0.0-1.0',
    'active'::prompt_status
WHERE NOT EXISTS (SELECT 1 FROM prompts WHERE slug = 'general_classification');

-- Create default approval thresholds for incident types
UPDATE incident_types
SET approval_thresholds = '{
    "min_confidence_auto_approve": 0.90,
    "min_confidence_review": 0.50,
    "auto_reject_below": 0.30,
    "field_confidence_threshold": 0.75
}'::jsonb
WHERE category = 'enforcement' AND (approval_thresholds IS NULL OR approval_thresholds = '{}'::jsonb);

UPDATE incident_types
SET approval_thresholds = '{
    "min_confidence_auto_approve": 0.85,
    "min_confidence_review": 0.50,
    "auto_reject_below": 0.30,
    "field_confidence_threshold": 0.70
}'::jsonb
WHERE category = 'crime' AND (approval_thresholds IS NULL OR approval_thresholds = '{}'::jsonb);

-- ============================================================================
-- TRIGGERS
-- ============================================================================

-- Update timestamp triggers for new tables
CREATE TRIGGER update_prompts_timestamp
    BEFORE UPDATE ON prompts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_field_definitions_timestamp
    BEFORE UPDATE ON field_definitions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_events_timestamp
    BEFORE UPDATE ON events
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_actors_timestamp
    BEFORE UPDATE ON actors
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_incident_types_timestamp
    BEFORE UPDATE ON incident_types
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_incident_type_pipeline_config_timestamp
    BEFORE UPDATE ON incident_type_pipeline_config
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Active prompts by type
CREATE OR REPLACE VIEW active_prompts AS
SELECT
    p.*,
    it.name as incident_type_name,
    it.category as incident_category
FROM prompts p
LEFT JOIN incident_types it ON p.incident_type_id = it.id
WHERE p.status = 'active';

-- Event summary with incident counts
CREATE OR REPLACE VIEW events_summary AS
SELECT
    e.*,
    COUNT(DISTINCT ie.incident_id) as incident_count,
    MIN(i.date) as first_incident_date,
    MAX(i.date) as last_incident_date
FROM events e
LEFT JOIN incident_events ie ON e.id = ie.event_id
LEFT JOIN incidents i ON ie.incident_id = i.id
GROUP BY e.id;

-- Actor summary with incident counts
CREATE OR REPLACE VIEW actors_summary AS
SELECT
    a.*,
    COUNT(DISTINCT ia.incident_id) as incident_count,
    array_agg(DISTINCT ia.role) as roles_played
FROM actors a
LEFT JOIN incident_actors ia ON a.id = ia.actor_id
WHERE NOT a.is_merged
GROUP BY a.id;

-- ============================================================================
-- GRANTS
-- ============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON prompts TO sentinel;
GRANT SELECT, INSERT, UPDATE, DELETE ON prompt_executions TO sentinel;
GRANT SELECT, INSERT, UPDATE, DELETE ON field_definitions TO sentinel;
GRANT SELECT, INSERT, UPDATE, DELETE ON events TO sentinel;
GRANT SELECT, INSERT, UPDATE, DELETE ON actors TO sentinel;
GRANT SELECT, INSERT, UPDATE, DELETE ON incident_events TO sentinel;
GRANT SELECT, INSERT, UPDATE, DELETE ON incident_actors TO sentinel;
GRANT SELECT, INSERT, UPDATE, DELETE ON actor_relations TO sentinel;
GRANT SELECT, INSERT, UPDATE, DELETE ON pipeline_stages TO sentinel;
GRANT SELECT, INSERT, UPDATE, DELETE ON incident_type_pipeline_config TO sentinel;
GRANT SELECT ON active_prompts TO sentinel;
GRANT SELECT ON events_summary TO sentinel;
GRANT SELECT ON actors_summary TO sentinel;
