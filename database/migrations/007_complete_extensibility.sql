-- Migration: Complete extensibility - Convert remaining enums to tables
-- Description: Makes outcome_category and victim_category fully extensible

BEGIN;

-- ============================================================================
-- CREATE EXTENSIBLE TYPE TABLES
-- ============================================================================

-- Outcome types (replaces outcome_category enum)
CREATE TABLE outcome_types (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    slug VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    severity_weight DECIMAL(3, 2) DEFAULT 1.0,  -- 0.00 to 5.00 for severity scoring
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
-- SEED WITH EXISTING ENUM VALUES
-- ============================================================================

-- Seed outcome types from existing enum
INSERT INTO outcome_types (name, slug, description, severity_weight, display_order) VALUES
    ('Death', 'death', 'Fatal outcome', 5.0, 1),
    ('Serious Injury', 'serious_injury', 'Significant physical harm requiring medical attention', 3.5, 2),
    ('Minor Injury', 'minor_injury', 'Minor physical harm', 2.0, 3),
    ('No Injury', 'no_injury', 'No physical harm occurred', 0.5, 4),
    ('Unknown', 'unknown', 'Outcome not specified or unclear', 1.0, 5),
    -- Add commonly extracted values that were causing errors
    ('Arrest', 'arrest', 'Subject was arrested', 1.5, 6),
    ('Detention', 'detention', 'Subject was detained', 1.5, 7),
    ('Release', 'release', 'Subject was released', 0.5, 8),
    ('Deportation', 'deportation', 'Subject was deported', 2.0, 9),
    ('Acquittal', 'acquittal', 'Found not guilty', 0.5, 10),
    ('Conviction', 'conviction', 'Found guilty', 2.5, 11),
    ('Property Damage', 'property_damage', 'Property was damaged', 1.0, 12);

-- Seed victim types from existing enum
INSERT INTO victim_types (name, slug, description, display_order) VALUES
    ('Detainee', 'detainee', 'Person in ICE/CBP custody', 1),
    ('Enforcement Target', 'enforcement_target', 'Target of enforcement action', 2),
    ('Protester', 'protester', 'Person participating in protest', 3),
    ('Journalist', 'journalist', 'Media/press member', 4),
    ('Bystander', 'bystander', 'Uninvolved person affected', 5),
    ('US Citizen (Collateral)', 'us_citizen_collateral', 'US citizen affected during enforcement', 6),
    ('Officer', 'officer', 'Law enforcement officer', 7),
    ('Multiple', 'multiple', 'Multiple victim categories', 8),
    -- Add commonly extracted values
    ('Witness', 'witness', 'Person who witnessed the incident', 9),
    ('Family Member', 'family_member', 'Family member of subject', 10),
    ('Legal Representative', 'legal_representative', 'Attorney or legal counsel', 11);

-- ============================================================================
-- MIGRATE INCIDENTS TABLE
-- ============================================================================

-- Add new foreign key columns
ALTER TABLE incidents
    ADD COLUMN outcome_type_id UUID REFERENCES outcome_types(id),
    ADD COLUMN victim_type_id UUID REFERENCES victim_types(id);

-- Migrate existing data from enums to foreign keys
UPDATE incidents SET outcome_type_id = (
    SELECT id FROM outcome_types WHERE slug = incidents.outcome_category::text
) WHERE outcome_category IS NOT NULL;

UPDATE incidents SET victim_type_id = (
    SELECT id FROM victim_types WHERE slug = incidents.victim_category::text
) WHERE victim_category IS NOT NULL;

-- Create indexes on new columns
CREATE INDEX idx_incidents_outcome_type ON incidents(outcome_type_id);
CREATE INDEX idx_incidents_victim_type ON incidents(victim_type_id);

-- ============================================================================
-- DROP OLD ENUM COLUMNS (after verification)
-- ============================================================================

-- Verify migration success
DO $$
DECLARE
    unmigrated_outcomes INTEGER;
    unmigrated_victims INTEGER;
BEGIN
    SELECT COUNT(*) INTO unmigrated_outcomes
    FROM incidents
    WHERE outcome_category IS NOT NULL AND outcome_type_id IS NULL;

    SELECT COUNT(*) INTO unmigrated_victims
    FROM incidents
    WHERE victim_category IS NOT NULL AND victim_type_id IS NULL;

    IF unmigrated_outcomes > 0 OR unmigrated_victims > 0 THEN
        RAISE EXCEPTION 'Migration incomplete: % outcomes, % victims not migrated',
            unmigrated_outcomes, unmigrated_victims;
    END IF;

    RAISE NOTICE 'Migration verified: All data successfully migrated';
END $$;

-- ============================================================================
-- UPDATE VIEWS (must drop before dropping columns they depend on)
-- ============================================================================

-- Drop views that depend on the enum columns
DROP VIEW IF EXISTS incidents_summary CASCADE;
DROP VIEW IF EXISTS jurisdiction_stats CASCADE;

-- Now safe to drop old enum columns
ALTER TABLE incidents
    DROP COLUMN outcome_category,
    DROP COLUMN victim_category;

-- Recreate incidents_summary view with new columns

CREATE VIEW incidents_summary AS
SELECT
    i.id,
    i.legacy_id,
    i.category,
    i.date,
    i.state,
    i.city,
    it.name AS incident_type,
    vt.name AS victim_category,
    i.victim_name,
    ot.name AS outcome_category,
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
LEFT JOIN outcome_types ot ON i.outcome_type_id = ot.id
LEFT JOIN victim_types vt ON i.victim_type_id = vt.id
WHERE i.curation_status = 'approved';

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Get or create outcome type
CREATE OR REPLACE FUNCTION get_or_create_outcome_type(
    p_name VARCHAR,
    p_slug VARCHAR DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    v_outcome_id UUID;
    v_slug VARCHAR;
BEGIN
    -- Generate slug if not provided
    v_slug := COALESCE(p_slug, LOWER(REGEXP_REPLACE(p_name, '[^a-zA-Z0-9]+', '_', 'g')));

    -- Try to find existing
    SELECT id INTO v_outcome_id FROM outcome_types WHERE slug = v_slug;

    -- Create if not found
    IF v_outcome_id IS NULL THEN
        INSERT INTO outcome_types (name, slug, severity_weight)
        VALUES (p_name, v_slug, 1.0)
        RETURNING id INTO v_outcome_id;

        RAISE NOTICE 'Created new outcome type: % (slug: %)', p_name, v_slug;
    END IF;

    RETURN v_outcome_id;
END;
$$ LANGUAGE plpgsql;

-- Get or create victim type
CREATE OR REPLACE FUNCTION get_or_create_victim_type(
    p_name VARCHAR,
    p_slug VARCHAR DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    v_victim_id UUID;
    v_slug VARCHAR;
BEGIN
    -- Generate slug if not provided
    v_slug := COALESCE(p_slug, LOWER(REGEXP_REPLACE(p_name, '[^a-zA-Z0-9]+', '_', 'g')));

    -- Try to find existing
    SELECT id INTO v_victim_id FROM victim_types WHERE slug = v_slug;

    -- Create if not found
    IF v_victim_id IS NULL THEN
        INSERT INTO victim_types (name, slug)
        VALUES (p_name, v_slug)
        RETURNING id INTO v_victim_id;

        RAISE NOTICE 'Created new victim type: % (slug: %)', p_name, v_slug;
    END IF;

    RETURN v_victim_id;
END;
$$ LANGUAGE plpgsql;

-- Update timestamp triggers
CREATE TRIGGER update_outcome_types_timestamp
    BEFORE UPDATE ON outcome_types
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_victim_types_timestamp
    BEFORE UPDATE ON victim_types
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================================
-- ADMIN VIEWS FOR MANAGING TYPES
-- ============================================================================

-- Outcome type usage stats
CREATE VIEW outcome_type_stats AS
SELECT
    ot.id,
    ot.name,
    ot.slug,
    ot.severity_weight,
    COUNT(i.id) as usage_count,
    COUNT(DISTINCT i.state) as states_count,
    MIN(i.date) as first_used,
    MAX(i.date) as last_used
FROM outcome_types ot
LEFT JOIN incidents i ON i.outcome_type_id = ot.id
GROUP BY ot.id, ot.name, ot.slug, ot.severity_weight
ORDER BY usage_count DESC;

-- Victim type usage stats
CREATE VIEW victim_type_stats AS
SELECT
    vt.id,
    vt.name,
    vt.slug,
    COUNT(i.id) as usage_count,
    COUNT(DISTINCT i.state) as states_count,
    MIN(i.date) as first_used,
    MAX(i.date) as last_used
FROM victim_types vt
LEFT JOIN incidents i ON i.victim_type_id = vt.id
GROUP BY vt.id, vt.name, vt.slug
ORDER BY usage_count DESC;

COMMIT;

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================

-- Run these after migration to verify success:
-- SELECT * FROM outcome_types ORDER BY display_order;
-- SELECT * FROM victim_types ORDER BY display_order;
-- SELECT * FROM outcome_type_stats;
-- SELECT * FROM victim_type_stats;

COMMENT ON TABLE outcome_types IS 'Extensible outcome categories - new types can be added dynamically';
COMMENT ON TABLE victim_types IS 'Extensible victim categories - new types can be added dynamically';
COMMENT ON FUNCTION get_or_create_outcome_type IS 'Safely get or create outcome type, auto-generating slug';
COMMENT ON FUNCTION get_or_create_victim_type IS 'Safely get or create victim type, auto-generating slug';
