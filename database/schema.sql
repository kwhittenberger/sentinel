-- Unified Incident Tracker Database Schema
-- This file represents the canonical schema after all migrations (001–035) are applied.
-- It is the single source of truth for the database structure.
-- Last synchronized: 2026-02-06
--
-- ==========================================================================
-- DATA MODEL LAYERS (three coexisting models):
--
--   Layer 1 — Person-centric (LEGACY):
--     persons, incident_persons
--     Original person/role model. Superseded by actors/incident_actors (migration 002).
--     Still referenced by import scripts and actor_service migration logic.
--
--   Layer 2 — Event-centric (ACTIVE, preferred for new code):
--     actors, incident_actors, events, incident_events, actor_relations
--     Introduced in migration 002. Supports typed actors (person/org/agency/group),
--     configurable roles (actor_role_types, migration 010), and event groupings.
--
--   Layer 3 — Case-centric (ACTIVE):
--     cases, charges, charge_history, dispositions, case_incidents, case_actors,
--     prosecutorial_actions, bail_decisions, case_jurisdictions
--     Introduced in migration 013. Legal case lifecycle tracking.
--
-- EXTRACTION PIPELINES:
--   Legacy (one-shot): ingested_articles.extracted_data (JSONB column)
--   Two-stage (preferred): article_extractions (Stage 1 IR) +
--     schema_extraction_results (Stage 2 per-schema output)
--     Introduced in migration 017. Check ingested_articles.extraction_pipeline
--     column ('legacy' or 'two_stage') to determine which pipeline was used.
-- ==========================================================================

-- ============================================================================
-- EXTENSIONS
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- For fuzzy text search

-- ============================================================================
-- ENUM TYPES
-- ============================================================================

-- Discriminator for incident type (legacy — see event_domains/event_categories for new system)
CREATE TYPE incident_category AS ENUM ('enforcement', 'crime');

-- Source tier for confidence scoring
CREATE TYPE source_tier AS ENUM ('1', '2', '3', '4');

-- Curation workflow status (migration 029 added 'error')
CREATE TYPE curation_status AS ENUM ('pending', 'in_review', 'approved', 'rejected', 'error');

-- Person role in incident (legacy — see actor_role_types table)
CREATE TYPE person_role AS ENUM ('victim', 'offender', 'witness', 'officer');

-- Incident relation type (migration 002 added additional values)
CREATE TYPE relation_type AS ENUM (
    'duplicate', 'related', 'follow_up',
    'same_event', 'caused_by', 'response_to',
    'involves_same_actor', 'escalation_of'
);

-- Incident scale
CREATE TYPE incident_scale AS ENUM ('single', 'small', 'medium', 'large', 'mass');

-- Prompt types for different AI tasks (migration 002)
CREATE TYPE prompt_type AS ENUM (
    'extraction', 'classification', 'entity_resolution',
    'pattern_detection', 'summarization', 'analysis'
);

CREATE TYPE prompt_status AS ENUM ('draft', 'active', 'testing', 'deprecated', 'archived');

-- Field types for custom field definitions (migration 002)
CREATE TYPE field_type AS ENUM (
    'string', 'text', 'integer', 'decimal', 'boolean',
    'date', 'datetime', 'enum', 'array', 'reference'
);

-- Actor types (migration 002)
CREATE TYPE actor_type AS ENUM ('person', 'organization', 'agency', 'group');

-- Actor roles in incidents (enum — see actor_role_types table for extensible version)
CREATE TYPE actor_role AS ENUM (
    'victim', 'offender', 'witness', 'officer',
    'arresting_agency', 'reporting_agency',
    'bystander', 'organizer', 'participant'
);

-- Actor relationship types (migration 002)
CREATE TYPE actor_relation_type AS ENUM (
    'alias_of', 'member_of', 'affiliated_with',
    'employed_by', 'family_of', 'associated_with'
);

-- ============================================================================
-- MIGRATION TRACKING
-- ============================================================================

CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(255) PRIMARY KEY,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- CORE TABLES
-- ============================================================================

-- Jurisdictions (states and counties with sanctuary policies) [ACTIVE — shared across all layers]
CREATE TABLE jurisdictions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    jurisdiction_type VARCHAR(50) NOT NULL CHECK (jurisdiction_type IN ('state', 'county', 'city')),
    state_code CHAR(2),
    fips_code VARCHAR(10),
    parent_jurisdiction_id UUID REFERENCES jurisdictions(id),

    -- Sanctuary policy data
    state_sanctuary_status VARCHAR(50),
    local_sanctuary_status VARCHAR(50),
    detainer_policy VARCHAR(100),
    policy_source_url TEXT,
    policy_effective_date DATE,

    -- Geographic data
    latitude DECIMAL(10, 7),
    longitude DECIMAL(10, 7),

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_jurisdictions_state ON jurisdictions(state_code);
CREATE INDEX idx_jurisdictions_fips ON jurisdictions(fips_code);
CREATE INDEX idx_jurisdictions_type ON jurisdictions(jurisdiction_type);

-- Sources (news outlets and government sources) [ACTIVE — shared across all layers]
-- Migration 033 added scheduling columns (interval_minutes, last_fetched, last_error)
-- and dropped rss_feeds table in favor of this unified sources table
CREATE TABLE sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL UNIQUE,
    source_type VARCHAR(50) NOT NULL,  -- government, news, investigative, social_media
    tier source_tier NOT NULL,
    url TEXT,
    description TEXT,
    reliability_score DECIMAL(3, 2),  -- 0.00 to 1.00
    is_active BOOLEAN DEFAULT TRUE,

    -- Fetcher configuration
    fetcher_class VARCHAR(100),
    fetcher_config JSONB,
    cache_hours INTEGER DEFAULT 24,

    -- Scheduling (migration 033, replaces rss_feeds)
    interval_minutes INTEGER DEFAULT 60,
    last_fetched TIMESTAMP WITH TIME ZONE,
    last_error TEXT,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_sources_tier ON sources(tier);
CREATE INDEX idx_sources_type ON sources(source_type);

