-- Migration 010: Actor Role Types
-- Replaces the fixed actor_role enum with a configurable role types table.
-- Part of Phase 1: Foundation for the Generic Event Tracking System.

-- ============================================================================
-- 1. ACTOR ROLE TYPES TABLE
-- ============================================================================

CREATE TABLE actor_role_types (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    slug VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    category_id UUID REFERENCES event_categories(id),  -- NULL = applies to all categories
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_actor_role_types_slug ON actor_role_types(slug);
CREATE INDEX idx_actor_role_types_category ON actor_role_types(category_id);
CREATE INDEX idx_actor_role_types_active ON actor_role_types(is_active) WHERE is_active = TRUE;


-- ============================================================================
-- 2. SEED COMMON ROLE TYPES
-- ============================================================================

INSERT INTO actor_role_types (name, slug, description) VALUES
    -- Generic roles
    ('Victim', 'victim', 'Person harmed or affected by incident'),
    ('Offender', 'offender', 'Person who committed the act'),
    ('Witness', 'witness', 'Person who witnessed the incident'),
    ('Reporting Party', 'reporting_party', 'Person who reported the incident'),
    ('Bystander', 'bystander', 'Uninvolved person present at incident'),

    -- Law enforcement roles
    ('Police Officer', 'officer', 'Police officer involved'),
    ('ICE Agent', 'ice_agent', 'Immigration and Customs Enforcement agent'),
    ('CBP Agent', 'cbp_agent', 'Customs and Border Protection agent'),
    ('Arresting Agency', 'arresting_agency', 'Agency that made the arrest'),
    ('Reporting Agency', 'reporting_agency', 'Agency that reported the incident'),

    -- Criminal justice roles
    ('Defendant', 'defendant', 'Person charged with crime'),
    ('Prosecutor', 'prosecutor', 'Prosecuting attorney'),
    ('Defense Attorney', 'defense_attorney', 'Defense attorney'),
    ('Judge', 'judge', 'Presiding judge'),
    ('Jury', 'jury', 'Jury in trial'),

    -- Civil rights roles
    ('Protester', 'protester', 'Person participating in protest'),
    ('Organizer', 'organizer', 'Event/protest organizer'),
    ('Participant', 'participant', 'General participant in incident'),
    ('Plaintiff', 'plaintiff', 'Plaintiff in civil case'),

    -- Immigration-specific roles
    ('Detainee', 'detainee', 'Person in immigration detention'),
    ('Deportee', 'deportee', 'Person being/having been deported'),
    ('Asylum Seeker', 'asylum_seeker', 'Person seeking asylum');


-- ============================================================================
-- 3. ADD role_type_id TO incident_actors
-- ============================================================================

ALTER TABLE incident_actors
    ADD COLUMN IF NOT EXISTS role_type_id UUID REFERENCES actor_role_types(id);

CREATE INDEX IF NOT EXISTS idx_incident_actors_role_type ON incident_actors(role_type_id);


-- ============================================================================
-- 4. MIGRATE EXISTING DATA
-- ============================================================================

-- The existing actor_role enum values are:
-- 'victim', 'offender', 'witness', 'officer', 'arresting_agency',
-- 'reporting_agency', 'bystander', 'organizer', 'participant'
-- All of these match seeded slugs above.

-- Map existing enum role values to the new role_type_id
UPDATE incident_actors SET role_type_id = (
    SELECT id FROM actor_role_types
    WHERE slug = incident_actors.role::text
) WHERE role_type_id IS NULL;

-- Create 'unknown' fallback for any unmapped roles
INSERT INTO actor_role_types (name, slug, description)
VALUES ('Unknown', 'unknown', 'Unmapped role type - requires manual review')
ON CONFLICT (slug) DO NOTHING;

-- Catch any remaining unmapped rows
UPDATE incident_actors SET
    role_type_id = (SELECT id FROM actor_role_types WHERE slug = 'unknown')
WHERE role_type_id IS NULL;


-- ============================================================================
-- 5. GRANTS
-- ============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON actor_role_types TO incident_tracker_app;

COMMENT ON TABLE actor_role_types IS 'Configurable role types for actors in incidents, replacing fixed enum';
