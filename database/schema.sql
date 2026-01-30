-- Unified Incident Tracker Database Schema
-- Consolidates ICE enforcement incidents and immigration-related crime cases

-- ============================================================================
-- ENUM TYPES
-- ============================================================================

-- Discriminator for incident type
CREATE TYPE incident_category AS ENUM ('enforcement', 'crime');

-- Source tier for confidence scoring
CREATE TYPE source_tier AS ENUM ('1', '2', '3', '4');

-- Curation workflow status
CREATE TYPE curation_status AS ENUM ('pending', 'in_review', 'approved', 'rejected');

-- Person role in incident
CREATE TYPE person_role AS ENUM ('victim', 'offender', 'witness', 'officer');

-- Incident relation type
CREATE TYPE relation_type AS ENUM ('duplicate', 'related', 'follow_up');

-- Incident scale
CREATE TYPE incident_scale AS ENUM ('single', 'small', 'medium', 'large', 'mass');

-- Outcome category
CREATE TYPE outcome_category AS ENUM ('death', 'serious_injury', 'minor_injury', 'no_injury', 'unknown');

-- Victim category
CREATE TYPE victim_category AS ENUM (
    'detainee', 'enforcement_target', 'protester', 'journalist',
    'bystander', 'us_citizen_collateral', 'officer', 'multiple'
);

-- ============================================================================
-- EXTENSIONS
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- For fuzzy text search

-- ============================================================================
-- CORE TABLES
-- ============================================================================

-- Jurisdictions (states and counties with sanctuary policies)
CREATE TABLE jurisdictions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    jurisdiction_type VARCHAR(50) NOT NULL CHECK (jurisdiction_type IN ('state', 'county', 'city')),
    state_code CHAR(2),
    fips_code VARCHAR(10),
    parent_jurisdiction_id UUID REFERENCES jurisdictions(id),

    -- Sanctuary policy data
    state_sanctuary_status VARCHAR(50),  -- sanctuary, anti_sanctuary, neutral
    local_sanctuary_status VARCHAR(50),  -- sanctuary, limited_cooperation, cooperative
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

-- Sources (news outlets and government sources)
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

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_sources_tier ON sources(tier);
CREATE INDEX idx_sources_type ON sources(source_type);

-- Incident types with severity weights
CREATE TABLE incident_types (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    category incident_category NOT NULL,
    description TEXT,
    severity_weight DECIMAL(3, 2) NOT NULL DEFAULT 1.0,  -- 0.00 to 5.00

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

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

-- Unified incidents table
CREATE TABLE incidents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    legacy_id VARCHAR(50),  -- Original ID from JSON (e.g., "T1-D-003")

    -- Category discriminator
    category incident_category NOT NULL,

    -- Core incident data
    date DATE NOT NULL,
    date_precision VARCHAR(20) DEFAULT 'day',  -- day, month, year
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

    -- Scale and outcome
    affected_count INTEGER DEFAULT 1,
    incident_scale incident_scale DEFAULT 'single',
    outcome VARCHAR(100),
    outcome_category outcome_category,
    outcome_detail TEXT,

    -- Victim information (for enforcement incidents)
    victim_category victim_category,
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
    offender_immigration_status VARCHAR(50),  -- For crime incidents
    prior_deportations INTEGER DEFAULT 0,
    gang_affiliated BOOLEAN DEFAULT FALSE,

    -- Curation workflow
    curation_status curation_status DEFAULT 'approved',  -- Legacy data is pre-approved
    extraction_confidence DECIMAL(3, 2),  -- LLM extraction confidence
    curated_by UUID,  -- References admin_users
    curated_at TIMESTAMP WITH TIME ZONE,

    -- Audit fields
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT valid_affected_count CHECK (affected_count >= 0),
    CONSTRAINT valid_age CHECK (victim_age IS NULL OR (victim_age >= 0 AND victim_age <= 150)),
    CONSTRAINT valid_confidence CHECK (extraction_confidence IS NULL OR (extraction_confidence >= 0 AND extraction_confidence <= 1))
);

-- Indexes for incidents
CREATE INDEX idx_incidents_category ON incidents(category);
CREATE INDEX idx_incidents_date ON incidents(date);
CREATE INDEX idx_incidents_state ON incidents(state);
CREATE INDEX idx_incidents_city ON incidents(city);
CREATE INDEX idx_incidents_type ON incidents(incident_type_id);
CREATE INDEX idx_incidents_tier ON incidents(source_tier);
CREATE INDEX idx_incidents_outcome ON incidents(outcome_category);
CREATE INDEX idx_incidents_victim_cat ON incidents(victim_category);
CREATE INDEX idx_incidents_legacy_id ON incidents(legacy_id);
CREATE INDEX idx_incidents_curation ON incidents(curation_status);
CREATE INDEX idx_incidents_location ON incidents(latitude, longitude) WHERE latitude IS NOT NULL;

-- Full-text search index
CREATE INDEX idx_incidents_search ON incidents USING gin(
    to_tsvector('english', COALESCE(title, '') || ' ' || COALESCE(description, '') || ' ' || COALESCE(notes, ''))
);