-- Incident types with severity weights [ACTIVE — extended in migration 002]
CREATE TABLE incident_types (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    category incident_category NOT NULL,
    description TEXT,
    severity_weight DECIMAL(3, 2) NOT NULL DEFAULT 1.0,

    -- Extensibility columns (migration 002)
    slug VARCHAR(50),
    display_name VARCHAR(100),
    icon VARCHAR(50),
    color VARCHAR(7),
    is_active BOOLEAN DEFAULT TRUE,
    parent_type_id UUID REFERENCES incident_types(id) ON DELETE SET NULL,
    pipeline_config JSONB DEFAULT '{}',
    approval_thresholds JSONB DEFAULT '{}',
    validation_rules JSONB DEFAULT '[]',

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_incident_types_slug ON incident_types(slug) WHERE slug IS NOT NULL;

-- Seed incident types
INSERT INTO incident_types (name, category, description, severity_weight) VALUES
    -- Enforcement incident types
    ('death_in_custody', 'enforcement', 'Death while in ICE/CBP custody', 5.0),
    ('shooting', 'enforcement', 'Shooting by enforcement officer', 4.5),
    ('taser', 'enforcement', 'Taser deployment', 3.0),
    ('pepper_spray', 'enforcement', 'Pepper spray deployment', 2.5),
    ('physical_force', 'enforcement', 'Physical force used', 2.5),
    ('vehicle_pursuit', 'enforcement', 'Vehicle pursuit incident', 3.5),
    ('raid_injury', 'enforcement', 'Injury during enforcement raid', 3.0),
    ('medical_neglect', 'enforcement', 'Medical neglect in custody', 4.0),
    ('wrongful_detention', 'enforcement', 'Wrongful detention of citizen', 3.5),
    ('property_damage', 'enforcement', 'Property damage during enforcement', 1.5),
    ('protest_clash', 'enforcement', 'Clash with protesters', 2.5),
    ('journalist_interference', 'enforcement', 'Interference with journalist', 2.0),
    -- Crime incident types
    ('homicide', 'crime', 'Homicide', 5.0),
    ('assault', 'crime', 'Assault', 3.5),
    ('robbery', 'crime', 'Robbery', 3.0),
    ('dui_fatality', 'crime', 'DUI resulting in fatality', 4.5),
    ('sexual_assault', 'crime', 'Sexual assault', 4.5),
    ('kidnapping', 'crime', 'Kidnapping', 4.0),
    ('gang_activity', 'crime', 'Gang-related activity', 3.5),
    ('drug_trafficking', 'crime', 'Drug trafficking', 3.0),
    ('human_trafficking', 'crime', 'Human trafficking', 4.5);

-- Backfill slugs
UPDATE incident_types SET slug = lower(replace(replace(name, ' ', '_'), '-', '_')) WHERE slug IS NULL;

-- ============================================================================
-- EVENT TAXONOMY (migration 009)
-- ============================================================================

-- Event domains (top-level grouping)
CREATE TABLE event_domains (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    slug VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    icon VARCHAR(50),
    color VARCHAR(7) CHECK (color IS NULL OR color ~ '^#[0-9A-Fa-f]{6}$'),
    is_active BOOLEAN DEFAULT TRUE,
    display_order INTEGER DEFAULT 0,
    relevance_scope TEXT,  -- Migration 030: LLM-readable domain relevance criteria
    archived_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_event_domains_slug ON event_domains(slug);
CREATE INDEX idx_event_domains_active ON event_domains(is_active) WHERE is_active = TRUE;

-- Event categories (hierarchical within domains)
CREATE TABLE event_categories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain_id UUID NOT NULL REFERENCES event_domains(id) ON DELETE RESTRICT,
    parent_category_id UUID REFERENCES event_categories(id),
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(100) NOT NULL,
    description TEXT,
    icon VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    display_order INTEGER DEFAULT 0,

    -- Schema definition for this category's custom fields
    required_fields JSONB DEFAULT '[]'::jsonb,
    optional_fields JSONB DEFAULT '[]'::jsonb,
    field_definitions JSONB DEFAULT '{}'::jsonb,

    archived_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(domain_id, slug)
);

CREATE INDEX idx_event_categories_domain ON event_categories(domain_id);
CREATE INDEX idx_event_categories_parent ON event_categories(parent_category_id);
CREATE INDEX idx_event_categories_slug ON event_categories(slug);
CREATE INDEX idx_event_categories_active ON event_categories(is_active) WHERE is_active = TRUE;

-- ============================================================================
-- EXTENSIBLE TYPE TABLES (migration 007)
-- ============================================================================

-- Outcome types (replaces outcome_category enum)
CREATE TABLE outcome_types (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    slug VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    severity_weight DECIMAL(3, 2) DEFAULT 1.0,
    is_active BOOLEAN DEFAULT TRUE,
    display_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_outcome_types_slug ON outcome_types(slug);
CREATE INDEX idx_outcome_types_active ON outcome_types(is_active) WHERE is_active = TRUE;

-- Victim categories (replaces victim_category enum)
CREATE TABLE victim_types (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    slug VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    display_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_victim_types_slug ON victim_types(slug);
CREATE INDEX idx_victim_types_active ON victim_types(is_active) WHERE is_active = TRUE;

-- ============================================================================
-- UNIFIED INCIDENTS TABLE
-- ============================================================================

-- Extended by migration 007 (outcome_type_id, victim_type_id replacing enum columns),
-- migration 009 (domain_id, category_id, custom_fields, event dates, tags),
-- migration 031 (unique source_url index)
CREATE TABLE incidents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    legacy_id VARCHAR(50),

    -- Category discriminator (legacy)
    category incident_category NOT NULL,

    -- Event taxonomy (migration 009)
    domain_id UUID REFERENCES event_domains(id),
    category_id UUID REFERENCES event_categories(id),
    custom_fields JSONB DEFAULT '{}'::jsonb,
    event_start_date TIMESTAMPTZ,
    event_end_date TIMESTAMPTZ,
    tags TEXT[] DEFAULT ARRAY[]::TEXT[],

    -- Core incident data
    date DATE NOT NULL,
    date_precision VARCHAR(20) DEFAULT 'day',
    incident_type_id UUID NOT NULL REFERENCES incident_types(id),

    -- Location
    jurisdiction_id UUID REFERENCES jurisdictions(id),
    state VARCHAR(50) NOT NULL,
    city VARCHAR(100),
    address TEXT,
    latitude DECIMAL(10, 7),
    longitude DECIMAL(10, 7),

    -- Incident details
    title VARCHAR(500),
    description TEXT,
    notes TEXT,

    -- Scale and outcome (migration 007: outcome_type_id replaces outcome_category enum)
    affected_count INTEGER DEFAULT 1,
    incident_scale incident_scale DEFAULT 'single',
    outcome VARCHAR(100),
    outcome_type_id UUID REFERENCES outcome_types(id),
    outcome_detail TEXT,

    -- Victim information (migration 007: victim_type_id replaces victim_category enum)
    victim_type_id UUID REFERENCES victim_types(id),
    victim_name VARCHAR(255),
    victim_age INTEGER,
    us_citizen BOOLEAN,
    protest_related BOOLEAN DEFAULT FALSE,

    -- Source tracking
    source_tier source_tier NOT NULL,
    primary_source_id UUID REFERENCES sources(id),
    source_url TEXT,
    source_name VARCHAR(255),
    verified BOOLEAN DEFAULT FALSE,

    -- Sanctuary policy context (denormalized for performance)
    state_sanctuary_status VARCHAR(50),
    local_sanctuary_status VARCHAR(50),
    detainer_policy VARCHAR(100),

    -- Crime-specific fields
    offender_immigration_status VARCHAR(50),
    prior_deportations INTEGER DEFAULT 0,
    gang_affiliated BOOLEAN DEFAULT FALSE,

    -- Curation workflow
    curation_status curation_status DEFAULT 'approved',
    extraction_confidence DECIMAL(3, 2),
    curated_by UUID,
    curated_at TIMESTAMP WITH TIME ZONE,

    -- Audit fields
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT valid_affected_count CHECK (affected_count >= 0),
    CONSTRAINT valid_age CHECK (victim_age IS NULL OR (victim_age >= 0 AND victim_age <= 150)),
    CONSTRAINT valid_confidence CHECK (extraction_confidence IS NULL OR (extraction_confidence >= 0 AND extraction_confidence <= 1))
);

CREATE INDEX idx_incidents_category ON incidents(category);
CREATE INDEX idx_incidents_date ON incidents(date);
CREATE INDEX idx_incidents_state ON incidents(state);
CREATE INDEX idx_incidents_city ON incidents(city);
CREATE INDEX idx_incidents_type ON incidents(incident_type_id);
CREATE INDEX idx_incidents_tier ON incidents(source_tier);
CREATE INDEX idx_incidents_outcome_type ON incidents(outcome_type_id);
CREATE INDEX idx_incidents_victim_type ON incidents(victim_type_id);
CREATE INDEX idx_incidents_legacy_id ON incidents(legacy_id);
CREATE INDEX idx_incidents_curation ON incidents(curation_status);
CREATE INDEX idx_incidents_location ON incidents(latitude, longitude) WHERE latitude IS NOT NULL;
CREATE INDEX idx_incidents_domain ON incidents(domain_id);
CREATE INDEX idx_incidents_category_id ON incidents(category_id);
CREATE INDEX idx_incidents_custom_fields ON incidents USING gin(custom_fields);
CREATE INDEX idx_incidents_tags ON incidents USING gin(tags);
CREATE INDEX idx_incidents_date_range ON incidents(event_start_date, event_end_date);
CREATE UNIQUE INDEX idx_incidents_source_url_unique ON incidents(source_url) WHERE source_url IS NOT NULL;

-- Full-text search index
CREATE INDEX idx_incidents_search ON incidents USING gin(
    to_tsvector('english', COALESCE(title, '') || ' ' || COALESCE(description, '') || ' ' || COALESCE(notes, ''))
);

-- Compound indexes for analytics queries (migration 035)
CREATE INDEX idx_incidents_state_date ON incidents(state, date);
CREATE INDEX idx_incidents_type_date ON incidents(incident_type_id, date);
CREATE INDEX idx_incidents_outcome_date ON incidents(outcome_category, date);
CREATE INDEX idx_incidents_curation_created ON incidents(curation_status, created_at);

-- ============================================================================
-- PERSONS (LEGACY Layer 1 — superseded by actors table)
-- ============================================================================

CREATE TABLE persons (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255),
    aliases TEXT[],
    age INTEGER,
    date_of_birth DATE,
    gender VARCHAR(20),
    nationality VARCHAR(100),
    immigration_status VARCHAR(100),
    prior_deportations INTEGER DEFAULT 0,
    reentry_after_deportation BOOLEAN DEFAULT FALSE,
    visa_type VARCHAR(50),
    visa_overstay BOOLEAN DEFAULT FALSE,
    gang_affiliated BOOLEAN DEFAULT FALSE,
    gang_name VARCHAR(100),
    prior_convictions INTEGER DEFAULT 0,
    prior_violent_convictions INTEGER DEFAULT 0,
    us_citizen BOOLEAN,
    occupation VARCHAR(100),
    external_ids JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_persons_name ON persons(name);
CREATE INDEX idx_persons_name_trgm ON persons USING gin(name gin_trgm_ops);
CREATE INDEX idx_persons_immigration ON persons(immigration_status);
CREATE INDEX idx_persons_gang ON persons(gang_affiliated) WHERE gang_affiliated = TRUE;

-- ============================================================================
-- ACTORS (ACTIVE Layer 2 — migration 002)
-- ============================================================================

CREATE TABLE actors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    canonical_name VARCHAR(500) NOT NULL,
    actor_type actor_type NOT NULL,
    aliases TEXT[],
    date_of_birth DATE,
    date_of_death DATE,
    gender VARCHAR(20),
    nationality VARCHAR(100),
    immigration_status VARCHAR(100),
    prior_deportations INTEGER DEFAULT 0,
    organization_type VARCHAR(100),
    parent_org_id UUID REFERENCES actors(id) ON DELETE SET NULL,
    is_government_entity BOOLEAN DEFAULT FALSE,
    is_law_enforcement BOOLEAN DEFAULT FALSE,
    jurisdiction VARCHAR(100),
    description TEXT,
    profile_data JSONB,
    external_ids JSONB,
    confidence_score DECIMAL(3,2),
    merged_from UUID[],
    is_merged BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_actors_type ON actors(actor_type);
CREATE INDEX idx_actors_name ON actors(canonical_name);
CREATE INDEX idx_actors_name_trgm ON actors USING gin(canonical_name gin_trgm_ops);
CREATE INDEX idx_actors_aliases ON actors USING gin(aliases);
CREATE INDEX idx_actors_immigration ON actors(immigration_status) WHERE immigration_status IS NOT NULL;
CREATE INDEX idx_actors_law_enforcement ON actors(is_law_enforcement) WHERE is_law_enforcement = TRUE;

-- Actor role types (extensible, replaces actor_role enum — migration 010)
CREATE TABLE actor_role_types (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    slug VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    category_id UUID REFERENCES event_categories(id),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_actor_role_types_slug ON actor_role_types(slug);
CREATE INDEX idx_actor_role_types_category ON actor_role_types(category_id);
CREATE INDEX idx_actor_role_types_active ON actor_role_types(is_active) WHERE is_active = TRUE;

-- ============================================================================
-- EVENTS TABLE (migration 002)
-- ============================================================================

CREATE TABLE events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(500) NOT NULL,
    slug VARCHAR(100),
    description TEXT,
    event_type VARCHAR(100),
    start_date DATE NOT NULL,
    end_date DATE,
    ongoing BOOLEAN DEFAULT FALSE,
    primary_state VARCHAR(50),
    primary_city VARCHAR(100),
    geographic_scope VARCHAR(50),
    latitude DECIMAL(10, 7),
    longitude DECIMAL(10, 7),
    ai_analysis JSONB,
    ai_summary TEXT,
    tags TEXT[],
    external_ids JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_events_dates ON events(start_date, end_date);
CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_state ON events(primary_state);
CREATE INDEX idx_events_slug ON events(slug) WHERE slug IS NOT NULL;
CREATE INDEX idx_events_tags ON events USING gin(tags);

-- ============================================================================
-- JUNCTION TABLES
-- ============================================================================

-- Links incidents to people (LEGACY Layer 1 — superseded by incident_actors)
CREATE TABLE incident_persons (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    person_id UUID NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    role person_role NOT NULL,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(incident_id, person_id, role)
);

CREATE INDEX idx_incident_persons_incident ON incident_persons(incident_id);
CREATE INDEX idx_incident_persons_person ON incident_persons(person_id);
CREATE INDEX idx_incident_persons_role ON incident_persons(role);

-- Multiple sources per incident [ACTIVE — shared across all layers]
CREATE TABLE incident_sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    source_id UUID REFERENCES sources(id),
    url TEXT,
    title VARCHAR(500),
    published_date DATE,
    archived_url TEXT,
    is_primary BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(incident_id, url)
);

CREATE INDEX idx_incident_sources_incident ON incident_sources(incident_id);
CREATE INDEX idx_incident_sources_source ON incident_sources(source_id);

-- Incident relations (legacy — extended in migration 002 with new relation types and columns)
CREATE TABLE incident_relations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    related_incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    relation_type relation_type NOT NULL,
    confidence DECIMAL(3, 2),
    notes TEXT,

    -- Added by migration 002
    source VARCHAR(20) DEFAULT 'manual',
    suggested_by_prompt_id UUID,  -- References prompts(id)
    verified BOOLEAN DEFAULT FALSE,
    verified_at TIMESTAMPTZ,
    verified_by UUID,  -- References admin_users(id)

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT no_self_relation CHECK (incident_id != related_incident_id),
    UNIQUE(incident_id, related_incident_id, relation_type)
);

CREATE INDEX idx_incident_relations_incident ON incident_relations(incident_id);
CREATE INDEX idx_incident_relations_related ON incident_relations(related_incident_id);
CREATE INDEX idx_incident_relations_type ON incident_relations(relation_type);

-- Incident <-> Event relationship (migration 002)
CREATE TABLE incident_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    is_primary_event BOOLEAN DEFAULT FALSE,
    sequence_number INTEGER,
    assigned_by VARCHAR(20) DEFAULT 'manual',
    assignment_confidence DECIMAL(3,2),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(incident_id, event_id)
);

CREATE INDEX idx_incident_events_incident ON incident_events(incident_id);
CREATE INDEX idx_incident_events_event ON incident_events(event_id);

-- Incident <-> Actor relationship (migration 002, replaces incident_persons)
CREATE TABLE incident_actors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    actor_id UUID NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
    role actor_role NOT NULL,
    role_detail TEXT,
    is_primary BOOLEAN DEFAULT FALSE,
    sequence_number INTEGER,
    assigned_by VARCHAR(20) DEFAULT 'manual',
    assignment_confidence DECIMAL(3,2),
    role_type_id UUID REFERENCES actor_role_types(id),  -- Migration 010
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(incident_id, actor_id, role)
);

CREATE INDEX idx_incident_actors_incident ON incident_actors(incident_id);
CREATE INDEX idx_incident_actors_actor ON incident_actors(actor_id);
CREATE INDEX idx_incident_actors_role ON incident_actors(role);
CREATE INDEX idx_incident_actors_role_type ON incident_actors(role_type_id);

