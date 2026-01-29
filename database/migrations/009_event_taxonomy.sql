-- Migration 009: Event Taxonomy System
-- Transforms binary category system into hierarchical domain/category taxonomy.
-- Part of Phase 1: Foundation for the Generic Event Tracking System.

-- ============================================================================
-- 1. EVENT DOMAINS
-- ============================================================================

CREATE TABLE event_domains (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    slug VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    icon VARCHAR(50),
    color VARCHAR(7) CHECK (color IS NULL OR color ~ '^#[0-9A-Fa-f]{6}$'),
    is_active BOOLEAN DEFAULT TRUE,
    display_order INTEGER DEFAULT 0,
    archived_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_event_domains_slug ON event_domains(slug);
CREATE INDEX idx_event_domains_active ON event_domains(is_active) WHERE is_active = TRUE;

-- Domain deactivation trigger: prevent deactivation if active categories exist
CREATE OR REPLACE FUNCTION check_domain_deactivation()
RETURNS TRIGGER AS $$
DECLARE
    v_incident_count INTEGER;
    v_category_count INTEGER;
BEGIN
    IF NEW.is_active = FALSE AND OLD.is_active = TRUE THEN
        SELECT COUNT(*) INTO v_category_count
        FROM event_categories
        WHERE domain_id = NEW.id AND is_active = TRUE;

        IF v_category_count > 0 THEN
            RAISE EXCEPTION 'Cannot deactivate domain %: has % active categories. Deactivate categories first.',
                NEW.name, v_category_count;
        END IF;

        SELECT COUNT(*) INTO v_incident_count
        FROM incidents
        WHERE domain_id = NEW.id;

        IF v_incident_count > 0 THEN
            NEW.archived_at = NOW();
            RAISE NOTICE 'Domain % archived (% incidents preserved)', NEW.name, v_incident_count;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_check_domain_deactivation
BEFORE UPDATE ON event_domains
FOR EACH ROW
EXECUTE FUNCTION check_domain_deactivation();

-- Domain deletion prevention trigger
CREATE OR REPLACE FUNCTION prevent_domain_deletion_with_incidents()
RETURNS TRIGGER AS $$
DECLARE
    v_incident_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_incident_count
    FROM incidents
    WHERE domain_id = OLD.id;

    IF v_incident_count > 0 THEN
        RAISE EXCEPTION 'Cannot delete domain %: has % incidents. Archive instead.',
            OLD.name, v_incident_count;
    END IF;

    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_prevent_domain_deletion
BEFORE DELETE ON event_domains
FOR EACH ROW
EXECUTE FUNCTION prevent_domain_deletion_with_incidents();


-- ============================================================================
-- 2. EVENT CATEGORIES (hierarchical within domains)
-- ============================================================================

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
-- 3. EXTEND INCIDENTS TABLE
-- ============================================================================

ALTER TABLE incidents
    ADD COLUMN IF NOT EXISTS domain_id UUID REFERENCES event_domains(id),
    ADD COLUMN IF NOT EXISTS category_id UUID REFERENCES event_categories(id),
    ADD COLUMN IF NOT EXISTS custom_fields JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS event_start_date TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS event_end_date TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT ARRAY[]::TEXT[];

-- Note: date_precision already exists on incidents from original schema

CREATE INDEX IF NOT EXISTS idx_incidents_domain ON incidents(domain_id);
CREATE INDEX IF NOT EXISTS idx_incidents_category_id ON incidents(category_id);
CREATE INDEX IF NOT EXISTS idx_incidents_custom_fields ON incidents USING gin(custom_fields);
CREATE INDEX IF NOT EXISTS idx_incidents_tags ON incidents USING gin(tags);
CREATE INDEX IF NOT EXISTS idx_incidents_date_range ON incidents(event_start_date, event_end_date);


-- ============================================================================
-- 4. SEED DOMAINS AND CATEGORIES
-- ============================================================================

INSERT INTO event_domains (name, slug, description, color, display_order) VALUES
    ('Immigration', 'immigration', 'Immigration enforcement and immigrant-involved incidents', '#3B82F6', 1),
    ('Criminal Justice', 'criminal_justice', 'Arrests, prosecution, sentencing, and corrections', '#EF4444', 2),
    ('Civil Rights', 'civil_rights', 'Civil rights violations, protests, and police accountability', '#10B981', 3);

-- Immigration categories (map existing binary categories)
INSERT INTO event_categories (domain_id, name, slug, description) VALUES
    ((SELECT id FROM event_domains WHERE slug = 'immigration'), 'Enforcement', 'enforcement', 'ICE/CBP enforcement actions against non-immigrants'),
    ((SELECT id FROM event_domains WHERE slug = 'immigration'), 'Crime', 'crime', 'Crimes committed by individuals with immigration status issues');

-- Criminal justice categories
INSERT INTO event_categories (domain_id, name, slug, description) VALUES
    ((SELECT id FROM event_domains WHERE slug = 'criminal_justice'), 'Arrest', 'arrest', 'Arrest events'),
    ((SELECT id FROM event_domains WHERE slug = 'criminal_justice'), 'Prosecution', 'prosecution', 'Prosecutorial decisions and actions'),
    ((SELECT id FROM event_domains WHERE slug = 'criminal_justice'), 'Trial', 'trial', 'Trial proceedings'),
    ((SELECT id FROM event_domains WHERE slug = 'criminal_justice'), 'Sentencing', 'sentencing', 'Sentencing decisions'),
    ((SELECT id FROM event_domains WHERE slug = 'criminal_justice'), 'Incarceration', 'incarceration', 'Prison/jail events'),
    ((SELECT id FROM event_domains WHERE slug = 'criminal_justice'), 'Release', 'release', 'Release from custody');

-- Civil rights categories
INSERT INTO event_categories (domain_id, name, slug, description) VALUES
    ((SELECT id FROM event_domains WHERE slug = 'civil_rights'), 'Protest', 'protest', 'Protest and demonstration events'),
    ((SELECT id FROM event_domains WHERE slug = 'civil_rights'), 'Police Force', 'police_force', 'Use of force by police'),
    ((SELECT id FROM event_domains WHERE slug = 'civil_rights'), 'Civil Rights Violation', 'civil_rights_violation', 'Alleged violations of civil rights'),
    ((SELECT id FROM event_domains WHERE slug = 'civil_rights'), 'Litigation', 'litigation', 'Civil rights litigation');


-- ============================================================================
-- 5. MIGRATE EXISTING DATA
-- ============================================================================

-- Map existing incidents to the immigration domain using the category enum column
UPDATE incidents SET
    domain_id = (SELECT id FROM event_domains WHERE slug = 'immigration'),
    category_id = (
        SELECT ec.id FROM event_categories ec
        JOIN event_domains ed ON ec.domain_id = ed.id
        WHERE ed.slug = 'immigration'
          AND ec.slug = incidents.category::text
    ),
    event_start_date = date::timestamptz,
    event_end_date = date::timestamptz
WHERE domain_id IS NULL;


-- ============================================================================
-- 6. CUSTOM FIELD VALIDATION TRIGGER
-- ============================================================================

-- Enforce required custom fields defined by category schema
CREATE OR REPLACE FUNCTION validate_custom_fields()
RETURNS TRIGGER AS $$
DECLARE
    v_required_fields JSONB;
    v_field TEXT;
    v_missing_fields TEXT[];
BEGIN
    IF NEW.category_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT required_fields INTO v_required_fields
    FROM event_categories
    WHERE id = NEW.category_id;

    IF v_required_fields IS NULL OR v_required_fields = '[]'::jsonb THEN
        RETURN NEW;
    END IF;

    v_missing_fields := ARRAY[]::TEXT[];
    FOR v_field IN SELECT jsonb_array_elements_text(v_required_fields)
    LOOP
        IF NOT (NEW.custom_fields ? v_field) OR NEW.custom_fields->>v_field IS NULL THEN
            v_missing_fields := array_append(v_missing_fields, v_field);
        END IF;
    END LOOP;

    IF array_length(v_missing_fields, 1) > 0 THEN
        RAISE EXCEPTION 'Missing required custom fields for category %: %',
            NEW.category_id, array_to_string(v_missing_fields, ', ');
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_validate_custom_fields
BEFORE INSERT OR UPDATE ON incidents
FOR EACH ROW
EXECUTE FUNCTION validate_custom_fields();


-- ============================================================================
-- 7. CROSS-DOMAIN ACTOR APPEARANCE VIEW
-- ============================================================================

CREATE OR REPLACE VIEW actor_domain_appearances AS
SELECT
    a.id as actor_id,
    a.canonical_name,
    ed.id as domain_id,
    ed.name as domain_name,
    COUNT(DISTINCT i.id) as incident_count,
    MIN(i.event_start_date) as first_appearance,
    MAX(i.event_start_date) as last_appearance
FROM actors a
JOIN incident_actors ia ON ia.actor_id = a.id
JOIN incidents i ON i.id = ia.incident_id
JOIN event_domains ed ON i.domain_id = ed.id
GROUP BY a.id, a.canonical_name, ed.id, ed.name;


-- ============================================================================
-- 8. GRANTS
-- ============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON event_domains TO incident_tracker_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON event_categories TO incident_tracker_app;

COMMENT ON TABLE event_domains IS 'Top-level event domains (Immigration, Criminal Justice, Civil Rights, etc.)';
COMMENT ON TABLE event_categories IS 'Hierarchical event categories within domains';
COMMENT ON VIEW actor_domain_appearances IS 'Tracks actor appearances across event domains';