-- Persons (victims and offenders)
CREATE TABLE persons (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Identity
    name VARCHAR(255),
    aliases TEXT[],  -- Array of known aliases
    age INTEGER,
    date_of_birth DATE,
    gender VARCHAR(20),
    nationality VARCHAR(100),

    -- Immigration status (for crime tracking)
    immigration_status VARCHAR(100),
    prior_deportations INTEGER DEFAULT 0,
    reentry_after_deportation BOOLEAN DEFAULT FALSE,
    visa_type VARCHAR(50),
    visa_overstay BOOLEAN DEFAULT FALSE,

    -- Criminal history (for offenders)
    gang_affiliated BOOLEAN DEFAULT FALSE,
    gang_name VARCHAR(100),
    prior_convictions INTEGER DEFAULT 0,
    prior_violent_convictions INTEGER DEFAULT 0,

    -- Victim info
    us_citizen BOOLEAN,
    occupation VARCHAR(100),

    -- External references
    external_ids JSONB,  -- ICE detainee number, court case IDs, etc.

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_persons_name ON persons(name);
CREATE INDEX idx_persons_name_trgm ON persons USING gin(name gin_trgm_ops);
CREATE INDEX idx_persons_immigration ON persons(immigration_status);
CREATE INDEX idx_persons_gang ON persons(gang_affiliated) WHERE gang_affiliated = TRUE;

-- ============================================================================
-- JUNCTION TABLES
-- ============================================================================

-- Links incidents to people (victim/offender roles)
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

-- Multiple sources per incident
CREATE TABLE incident_sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    source_id UUID REFERENCES sources(id),

    -- Source details (can be external URL even without registered source)
    url TEXT,
    title VARCHAR(500),
    published_date DATE,
    archived_url TEXT,  -- archive.org link

    is_primary BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(incident_id, url)
);

CREATE INDEX idx_incident_sources_incident ON incident_sources(incident_id);
CREATE INDEX idx_incident_sources_source ON incident_sources(source_id);

-- Incident relations (duplicates and related incidents)
CREATE TABLE incident_relations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    related_incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    relation_type relation_type NOT NULL,
    confidence DECIMAL(3, 2),  -- 0.00 to 1.00 for auto-detected duplicates
    notes TEXT,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT no_self_relation CHECK (incident_id != related_incident_id),
    UNIQUE(incident_id, related_incident_id, relation_type)
);

CREATE INDEX idx_incident_relations_incident ON incident_relations(incident_id);
CREATE INDEX idx_incident_relations_related ON incident_relations(related_incident_id);
CREATE INDEX idx_incident_relations_type ON incident_relations(relation_type);

-- ============================================================================
-- INGESTION TABLES
-- ============================================================================

-- Raw articles awaiting curation
CREATE TABLE ingested_articles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Source tracking
    source_id UUID REFERENCES sources(id),
    source_name VARCHAR(255),
    source_url TEXT NOT NULL UNIQUE,

    -- Article content
    title VARCHAR(500),
    content TEXT,
    content_hash VARCHAR(32),  -- md5(content) for dedup of syndicated copies
    published_date DATE,
    fetched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Relevance scoring
    relevance_score DECIMAL(3, 2),  -- 0.00 to 1.00
    relevance_reason TEXT,

    -- LLM extraction
    extracted_data JSONB,  -- Raw LLM output
    extraction_confidence DECIMAL(3, 2),
    extracted_at TIMESTAMP WITH TIME ZONE,

    -- Curation workflow
    status curation_status DEFAULT 'pending',
    reviewed_by UUID,  -- References admin_users
    reviewed_at TIMESTAMP WITH TIME ZONE,
    rejection_reason TEXT,

    -- Linked incident (if approved)
    incident_id UUID REFERENCES incidents(id),

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_ingested_status ON ingested_articles(status);
CREATE INDEX idx_ingested_source ON ingested_articles(source_id);
CREATE INDEX idx_ingested_date ON ingested_articles(published_date);
CREATE INDEX idx_ingested_relevance ON ingested_articles(relevance_score DESC);
CREATE INDEX idx_ingested_content_hash ON ingested_articles(content_hash) WHERE content_hash IS NOT NULL;

-- ============================================================================
-- ADMIN TABLES
-- ============================================================================

-- Admin users for authentication
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

-- Audit log for change tracking
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    user_id UUID REFERENCES admin_users(id),
    action VARCHAR(50) NOT NULL,  -- create, update, delete, approve, reject
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
-- FUNCTIONS
-- ============================================================================

-- Calculate severity score for an incident
CREATE OR REPLACE FUNCTION calculate_severity_score(p_incident_id UUID)
RETURNS DECIMAL AS $$
DECLARE
    v_base_score DECIMAL;
    v_tier_multiplier DECIMAL;
    v_scale_multiplier DECIMAL;
    v_outcome_multiplier DECIMAL;
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
        CASE i.outcome_category
            WHEN 'death' THEN 2.0
            WHEN 'serious_injury' THEN 1.5
            WHEN 'minor_injury' THEN 1.0
            WHEN 'no_injury' THEN 0.5
            ELSE 1.0
        END
    INTO v_base_score, v_tier_multiplier, v_scale_multiplier, v_outcome_multiplier
    FROM incidents i
    JOIN incident_types it ON i.incident_type_id = it.id
    WHERE i.id = p_incident_id;

    RETURN ROUND(v_base_score * v_tier_multiplier * v_scale_multiplier * v_outcome_multiplier, 2);