-- Actor <-> Actor relationships (migration 002)
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
-- EVENT RELATIONSHIPS (migration 011)
-- ============================================================================

-- Relationship type definitions
CREATE TABLE relationship_types (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    is_directional BOOLEAN DEFAULT TRUE,
    inverse_type VARCHAR(50)
);

-- Note: cases table is defined below; the FK on case_id is added by migration 034
CREATE TABLE event_relationships (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    target_incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    relationship_type VARCHAR(50) NOT NULL REFERENCES relationship_types(name),
    sequence_order INTEGER,
    case_id UUID,  -- FK to cases(id) added after cases table definition
    description TEXT,
    confidence DECIMAL(3,2) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    created_by VARCHAR(20) DEFAULT 'manual',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CHECK (source_incident_id != target_incident_id),
    UNIQUE(source_incident_id, target_incident_id, relationship_type)
);

CREATE INDEX idx_event_rel_source ON event_relationships(source_incident_id);
CREATE INDEX idx_event_rel_target ON event_relationships(target_incident_id);
CREATE INDEX idx_event_rel_case ON event_relationships(case_id);
CREATE INDEX idx_event_rel_type ON event_relationships(relationship_type);

-- ============================================================================
-- INGESTION TABLES
-- ============================================================================

-- Raw articles awaiting curation
-- Extended by migration 017 (two-stage extraction), 026 (SET NULL FK behavior),
-- 027 (extraction error tracking)
CREATE TABLE ingested_articles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Source tracking
    source_id UUID REFERENCES sources(id) ON DELETE SET NULL,  -- Migration 026
    source_name VARCHAR(255),
    source_url TEXT NOT NULL UNIQUE,

    -- Article content
    title VARCHAR(500),
    content TEXT,
    content_hash VARCHAR(32),
    published_date DATE,
    fetched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Relevance scoring
    relevance_score DECIMAL(3, 2),
    relevance_reason TEXT,

    -- LLM extraction (legacy pipeline)
    extracted_data JSONB,
    extraction_confidence DECIMAL(3, 2),
    extracted_at TIMESTAMP WITH TIME ZONE,

    -- Two-stage pipeline (migration 017)
    latest_extraction_id UUID,  -- FK to article_extractions(id) added below, SET NULL on delete (migration 026)
    extraction_pipeline VARCHAR(20) DEFAULT 'legacy'
        CHECK (extraction_pipeline IN ('legacy', 'two_stage')),

    -- Extraction error tracking (migration 027)
    extraction_error_count INTEGER DEFAULT 0,
    last_extraction_error TEXT,
    last_extraction_error_at TIMESTAMPTZ,
    extraction_error_category VARCHAR(20),

    -- Curation workflow
    status curation_status DEFAULT 'pending',
    reviewed_by UUID,
    reviewed_at TIMESTAMP WITH TIME ZONE,
    rejection_reason TEXT,

    -- Linked incident (if approved)
    incident_id UUID REFERENCES incidents(id) ON DELETE SET NULL,  -- Migration 026

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_ingested_status ON ingested_articles(status);
CREATE INDEX idx_ingested_source ON ingested_articles(source_id);
CREATE INDEX idx_ingested_date ON ingested_articles(published_date);
CREATE INDEX idx_ingested_relevance ON ingested_articles(relevance_score DESC);
CREATE INDEX idx_ingested_content_hash ON ingested_articles(content_hash) WHERE content_hash IS NOT NULL;
CREATE INDEX idx_articles_extractable ON ingested_articles(published_date DESC NULLS LAST)
    WHERE status = 'pending'
      AND content IS NOT NULL
      AND (extraction_error_category IS NULL OR extraction_error_category != 'permanent')
      AND extraction_error_count < 3;

-- Compound indexes for analytics queries (migration 035)
CREATE INDEX idx_ingested_source_fetched ON ingested_articles(source_name, fetched_at);
CREATE INDEX idx_ingested_status_fetched ON ingested_articles(status, fetched_at);
CREATE INDEX idx_ingested_curation_queue ON ingested_articles(status, relevance_score DESC, fetched_at DESC)
    WHERE status IN ('pending', 'in_review');

-- ============================================================================
-- ADMIN TABLES
-- ============================================================================

-- NOTE: admin_users table exists but authentication is NOT implemented.
-- No backend routes check authentication. No login UI exists in the frontend.
-- This table is a placeholder for future auth.
CREATE TABLE admin_users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(100) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    is_superuser BOOLEAN DEFAULT FALSE,
    last_login TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_admin_users_email ON admin_users(email);

-- Audit log for change tracking (currently unused — no backend code writes to this table)
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES admin_users(id),
    action VARCHAR(50) NOT NULL,
    table_name VARCHAR(100) NOT NULL,
    record_id UUID NOT NULL,
    old_values JSONB,
    new_values JSONB,
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_audit_table ON audit_log(table_name);
CREATE INDEX idx_audit_record ON audit_log(record_id);
CREATE INDEX idx_audit_user ON audit_log(user_id);
CREATE INDEX idx_audit_date ON audit_log(created_at);

-- ============================================================================
-- PROMPT MANAGEMENT (migrations 002, 006, 008)
-- ============================================================================

CREATE TABLE prompts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) NOT NULL,
    description TEXT,
    prompt_type prompt_type NOT NULL,
    incident_type_id UUID REFERENCES incident_types(id) ON DELETE SET NULL,
    system_prompt TEXT NOT NULL,
    user_prompt_template TEXT NOT NULL,
    output_schema JSONB,
    version INTEGER NOT NULL DEFAULT 1,
    parent_version_id UUID REFERENCES prompts(id) ON DELETE SET NULL,
    status prompt_status DEFAULT 'draft',
    model_name VARCHAR(100) DEFAULT 'claude-sonnet-4-20250514',
    max_tokens INTEGER DEFAULT 2000,
    temperature DECIMAL(2,1) DEFAULT 0.0,
    traffic_percentage INTEGER DEFAULT 100 CHECK (traffic_percentage >= 0 AND traffic_percentage <= 100),
    ab_test_group VARCHAR(50),
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

CREATE TABLE prompt_executions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    prompt_id UUID NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
    article_id UUID REFERENCES ingested_articles(id) ON DELETE SET NULL,
    incident_id UUID REFERENCES incidents(id) ON DELETE SET NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_ms INTEGER,
    success BOOLEAN NOT NULL DEFAULT TRUE,
    error_message TEXT,
    confidence_score DECIMAL(3,2),
    result_data JSONB,
    ab_variant VARCHAR(50),
    provider_name VARCHAR(50),   -- Migration 008
    model_name VARCHAR(100),     -- Migration 008
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_prompt_executions_prompt ON prompt_executions(prompt_id);
CREATE INDEX idx_prompt_executions_article ON prompt_executions(article_id);
CREATE INDEX idx_prompt_executions_created ON prompt_executions(created_at DESC);
CREATE INDEX idx_prompt_executions_success ON prompt_executions(prompt_id, success);
CREATE INDEX idx_prompt_executions_provider ON prompt_executions(provider_name) WHERE provider_name IS NOT NULL;

-- ============================================================================
-- CUSTOM FIELD DEFINITIONS (migration 002)
-- ============================================================================

CREATE TABLE field_definitions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_type_id UUID NOT NULL REFERENCES incident_types(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    field_type field_type NOT NULL,
    description TEXT,
    enum_values TEXT[],
    reference_table VARCHAR(100),
    default_value TEXT,
    required BOOLEAN DEFAULT FALSE,
    min_value DECIMAL,
    max_value DECIMAL,
    pattern VARCHAR(255),
    extraction_hint TEXT,
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
-- PIPELINE CONFIGURATION (migration 002)
-- ============================================================================

CREATE TABLE pipeline_stages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    handler_class VARCHAR(200) NOT NULL,
    default_order INTEGER NOT NULL,
    config_schema JSONB,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE incident_type_pipeline_config (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_type_id UUID NOT NULL REFERENCES incident_types(id) ON DELETE CASCADE,
    pipeline_stage_id UUID NOT NULL REFERENCES pipeline_stages(id) ON DELETE CASCADE,
    enabled BOOLEAN DEFAULT TRUE,
    execution_order INTEGER,
    stage_config JSONB DEFAULT '{}',
    prompt_id UUID REFERENCES prompts(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(incident_type_id, pipeline_stage_id)
);

CREATE INDEX idx_pipeline_config_type ON incident_type_pipeline_config(incident_type_id);
CREATE INDEX idx_pipeline_config_stage ON incident_type_pipeline_config(pipeline_stage_id);

-- ============================================================================
-- ENRICHMENT TRACKING (migration 003)
-- ============================================================================

CREATE TABLE enrichment_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID,  -- References background_jobs(id), defined below
    strategy VARCHAR(50) NOT NULL,
    params JSONB DEFAULT '{}',
    total_incidents INTEGER DEFAULT 0,
    incidents_enriched INTEGER DEFAULT 0,
    fields_filled INTEGER DEFAULT 0,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'running'
);

CREATE TABLE enrichment_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES enrichment_runs(id),
    incident_id UUID NOT NULL REFERENCES incidents(id),
    field_name VARCHAR(100) NOT NULL,
    old_value TEXT,
    new_value TEXT,
    source_type VARCHAR(30) NOT NULL,
    source_incident_id UUID REFERENCES incidents(id),
    source_article_id UUID REFERENCES ingested_articles(id),
    confidence DECIMAL(3,2),
    applied BOOLEAN DEFAULT FALSE,
    reverted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_enrichment_log_run ON enrichment_log(run_id);
CREATE INDEX idx_enrichment_log_incident ON enrichment_log(incident_id);
CREATE INDEX idx_enrichment_runs_status ON enrichment_runs(status);

-- ============================================================================
-- BACKGROUND JOBS & TASK METRICS
-- ============================================================================

CREATE TABLE background_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    progress INTEGER DEFAULT 0,
    total INTEGER DEFAULT 0,
    message TEXT,
    params JSONB,
    error TEXT,
    -- Celery integration (migration 023)
    celery_task_id VARCHAR(255),
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    queue VARCHAR(50) DEFAULT 'default',
    priority INTEGER DEFAULT 0,
    scheduled_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_background_jobs_status ON background_jobs(status);
CREATE INDEX idx_background_jobs_created_at ON background_jobs(created_at DESC);
CREATE INDEX idx_bg_jobs_celery_task ON background_jobs(celery_task_id);
CREATE INDEX idx_bg_jobs_scheduled ON background_jobs(scheduled_at) WHERE scheduled_at IS NOT NULL;

-- Wire up deferred FK for enrichment_runs
ALTER TABLE enrichment_runs
    ADD CONSTRAINT enrichment_runs_job_id_fkey
    FOREIGN KEY (job_id) REFERENCES background_jobs(id);

CREATE TABLE task_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID REFERENCES background_jobs(id) ON DELETE SET NULL,
    task_name VARCHAR(100) NOT NULL,
    queue VARCHAR(50) NOT NULL DEFAULT 'default',
    status VARCHAR(20) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    duration_ms INTEGER NOT NULL,
    error TEXT,
    items_processed INTEGER DEFAULT 0,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_task_metrics_task_name ON task_metrics(task_name);
CREATE INDEX idx_task_metrics_created_at ON task_metrics(created_at DESC);
CREATE INDEX idx_task_metrics_status ON task_metrics(status);

CREATE TABLE task_metrics_aggregate (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    task_name VARCHAR(100) NOT NULL,
    total_runs INTEGER DEFAULT 0,
    successful INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    avg_duration_ms INTEGER,
    p95_duration_ms INTEGER,
    total_items_processed INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(period_start, task_name)
);

CREATE INDEX idx_task_metrics_agg_period ON task_metrics_aggregate(period_start DESC);
CREATE INDEX idx_task_metrics_agg_task ON task_metrics_aggregate(task_name);

-- ============================================================================
-- CASES & LEGAL TRACKING (migrations 013, 014)
-- ============================================================================

CREATE TABLE cases (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_number VARCHAR(100),
    case_type VARCHAR(50) NOT NULL,
    jurisdiction VARCHAR(200),
    court_name VARCHAR(200),
    filed_date DATE,
    closed_date DATE,
    status VARCHAR(30) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'closed', 'appealed', 'dismissed', 'sealed')),
    domain_id UUID REFERENCES event_domains(id),
    category_id UUID REFERENCES event_categories(id),
    custom_fields JSONB DEFAULT '{}',
    data_classification VARCHAR(30) DEFAULT 'public'
        CHECK (data_classification IN ('public', 'restricted', 'sealed', 'expunged')),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(case_number, jurisdiction)
);

CREATE INDEX idx_cases_case_number ON cases(case_number);
CREATE INDEX idx_cases_case_type ON cases(case_type);
CREATE INDEX idx_cases_status ON cases(status);
CREATE INDEX idx_cases_filed_date ON cases(filed_date);
CREATE INDEX idx_cases_jurisdiction ON cases(jurisdiction);
CREATE INDEX idx_cases_domain ON cases(domain_id);
CREATE INDEX idx_cases_category ON cases(category_id);

-- Wire up deferred FK for event_relationships.case_id (migration 034)
ALTER TABLE event_relationships
    ADD CONSTRAINT fk_event_relationships_case_id
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE SET NULL;

CREATE TABLE charges (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    charge_number INTEGER NOT NULL,
    charge_code VARCHAR(50),
    charge_description TEXT NOT NULL,
    charge_level VARCHAR(20) NOT NULL DEFAULT 'misdemeanor'
        CHECK (charge_level IN ('felony', 'misdemeanor', 'infraction', 'violation')),
    charge_class VARCHAR(10),
    severity INTEGER,
    status VARCHAR(30) NOT NULL DEFAULT 'filed'
        CHECK (status IN ('filed', 'amended', 'reduced', 'dismissed', 'convicted', 'acquitted')),
    is_violent_crime BOOLEAN DEFAULT FALSE,
    is_original BOOLEAN DEFAULT TRUE,
    jail_days INTEGER,
    probation_days INTEGER,
    fine_amount DECIMAL(12,2),
    restitution_amount DECIMAL(12,2),
    community_service_hours INTEGER,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(case_id, charge_number)
);

CREATE INDEX idx_charges_case ON charges(case_id);
CREATE INDEX idx_charges_status ON charges(status);
CREATE INDEX idx_charges_code ON charges(charge_code);
CREATE INDEX idx_charges_violent ON charges(is_violent_crime) WHERE is_violent_crime = TRUE;

CREATE TABLE charge_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    charge_id UUID NOT NULL REFERENCES charges(id) ON DELETE CASCADE,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    event_type VARCHAR(30) NOT NULL
        CHECK (event_type IN ('filed', 'amended', 'reduced', 'dismissed', 'convicted', 'acquitted', 'reinstated', 'sealed')),
    actor_type VARCHAR(30)
        CHECK (actor_type IN ('prosecutor', 'judge', 'defense_attorney', 'system', 'clerk')),
    actor_name VARCHAR(200),
    actor_id UUID REFERENCES actors(id),
    previous_charge_code VARCHAR(50),
    new_charge_code VARCHAR(50),
    previous_level VARCHAR(20),
    new_level VARCHAR(20),
    reason TEXT,
    event_date DATE DEFAULT CURRENT_DATE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_charge_history_charge ON charge_history(charge_id);
CREATE INDEX idx_charge_history_case ON charge_history(case_id);
CREATE INDEX idx_charge_history_type ON charge_history(event_type);
CREATE INDEX idx_charge_history_date ON charge_history(event_date);
CREATE INDEX idx_charge_history_actor ON charge_history(actor_id);

CREATE TABLE case_jurisdictions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    jurisdiction VARCHAR(200) NOT NULL,
    jurisdiction_role VARCHAR(30) NOT NULL DEFAULT 'filing'
        CHECK (jurisdiction_role IN ('filing', 'transferred', 'appellate', 'concurrent')),
    court_name VARCHAR(200),
    transfer_date DATE,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_case_jurisdictions_case ON case_jurisdictions(case_id);
CREATE INDEX idx_case_jurisdictions_jurisdiction ON case_jurisdictions(jurisdiction);

CREATE TABLE external_system_ids (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type VARCHAR(30) NOT NULL
        CHECK (entity_type IN ('case', 'incident', 'actor', 'charge')),
    entity_id UUID NOT NULL,
    system_name VARCHAR(100) NOT NULL,
    external_id VARCHAR(500) NOT NULL,
    external_url TEXT,
    mapping_status VARCHAR(30) NOT NULL DEFAULT 'confirmed'
        CHECK (mapping_status IN ('confirmed', 'tentative', 'disputed', 'superseded')),
    match_confidence DECIMAL(3,2),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(entity_type, entity_id, system_name)
);

CREATE INDEX idx_external_ids_entity ON external_system_ids(entity_type, entity_id);
CREATE INDEX idx_external_ids_system ON external_system_ids(system_name, external_id);
CREATE INDEX idx_external_ids_status ON external_system_ids(mapping_status);

CREATE TABLE case_incidents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    incident_role VARCHAR(30) NOT NULL DEFAULT 'related'
        CHECK (incident_role IN ('arrest', 'arraignment', 'hearing', 'trial', 'sentencing', 'appeal', 'related', 'evidence')),
    sequence_order INTEGER,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(case_id, incident_id, incident_role)
);

CREATE INDEX idx_case_incidents_case ON case_incidents(case_id);
CREATE INDEX idx_case_incidents_incident ON case_incidents(incident_id);
CREATE INDEX idx_case_incidents_role ON case_incidents(incident_role);

CREATE TABLE case_actors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    actor_id UUID NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
    role_type_id UUID REFERENCES actor_role_types(id),
    role_description TEXT,
    is_primary BOOLEAN DEFAULT FALSE,
    notes TEXT,
    start_date DATE,
    end_date DATE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(case_id, actor_id, role_type_id)
);

CREATE INDEX idx_case_actors_case ON case_actors(case_id);
CREATE INDEX idx_case_actors_actor ON case_actors(actor_id);
CREATE INDEX idx_case_actors_role ON case_actors(role_type_id);

-- Prosecutorial tracking (migration 014)
CREATE TABLE prosecutorial_actions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    prosecutor_id UUID REFERENCES actors(id),
    prosecutor_name VARCHAR(200),
    action_type VARCHAR(40) NOT NULL
        CHECK (action_type IN (
            'filed_charges', 'amended_charges', 'plea_offer', 'dismissed',
            'trial_decision', 'sentencing_recommendation',
            'bail_recommendation', 'diversion_offer', 'nolle_prosequi'
        )),
    action_date DATE NOT NULL DEFAULT CURRENT_DATE,
    description TEXT,
    reasoning TEXT,
    legal_basis TEXT,
    justification TEXT,
    supervisor_reviewed BOOLEAN DEFAULT FALSE,
    supervisor_name VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_pros_actions_case ON prosecutorial_actions(case_id);
CREATE INDEX idx_pros_actions_prosecutor ON prosecutorial_actions(prosecutor_id);
CREATE INDEX idx_pros_actions_type ON prosecutorial_actions(action_type);
CREATE INDEX idx_pros_actions_date ON prosecutorial_actions(action_date);

CREATE TABLE prosecutor_action_charges (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    action_id UUID NOT NULL REFERENCES prosecutorial_actions(id) ON DELETE CASCADE,
    charge_id UUID NOT NULL REFERENCES charges(id) ON DELETE CASCADE,
    charge_role VARCHAR(30) NOT NULL DEFAULT 'affected'
        CHECK (charge_role IN ('original', 'amended_to', 'dismissed', 'affected', 'added')),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(action_id, charge_id, charge_role)
);

CREATE INDEX idx_action_charges_action ON prosecutor_action_charges(action_id);
CREATE INDEX idx_action_charges_charge ON prosecutor_action_charges(charge_id);

CREATE TABLE bail_decisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    judge_id UUID REFERENCES actors(id),
    judge_name VARCHAR(200),
    decision_type VARCHAR(30) NOT NULL
        CHECK (decision_type IN ('initial_bail', 'bail_modification', 'bail_revocation', 'release_on_recognizance')),
    decision_date DATE NOT NULL DEFAULT CURRENT_DATE,
    bail_amount DECIMAL(12,2),
    bail_type VARCHAR(30)
        CHECK (bail_type IN ('cash', 'surety', 'property', 'unsecured', 'personal_recognizance', 'no_bail')),
    conditions TEXT,
    flight_risk_assessed VARCHAR(10) CHECK (flight_risk_assessed IN ('low', 'medium', 'high')),
    danger_to_public_assessed VARCHAR(10) CHECK (danger_to_public_assessed IN ('low', 'medium', 'high')),
    prior_record_considered BOOLEAN DEFAULT FALSE,
    community_ties_considered BOOLEAN DEFAULT FALSE,
    risk_factors_notes TEXT,
    prosecution_position TEXT,
    prosecution_requested_amount DECIMAL(12,2),
    defense_position TEXT,
    defense_requested_amount DECIMAL(12,2),
    decision_rationale TEXT,
    bail_status VARCHAR(20) DEFAULT 'set'
        CHECK (bail_status IN ('set', 'posted', 'revoked', 'forfeited', 'exonerated')),
    defendant_released BOOLEAN,
    release_date DATE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_bail_case ON bail_decisions(case_id);
CREATE INDEX idx_bail_judge ON bail_decisions(judge_id);
CREATE INDEX idx_bail_date ON bail_decisions(decision_date);
CREATE INDEX idx_bail_type ON bail_decisions(decision_type);

CREATE TABLE dispositions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    charge_id UUID REFERENCES charges(id) ON DELETE SET NULL,
    judge_id UUID REFERENCES actors(id),
    judge_name VARCHAR(200),
    disposition_type VARCHAR(30) NOT NULL
        CHECK (disposition_type IN ('convicted', 'acquitted', 'dismissed', 'plea', 'mistrial', 'nolle_prosequi', 'deferred_adjudication', 'diverted')),
    disposition_date DATE NOT NULL DEFAULT CURRENT_DATE,
    total_jail_days INTEGER,
    jail_days_suspended INTEGER,
    jail_days_served INTEGER,
    incarceration_start_date DATE,
    projected_release_date DATE,
    actual_release_date DATE,
    incarceration_facility VARCHAR(200),
    probation_days INTEGER,
    probation_start_date DATE,
    probation_end_date DATE,
    probation_conditions JSONB,
    fine_amount DECIMAL(12,2),
    fine_amount_paid DECIMAL(12,2),
    restitution_amount DECIMAL(12,2),
    restitution_amount_paid DECIMAL(12,2),
    court_costs DECIMAL(12,2),
    community_service_hours INTEGER,
    community_service_hours_completed INTEGER,
    ordered_programs JSONB,
    substance_abuse_treatment_ordered BOOLEAN DEFAULT FALSE,
    mental_health_treatment_ordered BOOLEAN DEFAULT FALSE,
    compliance_status VARCHAR(20) DEFAULT 'pending'
        CHECK (compliance_status IN ('pending', 'compliant', 'non_compliant', 'completed', 'revoked')),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_dispositions_case ON dispositions(case_id);