END;
$$ LANGUAGE plpgsql;

-- Check if incident is non-immigrant (for filtering)
CREATE OR REPLACE FUNCTION is_non_immigrant(p_incident_id UUID)
RETURNS BOOLEAN AS $$
DECLARE
    v_incident incidents%ROWTYPE;
BEGIN
    SELECT * INTO v_incident FROM incidents WHERE id = p_incident_id;

    RETURN (
        v_incident.victim_category IN ('protester', 'journalist', 'bystander', 'us_citizen_collateral', 'officer')
        OR v_incident.us_citizen = TRUE
        OR v_incident.protest_related = TRUE
    );
END;
$$ LANGUAGE plpgsql;

-- Update timestamp trigger
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create update triggers
CREATE TRIGGER update_incidents_timestamp
    BEFORE UPDATE ON incidents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_persons_timestamp
    BEFORE UPDATE ON persons
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_jurisdictions_timestamp
    BEFORE UPDATE ON jurisdictions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_sources_timestamp
    BEFORE UPDATE ON sources
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_admin_users_timestamp
    BEFORE UPDATE ON admin_users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_ingested_articles_timestamp
    BEFORE UPDATE ON ingested_articles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================================
-- BACKGROUND JOBS & FEEDS
-- ============================================================================

-- Background jobs for async processing
CREATE TABLE background_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_type VARCHAR(50) NOT NULL,  -- fetch, process, batch_extract, batch_enrich, full_pipeline
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed, cancelled
    progress INTEGER DEFAULT 0,
    total INTEGER DEFAULT 0,
    message TEXT,
    params JSONB,
    error TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_background_jobs_status ON background_jobs(status);
CREATE INDEX idx_background_jobs_created_at ON background_jobs(created_at DESC);

-- RSS feeds for data ingestion
CREATE TABLE rss_feeds (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    url TEXT NOT NULL,
    feed_type VARCHAR(50) DEFAULT 'rss',  -- rss, atom, api
    interval_minutes INTEGER DEFAULT 60,
    active BOOLEAN DEFAULT TRUE,
    last_fetched TIMESTAMP WITH TIME ZONE,
    last_error TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_rss_feeds_active ON rss_feeds(active);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Incident summary view with computed fields
CREATE VIEW incidents_summary AS
SELECT
    i.id,
    i.legacy_id,
    i.category,
    i.date,
    i.state,
    i.city,
    it.name AS incident_type,
    i.victim_category,
    i.victim_name,
    i.outcome_category,
    i.source_tier,
    i.latitude,
    i.longitude,
    i.affected_count,
    i.us_citizen,
    i.protest_related,
    i.state_sanctuary_status,
    i.local_sanctuary_status,
    is_non_immigrant(i.id) AS is_non_immigrant,
    calculate_severity_score(i.id) AS severity_score,
    i.created_at,
    i.updated_at
FROM incidents i
JOIN incident_types it ON i.incident_type_id = it.id
WHERE i.curation_status = 'approved';

-- Jurisdiction statistics view
CREATE VIEW jurisdiction_stats AS
SELECT
    j.id,
    j.name,
    j.jurisdiction_type,
    j.state_code,
    j.state_sanctuary_status,
    j.local_sanctuary_status,
    COUNT(DISTINCT i.id) AS total_incidents,
    COUNT(DISTINCT i.id) FILTER (WHERE i.category = 'enforcement') AS enforcement_incidents,
    COUNT(DISTINCT i.id) FILTER (WHERE i.category = 'crime') AS crime_incidents,
    COUNT(DISTINCT i.id) FILTER (WHERE i.outcome_category = 'death') AS deaths,
    COUNT(DISTINCT i.id) FILTER (WHERE is_non_immigrant(i.id)) AS non_immigrant_incidents
FROM jurisdictions j
LEFT JOIN incidents i ON i.jurisdiction_id = j.id AND i.curation_status = 'approved'
GROUP BY j.id, j.name, j.jurisdiction_type, j.state_code, j.state_sanctuary_status, j.local_sanctuary_status;

-- Curation queue view
CREATE VIEW curation_queue AS
SELECT
    ia.id,
    ia.title,
    ia.source_name,
    ia.source_url,
    ia.published_date,
    ia.relevance_score,
    ia.extraction_confidence,
    ia.extracted_data,
    ia.status,
    ia.fetched_at
FROM ingested_articles ia
WHERE ia.status IN ('pending', 'in_review')
ORDER BY ia.relevance_score DESC, ia.fetched_at DESC;

-- ============================================================================
-- GRANTS (adjust roles as needed)
-- ============================================================================

-- Create application role
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