CREATE INDEX idx_dispositions_charge ON dispositions(charge_id);
CREATE INDEX idx_dispositions_type ON dispositions(disposition_type);
CREATE INDEX idx_dispositions_date ON dispositions(disposition_date);
CREATE INDEX idx_dispositions_judge ON dispositions(judge_id);
CREATE INDEX idx_dispositions_compliance ON dispositions(compliance_status);

-- ============================================================================
-- EXTRACTION SYSTEM (migrations 015, 017)
-- ============================================================================

CREATE TABLE extraction_schemas (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain_id UUID REFERENCES event_domains(id),
    category_id UUID REFERENCES event_categories(id),
    schema_version INTEGER NOT NULL DEFAULT 1,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    system_prompt TEXT NOT NULL,
    user_prompt_template TEXT NOT NULL,
    model_name VARCHAR(50) DEFAULT 'claude-sonnet-4-5',
    temperature DECIMAL(3,2) DEFAULT 0.7,
    max_tokens INTEGER DEFAULT 4000,
    required_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    optional_fields JSONB DEFAULT '[]'::jsonb,
    field_definitions JSONB NOT NULL DEFAULT '{}'::jsonb,
    validation_rules JSONB DEFAULT '{}'::jsonb,
    confidence_thresholds JSONB DEFAULT '{}'::jsonb,
    test_dataset_id UUID,  -- FK added below after prompt_test_datasets
    quality_metrics JSONB DEFAULT '{}'::jsonb,
    min_quality_threshold DECIMAL(3,2) DEFAULT 0.80,
    git_commit_sha VARCHAR(40),
    previous_version_id UUID REFERENCES extraction_schemas(id),
    rollback_reason TEXT,
    -- Two-stage pipeline (migration 017)
    schema_type VARCHAR(20) DEFAULT 'legacy'
        CHECK (schema_type IN ('stage1', 'stage2', 'legacy')),
    input_format VARCHAR(20) DEFAULT 'article_text'
        CHECK (input_format IN ('article_text', 'stage1_output', 'both')),
    is_active BOOLEAN DEFAULT TRUE,
    is_production BOOLEAN DEFAULT FALSE,
    deployed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CHECK (schema_version > 0),
    CHECK (min_quality_threshold BETWEEN 0 AND 1)
);

CREATE UNIQUE INDEX idx_extraction_schemas_production
ON extraction_schemas(domain_id, category_id)
WHERE is_production = TRUE AND is_active = TRUE;

CREATE INDEX idx_extraction_schemas_domain ON extraction_schemas(domain_id);
CREATE INDEX idx_extraction_schemas_category ON extraction_schemas(category_id);
CREATE INDEX idx_extraction_schemas_active ON extraction_schemas(is_active) WHERE is_active = TRUE;

-- Article extractions — Stage 1 IR (migration 017)
CREATE TABLE article_extractions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    article_id UUID NOT NULL REFERENCES ingested_articles(id) ON DELETE CASCADE,
    extraction_data JSONB NOT NULL,
    classification_hints JSONB DEFAULT '[]',
    entity_count INTEGER,
    event_count INTEGER,
    overall_confidence DECIMAL(3,2),
    extraction_notes TEXT,
    stage1_schema_version INTEGER NOT NULL DEFAULT 1,
    stage1_prompt_hash VARCHAR(64),
    provider VARCHAR(50),
    model VARCHAR(100),
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_ms INTEGER,
    status VARCHAR(20) DEFAULT 'completed' CHECK (status IN ('pending','completed','failed','stale')),
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_article_extractions_article ON article_extractions(article_id);
CREATE INDEX idx_article_extractions_status ON article_extractions(status);
CREATE INDEX idx_article_extractions_classification ON article_extractions USING gin(classification_hints);

-- Wire up deferred FK: ingested_articles.latest_extraction_id -> article_extractions(id)
ALTER TABLE ingested_articles
    ADD CONSTRAINT ingested_articles_latest_extraction_id_fkey
    FOREIGN KEY (latest_extraction_id) REFERENCES article_extractions(id) ON DELETE SET NULL;

-- Schema extraction results — Stage 2 per-schema output (migration 017)
CREATE TABLE schema_extraction_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    article_extraction_id UUID NOT NULL REFERENCES article_extractions(id) ON DELETE CASCADE,
    schema_id UUID NOT NULL REFERENCES extraction_schemas(id),
    article_id UUID NOT NULL REFERENCES ingested_articles(id),
    extracted_data JSONB NOT NULL,
    confidence DECIMAL(3,2),
    validation_errors JSONB DEFAULT '[]',
    provider VARCHAR(50),
    model VARCHAR(100),
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_ms INTEGER,
    used_original_text BOOLEAN DEFAULT FALSE,
    stage1_version INTEGER,
    status VARCHAR(20) DEFAULT 'completed' CHECK (status IN ('pending','completed','failed','superseded')),
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(article_extraction_id, schema_id)
);

CREATE INDEX idx_schema_results_extraction ON schema_extraction_results(article_extraction_id);
CREATE INDEX idx_schema_results_schema ON schema_extraction_results(schema_id);
CREATE INDEX idx_schema_results_article ON schema_extraction_results(article_id);

-- ============================================================================
-- PROMPT TESTING (migrations 015, 018, 019, 020, 021, 025)
-- ============================================================================

CREATE TABLE prompt_test_datasets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(200) NOT NULL,
    description TEXT,
    domain_id UUID REFERENCES event_domains(id),
    category_id UUID REFERENCES event_categories(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Wire up deferred FK
ALTER TABLE extraction_schemas
    ADD CONSTRAINT fk_extraction_schemas_test_dataset
    FOREIGN KEY (test_dataset_id) REFERENCES prompt_test_datasets(id);

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

CREATE TABLE prompt_test_comparisons (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    schema_id UUID REFERENCES extraction_schemas(id),  -- Nullable for pipeline comparisons (021)
    dataset_id UUID REFERENCES prompt_test_datasets(id),  -- Nullable for calibration mode (020)
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
    -- Calibration mode (migration 020)
    mode VARCHAR(20) NOT NULL DEFAULT 'dataset'
        CHECK (mode IN ('dataset', 'calibration')),
    output_dataset_id UUID REFERENCES prompt_test_datasets(id),
    article_count INTEGER,
    article_filters JSONB DEFAULT '{}'::jsonb,
    reviewed_count INTEGER DEFAULT 0,
    total_articles INTEGER DEFAULT 0,
    -- Pipeline comparisons (migration 021)
    comparison_type VARCHAR(20) DEFAULT 'schema'
        CHECK (comparison_type IN ('schema', 'pipeline')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE INDEX idx_comparisons_status ON prompt_test_comparisons(status);
CREATE INDEX idx_comparisons_created ON prompt_test_comparisons(created_at DESC);

CREATE TABLE prompt_test_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    schema_id UUID NOT NULL REFERENCES extraction_schemas(id) ON DELETE CASCADE,
    dataset_id UUID NOT NULL REFERENCES prompt_test_datasets(id),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'running'
        CHECK (status IN ('running', 'passed', 'failed', 'error')),
    total_cases INTEGER,
    passed_cases INTEGER,
    failed_cases INTEGER,
    precision DECIMAL(5,4),
    recall DECIMAL(5,4),
    f1_score DECIMAL(5,4),
    total_input_tokens BIGINT,
    total_output_tokens BIGINT,
    estimated_cost DECIMAL(10,4),
    results JSONB DEFAULT '[]'::jsonb,
    provider_name VARCHAR(50),    -- Migration 018
    model_name VARCHAR(200),      -- Migration 018
    comparison_id UUID REFERENCES prompt_test_comparisons(id),  -- Migration 019
    iteration_number INTEGER,     -- Migration 019
    config_label VARCHAR(1) CHECK (config_label IN ('A','B')),  -- Migration 019
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_test_runs_schema ON prompt_test_runs(schema_id);
CREATE INDEX idx_test_runs_status ON prompt_test_runs(status);
CREATE INDEX idx_test_runs_provider ON prompt_test_runs(provider_name);
CREATE INDEX idx_test_runs_comparison ON prompt_test_runs(comparison_id);

-- Comparison articles for calibration (migrations 020, 021, 025)
CREATE TABLE comparison_articles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    comparison_id UUID NOT NULL REFERENCES prompt_test_comparisons(id) ON DELETE CASCADE,
    article_id UUID NOT NULL REFERENCES ingested_articles(id),
    article_title VARCHAR(500),
    article_content TEXT,
    article_source_url TEXT,
    article_published_date DATE,
    config_a_extraction JSONB,
    config_a_confidence DECIMAL(3, 2),
    config_a_duration_ms INTEGER,
    config_a_error TEXT,
    config_b_extraction JSONB,
    config_b_confidence DECIMAL(3, 2),
    config_b_duration_ms INTEGER,
    config_b_error TEXT,
    -- Pipeline comparison (migration 021)
    config_a_stage1 JSONB,
    config_b_stage1 JSONB,
    config_a_stage2_results JSONB DEFAULT '[]'::jsonb,
    config_b_stage2_results JSONB DEFAULT '[]'::jsonb,
    config_a_total_tokens INTEGER,
    config_b_total_tokens INTEGER,
    config_a_total_latency_ms INTEGER,
    config_b_total_latency_ms INTEGER,
    -- Merge info (migration 025)
    config_a_merge_info JSONB,
    config_b_merge_info JSONB,
    -- Human review
    review_status VARCHAR(20) DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'reviewed', 'skipped')),
    chosen_config VARCHAR(1) CHECK (chosen_config IN ('A', 'B')),
    golden_extraction JSONB,
    reviewer_notes TEXT,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(comparison_id, article_id)
);

CREATE INDEX idx_comparison_articles_comp ON comparison_articles(comparison_id);
CREATE INDEX idx_comparison_articles_review ON comparison_articles(review_status);

-- Extraction quality samples (migration 015)
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

-- Materialized view refresh configuration (migration 015)
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

-- ============================================================================
-- ETL & STAGING (migration 016)
-- ============================================================================

CREATE TABLE import_sagas (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    saga_type VARCHAR(100) NOT NULL,
    source_system VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'created'
        CHECK (status IN ('created', 'fetching', 'validating', 'deduplicating',
                          'importing', 'completed', 'failed', 'cancelled', 'rolled_back')),
    current_step INTEGER DEFAULT 0,
    total_steps INTEGER,
    steps_completed JSONB DEFAULT '[]'::jsonb,
    total_records INTEGER DEFAULT 0,
    valid_records INTEGER DEFAULT 0,
    invalid_records INTEGER DEFAULT 0,
    duplicate_records INTEGER DEFAULT 0,
    imported_records INTEGER DEFAULT 0,
    error_message TEXT,
    error_details JSONB,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    initiated_by UUID,
    custom_fields JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_import_sagas_status ON import_sagas(status);
CREATE INDEX idx_import_sagas_type ON import_sagas(saga_type);
CREATE INDEX idx_import_sagas_source ON import_sagas(source_system);

CREATE TABLE staging_incidents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    import_saga_id UUID REFERENCES import_sagas(id),
    source_system VARCHAR(100) NOT NULL,
    source_id VARCHAR(200),
    raw_data JSONB NOT NULL,
    parsed_date TIMESTAMPTZ,
    parsed_state VARCHAR(2),
    parsed_category VARCHAR(100),
    parsed_domain VARCHAR(100),
    validation_status VARCHAR(50) DEFAULT 'pending'
        CHECK (validation_status IN ('pending', 'valid', 'invalid', 'duplicate', 'imported')),
    validation_errors JSONB DEFAULT '[]'::jsonb,
    duplicate_of_incident_id UUID,
    match_confidence DECIMAL(5,4),
    comparison_status VARCHAR(50) DEFAULT 'new'
        CHECK (comparison_status IN ('new', 'matched', 'updated', 'conflict', 'orphaned')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    imported_incident_id UUID
);

CREATE INDEX idx_staging_incidents_status ON staging_incidents(validation_status);
CREATE INDEX idx_staging_incidents_saga ON staging_incidents(import_saga_id);
CREATE INDEX idx_staging_incidents_source ON staging_incidents(source_system, source_id);

CREATE TABLE staging_actors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    import_saga_id UUID REFERENCES import_sagas(id),
    source_system VARCHAR(100) NOT NULL,
    source_id VARCHAR(200),
    raw_data JSONB NOT NULL,
    parsed_name VARCHAR(200),
    parsed_type VARCHAR(50),
    validation_status VARCHAR(50) DEFAULT 'pending'
        CHECK (validation_status IN ('pending', 'valid', 'invalid', 'duplicate', 'imported')),
    validation_errors JSONB DEFAULT '[]'::jsonb,
    duplicate_of_actor_id UUID,
    match_confidence DECIMAL(5,4),
    comparison_status VARCHAR(50) DEFAULT 'new'
        CHECK (comparison_status IN ('new', 'matched', 'updated', 'conflict', 'orphaned')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    imported_actor_id UUID
);

CREATE INDEX idx_staging_actors_status ON staging_actors(validation_status);
CREATE INDEX idx_staging_actors_saga ON staging_actors(import_saga_id);

CREATE TABLE migration_rollback_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    migration_phase VARCHAR(10) NOT NULL,
    rollback_type VARCHAR(50) NOT NULL,
    reason TEXT NOT NULL,
    executed_by VARCHAR(100),
    executed_at TIMESTAMPTZ DEFAULT NOW(),
    rollback_sql TEXT,
    success BOOLEAN,
    error_message TEXT
);

-- ============================================================================
-- FUNCTIONS
-- ============================================================================

-- Update timestamp trigger
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Case timestamp trigger (migration 013)
CREATE OR REPLACE FUNCTION update_case_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Calculate severity score for an incident
CREATE OR REPLACE FUNCTION calculate_severity_score(p_incident_id UUID)
RETURNS DECIMAL AS $$
DECLARE
    v_base_score DECIMAL;
    v_tier_multiplier DECIMAL;
    v_scale_multiplier DECIMAL;
    v_outcome_multiplier DECIMAL;
    v_outcome_slug TEXT;
BEGIN
    SELECT
        it.severity_weight,
        CASE i.source_tier
            WHEN '1' THEN 1.0
            WHEN '2' THEN 0.9
            WHEN '3' THEN 0.7
            WHEN '4' THEN 0.5
        END,
        CASE i.incident_scale
            WHEN 'single' THEN 1.0
            WHEN 'small' THEN 1.2
            WHEN 'medium' THEN 1.5
            WHEN 'large' THEN 2.0
            WHEN 'mass' THEN 3.0
        END,
        ot.slug
    INTO v_base_score, v_tier_multiplier, v_scale_multiplier, v_outcome_slug
    FROM incidents i
    JOIN incident_types it ON i.incident_type_id = it.id
    LEFT JOIN outcome_types ot ON i.outcome_type_id = ot.id
    WHERE i.id = p_incident_id;

    v_outcome_multiplier := CASE v_outcome_slug
        WHEN 'death' THEN 2.0
        WHEN 'serious_injury' THEN 1.5
        WHEN 'minor_injury' THEN 1.0
        WHEN 'no_injury' THEN 0.5
        ELSE 1.0
    END;

    RETURN ROUND(v_base_score * v_tier_multiplier * v_scale_multiplier * v_outcome_multiplier, 2);
END;
$$ LANGUAGE plpgsql;

-- Check if incident is non-immigrant (for filtering)
CREATE OR REPLACE FUNCTION is_non_immigrant(p_incident_id UUID)
RETURNS BOOLEAN AS $$
DECLARE
    v_incident incidents%ROWTYPE;
    v_victim_slug TEXT;
BEGIN
    SELECT * INTO v_incident FROM incidents WHERE id = p_incident_id;

    SELECT vt.slug INTO v_victim_slug
    FROM victim_types vt WHERE vt.id = v_incident.victim_type_id;

    RETURN (
        v_victim_slug IN ('protester', 'journalist', 'bystander', 'us_citizen_collateral', 'officer')
        OR v_incident.us_citizen = TRUE
        OR v_incident.protest_related = TRUE
    );
END;
$$ LANGUAGE plpgsql;

-- Get active prompt for a type
CREATE OR REPLACE FUNCTION get_active_prompt(
    p_prompt_type VARCHAR,
    p_incident_type_id UUID DEFAULT NULL,
    p_slug VARCHAR DEFAULT NULL
)
RETURNS UUID AS $$
DECLARE
    v_prompt_id UUID;
BEGIN
    IF p_incident_type_id IS NOT NULL THEN
        SELECT id INTO v_prompt_id
        FROM prompts
        WHERE prompt_type = p_prompt_type
          AND incident_type_id = p_incident_type_id
          AND status = 'active'
          AND (p_slug IS NULL OR slug = p_slug)
        ORDER BY version DESC LIMIT 1;
        IF v_prompt_id IS NOT NULL THEN RETURN v_prompt_id; END IF;
    END IF;
    SELECT id INTO v_prompt_id
    FROM prompts
    WHERE prompt_type = p_prompt_type
      AND incident_type_id IS NULL
      AND status = 'active'
      AND (p_slug IS NULL OR slug = p_slug)
    ORDER BY version DESC LIMIT 1;
    RETURN v_prompt_id;
END;
$$ LANGUAGE plpgsql;

-- Cost estimation function
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
    CASE p_model
        WHEN 'claude-sonnet-4-20250514' THEN
            v_input_price_per_mtok := 3.00; v_output_price_per_mtok := 15.00;
        WHEN 'claude-opus-4-5-20251101' THEN
            v_input_price_per_mtok := 15.00; v_output_price_per_mtok := 75.00;
        WHEN 'claude-haiku-3-5-20241022' THEN
            v_input_price_per_mtok := 1.00; v_output_price_per_mtok := 5.00;
        ELSE
            v_input_price_per_mtok := 3.00; v_output_price_per_mtok := 15.00;
    END CASE;
    RETURN ROUND(
        (p_input_tokens::DECIMAL / 1000000.0 * v_input_price_per_mtok) +
        (p_output_tokens::DECIMAL / 1000000.0 * v_output_price_per_mtok), 4);
END;
$$ LANGUAGE plpgsql;

-- Get or create outcome type
CREATE OR REPLACE FUNCTION get_or_create_outcome_type(p_name VARCHAR, p_slug VARCHAR DEFAULT NULL)
RETURNS UUID AS $$
DECLARE v_outcome_id UUID; v_slug VARCHAR;
BEGIN
    v_slug := COALESCE(p_slug, LOWER(REGEXP_REPLACE(p_name, '[^a-zA-Z0-9]+', '_', 'g')));
    SELECT id INTO v_outcome_id FROM outcome_types WHERE slug = v_slug;
    IF v_outcome_id IS NULL THEN
        INSERT INTO outcome_types (name, slug, severity_weight) VALUES (p_name, v_slug, 1.0) RETURNING id INTO v_outcome_id;
    END IF;
    RETURN v_outcome_id;
END;
$$ LANGUAGE plpgsql;

-- Get or create victim type
CREATE OR REPLACE FUNCTION get_or_create_victim_type(p_name VARCHAR, p_slug VARCHAR DEFAULT NULL)
RETURNS UUID AS $$
DECLARE v_victim_id UUID; v_slug VARCHAR;
BEGIN
    v_slug := COALESCE(p_slug, LOWER(REGEXP_REPLACE(p_name, '[^a-zA-Z0-9]+', '_', 'g')));
    SELECT id INTO v_victim_id FROM victim_types WHERE slug = v_slug;
    IF v_victim_id IS NULL THEN
        INSERT INTO victim_types (name, slug) VALUES (p_name, v_slug) RETURNING id INTO v_victim_id;
    END IF;
    RETURN v_victim_id;
END;
$$ LANGUAGE plpgsql;

-- Domain deactivation check (migration 009)
CREATE OR REPLACE FUNCTION check_domain_deactivation()
RETURNS TRIGGER AS $$
DECLARE v_category_count INTEGER; v_incident_count INTEGER;
BEGIN
    IF NEW.is_active = FALSE AND OLD.is_active = TRUE THEN
        SELECT COUNT(*) INTO v_category_count FROM event_categories WHERE domain_id = NEW.id AND is_active = TRUE;
        IF v_category_count > 0 THEN
            RAISE EXCEPTION 'Cannot deactivate domain %: has % active categories.', NEW.name, v_category_count;
        END IF;
        SELECT COUNT(*) INTO v_incident_count FROM incidents WHERE domain_id = NEW.id;
        IF v_incident_count > 0 THEN NEW.archived_at = NOW(); END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Prevent domain deletion with incidents (migration 009)
CREATE OR REPLACE FUNCTION prevent_domain_deletion_with_incidents()
RETURNS TRIGGER AS $$
DECLARE v_incident_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_incident_count FROM incidents WHERE domain_id = OLD.id;
    IF v_incident_count > 0 THEN
        RAISE EXCEPTION 'Cannot delete domain %: has % incidents.', OLD.name, v_incident_count;
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

-- Custom field validation (migration 009, disabled by migration 028)
CREATE OR REPLACE FUNCTION validate_custom_fields()
RETURNS TRIGGER AS $$
DECLARE v_required_fields JSONB; v_field TEXT; v_missing_fields TEXT[];
BEGIN
    IF NEW.category_id IS NULL THEN RETURN NEW; END IF;
    SELECT required_fields INTO v_required_fields FROM event_categories WHERE id = NEW.category_id;
    IF v_required_fields IS NULL OR v_required_fields = '[]'::jsonb THEN RETURN NEW; END IF;
    v_missing_fields := ARRAY[]::TEXT[];
    FOR v_field IN SELECT jsonb_array_elements_text(v_required_fields) LOOP
        IF NOT (NEW.custom_fields ? v_field) OR NEW.custom_fields->>v_field IS NULL THEN
            v_missing_fields := array_append(v_missing_fields, v_field);
        END IF;
    END LOOP;
    IF array_length(v_missing_fields, 1) > 0 THEN
        RAISE EXCEPTION 'Missing required custom fields for category %: %', NEW.category_id, array_to_string(v_missing_fields, ', ');
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Cycle detection for event relationships (migration 011)
CREATE OR REPLACE FUNCTION check_relationship_cycle()
RETURNS TRIGGER AS $$
DECLARE v_max_depth INTEGER := 20; v_has_cycle BOOLEAN; v_is_directional BOOLEAN;
BEGIN
    SELECT is_directional INTO v_is_directional FROM relationship_types WHERE name = NEW.relationship_type;
    IF v_is_directional IS TRUE THEN
        WITH RECURSIVE chain AS (
            SELECT target_incident_id AS current_id, 1 AS depth
            FROM event_relationships
            WHERE source_incident_id = NEW.target_incident_id AND relationship_type = NEW.relationship_type
            UNION ALL
            SELECT er.target_incident_id, c.depth + 1
            FROM event_relationships er JOIN chain c ON er.source_incident_id = c.current_id
            WHERE c.depth < v_max_depth AND er.relationship_type = NEW.relationship_type
        )
        SELECT EXISTS(SELECT 1 FROM chain WHERE current_id = NEW.source_incident_id) INTO v_has_cycle;
        IF v_has_cycle THEN
            RAISE EXCEPTION 'Cycle detected for relationship type %', NEW.relationship_type;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Recidivism indicator function (migration 016)
-- WARNING: Heuristic indicator, NOT validated for judicial decision-making
CREATE FUNCTION calculate_recidivism_indicator(p_actor_id UUID)
RETURNS TABLE (indicator_score DECIMAL(5,4), is_preliminary BOOLEAN, model_version VARCHAR(20), disclaimer TEXT)
AS $$
DECLARE v_total INTEGER; v_avg NUMERIC; v_days_ago INTEGER; v_score DECIMAL(5,4);
BEGIN
    SELECT total_incidents, avg_days_between_incidents, EXTRACT(days FROM NOW() - most_recent_incident_date)::INTEGER
    INTO v_total, v_avg, v_days_ago FROM recidivism_analysis WHERE actor_id = p_actor_id;
    IF v_total IS NULL THEN
        RETURN QUERY SELECT 0.0000::DECIMAL(5,4), TRUE, 'heuristic-v1'::VARCHAR(20), 'No incident history found.'::TEXT;
        RETURN;
    END IF;
    v_score := LEAST(1.0, (v_total * 0.1) + (1.0 / NULLIF(v_avg, 0) * 100) +
        CASE WHEN v_days_ago < 90 THEN 0.3 WHEN v_days_ago < 180 THEN 0.2 WHEN v_days_ago < 365 THEN 0.1 ELSE 0.0 END);
    RETURN QUERY SELECT v_score, TRUE, 'heuristic-v1'::VARCHAR(20),
        'FOR INFORMATIONAL USE ONLY. Not validated for judicial decision-making.'::TEXT;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- TRIGGERS
-- ============================================================================

CREATE TRIGGER update_incidents_timestamp BEFORE UPDATE ON incidents FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_persons_timestamp BEFORE UPDATE ON persons FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_jurisdictions_timestamp BEFORE UPDATE ON jurisdictions FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_sources_timestamp BEFORE UPDATE ON sources FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_admin_users_timestamp BEFORE UPDATE ON admin_users FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_ingested_articles_timestamp BEFORE UPDATE ON ingested_articles FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_prompts_timestamp BEFORE UPDATE ON prompts FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_field_definitions_timestamp BEFORE UPDATE ON field_definitions FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_events_timestamp BEFORE UPDATE ON events FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_actors_timestamp BEFORE UPDATE ON actors FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_incident_types_timestamp BEFORE UPDATE ON incident_types FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_incident_type_pipeline_config_timestamp BEFORE UPDATE ON incident_type_pipeline_config FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_outcome_types_timestamp BEFORE UPDATE ON outcome_types FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_victim_types_timestamp BEFORE UPDATE ON victim_types FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_article_extractions_timestamp BEFORE UPDATE ON article_extractions FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_schema_extraction_results_timestamp BEFORE UPDATE ON schema_extraction_results FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_extraction_schemas_timestamp BEFORE UPDATE ON extraction_schemas FOR EACH ROW EXECUTE FUNCTION update_case_timestamp();

-- Custom field validation trigger (disabled by migration 028, replaced by Python-level validation)
CREATE TRIGGER trigger_validate_custom_fields BEFORE INSERT OR UPDATE ON incidents FOR EACH ROW EXECUTE FUNCTION validate_custom_fields();
ALTER TABLE incidents DISABLE TRIGGER trigger_validate_custom_fields;

-- Domain safety triggers (migration 009)
CREATE TRIGGER trigger_check_domain_deactivation BEFORE UPDATE ON event_domains FOR EACH ROW EXECUTE FUNCTION check_domain_deactivation();
CREATE TRIGGER trigger_prevent_domain_deletion BEFORE DELETE ON event_domains FOR EACH ROW EXECUTE FUNCTION prevent_domain_deletion_with_incidents();

-- Cycle detection trigger (migration 011)
CREATE TRIGGER trigger_check_relationship_cycle BEFORE INSERT ON event_relationships FOR EACH ROW EXECUTE FUNCTION check_relationship_cycle();

-- Case table timestamp triggers (migration 013)
CREATE TRIGGER trigger_case_updated BEFORE UPDATE ON cases FOR EACH ROW EXECUTE FUNCTION update_case_timestamp();
CREATE TRIGGER trigger_charge_updated BEFORE UPDATE ON charges FOR EACH ROW EXECUTE FUNCTION update_case_timestamp();

-- Prosecutorial tracking timestamp triggers (migration 014)
CREATE TRIGGER trigger_pros_action_updated BEFORE UPDATE ON prosecutorial_actions FOR EACH ROW EXECUTE FUNCTION update_case_timestamp();
CREATE TRIGGER trigger_bail_updated BEFORE UPDATE ON bail_decisions FOR EACH ROW EXECUTE FUNCTION update_case_timestamp();
CREATE TRIGGER trigger_disposition_updated BEFORE UPDATE ON dispositions FOR EACH ROW EXECUTE FUNCTION update_case_timestamp();

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Incident summary view (updated by migration 007 to use outcome_types/victim_types)
CREATE VIEW incidents_summary AS
SELECT
    i.id, i.legacy_id, i.category, i.date, i.state, i.city,
    it.name AS incident_type,
    vt.name AS victim_category,
    i.victim_name,
    ot.name AS outcome_category,
    i.source_tier, i.latitude, i.longitude, i.affected_count,
    i.us_citizen, i.protest_related,
    i.state_sanctuary_status, i.local_sanctuary_status,
    is_non_immigrant(i.id) AS is_non_immigrant,
    calculate_severity_score(i.id) AS severity_score,
    i.created_at, i.updated_at
FROM incidents i
JOIN incident_types it ON i.incident_type_id = it.id
LEFT JOIN outcome_types ot ON i.outcome_type_id = ot.id
LEFT JOIN victim_types vt ON i.victim_type_id = vt.id
WHERE i.curation_status = 'approved';

-- Curation queue view
CREATE VIEW curation_queue AS
SELECT
    ia.id, ia.title, ia.source_name, ia.source_url, ia.published_date,
    ia.relevance_score, ia.extraction_confidence, ia.extracted_data, ia.status, ia.fetched_at
FROM ingested_articles ia
WHERE ia.status IN ('pending', 'in_review')
ORDER BY ia.relevance_score DESC, ia.fetched_at DESC;

-- Active prompts view (migration 002)
CREATE OR REPLACE VIEW active_prompts AS
SELECT p.*, it.name as incident_type_name, it.category as incident_category
FROM prompts p LEFT JOIN incident_types it ON p.incident_type_id = it.id
WHERE p.status = 'active';

-- Event summary (migration 002)
CREATE OR REPLACE VIEW events_summary AS
SELECT e.*, COUNT(DISTINCT ie.incident_id) as incident_count,
    MIN(i.date) as first_incident_date, MAX(i.date) as last_incident_date
FROM events e
LEFT JOIN incident_events ie ON e.id = ie.event_id
LEFT JOIN incidents i ON ie.incident_id = i.id
GROUP BY e.id;

-- Actor summary (migration 002)
CREATE OR REPLACE VIEW actors_summary AS
SELECT a.*, COUNT(DISTINCT ia.incident_id) as incident_count,
    array_agg(DISTINCT ia.role) as roles_played
FROM actors a LEFT JOIN incident_actors ia ON a.id = ia.actor_id
WHERE NOT a.is_merged GROUP BY a.id;

-- Prompt performance (migration 006)
CREATE OR REPLACE VIEW prompt_performance AS
SELECT
    p.id, p.name, p.slug, p.version, p.prompt_type, p.status, p.ab_test_group,
    COUNT(pe.id) as total_executions,
    COUNT(pe.id) FILTER (WHERE pe.success) as successful_executions,
    COUNT(pe.id) FILTER (WHERE NOT pe.success) as failed_executions,
    ROUND(COUNT(pe.id) FILTER (WHERE pe.success)::DECIMAL / NULLIF(COUNT(pe.id), 0) * 100, 2) as success_rate_pct,
    AVG(pe.latency_ms) as avg_latency_ms,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY pe.latency_ms) as median_latency_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY pe.latency_ms) as p95_latency_ms,
    AVG(pe.input_tokens) as avg_input_tokens, AVG(pe.output_tokens) as avg_output_tokens,
    SUM(pe.input_tokens) as total_input_tokens, SUM(pe.output_tokens) as total_output_tokens,
    AVG(pe.confidence_score) as avg_confidence,
    MIN(pe.created_at) as first_execution, MAX(pe.created_at) as last_execution
FROM prompts p LEFT JOIN prompt_executions pe ON p.id = pe.prompt_id
GROUP BY p.id, p.name, p.slug, p.version, p.prompt_type, p.status, p.ab_test_group;

-- Token usage by day (migration 006)
CREATE OR REPLACE VIEW token_usage_by_day AS
SELECT DATE(pe.created_at) as date, p.slug, p.version, p.prompt_type,
    COUNT(pe.id) as executions,
    SUM(pe.input_tokens) as total_input_tokens, SUM(pe.output_tokens) as total_output_tokens,
    SUM(pe.input_tokens + pe.output_tokens) as total_tokens, AVG(pe.confidence_score) as avg_confidence
FROM prompt_executions pe JOIN prompts p ON pe.prompt_id = p.id
WHERE pe.created_at >= CURRENT_DATE - INTERVAL '90 days'
GROUP BY DATE(pe.created_at), p.slug, p.version, p.prompt_type ORDER BY date DESC, total_tokens DESC;

-- Token cost summary (migration 006)
CREATE OR REPLACE VIEW token_cost_summary AS
SELECT p.slug, p.version, p.model_name, COUNT(pe.id) as executions,
    SUM(pe.input_tokens) as total_input_tokens, SUM(pe.output_tokens) as total_output_tokens,
    estimate_cost_usd(SUM(pe.input_tokens), SUM(pe.output_tokens), p.model_name) as estimated_cost_usd
FROM prompt_executions pe JOIN prompts p ON pe.prompt_id = p.id
WHERE pe.created_at >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY p.slug, p.version, p.model_name ORDER BY estimated_cost_usd DESC;

-- Provider performance (migration 008)
CREATE OR REPLACE VIEW provider_performance AS
SELECT pe.provider_name, pe.model_name, p.prompt_type,
    COUNT(*) as total_executions, COUNT(*) FILTER (WHERE pe.success) as successful,
    ROUND(COUNT(*) FILTER (WHERE pe.success) * 100.0 / NULLIF(COUNT(*), 0), 2) as success_rate_pct,
    ROUND(AVG(pe.latency_ms)::numeric, 0) as avg_latency_ms,
    ROUND(AVG(pe.confidence_score)::numeric, 3) as avg_confidence,
    SUM(pe.input_tokens) as total_input_tokens, SUM(pe.output_tokens) as total_output_tokens,
    MIN(pe.created_at) as first_seen, MAX(pe.created_at) as last_seen
FROM prompt_executions pe JOIN prompts p ON pe.prompt_id = p.id
WHERE pe.provider_name IS NOT NULL AND pe.created_at >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY pe.provider_name, pe.model_name, p.prompt_type ORDER BY total_executions DESC;

-- Outcome/victim type stats (migration 007)
CREATE VIEW outcome_type_stats AS
SELECT ot.id, ot.name, ot.slug, ot.severity_weight,
    COUNT(i.id) as usage_count, COUNT(DISTINCT i.state) as states_count,
    MIN(i.date) as first_used, MAX(i.date) as last_used
FROM outcome_types ot LEFT JOIN incidents i ON i.outcome_type_id = ot.id
GROUP BY ot.id, ot.name, ot.slug, ot.severity_weight ORDER BY usage_count DESC;

CREATE VIEW victim_type_stats AS
SELECT vt.id, vt.name, vt.slug,
    COUNT(i.id) as usage_count, COUNT(DISTINCT i.state) as states_count,
    MIN(i.date) as first_used, MAX(i.date) as last_used
FROM victim_types vt LEFT JOIN incidents i ON i.victim_type_id = vt.id
GROUP BY vt.id, vt.name, vt.slug ORDER BY usage_count DESC;

-- Cross-domain actor appearances (migration 009)
CREATE OR REPLACE VIEW actor_domain_appearances AS
SELECT a.id as actor_id, a.canonical_name, ed.id as domain_id, ed.name as domain_name,
    COUNT(DISTINCT i.id) as incident_count,
    MIN(i.event_start_date) as first_appearance, MAX(i.event_start_date) as last_appearance
FROM actors a
JOIN incident_actors ia ON ia.actor_id = a.id
JOIN incidents i ON i.id = ia.incident_id
JOIN event_domains ed ON i.domain_id = ed.id
GROUP BY a.id, a.canonical_name, ed.id, ed.name;

-- Actor incident history (migration 016)
CREATE VIEW actor_incident_history AS
SELECT a.id as actor_id, a.canonical_name, i.id as incident_id,
    i.event_start_date as incident_date, ed.name as domain, ec.name as category,
    it.name as incident_type, ot.name as outcome, i.custom_fields,
    ROW_NUMBER() OVER (PARTITION BY a.id ORDER BY i.event_start_date) as incident_number,
    LAG(i.event_start_date) OVER (PARTITION BY a.id ORDER BY i.event_start_date) as previous_incident_date,
    EXTRACT(days FROM i.event_start_date - LAG(i.event_start_date) OVER (PARTITION BY a.id ORDER BY i.event_start_date))::INTEGER as days_since_last_incident,
    COUNT(*) OVER (PARTITION BY a.id) as total_incidents_for_actor
FROM actors a
JOIN incident_actors ia ON ia.actor_id = a.id
JOIN incidents i ON i.id = ia.incident_id
JOIN event_domains ed ON i.domain_id = ed.id
JOIN event_categories ec ON i.category_id = ec.id
JOIN incident_types it ON i.incident_type_id = it.id
LEFT JOIN outcome_types ot ON i.outcome_type_id = ot.id
WHERE ia.role_type_id IN (SELECT id FROM actor_role_types WHERE slug IN ('defendant', 'offender', 'arrestee'));

-- Defendant lifecycle timeline (migration 016)
CREATE VIEW defendant_lifecycle_timeline AS
WITH lifecycle_events AS (
    SELECT a.id as actor_id, a.canonical_name, i.id as incident_id, c.id as case_id, c.case_number,
        CASE
            WHEN ec.slug = 'arrest' THEN '01_arrest'
            WHEN ec.slug = 'booking' OR i.custom_fields->>'phase' = 'booking' THEN '02_booking'
            WHEN ci.incident_role = 'initial_appearance' THEN '03_initial_appearance'
            WHEN bd.id IS NOT NULL THEN '04_bail'
            WHEN pa.action_type = 'filed_charges' THEN '05_prosecution'
            WHEN ch.event_type IN ('amended', 'reduced') THEN '07_charge_evolution'
            WHEN pa.action_type = 'plea_offer' THEN '08_plea_negotiations'
            WHEN ec.slug = 'trial' OR ci.incident_role = 'hearing' THEN '09_pre_trial'
            WHEN ci.incident_role = 'trial' THEN '10_trial'
            WHEN d.id IS NOT NULL AND d.disposition_type IS NOT NULL THEN '11_disposition'
            WHEN d.total_jail_days IS NOT NULL OR d.fine_amount IS NOT NULL THEN '12_sentencing'
            ELSE '00_unknown'
        END as lifecycle_phase,
        COALESCE(i.event_start_date, pa.action_date::timestamptz, d.disposition_date::timestamptz, ch.event_date) as event_date
    FROM actors a
    JOIN incident_actors ia ON ia.actor_id = a.id
    JOIN incidents i ON i.id = ia.incident_id
    LEFT JOIN event_categories ec ON i.category_id = ec.id
    LEFT JOIN case_incidents ci ON ci.incident_id = i.id
    LEFT JOIN cases c ON ci.case_id = c.id
    LEFT JOIN prosecutorial_actions pa ON pa.case_id = c.id
    LEFT JOIN dispositions d ON d.case_id = c.id
    LEFT JOIN charge_history ch ON ch.case_id = c.id
    LEFT JOIN bail_decisions bd ON bd.case_id = c.id
    WHERE ia.role_type_id IN (SELECT id FROM actor_role_types WHERE slug IN ('defendant', 'offender', 'arrestee'))
)
SELECT actor_id, canonical_name, case_id, case_number, lifecycle_phase,
    MIN(event_date) as phase_start_date, MAX(event_date) as phase_end_date, COUNT(*) as events_in_phase
FROM lifecycle_events WHERE lifecycle_phase != '00_unknown'
GROUP BY actor_id, canonical_name, case_id, case_number, lifecycle_phase
ORDER BY actor_id, case_id, lifecycle_phase;

-- ============================================================================
-- MATERIALIZED VIEWS
-- ============================================================================

-- Prosecutor statistics (migration 014)
CREATE MATERIALIZED VIEW prosecutor_stats AS
SELECT
    pa.prosecutor_id,
    COALESCE(a.canonical_name, pa.prosecutor_name, 'Unknown') AS prosecutor_name,
    COUNT(DISTINCT pa.case_id) AS total_cases,
    COUNT(DISTINCT d_conv.case_id) AS convictions,
    COUNT(DISTINCT d_acq.case_id) AS acquittals,
    COUNT(DISTINCT d_dis.case_id) AS dismissals,
    COUNT(DISTINCT d_plea.case_id) AS plea_bargains,
    CASE WHEN COUNT(DISTINCT pa.case_id) > 0
        THEN ROUND(COUNT(DISTINCT d_conv.case_id)::DECIMAL / COUNT(DISTINCT pa.case_id), 3) ELSE 0
    END AS conviction_rate,
    COUNT(DISTINCT CASE WHEN pa.action_type = 'amended_charges' THEN pa.id END) AS charges_amended,
    COUNT(DISTINCT CASE WHEN pa.action_type = 'dismissed' THEN pa.id END) AS charges_dismissed_count,
    AVG(CASE WHEN pa.action_type = 'bail_recommendation' THEN bd.prosecution_requested_amount END) AS avg_bail_requested,
    AVG(d_sent.total_jail_days) AS avg_sentence_days,
    ROUND((COUNT(DISTINCT pa.case_id) FILTER (WHERE pa.reasoning IS NOT NULL))::DECIMAL / GREATEST(COUNT(DISTINCT pa.case_id), 1) * 100, 1) AS data_completeness_pct,
    NOW() AS refreshed_at
FROM prosecutorial_actions pa
LEFT JOIN actors a ON pa.prosecutor_id = a.id
LEFT JOIN dispositions d_conv ON d_conv.case_id = pa.case_id AND d_conv.disposition_type = 'convicted'
LEFT JOIN dispositions d_acq ON d_acq.case_id = pa.case_id AND d_acq.disposition_type = 'acquitted'
LEFT JOIN dispositions d_dis ON d_dis.case_id = pa.case_id AND d_dis.disposition_type = 'dismissed'
LEFT JOIN dispositions d_plea ON d_plea.case_id = pa.case_id AND d_plea.disposition_type = 'plea'
LEFT JOIN dispositions d_sent ON d_sent.case_id = pa.case_id AND d_sent.disposition_type IN ('convicted', 'plea')
LEFT JOIN bail_decisions bd ON bd.case_id = pa.case_id
GROUP BY pa.prosecutor_id, COALESCE(a.canonical_name, pa.prosecutor_name, 'Unknown');

CREATE UNIQUE INDEX idx_prosecutor_stats_id ON prosecutor_stats(prosecutor_id);

-- Recidivism analysis (migration 016)
CREATE MATERIALIZED VIEW recidivism_analysis AS
SELECT actor_id, canonical_name, COUNT(*) as total_incidents,
    MIN(incident_date) as first_incident_date, MAX(incident_date) as most_recent_incident_date,
    EXTRACT(days FROM MAX(incident_date) - MIN(incident_date))::INTEGER as total_days_span,
    AVG(days_since_last_incident) as avg_days_between_incidents,
    STDDEV(days_since_last_incident) as stddev_days_between,
    COUNT(*) FILTER (WHERE incident_number > 1) as recidivist_incidents,
    ARRAY_AGG(incident_type ORDER BY incident_date) as incident_progression,
    ARRAY_AGG(outcome ORDER BY incident_date) as outcome_progression
FROM actor_incident_history WHERE total_incidents_for_actor > 1
GROUP BY actor_id, canonical_name ORDER BY total_incidents DESC;

CREATE UNIQUE INDEX idx_recidivism_actor ON recidivism_analysis(actor_id);

-- ============================================================================
-- GRANTS
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sentinel') THEN
        CREATE ROLE sentinel WITH LOGIN PASSWORD 'changeme';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO sentinel;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sentinel;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sentinel;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO sentinel;

-- ============================================================================
-- TABLE COMMENTS
-- ============================================================================

COMMENT ON TABLE prompts IS 'LLM prompt configurations with versioning and A/B testing';
COMMENT ON TABLE prompt_executions IS 'Tracks every LLM prompt execution for analytics and cost monitoring';
COMMENT ON TABLE outcome_types IS 'Extensible outcome categories - new types can be added dynamically';
COMMENT ON TABLE victim_types IS 'Extensible victim categories - new types can be added dynamically';
COMMENT ON TABLE event_domains IS 'Top-level event domains (Immigration, Criminal Justice, Civil Rights, etc.)';
COMMENT ON TABLE event_categories IS 'Hierarchical event categories within domains';
COMMENT ON TABLE actor_role_types IS 'Configurable role types for actors in incidents, replacing fixed enum';
COMMENT ON TABLE relationship_types IS 'Definitions for event relationship semantics (directional, inverse pairs)';
COMMENT ON TABLE event_relationships IS 'Links between related incidents with type and confidence';
COMMENT ON TABLE cases IS 'Legal case records with jurisdiction and status tracking';
COMMENT ON TABLE charges IS 'Individual charges within a case with lifecycle tracking';
COMMENT ON TABLE charge_history IS 'Audit trail for charge modifications';
COMMENT ON TABLE case_jurisdictions IS 'Multi-jurisdiction support for transferred/concurrent cases';
COMMENT ON TABLE external_system_ids IS 'Cross-system ID mapping for deduplication across external systems';
COMMENT ON TABLE case_incidents IS 'Links incidents to legal cases with role semantics';
COMMENT ON TABLE case_actors IS 'Links actors to legal cases with role assignments';
COMMENT ON TABLE prosecutorial_actions IS 'Tracks prosecutor decisions throughout case lifecycle';
COMMENT ON TABLE prosecutor_action_charges IS 'Links prosecutorial actions to affected charges';
COMMENT ON TABLE bail_decisions IS 'Bail hearing decisions with risk assessment context';
COMMENT ON TABLE dispositions IS 'Case outcomes with granular sentencing, probation, and compliance tracking';
COMMENT ON MATERIALIZED VIEW prosecutor_stats IS 'Aggregated prosecutor performance metrics (refresh periodically)';
COMMENT ON FUNCTION get_or_create_outcome_type IS 'Safely get or create outcome type, auto-generating slug';
COMMENT ON FUNCTION get_or_create_victim_type IS 'Safely get or create victim type, auto-generating slug';
COMMENT ON VIEW prompt_performance IS 'Aggregated performance metrics per prompt version';
COMMENT ON VIEW token_usage_by_day IS 'Daily token usage and costs by prompt type';
COMMENT ON VIEW token_cost_summary IS 'Cost estimates by prompt (last 30 days)';
COMMENT ON VIEW provider_performance IS 'Performance comparison across LLM providers (last 30 days)';
COMMENT ON VIEW actor_domain_appearances IS 'Tracks actor appearances across event domains';
