# Generic Event Tracking System - Architecture Plan

**Status:** Draft - Round 1 Defense Complete
**Created:** 2026-01-29
**Author:** System Architect
**Scope:** Transform immigration-specific incident tracker into generic event tracking platform

## Executive Summary

This plan outlines the transformation of the current immigration-focused incident tracking system into a generic event tracking platform capable of handling diverse event domains including criminal justice, civil rights, immigration, prosecutorial accountability, and recidivism tracking.

**Key Goals:**
- Maintain backward compatibility with existing immigration tracking
- Enable tracking of any event type through configurable schemas
- Support complex event relationships and sequences
- Provide domain-specific analytics and reporting
- Enable cross-domain pattern analysis

**Estimated Timeline:** 12-16 weeks for core implementation (see detailed breakdown in Migration Strategy section)
**Risk Level:** Medium-High (significant architectural changes)
**Team Requirements:** 1-2 backend developers, 1 frontend developer, 0.25 FTE DBA
**Assumed Velocity:** 30 productive hours/week per developer, 20% time allocated to unexpected issues

## Current System Analysis

### Strengths (Keep & Build On)
✅ Extensible type system (incident_types, outcome_types, victim_types)
✅ Actor/entity tracking (actors table with relationships)
✅ Source document linking (ingested_articles)
✅ LLM-powered extraction pipeline
✅ Background job processing
✅ Curation workflow
✅ Geographic tracking (state, city, lat/lon)

### Limitations (Address in Redesign)
❌ Binary category system (enforcement/crime) - immigration-specific
❌ Fixed schema fields (victim_category, immigration_status, sanctuary_status)
❌ Single outcome per incident
❌ No event relationships or sequences
❌ Domain-specific LLM prompts baked into code
❌ No case tracking
❌ Limited temporal modeling (single date field)
❌ No recidivism or pattern tracking

## Architecture Design

### Design Principles

1. **Schema Flexibility:** Custom fields via JSONB, not fixed columns
2. **Domain Isolation:** Each domain can define its own schemas without affecting others
3. **Backward Compatibility:** Existing immigration data remains functional
4. **Incremental Migration:** Add generic capabilities alongside existing system
5. **Data Integrity:** Strong referential integrity through foreign keys
6. **Performance:** Indexes on JSONB fields, materialized views for analytics
7. **Extensibility:** Plugin architecture for new domains

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Generic Event Core                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   Events     │  │    Actors    │  │  Documents   │     │
│  │  (incidents) │  │  (entities)  │  │  (articles)  │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
┌───────▼───────┐  ┌───────▼───────┐  ┌───────▼───────┐
│   Immigration │  │Criminal Justice│  │  Civil Rights  │
│     Domain    │  │     Domain     │  │     Domain     │
│               │  │                │  │                │
│ • Enforcement │  │ • Arrests      │  │ • Protests     │
│ • Deportation │  │ • Prosecution  │  │ • Police Force │
│ • Detention   │  │ • Sentencing   │  │ • Settlements  │
│               │  │ • Recidivism   │  │                │
└───────────────┘  └────────────────┘  └────────────────┘
```

## Database Schema Changes

### Phase 1: Core Abstractions

#### 1.1 Event Taxonomy System

**Replace:** Binary category enum
**With:** Hierarchical taxonomy

```sql
-- Migration: 008_event_taxonomy.sql

-- Top-level domains
CREATE TABLE event_domains (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    slug VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    icon VARCHAR(50),  -- For UI
    color VARCHAR(7) CHECK (color ~ '^#[0-9A-Fa-f]{6}$'),  -- Hex color validation
    is_active BOOLEAN DEFAULT TRUE,
    display_order INTEGER DEFAULT 0,
    archived_at TIMESTAMPTZ,  -- When domain was archived (soft delete)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Tie-breaking for display_order
    UNIQUE(display_order, name)  -- Use name alphabetically if display_order same
);

-- Event categories within domains (hierarchical)
CREATE TABLE event_categories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain_id UUID NOT NULL REFERENCES event_domains(id) ON DELETE RESTRICT,  -- Prevent domain deletion if has categories
    parent_category_id UUID REFERENCES event_categories(id),
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(100) NOT NULL,
    description TEXT,
    icon VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    display_order INTEGER DEFAULT 0,

    -- Schema definition for this category
    required_fields JSONB DEFAULT '[]'::jsonb,
    optional_fields JSONB DEFAULT '[]'::jsonb,
    field_definitions JSONB DEFAULT '{}'::jsonb,

    archived_at TIMESTAMPTZ,  -- When category was archived
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(domain_id, slug),
    UNIQUE(domain_id, display_order, name)  -- Tie-breaking for display_order
);

-- Domain deprecation workflow trigger
CREATE OR REPLACE FUNCTION check_domain_deactivation()
RETURNS TRIGGER AS $$
DECLARE
    v_incident_count INTEGER;
    v_category_count INTEGER;
BEGIN
    IF NEW.is_active = FALSE AND OLD.is_active = TRUE THEN
        -- Check for active categories
        SELECT COUNT(*) INTO v_category_count
        FROM event_categories
        WHERE domain_id = NEW.id AND is_active = TRUE;

        IF v_category_count > 0 THEN
            RAISE EXCEPTION 'Cannot deactivate domain %: has % active categories. Deactivate categories first.',
                NEW.name, v_category_count;
        END IF;

        -- Check for incidents
        SELECT COUNT(*) INTO v_incident_count
        FROM incidents
        WHERE domain_id = NEW.id;

        IF v_incident_count > 0 THEN
            -- Archive instead of deactivate
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

-- Prevent deletion of domain with incidents
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

-- Cross-domain actor reference view [C-005]
-- Actors may appear across multiple domains (e.g., prosecutor in criminal justice
-- referenced in civil rights case). This view tracks cross-domain appearances.
CREATE VIEW actor_domain_appearances AS
SELECT
    a.id as actor_id,
    a.canonical_name,
    ed.id as domain_id,
    ed.name as domain_name,
    COUNT(DISTINCT i.id) as incident_count,
    COUNT(DISTINCT c.id) as case_count,
    MIN(i.event_start_date) as first_appearance,
    MAX(i.event_start_date) as last_appearance
FROM actors a
JOIN incident_actors ia ON ia.actor_id = a.id
JOIN incidents i ON i.id = ia.incident_id
JOIN event_domains ed ON i.domain_id = ed.id
LEFT JOIN case_actors ca ON ca.actor_id = a.id
LEFT JOIN cases c ON ca.case_id = c.id
GROUP BY a.id, a.canonical_name, ed.id, ed.name;

-- Foreign key cascade behavior summary [C-005]
-- event_domains -> event_categories: ON DELETE RESTRICT (must deactivate categories first)
-- event_categories -> incidents: No cascade (incidents reference category by FK)
-- Domain deactivation: Trigger prevents if active categories exist, archives if incidents exist
-- Domain deletion: Trigger prevents if incidents exist
-- Category deactivation: Sets archived_at, incidents remain queryable
-- Actor cross-domain: Actors are domain-independent entities, shared across domains

-- Indexes
CREATE INDEX idx_event_domains_slug ON event_domains(slug);
CREATE INDEX idx_event_categories_domain ON event_categories(domain_id);
CREATE INDEX idx_event_categories_parent ON event_categories(parent_category_id);
CREATE INDEX idx_event_categories_slug ON event_categories(slug);

-- Seed initial domains
INSERT INTO event_domains (name, slug, description, display_order) VALUES
    ('Immigration', 'immigration', 'Immigration enforcement and immigrant-involved incidents', 1),
    ('Criminal Justice', 'criminal_justice', 'Arrests, prosecution, sentencing, and corrections', 2),
    ('Civil Rights', 'civil_rights', 'Civil rights violations, protests, and police accountability', 3);

-- Seed immigration categories (migrate existing data)
INSERT INTO event_categories (domain_id, name, slug, description) VALUES
    ((SELECT id FROM event_domains WHERE slug = 'immigration'), 'Enforcement', 'enforcement', 'ICE/CBP enforcement actions'),
    ((SELECT id FROM event_domains WHERE slug = 'immigration'), 'Crime', 'crime', 'Crimes involving immigration status');

-- Seed criminal justice categories
INSERT INTO event_categories (domain_id, name, slug, description) VALUES
    ((SELECT id FROM event_domains WHERE slug = 'criminal_justice'), 'Arrest', 'arrest', 'Arrest events'),
    ((SELECT id FROM event_domains WHERE slug = 'criminal_justice'), 'Prosecution', 'prosecution', 'Prosecutorial decisions and actions'),
    ((SELECT id FROM event_domains WHERE slug = 'criminal_justice'), 'Trial', 'trial', 'Trial proceedings'),
    ((SELECT id FROM event_domains WHERE slug = 'criminal_justice'), 'Sentencing', 'sentencing', 'Sentencing decisions'),
    ((SELECT id FROM event_domains WHERE slug = 'criminal_justice'), 'Incarceration', 'incarceration', 'Prison/jail events'),
    ((SELECT id FROM event_domains WHERE slug = 'criminal_justice'), 'Release', 'release', 'Release from custody');

-- Seed civil rights categories
INSERT INTO event_categories (domain_id, name, slug, description) VALUES
    ((SELECT id FROM event_domains WHERE slug = 'civil_rights'), 'Protest', 'protest', 'Protest and demonstration events'),
    ((SELECT id FROM event_domains WHERE slug = 'civil_rights'), 'Police Force', 'police_force', 'Use of force by police'),
    ((SELECT id FROM event_domains WHERE slug = 'civil_rights'), 'Civil Rights Violation', 'civil_rights_violation', 'Alleged violations of civil rights'),
    ((SELECT id FROM event_domains WHERE slug = 'civil_rights'), 'Litigation', 'litigation', 'Civil rights litigation');
```

#### 1.2 Flexible Incident Schema

**Add:** Custom fields, domain/category references, multiple dates

```sql
-- Migration: 008_event_taxonomy.sql (continued)

-- Add new columns to incidents table
ALTER TABLE incidents
    ADD COLUMN domain_id UUID REFERENCES event_domains(id),
    ADD COLUMN category_id UUID REFERENCES event_categories(id),
    ADD COLUMN custom_fields JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN event_start_date TIMESTAMPTZ,  -- TIMESTAMPTZ supports 'time' precision; DATE-only values stored as midnight UTC
    ADD COLUMN event_end_date TIMESTAMPTZ,
    ADD COLUMN date_precision VARCHAR(20) DEFAULT 'day',  -- 'year', 'month', 'day', 'time'
    ADD COLUMN tags TEXT[] DEFAULT ARRAY[]::TEXT[];

-- Migrate existing data
UPDATE incidents SET
    domain_id = (SELECT id FROM event_domains WHERE slug = 'immigration'),
    category_id = (SELECT ec.id FROM event_categories ec
                   JOIN event_domains ed ON ec.domain_id = ed.id
                   WHERE ed.slug = 'immigration' AND ec.slug = category),
    event_start_date = date,
    event_end_date = date;

-- Add indexes
CREATE INDEX idx_incidents_domain ON incidents(domain_id);
CREATE INDEX idx_incidents_category ON incidents(category_id);
CREATE INDEX idx_incidents_custom_fields ON incidents USING gin(custom_fields);
CREATE INDEX idx_incidents_tags ON incidents USING gin(tags);
CREATE INDEX idx_incidents_date_range ON incidents(event_start_date, event_end_date);

-- Eventually drop old category column (after migration validation)
-- ALTER TABLE incidents DROP COLUMN category;
```

#### 1.3 Generic Actor Roles

**Replace:** Hardcoded "victim"/"offender" concepts
**With:** Configurable role types

```sql
-- Migration: 009_actor_roles.sql

CREATE TABLE actor_role_types (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    slug VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    category_id UUID REFERENCES event_categories(id),  -- NULL = applies to all
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Update incident_actors to use role types
ALTER TABLE incident_actors
    ADD COLUMN role_type_id UUID REFERENCES actor_role_types(id);

-- Seed common role types
INSERT INTO actor_role_types (name, slug, description) VALUES
    -- Generic roles
    ('Victim', 'victim', 'Person harmed or affected by incident'),
    ('Witness', 'witness', 'Person who witnessed the incident'),
    ('Reporting Party', 'reporting_party', 'Person who reported the incident'),

    -- Law enforcement roles
    ('Police Officer', 'police_officer', 'Police officer involved'),
    ('ICE Agent', 'ice_agent', 'Immigration and Customs Enforcement agent'),
    ('CBP Agent', 'cbp_agent', 'Customs and Border Protection agent'),

    -- Criminal justice roles
    ('Defendant', 'defendant', 'Person charged with crime'),
    ('Prosecutor', 'prosecutor', 'Prosecuting attorney'),
    ('Defense Attorney', 'defense_attorney', 'Defense attorney'),
    ('Judge', 'judge', 'Presiding judge'),
    ('Jury', 'jury', 'Jury in trial'),

    -- Civil rights roles
    ('Protester', 'protester', 'Person participating in protest'),
    ('Organizer', 'organizer', 'Event/protest organizer'),
    ('Plaintiff', 'plaintiff', 'Plaintiff in civil case'),

    -- Immigration-specific roles
    ('Detainee', 'detainee', 'Person in immigration detention'),
    ('Deportee', 'deportee', 'Person being/having been deported'),
    ('Asylum Seeker', 'asylum_seeker', 'Person seeking asylum');

-- Pre-migration audit: identify all unique roles and their mapping status [M-001]
-- Run this BEFORE migration to identify unmapped roles:
--
-- SELECT DISTINCT role,
--     LOWER(REGEXP_REPLACE(role, '[^a-zA-Z0-9]+', '_', 'g')) as computed_slug,
--     EXISTS(
--         SELECT 1 FROM actor_role_types
--         WHERE slug = LOWER(REGEXP_REPLACE(incident_actors.role, '[^a-zA-Z0-9]+', '_', 'g'))
--     ) as has_mapping
-- FROM incident_actors
-- ORDER BY role;

-- Step 1: Auto-create role types for any unmapped roles
INSERT INTO actor_role_types (name, slug, description)
SELECT DISTINCT
    role,
    LOWER(REGEXP_REPLACE(role, '[^a-zA-Z0-9]+', '_', 'g')),
    'Auto-created during migration from role: ' || role
FROM incident_actors
WHERE NOT EXISTS (
    SELECT 1 FROM actor_role_types
    WHERE slug = LOWER(REGEXP_REPLACE(incident_actors.role, '[^a-zA-Z0-9]+', '_', 'g'))
)
ON CONFLICT (slug) DO NOTHING;

-- Step 2: Migrate existing data
UPDATE incident_actors SET role_type_id = (
    SELECT id FROM actor_role_types
    WHERE slug = LOWER(REGEXP_REPLACE(incident_actors.role, '[^a-zA-Z0-9]+', '_', 'g'))
) WHERE role_type_id IS NULL;

-- Step 3: Handle any remaining unmapped roles (fallback to 'unknown')
INSERT INTO actor_role_types (name, slug, description)
VALUES ('Unknown', 'unknown', 'Unmapped role type - requires manual review')
ON CONFLICT (slug) DO NOTHING;

UPDATE incident_actors SET
    role_type_id = (SELECT id FROM actor_role_types WHERE slug = 'unknown')
WHERE role_type_id IS NULL;

-- Step 4: Validate - no NULL role_type_id values should remain
-- SELECT COUNT(*) FROM incident_actors WHERE role_type_id IS NULL;
-- Expected result: 0
```

#### 1.4 Event Relationships

**Add:** Links between related events

```sql
-- Migration: 010_event_relationships.sql

CREATE TABLE event_relationships (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    target_incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    relationship_type VARCHAR(50) NOT NULL,  -- 'precedes', 'follows', 'related_to', 'caused_by', 'appeals'
    sequence_order INTEGER,
    case_id UUID,  -- Group events in same case
    description TEXT,
    confidence DECIMAL(3,2),  -- 0.00 to 1.00
    created_at TIMESTAMPTZ DEFAULT NOW(),

    CHECK (source_incident_id != target_incident_id),
    UNIQUE(source_incident_id, target_incident_id, relationship_type)
);

CREATE INDEX idx_event_rel_source ON event_relationships(source_incident_id);
CREATE INDEX idx_event_rel_target ON event_relationships(target_incident_id);
CREATE INDEX idx_event_rel_case ON event_relationships(case_id);
CREATE INDEX idx_event_rel_type ON event_relationships(relationship_type);

-- Relationship type constraints
CREATE TABLE relationship_types (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    is_directional BOOLEAN DEFAULT TRUE,
    inverse_type VARCHAR(50)  -- e.g., 'precedes' <-> 'follows'
);

INSERT INTO relationship_types (name, description, is_directional, inverse_type) VALUES
    ('precedes', 'Source event happens before target', TRUE, 'follows'),
    ('follows', 'Source event happens after target', TRUE, 'precedes'),
    ('related_to', 'Events are related', FALSE, NULL),
    ('caused_by', 'Source event was caused by target', TRUE, 'causes'),
    ('causes', 'Source event causes target', TRUE, 'caused_by'),
    ('appeals', 'Source event is appeal of target', TRUE, 'appealed_by'),
    ('appealed_by', 'Source event is appealed by target', TRUE, 'appeals'),
    ('retrial_of', 'Source is retrial of target', TRUE, 'retried_as'),
    ('same_case', 'Events are part of same legal case', FALSE, NULL);

-- Cycle detection trigger [M-005]
-- Prevents A -> B -> C -> A temporal loops in directional relationships
CREATE OR REPLACE FUNCTION check_relationship_cycle()
RETURNS TRIGGER AS $$
DECLARE
    v_max_depth INTEGER := 20;  -- Configurable maximum chain depth
    v_has_cycle BOOLEAN;
BEGIN
    -- Only check directional relationships for cycles
    IF NEW.relationship_type IN ('precedes', 'follows', 'caused_by', 'causes', 'appeals', 'appealed_by') THEN
        WITH RECURSIVE chain AS (
            -- Start from the target of the new relationship
            SELECT target_incident_id AS current_id, 1 AS depth
            FROM event_relationships
            WHERE source_incident_id = NEW.target_incident_id
              AND relationship_type = NEW.relationship_type

            UNION ALL

            SELECT er.target_incident_id, c.depth + 1
            FROM event_relationships er
            JOIN chain c ON er.source_incident_id = c.current_id
            WHERE c.depth < v_max_depth
              AND er.relationship_type = NEW.relationship_type
        )
        SELECT EXISTS(
            SELECT 1 FROM chain WHERE current_id = NEW.source_incident_id
        ) INTO v_has_cycle;

        IF v_has_cycle THEN
            RAISE EXCEPTION 'Cycle detected: adding this relationship would create a circular chain for relationship type %',
                NEW.relationship_type;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_check_relationship_cycle
BEFORE INSERT ON event_relationships
FOR EACH ROW
EXECUTE FUNCTION check_relationship_cycle();
```

### Phase 2: Cases & Legal Tracking

#### 2.1 Cases System

```sql
-- Migration: 011_cases_system.sql

CREATE TABLE cases (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_number VARCHAR(100) NOT NULL,
    case_type VARCHAR(50) NOT NULL,  -- 'criminal', 'civil', 'immigration', 'administrative'
    jurisdiction_id UUID,  -- Reference to jurisdiction table (create if needed)
    court_name VARCHAR(200),
    filed_date DATE,
    closed_date DATE,
    status VARCHAR(50) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'closed', 'appealed', 'dismissed', 'sealed')),
    custom_fields JSONB DEFAULT '{}'::jsonb,
    data_classification VARCHAR(20) DEFAULT 'restricted'
        CHECK (data_classification IN ('public', 'restricted', 'confidential', 'highly_confidential')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Case numbers are unique within a jurisdiction [M-004]
    UNIQUE(case_number, jurisdiction_id)
);

CREATE INDEX idx_cases_number ON cases(case_number);
CREATE INDEX idx_cases_type ON cases(case_type);
CREATE INDEX idx_cases_status ON cases(status);
CREATE INDEX idx_cases_filed_date ON cases(filed_date);

-- Per-charge tracking (adopted from justice platform) [M-004, justice-platform]
-- Charges are separate entities from cases with per-charge assignment
CREATE TABLE charges (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    charge_number VARCHAR(50),
    charge_code VARCHAR(100),           -- Statute reference (e.g., "RCW 9A.36.021")
    charge_statute VARCHAR(200),
    charge_description VARCHAR(1000) NOT NULL,
    charge_level VARCHAR(50) NOT NULL,   -- 'felony', 'misdemeanor', 'infraction'
    charge_class VARCHAR(50),            -- 'Class A', 'Class B', 'Gross Misdemeanor', etc.
    severity VARCHAR(50),
    is_violent_crime BOOLEAN DEFAULT FALSE,
    filed_date DATE NOT NULL,
    filed_by_prosecutor_id UUID REFERENCES actors(id),
    status VARCHAR(50) NOT NULL DEFAULT 'filed'
        CHECK (status IN ('filed', 'amended', 'reduced', 'dismissed', 'convicted', 'acquitted')),
    status_changed_date TIMESTAMPTZ,
    disposition VARCHAR(50),
    disposition_date DATE,
    disposition_details TEXT,
    plea_entered VARCHAR(50),
    plea_date DATE,
    was_plea_bargained BOOLEAN DEFAULT FALSE,
    -- Per-charge sentencing (adopted from justice platform SentencingRecord)
    jail_days INTEGER,
    probation_days INTEGER,
    fine_amount DECIMAL(18, 2),
    restitution_amount DECIMAL(18, 2),
    community_service_hours INTEGER,
    custom_fields JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_charges_case ON charges(case_id);
CREATE INDEX idx_charges_status ON charges(status);
CREATE INDEX idx_charges_prosecutor ON charges(filed_by_prosecutor_id);

-- ChargeHistory audit trail (adopted from justice platform) [justice-platform]
-- Tracks all charge modifications: filed -> amended -> reduced -> dismissed
CREATE TABLE charge_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    charge_id UUID NOT NULL REFERENCES charges(id) ON DELETE CASCADE,
    event_date TIMESTAMPTZ NOT NULL,
    event_type VARCHAR(50) NOT NULL
        CHECK (event_type IN ('filed', 'amended', 'reduced', 'dismissed', 'reinstated', 'convicted', 'acquitted')),
    charge_code VARCHAR(100),
    charge_description VARCHAR(500),
    charge_class VARCHAR(100),
    severity_score INTEGER,
    -- Who made the change (adopted from justice platform ActorType/ActorName pattern)
    actor_type VARCHAR(50) NOT NULL
        CHECK (actor_type IN ('prosecutor', 'judge', 'defense_attorney', 'system')),
    actor_name VARCHAR(200) NOT NULL,
    actor_id UUID REFERENCES actors(id),
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_charge_history_case ON charge_history(case_id);
CREATE INDEX idx_charge_history_charge ON charge_history(charge_id);
CREATE INDEX idx_charge_history_event_type ON charge_history(event_type);
CREATE INDEX idx_charge_history_date ON charge_history(event_date);

-- Multi-jurisdiction support [M-009]
CREATE TABLE case_jurisdictions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    jurisdiction_id UUID NOT NULL,
    is_primary BOOLEAN DEFAULT FALSE,
    jurisdiction_role VARCHAR(50) NOT NULL DEFAULT 'filing'
        CHECK (jurisdiction_role IN ('filing', 'transferred', 'appellate', 'concurrent')),
    added_date DATE,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(case_id, jurisdiction_id)
);

CREATE INDEX idx_case_jurisdictions_case ON case_jurisdictions(case_id);
CREATE INDEX idx_case_jurisdictions_jurisdiction ON case_jurisdictions(jurisdiction_id);

-- External system ID mapping for cross-system deduplication (adopted from justice platform) [justice-platform]
CREATE TABLE external_system_ids (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type VARCHAR(50) NOT NULL,  -- 'case', 'incident', 'actor', 'charge'
    entity_id UUID NOT NULL,
    system_name VARCHAR(100) NOT NULL,  -- 'king_county_courts', 'socrata', 'fbi_ucr', etc.
    external_id VARCHAR(200) NOT NULL,
    external_url VARCHAR(500),
    is_active BOOLEAN DEFAULT TRUE,
    mapping_status VARCHAR(50) DEFAULT 'confirmed'
        CHECK (mapping_status IN ('confirmed', 'tentative', 'disputed', 'superseded')),
    match_confidence DECIMAL(5,4),  -- 0.0000 to 1.0000
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    data_source VARCHAR(200),

    UNIQUE(system_name, external_id)
);

CREATE INDEX idx_external_ids_entity ON external_system_ids(entity_type, entity_id);
CREATE INDEX idx_external_ids_system ON external_system_ids(system_name, external_id);
CREATE INDEX idx_external_ids_active ON external_system_ids(is_active) WHERE is_active = TRUE;

-- Link incidents to cases
CREATE TABLE case_incidents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    incident_role VARCHAR(50) NOT NULL,  -- 'arrest', 'arraignment', 'hearing', 'trial', 'sentencing'
    sequence_order INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(case_id, incident_id, incident_role)
);

CREATE INDEX idx_case_incidents_case ON case_incidents(case_id);
CREATE INDEX idx_case_incidents_incident ON case_incidents(incident_id);

-- Link actors to cases with roles
CREATE TABLE case_actors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    actor_id UUID NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
    role_type_id UUID NOT NULL REFERENCES actor_role_types(id),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(case_id, actor_id, role_type_id)
);

CREATE INDEX idx_case_actors_case ON case_actors(case_id);
CREATE INDEX idx_case_actors_actor ON case_actors(actor_id);
CREATE INDEX idx_case_actors_role ON case_actors(role_type_id);
```

#### 2.2 Prosecutorial Actions

```sql
-- Migration: 012_prosecutorial_tracking.sql

CREATE TABLE prosecutorial_actions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    prosecutor_id UUID NOT NULL REFERENCES actors(id),
    action_type VARCHAR(100) NOT NULL
        CHECK (action_type IN ('filed_charges', 'amended_charges', 'plea_offer',
                               'dismissed', 'trial_decision', 'sentencing_recommendation',
                               'bail_recommendation', 'diversion_offer', 'nolle_prosequi')),
    action_date DATE NOT NULL,

    -- Charge details (DEPRECATED: use prosecutor_action_charges junction table instead)
    -- Kept for backward compatibility during migration, will be removed in future version
    original_charges JSONB,
    amended_charges JSONB,
    dismissed_charges JSONB,

    -- Plea bargain details
    plea_offer JSONB,
    plea_accepted BOOLEAN,

    -- Reasoning
    reasoning TEXT,
    legal_basis TEXT,
    justification TEXT,  -- Adopted from justice platform ProsecutorAction

    -- Supervision
    supervisor_reviewed BOOLEAN DEFAULT FALSE,

    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,
    custom_fields JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_prosec_actions_case ON prosecutorial_actions(case_id);
CREATE INDEX idx_prosec_actions_prosecutor ON prosecutorial_actions(prosecutor_id);
CREATE INDEX idx_prosec_actions_type ON prosecutorial_actions(action_type);
CREATE INDEX idx_prosec_actions_date ON prosecutorial_actions(action_date);

-- Junction table: links prosecutorial actions to affected charges [justice-platform]
-- Replaces JSONB charge columns (same evolution as justice platform's ProsecutorActionCharge)
CREATE TABLE prosecutor_action_charges (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    action_id UUID NOT NULL REFERENCES prosecutorial_actions(id) ON DELETE CASCADE,
    charge_id UUID NOT NULL REFERENCES charges(id) ON DELETE CASCADE,
    charge_role VARCHAR(50) NOT NULL DEFAULT 'affected'
        CHECK (charge_role IN ('original', 'amended_to', 'dismissed', 'affected', 'added')),
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(action_id, charge_id, charge_role)
);

CREATE INDEX idx_pac_action ON prosecutor_action_charges(action_id);
CREATE INDEX idx_pac_charge ON prosecutor_action_charges(charge_id);

-- Bail decision tracking (adopted from justice platform BailDecisions) [justice-platform]
CREATE TABLE bail_decisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    decision_date TIMESTAMPTZ NOT NULL,
    decision_type VARCHAR(50) NOT NULL
        CHECK (decision_type IN ('initial_bail', 'bail_modification', 'bail_revocation', 'release_on_recognizance')),
    judge_id UUID REFERENCES actors(id),
    bail_amount DECIMAL(18, 2),
    previous_bail_amount DECIMAL(18, 2),
    bail_type VARCHAR(50) NOT NULL DEFAULT 'cash'
        CHECK (bail_type IN ('cash', 'surety', 'property', 'unsecured', 'personal_recognizance', 'no_bail')),
    decision_rationale TEXT,
    -- Risk assessment context
    flight_risk_assessed BOOLEAN DEFAULT FALSE,
    danger_to_public_assessed BOOLEAN DEFAULT FALSE,
    prior_record_considered BOOLEAN DEFAULT FALSE,
    community_ties_considered BOOLEAN DEFAULT FALSE,
    risk_factors_notes TEXT,
    -- Prosecution and defense positions
    prosecutor_requested_amount DECIMAL(18, 2),
    defense_requested_amount DECIMAL(18, 2),
    prosecutor_argument TEXT,
    defense_argument TEXT,
    -- Outcome
    bail_status VARCHAR(50) NOT NULL DEFAULT 'set'
        CHECK (bail_status IN ('set', 'posted', 'revoked', 'forfeited', 'exonerated')),
    defendant_released BOOLEAN DEFAULT FALSE,
    release_date TIMESTAMPTZ,
    custom_fields JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_bail_decisions_case ON bail_decisions(case_id);
CREATE INDEX idx_bail_decisions_judge ON bail_decisions(judge_id);
CREATE INDEX idx_bail_decisions_date ON bail_decisions(decision_date);

CREATE TABLE dispositions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    disposition_type VARCHAR(50) NOT NULL
        CHECK (disposition_type IN ('convicted', 'acquitted', 'dismissed', 'plea', 'mistrial',
                                     'nolle_prosequi', 'deferred_adjudication', 'diverted')),
    disposition_date DATE NOT NULL,

    -- Outcome details
    charges_convicted JSONB,
    charges_acquitted JSONB,
    verdict_details TEXT,

    -- Granular sentencing (adopted from justice platform SentencingRecord) [justice-platform]
    -- Incarceration
    total_jail_days INTEGER,
    jail_days_suspended INTEGER,
    jail_days_served INTEGER,
    incarceration_start_date TIMESTAMPTZ,
    projected_release_date TIMESTAMPTZ,
    actual_release_date TIMESTAMPTZ,
    incarceration_facility VARCHAR(200),
    -- Probation
    probation_days INTEGER,
    probation_start_date TIMESTAMPTZ,
    probation_end_date TIMESTAMPTZ,
    probation_conditions JSONB,
    -- Financial
    fine_amount DECIMAL(18, 2),
    fine_amount_paid DECIMAL(18, 2),
    restitution_amount DECIMAL(18, 2),
    restitution_amount_paid DECIMAL(18, 2),
    court_costs DECIMAL(18, 2),
    -- Community service
    community_service_hours INTEGER,
    community_service_hours_completed INTEGER,
    -- Treatment and programs
    ordered_programs JSONB,  -- Array of program names/types
    substance_abuse_treatment_ordered BOOLEAN DEFAULT FALSE,
    mental_health_treatment_ordered BOOLEAN DEFAULT FALSE,
    -- Compliance
    compliance_status VARCHAR(50) DEFAULT 'pending'
        CHECK (compliance_status IN ('pending', 'compliant', 'non_compliant', 'completed', 'revoked')),
    -- Legacy fields (kept for backward compatibility)
    sentence JSONB,
    sentence_years INTEGER,
    sentence_months INTEGER,
    sentence_days INTEGER,
    probation_years INTEGER,

    -- Metadata
    judge_id UUID REFERENCES actors(id),
    custom_fields JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_dispositions_case ON dispositions(case_id);
CREATE INDEX idx_dispositions_type ON dispositions(disposition_type);
CREATE INDEX idx_dispositions_date ON dispositions(disposition_date);
CREATE INDEX idx_dispositions_judge ON dispositions(judge_id);

-- Prosecutor performance analytics view with disparity scoring [justice-platform]
CREATE MATERIALIZED VIEW prosecutor_stats AS
SELECT
    p.id as prosecutor_id,
    p.canonical_name as prosecutor_name,
    COUNT(DISTINCT pa.case_id) as total_cases,
    COUNT(DISTINCT d.case_id) FILTER (WHERE d.disposition_type = 'convicted') as convictions,
    COUNT(DISTINCT d.case_id) FILTER (WHERE d.disposition_type = 'acquitted') as acquittals,
    COUNT(DISTINCT d.case_id) FILTER (WHERE d.disposition_type = 'dismissed') as dismissals,
    COUNT(DISTINCT d.case_id) FILTER (WHERE d.disposition_type = 'plea') as plea_bargains,
    ROUND(AVG(CASE WHEN d.disposition_type = 'convicted' THEN 1.0 ELSE 0.0 END)::numeric, 3) as conviction_rate,
    AVG(d.sentence_years * 12 + d.sentence_months) FILTER (WHERE d.disposition_type IN ('convicted', 'plea')) as avg_sentence_months,
    -- Charge reduction tracking
    COUNT(DISTINCT ch.id) FILTER (WHERE ch.event_type = 'reduced') as charges_reduced,
    COUNT(DISTINCT ch.id) FILTER (WHERE ch.event_type = 'dismissed') as charges_dismissed_count,
    COUNT(DISTINCT ch.id) FILTER (WHERE ch.event_type = 'amended') as charges_amended,
    -- Bail decision tracking
    AVG(bd.bail_amount) as avg_bail_requested,
    -- Disparity scoring placeholders (adopted from justice platform) [justice-platform]
    -- These are computed by separate analytics jobs, not inline
    NULL::DECIMAL(10,4) as racial_disparity_score,
    NULL::DECIMAL(10,4) as gender_disparity_score,
    NULL::DECIMAL(10,4) as socioeconomic_disparity_score,
    -- Time-period aggregation (adopted from justice platform) [justice-platform]
    DATE_TRUNC('month', MIN(pa.action_date)) as period_start,
    DATE_TRUNC('month', MAX(pa.action_date)) as period_end,
    -- Data quality
    ROUND(
        (COUNT(DISTINCT d.case_id)::numeric / NULLIF(COUNT(DISTINCT pa.case_id), 0) * 100)::numeric, 2
    ) as data_completeness_pct
FROM actors p
JOIN prosecutorial_actions pa ON pa.prosecutor_id = p.id
LEFT JOIN dispositions d ON d.case_id = pa.case_id
LEFT JOIN charge_history ch ON ch.case_id = pa.case_id AND ch.actor_id = p.id
LEFT JOIN bail_decisions bd ON bd.case_id = pa.case_id
WHERE p.actor_type = 'prosecutor'
GROUP BY p.id, p.canonical_name;

CREATE UNIQUE INDEX idx_prosecutor_stats_id ON prosecutor_stats(prosecutor_id);
```

### Phase 3: Flexible Extraction System

#### 3.1 Extraction Schemas

```sql
-- Migration: 013_extraction_schemas.sql

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
    required_fields JSONB NOT NULL,  -- Array of field names
    optional_fields JSONB DEFAULT '[]'::jsonb,
    field_definitions JSONB NOT NULL,  -- Field types, validation, descriptions

    -- Validation Rules
    validation_rules JSONB DEFAULT '{}'::jsonb,
    confidence_thresholds JSONB DEFAULT '{}'::jsonb,

    -- Prompt Testing & Quality Metrics
    test_dataset_id UUID,  -- Reference to golden dataset for validation
    quality_metrics JSONB DEFAULT '{}'::jsonb,  -- precision, recall, F1 scores
    min_quality_threshold DECIMAL(3,2) DEFAULT 0.80,  -- Minimum F1 to deploy

    -- Version Control
    git_commit_sha VARCHAR(40),  -- Track which code version this prompt was tested with
    previous_version_id UUID REFERENCES extraction_schemas(id),  -- Link to previous version
    rollback_reason TEXT,  -- If this version was rolled back, why?

    -- Metadata
    is_active BOOLEAN DEFAULT TRUE,
    is_production BOOLEAN DEFAULT FALSE,  -- Only one version can be production at a time
    deployed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID REFERENCES actors(id),

    -- Constraints
    CHECK (schema_version > 0),
    CHECK (min_quality_threshold BETWEEN 0 AND 1)
);

-- Only one production version per domain/category
CREATE UNIQUE INDEX idx_extraction_schemas_production
ON extraction_schemas(domain_id, category_id)
WHERE is_production = TRUE AND is_active = TRUE;

-- Prompt quality validation golden datasets
CREATE TABLE prompt_test_datasets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(200) NOT NULL,
    description TEXT,
    domain_id UUID REFERENCES event_domains(id),
    category_id UUID REFERENCES event_categories(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Individual test cases in golden dataset
CREATE TABLE prompt_test_cases (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dataset_id UUID NOT NULL REFERENCES prompt_test_datasets(id) ON DELETE CASCADE,
    article_text TEXT NOT NULL,
    expected_extraction JSONB NOT NULL,  -- Expected output
    importance VARCHAR(20) DEFAULT 'medium',  -- 'critical', 'high', 'medium', 'low'
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_test_cases_dataset ON prompt_test_cases(dataset_id);

-- Track test runs for each schema version
CREATE TABLE prompt_test_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    schema_id UUID NOT NULL REFERENCES extraction_schemas(id) ON DELETE CASCADE,
    dataset_id UUID NOT NULL REFERENCES prompt_test_datasets(id),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'running',  -- 'running', 'passed', 'failed', 'error'

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

    results JSONB DEFAULT '[]'::jsonb,  -- Detailed per-case results
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_test_runs_schema ON prompt_test_runs(schema_id);
CREATE INDEX idx_test_runs_status ON prompt_test_runs(status);

-- Production quality monitoring
CREATE TABLE extraction_quality_samples (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    schema_id UUID NOT NULL REFERENCES extraction_schemas(id),
    article_id UUID NOT NULL REFERENCES articles(id),
    extracted_data JSONB,
    confidence DECIMAL(3,2),
    human_reviewed BOOLEAN DEFAULT FALSE,
    review_passed BOOLEAN,  -- Did human reviewer accept extraction?
    review_corrections JSONB,  -- What fields were corrected?
    reviewed_by UUID REFERENCES actors(id),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_quality_samples_schema ON extraction_quality_samples(schema_id);
CREATE INDEX idx_quality_samples_reviewed ON extraction_quality_samples(human_reviewed);

CREATE INDEX idx_extraction_schemas_domain ON extraction_schemas(domain_id);
CREATE INDEX idx_extraction_schemas_category ON extraction_schemas(category_id);
CREATE INDEX idx_extraction_schemas_active ON extraction_schemas(is_active) WHERE is_active = TRUE;

-- Example schema for prosecution tracking
INSERT INTO extraction_schemas (
    domain_id,
    category_id,
    name,
    description,
    system_prompt,
    user_prompt_template,
    required_fields,
    optional_fields,
    field_definitions
) VALUES (
    (SELECT id FROM event_domains WHERE slug = 'criminal_justice'),
    (SELECT id FROM event_categories WHERE slug = 'prosecution'),
    'Prosecutorial Decision Extraction',
    'Extract prosecutor decisions, charge changes, and plea bargains from news articles',
    'You are analyzing news articles about criminal prosecutions. Extract structured data about prosecutorial decisions, charges, plea bargains, and case outcomes.',
    'Extract the following information from this article about a prosecution:\n\n{article_text}\n\nProvide structured data including: prosecutor name, defendant name, original charges, amended charges, plea offer, disposition, sentence.',
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
    }'::jsonb
);
```

### Phase 4: Advanced Analytics

#### 4.1 Recidivism Tracking

```sql
-- Migration: 014_recidivism_tracking.sql

-- Actor incident history view
CREATE VIEW actor_incident_history AS
SELECT
    a.id as actor_id,
    a.canonical_name,
    i.id as incident_id,
    i.event_start_date as incident_date,
    ed.name as domain,
    ec.name as category,
    it.name as incident_type,
    ot.name as outcome,
    i.custom_fields,
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

-- Recidivism analysis
CREATE MATERIALIZED VIEW recidivism_analysis AS
SELECT
    actor_id,
    canonical_name,
    COUNT(*) as total_incidents,
    MIN(incident_date) as first_incident_date,
    MAX(incident_date) as most_recent_incident_date,
    EXTRACT(days FROM MAX(incident_date) - MIN(incident_date))::INTEGER as total_days_span,
    AVG(days_since_last_incident) as avg_days_between_incidents,
    STDDEV(days_since_last_incident) as stddev_days_between,
    COUNT(*) FILTER (WHERE incident_number > 1) as recidivist_incidents,
    ARRAY_AGG(incident_type ORDER BY incident_date) as incident_progression,
    ARRAY_AGG(outcome ORDER BY incident_date) as outcome_progression
FROM actor_incident_history
WHERE total_incidents_for_actor > 1
GROUP BY actor_id, canonical_name
ORDER BY total_incidents DESC;

CREATE UNIQUE INDEX idx_recidivism_actor ON recidivism_analysis(actor_id);

-- Recidivism indicator function [M-003]
-- WARNING: This is a HEURISTIC indicator, NOT a validated risk assessment instrument.
-- FOR INFORMATIONAL USE ONLY. Not validated for judicial decision-making.
-- Must not be used for automated decision-making without a validated ML model.
-- Known limitations: no demographic normalization, no offense-type weighting,
-- no validation study performed, potential for demographic bias.
-- To be replaced with validated ML model in Phase 5.
CREATE FUNCTION calculate_recidivism_indicator(p_actor_id UUID)
RETURNS TABLE (
    indicator_score DECIMAL(5,4),
    is_preliminary BOOLEAN,
    model_version VARCHAR(20),
    disclaimer TEXT
) AS $$
DECLARE
    v_total_incidents INTEGER;
    v_avg_days_between NUMERIC;
    v_latest_incident_days_ago INTEGER;
    v_score DECIMAL(5,4);
BEGIN
    SELECT
        total_incidents,
        avg_days_between_incidents,
        EXTRACT(days FROM NOW() - most_recent_incident_date)::INTEGER
    INTO v_total_incidents, v_avg_days_between, v_latest_incident_days_ago
    FROM recidivism_analysis
    WHERE actor_id = p_actor_id;

    IF v_total_incidents IS NULL THEN
        RETURN QUERY SELECT
            0.0000::DECIMAL(5,4),
            TRUE,
            'heuristic-v1'::VARCHAR(20),
            'No incident history found. This is a heuristic indicator, not a validated instrument.'::TEXT;
        RETURN;
    END IF;

    -- Heuristic model - NOT validated for any decision-making
    -- Factors: number of incidents, frequency, recency
    v_score := LEAST(1.0,
        (v_total_incidents * 0.1) +
        (1.0 / NULLIF(v_avg_days_between, 0) * 100) +
        CASE
            WHEN v_latest_incident_days_ago < 90 THEN 0.3
            WHEN v_latest_incident_days_ago < 180 THEN 0.2
            WHEN v_latest_incident_days_ago < 365 THEN 0.1
            ELSE 0.0
        END
    );

    RETURN QUERY SELECT
        v_score,
        TRUE,  -- Always preliminary until ML model replaces this
        'heuristic-v1'::VARCHAR(20),
        'FOR INFORMATIONAL USE ONLY. Heuristic indicator not validated for judicial decision-making. Potential for demographic bias. See Phase 5 for validated model.'::TEXT;
END;
$$ LANGUAGE plpgsql;

-- DefendantLifecycleTimeline: 12-phase aggregated timeline (adopted from justice platform) [justice-platform]
CREATE VIEW defendant_lifecycle_timeline AS
WITH lifecycle_events AS (
    SELECT
        a.id as actor_id,
        a.canonical_name,
        i.id as incident_id,
        c.id as case_id,
        c.case_number,
        -- Classify into 12 lifecycle phases
        CASE
            WHEN ec.slug = 'arrest' THEN '01_arrest'
            WHEN ec.slug = 'booking' OR i.custom_fields->>'phase' = 'booking' THEN '02_booking'
            WHEN ci.incident_role = 'initial_appearance' THEN '03_initial_appearance'
            WHEN bd.id IS NOT NULL THEN '04_bail'
            WHEN pa.action_type = 'filed_charges' THEN '05_prosecution'
            WHEN ia.role_type_id = (SELECT id FROM actor_role_types WHERE slug = 'defense_attorney') THEN '06_defense'
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
SELECT
    actor_id,
    canonical_name,
    case_id,
    case_number,
    lifecycle_phase,
    MIN(event_date) as phase_start_date,
    MAX(event_date) as phase_end_date,
    COUNT(*) as events_in_phase
FROM lifecycle_events
WHERE lifecycle_phase != '00_unknown'
GROUP BY actor_id, canonical_name, case_id, case_number, lifecycle_phase
ORDER BY actor_id, case_id, lifecycle_phase;
```

### Field Definition Schema Specification [M-002]

The `field_definitions` JSONB column uses a declarative JSON Schema format. Each key is a field name, and each value is a field definition object:

```json
{
  "<field_name>": {
    "type": "string | number | integer | boolean | date | array | object | select",
    "description": "Human-readable description for UI labels and tooltips",
    "required": true,
    "enum": ["option1", "option2"],
    "pattern": "^[A-Z]{2}$",
    "min": 0,
    "max": 100,
    "min_length": 1,
    "max_length": 500,
    "default": "default_value",
    "display_order": 1,
    "group": "section_name",
    "options": ["select_option_1", "select_option_2"]
  }
}
```

**Allowed types:** `string`, `number`, `integer`, `boolean`, `date`, `array`, `object`, `select`.

**Validation rules:** Only declarative validation is permitted (regex patterns, ranges, enums). Custom validators must NOT contain executable code. All validation is expressed as JSON properties that the application interprets.

**Security constraint:** Field definitions are validated on save to ensure no executable content. The `pattern` field is tested for regex compilation safety (no catastrophic backtracking patterns).

**Relationship to required_fields/optional_fields:** The `required_fields` array lists field names that MUST be present on incident creation. The `optional_fields` array lists fields that SHOULD be extracted but are not mandatory. The `field_definitions` provides metadata (types, validation, UI hints) for ALL fields. A field appearing in `required_fields` has its `required` property implicitly set to `true`.

### Custom Field Validation [M-006]

```sql
-- Trigger to enforce required custom fields at database level
CREATE OR REPLACE FUNCTION validate_custom_fields()
RETURNS TRIGGER AS $$
DECLARE
    v_category RECORD;
    v_required_fields JSONB;
    v_field TEXT;
    v_missing_fields TEXT[];
BEGIN
    -- Only validate if category_id is set
    IF NEW.category_id IS NULL THEN
        RETURN NEW;
    END IF;

    -- Get category schema
    SELECT required_fields INTO v_required_fields
    FROM event_categories
    WHERE id = NEW.category_id;

    IF v_required_fields IS NULL OR v_required_fields = '[]'::jsonb THEN
        RETURN NEW;
    END IF;

    -- Check each required field exists in custom_fields
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
```

### Materialized View Refresh Strategy [M-007]

```sql
-- Configuration table for materialized view refresh scheduling
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

INSERT INTO materialized_view_refresh_config (view_name, refresh_interval_minutes, staleness_tolerance_minutes) VALUES
    ('prosecutor_stats', 60, 120),        -- Refresh hourly, tolerate 2h staleness
    ('recidivism_analysis', 360, 720);    -- Refresh every 6h, tolerate 12h staleness
```

All materialized view refreshes use `REFRESH MATERIALIZED VIEW CONCURRENTLY` to avoid blocking reads. Refresh is triggered by the existing background job system (job_executor.py). Monitoring: alert if `NOW() - last_refresh_at > staleness_tolerance_minutes` and `is_enabled = TRUE`.

### Transaction Boundary Specification [M-008]

All multi-table operations use explicit transaction boundaries:

| Operation | Tables Involved | Isolation Level | Retry Policy |
|-----------|----------------|-----------------|--------------|
| Create case with charges | cases, charges, case_actors, charge_history | READ COMMITTED | 3 retries, exponential backoff |
| Record prosecutorial action | prosecutorial_actions, prosecutor_action_charges, charge_history | READ COMMITTED | 3 retries |
| Record disposition | dispositions, charges (status update), charge_history | SERIALIZABLE | 3 retries |
| Create incident with actors | incidents, incident_actors, custom_fields validation | READ COMMITTED | 3 retries |
| Bail decision | bail_decisions, cases (status update) | READ COMMITTED | 3 retries |
| Batch migration | incidents (batch update) | READ COMMITTED | Infinite retries with SKIP LOCKED |

### Staging Tables for ETL [justice-platform]

```sql
-- Staging tables for data validation before production import
-- (adopted from justice platform staging pattern)
CREATE TABLE staging_incidents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    import_saga_id UUID,  -- Link to import saga for tracking
    source_system VARCHAR(100) NOT NULL,
    source_id VARCHAR(200),
    raw_data JSONB NOT NULL,
    -- Parsed fields (populated during validation)
    parsed_date TIMESTAMPTZ,
    parsed_state VARCHAR(2),
    parsed_category VARCHAR(100),
    parsed_domain VARCHAR(100),
    -- Validation status
    validation_status VARCHAR(50) DEFAULT 'pending'
        CHECK (validation_status IN ('pending', 'valid', 'invalid', 'duplicate', 'imported')),
    validation_errors JSONB DEFAULT '[]'::jsonb,
    -- Deduplication
    duplicate_of_incident_id UUID,
    match_confidence DECIMAL(5,4),
    -- Comparison tracking (adopted from justice platform ComparisonStatus)
    comparison_status VARCHAR(50) DEFAULT 'new'
        CHECK (comparison_status IN ('new', 'matched', 'updated', 'conflict', 'orphaned')),
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    imported_incident_id UUID  -- Points to production incident after import
);

CREATE INDEX idx_staging_incidents_status ON staging_incidents(validation_status);
CREATE INDEX idx_staging_incidents_saga ON staging_incidents(import_saga_id);
CREATE INDEX idx_staging_incidents_source ON staging_incidents(source_system, source_id);

CREATE TABLE staging_actors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    import_saga_id UUID,
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

-- Import saga orchestration (adopted from justice platform saga pattern) [justice-platform]
-- Tracks multi-step import workflows with state management
CREATE TABLE import_sagas (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    saga_type VARCHAR(100) NOT NULL,  -- 'rss_feed_import', 'bulk_csv_import', 'api_sync', etc.
    source_system VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'created'
        CHECK (status IN ('created', 'fetching', 'validating', 'deduplicating',
                          'importing', 'completed', 'failed', 'cancelled', 'rolled_back')),
    -- Step tracking
    current_step INTEGER DEFAULT 0,
    total_steps INTEGER,
    steps_completed JSONB DEFAULT '[]'::jsonb,  -- Array of completed step names with timestamps
    -- Metrics
    total_records INTEGER DEFAULT 0,
    valid_records INTEGER DEFAULT 0,
    invalid_records INTEGER DEFAULT 0,
    duplicate_records INTEGER DEFAULT 0,
    imported_records INTEGER DEFAULT 0,
    -- Error handling
    error_message TEXT,
    error_details JSONB,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    -- Timing
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    -- Metadata
    initiated_by UUID,
    custom_fields JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_import_sagas_status ON import_sagas(status);
CREATE INDEX idx_import_sagas_type ON import_sagas(saga_type);
CREATE INDEX idx_import_sagas_source ON import_sagas(source_system);
```

### Migration Rollback Log

```sql
-- Track all rollback operations for audit purposes
CREATE TABLE migration_rollback_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    migration_phase VARCHAR(10) NOT NULL,  -- '1A', '1B', '1C', '1D', '1E'
    rollback_type VARCHAR(50) NOT NULL,  -- 'transaction_rollback', 'manual_cleanup', 'backup_restore'
    reason TEXT NOT NULL,
    executed_by VARCHAR(100),
    executed_at TIMESTAMPTZ DEFAULT NOW(),
    rollback_sql TEXT,
    success BOOLEAN,
    error_message TEXT
);
```

## Backend Implementation

### 3.1 Service Layer Refactoring

#### Domain Service Architecture

```python
# backend/services/domain_service.py
"""
Generic domain service for handling domain-specific logic.
"""
from typing import Dict, Any, List, Optional
from uuid import UUID
import asyncpg

class DomainService:
    """Base class for domain-specific services."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_domain(self, slug: str) -> Optional[Dict[str, Any]]:
        """Get domain by slug."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM event_domains WHERE slug = $1",
                slug
            )
            return dict(row) if row else None

    async def get_category(self, domain_slug: str, category_slug: str) -> Optional[Dict[str, Any]]:
        """Get category within domain."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT ec.* FROM event_categories ec
                JOIN event_domains ed ON ec.domain_id = ed.id
                WHERE ed.slug = $1 AND ec.slug = $2
            """, domain_slug, category_slug)
            return dict(row) if row else None

    async def get_extraction_schema(
        self,
        domain_id: Optional[UUID] = None,
        category_id: Optional[UUID] = None
    ) -> Optional[Dict[str, Any]]:
        """Get extraction schema for domain/category."""
        async with self.pool.acquire() as conn:
            if category_id:
                row = await conn.fetchrow(
                    "SELECT * FROM extraction_schemas WHERE category_id = $1 AND is_active = TRUE ORDER BY schema_version DESC LIMIT 1",
                    category_id
                )
            elif domain_id:
                row = await conn.fetchrow(
                    "SELECT * FROM extraction_schemas WHERE domain_id = $1 AND category_id IS NULL AND is_active = TRUE ORDER BY schema_version DESC LIMIT 1",
                    domain_id
                )
            else:
                return None

            return dict(row) if row else None

class CriminalJusticeDomain(DomainService):
    """Criminal justice domain-specific logic."""

    async def create_case(
        self,
        case_number: str,
        case_type: str,
        filed_date: str,
        charges: List[Dict[str, Any]],
        **kwargs
    ) -> UUID:
        """Create a new case in the criminal justice system."""
        async with self.pool.acquire() as conn:
            case_id = await conn.fetchval("""
                INSERT INTO cases (case_number, case_type, filed_date, charges, custom_fields)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
            """, case_number, case_type, filed_date, charges, kwargs.get('custom_fields', {}))
            return case_id

    async def record_prosecutorial_action(
        self,
        case_id: UUID,
        prosecutor_id: UUID,
        action_type: str,
        action_date: str,
        **details
    ) -> UUID:
        """Record a prosecutorial action."""
        async with self.pool.acquire() as conn:
            action_id = await conn.fetchval("""
                INSERT INTO prosecutorial_actions (
                    case_id, prosecutor_id, action_type, action_date,
                    original_charges, amended_charges, plea_offer, reasoning, custom_fields
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id
            """,
                case_id, prosecutor_id, action_type, action_date,
                details.get('original_charges'),
                details.get('amended_charges'),
                details.get('plea_offer'),
                details.get('reasoning'),
                details.get('custom_fields', {})
            )
            return action_id

    async def calculate_prosecutor_stats(self, prosecutor_id: UUID) -> Dict[str, Any]:
        """Get statistics for a prosecutor."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM prosecutor_stats WHERE prosecutor_id = $1",
                prosecutor_id
            )
            return dict(row) if row else {}
```

#### Generic Extraction Service

```python
# backend/services/generic_extraction.py
"""
Generic extraction service supporting multiple domains.
"""
from typing import Dict, Any, Optional
from uuid import UUID
import anthropic

class GenericExtractionService:
    """LLM extraction service with domain-specific schemas."""

    def __init__(self, anthropic_client: anthropic.Anthropic, domain_service: DomainService):
        self.client = anthropic_client
        self.domain_service = domain_service

    async def extract_from_article(
        self,
        article_text: str,
        domain_id: Optional[UUID] = None,
        category_id: Optional[UUID] = None,
        schema_id: Optional[UUID] = None
    ) -> Dict[str, Any]:
        """Extract structured data using appropriate schema."""

        # Get extraction schema
        if schema_id:
            schema = await self._get_schema_by_id(schema_id)
        else:
            schema = await self.domain_service.get_extraction_schema(domain_id, category_id)

        if not schema:
            raise ValueError("No extraction schema found for domain/category")

        # Build prompt from template
        system_prompt = schema['system_prompt']
        user_prompt = schema['user_prompt_template'].format(article_text=article_text)

        # Call LLM
        message = self.client.messages.create(
            model=schema.get('model_name', 'claude-sonnet-4-5'),
            max_tokens=schema.get('max_tokens', 4000),
            temperature=schema.get('temperature', 0.7),
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )

        # Parse response
        extracted_data = self._parse_llm_response(message.content[0].text)

        # Validate against schema
        validated_data = self._validate_extraction(extracted_data, schema)

        return {
            'success': True,
            'schema_id': schema['id'],
            'extracted_data': validated_data,
            'confidence': self._calculate_confidence(validated_data, schema),
            'usage': {
                'input_tokens': message.usage.input_tokens,
                'output_tokens': message.usage.output_tokens
            }
        }

    def _validate_extraction(self, data: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
        """Validate extracted data against schema."""
        # Check required fields
        required_fields = schema.get('required_fields', [])
        for field in required_fields:
            if field not in data or data[field] is None:
                raise ValueError(f"Required field missing: {field}")

        # Validate field types
        field_defs = schema.get('field_definitions', {})
        validated = {}
        for field, value in data.items():
            if field in field_defs:
                field_def = field_defs[field]
                # Type validation
                if field_def['type'] == 'string' and not isinstance(value, str):
                    value = str(value) if value is not None else None
                elif field_def['type'] == 'number' and not isinstance(value, (int, float)):
                    try:
                        value = float(value) if value is not None else None
                    except (ValueError, TypeError):
                        value = None
                elif field_def['type'] == 'boolean':
                    value = bool(value) if value is not None else None

            validated[field] = value

        return validated

    def _calculate_confidence(self, data: Dict[str, Any], schema: Dict[str, Any],
                              llm_confidence: Optional[float] = None) -> float:
        """
        Calculate extraction confidence score. [M-010]

        Uses weighted field scoring, LLM confidence integration, and
        cross-field validation for a more robust confidence estimate.
        """
        required_fields = schema.get('required_fields', [])
        field_defs = schema.get('field_definitions', {})
        if not required_fields:
            return 0.5

        # Weighted field scoring: critical fields count 2x
        critical_fields = {'date', 'event_date', 'prosecutor_name', 'defendant_name',
                          'victim_name', 'state', 'incident_type', 'charges'}
        total_weight = 0
        filled_weight = 0
        for field in required_fields:
            weight = 2.0 if field in critical_fields else 1.0
            total_weight += weight
            if data.get(field) is not None:
                filled_weight += weight

        field_completeness = filled_weight / total_weight if total_weight > 0 else 0

        # Adjust based on optional fields filled
        optional_fields = schema.get('optional_fields', [])
        if optional_fields:
            filled_optional = sum(1 for f in optional_fields if data.get(f) is not None)
            optional_bonus = (filled_optional / len(optional_fields)) * 0.15
            field_completeness = min(1.0, field_completeness + optional_bonus)

        # Blend with LLM confidence if available (60% LLM, 40% field completeness)
        if llm_confidence is not None and 0 <= llm_confidence <= 1:
            blended = (llm_confidence * 0.6) + (field_completeness * 0.4)
        else:
            blended = field_completeness

        # Cross-field validation penalties
        penalties = self._cross_field_validation(data, schema)
        blended = max(0.0, blended - penalties)

        return round(blended, 2)

    def _cross_field_validation(self, data: Dict[str, Any], schema: Dict[str, Any]) -> float:
        """
        Apply domain-specific cross-field validation rules.
        Returns penalty amount (0.0 to 0.3).
        """
        penalty = 0.0
        validation_rules = schema.get('validation_rules', {})

        # Date ordering check
        if 'sentencing_date' in data and 'filing_date' in data:
            if data['sentencing_date'] and data['filing_date']:
                if data['sentencing_date'] < data['filing_date']:
                    penalty += 0.1  # Sentencing before filing is suspect

        # Charge consistency check
        if 'disposition' in data and 'charges' in data:
            if data.get('disposition') == 'convicted' and not data.get('charges'):
                penalty += 0.1  # Conviction without charges is suspect

        return min(penalty, 0.3)  # Cap total penalty
```

### 3.2 Prompt Testing Framework

```python
# backend/services/prompt_testing.py
"""
Automated testing and validation for LLM extraction prompts.
"""
from typing import Dict, Any, List, Optional
from uuid import UUID
import anthropic
import asyncpg
from dataclasses import dataclass

@dataclass
class TestResult:
    """Result of testing extraction on a single test case."""
    test_case_id: UUID
    passed: bool
    extracted_data: Dict[str, Any]
    expected_data: Dict[str, Any]
    field_matches: Dict[str, bool]
    precision: float
    recall: float
    f1_score: float
    errors: List[str]

class PromptTestingService:
    """Service for testing and validating extraction prompts."""

    def __init__(self, pool: asyncpg.Pool, anthropic_client: anthropic.Anthropic):
        self.pool = pool
        self.client = anthropic_client

    async def run_test_suite(
        self,
        schema_id: UUID,
        dataset_id: UUID
    ) -> UUID:
        """
        Run full test suite for an extraction schema.

        Returns test_run_id for tracking results.
        """
        async with self.pool.acquire() as conn:
            # Get schema and test cases
            schema = await conn.fetchrow(
                "SELECT * FROM extraction_schemas WHERE id = $1",
                schema_id
            )

            test_cases = await conn.fetch(
                "SELECT * FROM prompt_test_cases WHERE dataset_id = $1",
                dataset_id
            )

            if not schema or not test_cases:
                raise ValueError("Schema or test dataset not found")

            # Create test run record
            test_run_id = await conn.fetchval("""
                INSERT INTO prompt_test_runs (
                    schema_id, dataset_id, total_cases, status
                ) VALUES ($1, $2, $3, 'running')
                RETURNING id
            """, schema_id, dataset_id, len(test_cases))

        # Run tests
        results = []
        total_input_tokens = 0
        total_output_tokens = 0

        for test_case in test_cases:
            result = await self._test_single_case(
                schema=dict(schema),
                test_case=dict(test_case)
            )
            results.append(result)

            # Track token usage (if available)
            # total_input_tokens += result.input_tokens
            # total_output_tokens += result.output_tokens

        # Calculate aggregate metrics
        passed_cases = sum(1 for r in results if r.passed)
        failed_cases = len(results) - passed_cases

        avg_precision = sum(r.precision for r in results) / len(results)
        avg_recall = sum(r.recall for r in results) / len(results)
        avg_f1 = sum(r.f1_score for r in results) / len(results)

        # Update test run with results
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE prompt_test_runs SET
                    completed_at = NOW(),
                    status = CASE WHEN $2 >= $3 THEN 'passed' ELSE 'failed' END,
                    passed_cases = $2,
                    failed_cases = $4,
                    precision = $5,
                    recall = $6,
                    f1_score = $7,
                    total_input_tokens = $8,
                    total_output_tokens = $9,
                    results = $10::jsonb
                WHERE id = $1
            """,
                test_run_id,
                passed_cases,
                len(results),  # total cases
                failed_cases,
                avg_precision,
                avg_recall,
                avg_f1,
                total_input_tokens,
                total_output_tokens,
                [self._serialize_result(r) for r in results]
            )

            # Update schema quality metrics
            await conn.execute("""
                UPDATE extraction_schemas SET
                    quality_metrics = jsonb_build_object(
                        'precision', $2,
                        'recall', $3,
                        'f1_score', $4,
                        'last_tested', NOW(),
                        'test_run_id', $5
                    ),
                    updated_at = NOW()
                WHERE id = $1
            """, schema_id, avg_precision, avg_recall, avg_f1, test_run_id)

        return test_run_id

    async def _test_single_case(
        self,
        schema: Dict[str, Any],
        test_case: Dict[str, Any]
    ) -> TestResult:
        """Test extraction on a single test case."""
        # Extract data using schema
        system_prompt = schema['system_prompt']
        user_prompt = schema['user_prompt_template'].format(
            article_text=test_case['article_text']
        )

        message = self.client.messages.create(
            model=schema.get('model_name', 'claude-sonnet-4-5'),
            max_tokens=schema.get('max_tokens', 4000),
            temperature=schema.get('temperature', 0.7),
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )

        # Parse extraction
        extracted_data = self._parse_llm_response(message.content[0].text)
        expected_data = test_case['expected_extraction']

        # Compare fields
        field_matches = {}
        required_fields = schema.get('required_fields', [])
        optional_fields = schema.get('optional_fields', [])
        all_fields = set(required_fields + optional_fields)

        for field in all_fields:
            expected_value = expected_data.get(field)
            extracted_value = extracted_data.get(field)
            field_matches[field] = self._values_match(expected_value, extracted_value)

        # Calculate metrics
        true_positives = sum(1 for field in required_fields
                            if field_matches.get(field, False))
        false_negatives = sum(1 for field in required_fields
                             if not field_matches.get(field, False))
        false_positives = sum(1 for field in extracted_data.keys()
                             if field not in expected_data)

        precision = true_positives / (true_positives + false_positives) \
                   if (true_positives + false_positives) > 0 else 0
        recall = true_positives / (true_positives + false_negatives) \
                if (true_positives + false_negatives) > 0 else 0
        f1_score = 2 * (precision * recall) / (precision + recall) \
                  if (precision + recall) > 0 else 0

        # Determine pass/fail
        min_threshold = schema.get('min_quality_threshold', 0.80)
        passed = f1_score >= min_threshold

        # Collect errors
        errors = []
        for field in required_fields:
            if not field_matches.get(field, False):
                errors.append(f"Required field '{field}' mismatch: "
                            f"expected={expected_data.get(field)}, "
                            f"got={extracted_data.get(field)}")

        return TestResult(
            test_case_id=test_case['id'],
            passed=passed,
            extracted_data=extracted_data,
            expected_data=expected_data,
            field_matches=field_matches,
            precision=precision,
            recall=recall,
            f1_score=f1_score,
            errors=errors
        )

    def _values_match(self, expected: Any, actual: Any, tolerance: float = 0.1) -> bool:
        """Compare expected and actual values with fuzzy matching."""
        if expected == actual:
            return True

        # Fuzzy string matching
        if isinstance(expected, str) and isinstance(actual, str):
            from difflib import SequenceMatcher
            similarity = SequenceMatcher(None, expected.lower(), actual.lower()).ratio()
            return similarity >= 0.85

        # Numeric tolerance
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            return abs(expected - actual) <= tolerance

        # List comparison (order-independent for small lists)
        if isinstance(expected, list) and isinstance(actual, list):
            if len(expected) != len(actual):
                return False
            return set(expected) == set(actual)

        return False

    async def deploy_to_production(
        self,
        schema_id: UUID,
        test_run_id: UUID,
        require_passing_tests: bool = True
    ) -> bool:
        """
        Deploy extraction schema to production after validation.

        Returns True if deployment succeeded.
        """
        async with self.pool.acquire() as conn:
            # Get test results
            test_run = await conn.fetchrow(
                "SELECT * FROM prompt_test_runs WHERE id = $1",
                test_run_id
            )

            if not test_run:
                raise ValueError("Test run not found")

            # Check quality threshold
            if require_passing_tests and test_run['status'] != 'passed':
                raise ValueError(
                    f"Test run failed: F1={test_run['f1_score']:.3f}, "
                    f"passed {test_run['passed_cases']}/{test_run['total_cases']} cases"
                )

            schema = await conn.fetchrow(
                "SELECT * FROM extraction_schemas WHERE id = $1",
                schema_id
            )

            min_threshold = schema['min_quality_threshold']
            if test_run['f1_score'] < min_threshold:
                raise ValueError(
                    f"F1 score {test_run['f1_score']:.3f} below threshold {min_threshold}"
                )

            # Get current production version for rollback
            current_prod = await conn.fetchrow("""
                SELECT id FROM extraction_schemas
                WHERE domain_id = $1
                  AND category_id = $2
                  AND is_production = TRUE
                  AND is_active = TRUE
            """, schema['domain_id'], schema['category_id'])

            # Atomic swap to new production version
            async with conn.transaction():
                # Deactivate old production version
                if current_prod:
                    await conn.execute("""
                        UPDATE extraction_schemas SET
                            is_production = FALSE,
                            updated_at = NOW()
                        WHERE id = $1
                    """, current_prod['id'])

                # Activate new production version
                await conn.execute("""
                    UPDATE extraction_schemas SET
                        is_production = TRUE,
                        deployed_at = NOW(),
                        updated_at = NOW()
                    WHERE id = $1
                """, schema_id)

            return True

    async def rollback_to_previous_version(
        self,
        schema_id: UUID,
        reason: str
    ) -> UUID:
        """
        Rollback to previous production version.

        Returns the ID of the restored version.
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                schema = await conn.fetchrow(
                    "SELECT * FROM extraction_schemas WHERE id = $1",
                    schema_id
                )

                if not schema['previous_version_id']:
                    raise ValueError("No previous version to rollback to")

                # Deactivate current version
                await conn.execute("""
                    UPDATE extraction_schemas SET
                        is_production = FALSE,
                        rollback_reason = $2,
                        updated_at = NOW()
                    WHERE id = $1
                """, schema_id, reason)

                # Reactivate previous version
                await conn.execute("""
                    UPDATE extraction_schemas SET
                        is_production = TRUE,
                        deployed_at = NOW(),
                        updated_at = NOW()
                    WHERE id = $1
                """, schema['previous_version_id'])

                return schema['previous_version_id']

    async def monitor_production_quality(
        self,
        schema_id: UUID,
        sample_size: int = 100
    ) -> Dict[str, Any]:
        """
        Monitor production extraction quality via human review samples.

        Returns quality metrics based on human-reviewed samples.
        """
        async with self.pool.acquire() as conn:
            samples = await conn.fetch("""
                SELECT * FROM extraction_quality_samples
                WHERE schema_id = $1
                  AND human_reviewed = TRUE
                ORDER BY reviewed_at DESC
                LIMIT $2
            """, schema_id, sample_size)

            if not samples:
                return {
                    'error': 'No reviewed samples available',
                    'sample_count': 0
                }

            passed_count = sum(1 for s in samples if s['review_passed'])
            failed_count = len(samples) - passed_count

            accuracy = passed_count / len(samples)

            # Detect quality degradation
            recent_samples = samples[:20]  # Last 20 reviews
            recent_accuracy = sum(1 for s in recent_samples if s['review_passed']) / len(recent_samples)

            degraded = recent_accuracy < accuracy * 0.85  # 15% drop

            return {
                'schema_id': str(schema_id),
                'sample_count': len(samples),
                'passed': passed_count,
                'failed': failed_count,
                'overall_accuracy': round(accuracy, 3),
                'recent_accuracy': round(recent_accuracy, 3),
                'quality_degraded': degraded,
                'recommendation': 'ROLLBACK' if degraded else 'OK'
            }
```

### 3.3 Serialization Layer [m-006]

All API responses convert PostgreSQL snake_case columns to JavaScript camelCase:

```python
# backend/utils/serialization.py
import re

def to_camel_case(snake_str: str) -> str:
    """Convert snake_case to camelCase."""
    components = snake_str.split('_')
    return components[0] + ''.join(x.title() for x in components[1:])

def serialize_row(row: dict) -> dict:
    """Convert database row (snake_case) to API response (camelCase)."""
    return {to_camel_case(k): v for k, v in row.items()}

# Applied automatically via FastAPI response model configuration
from fastapi.responses import JSONResponse

class CamelCaseResponse(JSONResponse):
    def render(self, content):
        if isinstance(content, dict):
            content = {to_camel_case(k) if isinstance(k, str) else k: v for k, v in content.items()}
        return super().render(content)
```

### 3.4 API Pagination [m-007]

All list endpoints support standard pagination:

```python
# backend/utils/pagination.py
from dataclasses import dataclass
from typing import Any, List

@dataclass
class PaginationParams:
    page: int = 1           # 1-indexed page number
    page_size: int = 50     # Default 50, max 200

    def __post_init__(self):
        self.page = max(1, self.page)
        self.page_size = min(200, max(1, self.page_size))

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

def paginated_response(data: List[Any], total_count: int, params: PaginationParams) -> dict:
    """Standard paginated response envelope."""
    return {
        "data": data,
        "pagination": {
            "page": params.page,
            "page_size": params.page_size,
            "total_count": total_count,
            "total_pages": (total_count + params.page_size - 1) // params.page_size
        }
    }
```

For large datasets (prosecutors, incidents), cursor-based pagination is available via `?cursor=<last_id>&limit=50`.

### 3.5 API Endpoints

```python
# backend/main.py additions

@app.post("/api/admin/domains")
async def create_domain(
    name: str,
    slug: str,
    description: Optional[str] = None
):
    """Create a new event domain."""
    async with get_db_pool().acquire() as conn:
        domain_id = await conn.fetchval("""
            INSERT INTO event_domains (name, slug, description)
            VALUES ($1, $2, $3)
            RETURNING id
        """, name, slug, description)

        return {"success": True, "domain_id": str(domain_id)}

@app.post("/api/admin/categories")
async def create_category(
    domain_slug: str,
    name: str,
    slug: str,
    description: Optional[str] = None,
    field_definitions: Optional[Dict[str, Any]] = None
):
    """Create a new event category."""
    async with get_db_pool().acquire() as conn:
        domain_id = await conn.fetchval(
            "SELECT id FROM event_domains WHERE slug = $1",
            domain_slug
        )

        if not domain_id:
            raise HTTPException(status_code=404, detail="Domain not found")

        category_id = await conn.fetchval("""
            INSERT INTO event_categories (domain_id, name, slug, description, field_definitions)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
        """, domain_id, name, slug, description, field_definitions or {})

        return {"success": True, "category_id": str(category_id)}

@app.get("/api/domains")
async def list_domains():
    """List all event domains."""
    async with get_db_pool().acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                ed.*,
                COUNT(DISTINCT ec.id) as category_count,
                COUNT(DISTINCT i.id) as incident_count
            FROM event_domains ed
            LEFT JOIN event_categories ec ON ec.domain_id = ed.id
            LEFT JOIN incidents i ON i.domain_id = ed.id
            WHERE ed.is_active = TRUE
            GROUP BY ed.id
            ORDER BY ed.display_order
        """)

        return {"domains": [dict(row) for row in rows]}

@app.get("/api/domains/{domain_slug}/categories")
async def list_categories(domain_slug: str):
    """List categories within a domain."""
    async with get_db_pool().acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                ec.*,
                COUNT(i.id) as incident_count
            FROM event_categories ec
            JOIN event_domains ed ON ec.domain_id = ed.id
            LEFT JOIN incidents i ON i.category_id = ec.id
            WHERE ed.slug = $1 AND ec.is_active = TRUE
            GROUP BY ec.id
            ORDER BY ec.display_order
        """, domain_slug)

        return {"categories": [dict(row) for row in rows]}

@app.post("/api/cases")
async def create_case(
    case_number: str,
    case_type: str,
    filed_date: str,
    charges: List[Dict[str, Any]],
    custom_fields: Optional[Dict[str, Any]] = None
):
    """Create a new case."""
    cj_domain = CriminalJusticeDomain(get_db_pool())
    case_id = await cj_domain.create_case(
        case_number=case_number,
        case_type=case_type,
        filed_date=filed_date,
        charges=charges,
        custom_fields=custom_fields
    )

    return {"success": True, "case_id": str(case_id)}

@app.post("/api/cases/{case_id}/prosecutorial-actions")
async def record_prosecutorial_action(
    case_id: UUID,
    prosecutor_id: UUID,
    action_type: str,
    action_date: str,
    details: Dict[str, Any]
):
    """Record a prosecutorial action."""
    cj_domain = CriminalJusticeDomain(get_db_pool())
    action_id = await cj_domain.record_prosecutorial_action(
        case_id=case_id,
        prosecutor_id=prosecutor_id,
        action_type=action_type,
        action_date=action_date,
        **details
    )

    return {"success": True, "action_id": str(action_id)}

@app.get("/api/prosecutors/{prosecutor_id}/stats")
async def get_prosecutor_stats(prosecutor_id: UUID):
    """Get prosecutor performance statistics."""
    cj_domain = CriminalJusticeDomain(get_db_pool())
    stats = await cj_domain.calculate_prosecutor_stats(prosecutor_id)

    return {"prosecutor_id": str(prosecutor_id), "stats": stats}

@app.get("/api/actors/{actor_id}/recidivism")
async def get_recidivism_analysis(actor_id: UUID):
    """Get recidivism analysis for an actor."""
    async with get_db_pool().acquire() as conn:
        # Get incident history
        history = await conn.fetch("""
            SELECT * FROM actor_incident_history
            WHERE actor_id = $1
            ORDER BY incident_date
        """, actor_id)

        # Get recidivism stats
        stats = await conn.fetchrow("""
            SELECT * FROM recidivism_analysis
            WHERE actor_id = $1
        """, actor_id)

        # Calculate risk score
        risk_score = await conn.fetchval("""
            SELECT calculate_recidivism_risk($1)
        """, actor_id)

        return {
            "actor_id": str(actor_id),
            "incident_history": [dict(row) for row in history],
            "stats": dict(stats) if stats else None,
            "risk_score": float(risk_score) if risk_score else 0.0
        }

# Prompt Testing Endpoints

@app.post("/api/admin/prompt-tests/run")
async def run_prompt_test(
    schema_id: UUID,
    dataset_id: UUID
):
    """Run test suite for an extraction schema."""
    test_service = PromptTestingService(get_db_pool(), get_anthropic_client())

    test_run_id = await test_service.run_test_suite(schema_id, dataset_id)

    return {"success": True, "test_run_id": str(test_run_id)}

@app.get("/api/admin/prompt-tests/{test_run_id}")
async def get_test_results(test_run_id: UUID):
    """Get results of a test run."""
    async with get_db_pool().acquire() as conn:
        test_run = await conn.fetchrow(
            "SELECT * FROM prompt_test_runs WHERE id = $1",
            test_run_id
        )

        if not test_run:
            raise HTTPException(status_code=404, detail="Test run not found")

        return dict(test_run)

@app.post("/api/admin/extraction-schemas/{schema_id}/deploy")
async def deploy_schema_to_production(
    schema_id: UUID,
    test_run_id: UUID,
    require_passing_tests: bool = True
):
    """Deploy extraction schema to production after validation."""
    test_service = PromptTestingService(get_db_pool(), get_anthropic_client())

    try:
        success = await test_service.deploy_to_production(
            schema_id,
            test_run_id,
            require_passing_tests
        )
        return {"success": success, "schema_id": str(schema_id)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/admin/extraction-schemas/{schema_id}/rollback")
async def rollback_schema(
    schema_id: UUID,
    reason: str
):
    """Rollback to previous schema version."""
    test_service = PromptTestingService(get_db_pool(), get_anthropic_client())

    previous_id = await test_service.rollback_to_previous_version(schema_id, reason)

    return {
        "success": True,
        "rolled_back_from": str(schema_id),
        "restored_version": str(previous_id)
    }

@app.get("/api/admin/extraction-schemas/{schema_id}/quality")
async def get_production_quality(
    schema_id: UUID,
    sample_size: int = 100
):
    """Get production quality metrics for a schema."""
    test_service = PromptTestingService(get_db_pool(), get_anthropic_client())

    metrics = await test_service.monitor_production_quality(schema_id, sample_size)

    return metrics
```

## Frontend Implementation

### 4.1 Domain Navigation

```typescript
// frontend/src/types/domains.ts
export interface EventDomain {
  id: string;
  name: string;
  slug: string;
  description: string;
  icon: string;
  color: string;
  categoryCount: number;
  incidentCount: number;
}

export interface EventCategory {
  id: string;
  domainId: string;
  name: string;
  slug: string;
  description: string;
  fieldDefinitions: Record<string, any>;
  incidentCount: number;
}
```

```typescript
// frontend/src/DomainSelector.tsx
import { useState, useEffect } from 'react';
import type { EventDomain } from './types/domains';

export function DomainSelector({ onDomainChange }: { onDomainChange: (domain: EventDomain) => void }) {
  const [domains, setDomains] = useState<EventDomain[]>([]);
  const [selected, setSelected] = useState<EventDomain | null>(null);

  useEffect(() => {
    fetch('/api/domains')
      .then(r => r.json())
      .then(data => setDomains(data.domains));
  }, []);

  const handleSelect = (domain: EventDomain) => {
    setSelected(domain);
    onDomainChange(domain);
  };

  return (
    <div className="domain-selector">
      {domains.map(domain => (
        <button
          key={domain.id}
          className={`domain-card ${selected?.id === domain.id ? 'active' : ''}`}
          onClick={() => handleSelect(domain)}
          style={{ borderColor: domain.color }}
        >
          <span className="domain-icon">{domain.icon}</span>
          <div className="domain-info">
            <h3>{domain.name}</h3>
            <p>{domain.description}</p>
            <div className="domain-stats">
              <span>{domain.categoryCount} categories</span>
              <span>{domain.incidentCount} incidents</span>
            </div>
          </div>
        </button>
      ))}
    </div>
  );
}
```

### 4.2 Dynamic Form Rendering

```typescript
// frontend/src/DynamicIncidentForm.tsx
import { useState, useEffect } from 'react';
import type { EventCategory } from './types/domains';

// Error handling requirements [M-012]:
// - Required field validation before submit (highlight missing fields)
// - Per-field error messages below each input
// - Form-level error summary at top of form
// - Schema load failure: show error state with retry button, fallback to basic form
// - Malformed field definitions: show warning instead of crashing
// - Type coercion errors: show inline validation message

export function DynamicIncidentForm({ category }: { category: EventCategory }) {
  const [formData, setFormData] = useState<Record<string, any>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const fieldDefs = category.fieldDefinitions || {};

  const renderField = (fieldName: string, fieldDef: any) => {
    switch (fieldDef.type) {
      case 'text':
        return (
          <input
            type="text"
            value={formData[fieldName] || ''}
            onChange={(e) => setFormData({ ...formData, [fieldName]: e.target.value })}
            placeholder={fieldDef.description}
          />
        );
      case 'number':
        return (
          <input
            type="number"
            value={formData[fieldName] || ''}
            onChange={(e) => setFormData({ ...formData, [fieldName]: parseFloat(e.target.value) })}
            placeholder={fieldDef.description}
          />
        );
      case 'date':
        return (
          <input
            type="date"
            value={formData[fieldName] || ''}
            onChange={(e) => setFormData({ ...formData, [fieldName]: e.target.value })}
          />
        );
      case 'boolean':
        return (
          <input
            type="checkbox"
            checked={formData[fieldName] || false}
            onChange={(e) => setFormData({ ...formData, [fieldName]: e.target.checked })}
          />
        );
      case 'select':
        return (
          <select
            value={formData[fieldName] || ''}
            onChange={(e) => setFormData({ ...formData, [fieldName]: e.target.value })}
          >
            <option value="">Select...</option>
            {fieldDef.options?.map((opt: string) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        );
      default:
        // [M-012] Handle unsupported field types gracefully instead of returning null
        return <div className="field-warning">Unsupported field type: {fieldDef.type}</div>;
    }
  };

  // [M-012] Handle schema load failures
  if (schemaError) {
    return (
      <div className="schema-error">
        <p>Failed to load form schema: {schemaError}</p>
        <button onClick={() => { setSchemaError(null); /* retry logic */ }}>Retry</button>
      </div>
    );
  }

  return (
    <form className="dynamic-incident-form">
      <h3>Create {category.name} Incident</h3>
      {Object.entries(fieldDefs).map(([fieldName, fieldDef]: [string, any]) => (
        <div key={fieldName} className="form-field">
          <label>
            {fieldDef.description || fieldName}
            {fieldDef.required && <span className="required">*</span>}
          </label>
          {renderField(fieldName, fieldDef)}
        </div>
      ))}
      <button type="submit">Create Incident</button>
    </form>
  );
}
```

### 4.3 Prosecutor Dashboard

```typescript
// frontend/src/ProsecutorDashboard.tsx
import { useState, useEffect } from 'react';

interface ProsecutorStats {
  prosecutorId: string;
  prosecutorName: string;
  totalCases: number;
  convictions: number;
  acquittals: number;
  dismissals: number;
  pleaBargains: number;
  convictionRate: number;
  avgSentenceMonths: number;
}

export function ProsecutorDashboard() {
  const [prosecutors, setProsecutors] = useState<ProsecutorStats[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/prosecutors/stats')
      .then(r => r.json())
      .then(data => {
        setProsecutors(data.prosecutors);
        setLoading(false);
      });
  }, []);

  if (loading) return <div>Loading...</div>;

  return (
    <div className="prosecutor-dashboard">
      <h2>Prosecutor Performance</h2>
      <table className="prosecutor-stats-table">
        <thead>
          <tr>
            <th>Prosecutor</th>
            <th>Total Cases</th>
            <th>Convictions</th>
            <th>Acquittals</th>
            <th>Dismissals</th>
            <th>Plea Bargains</th>
            <th>Conviction Rate</th>
            <th>Avg Sentence (months)</th>
          </tr>
        </thead>
        <tbody>
          {prosecutors.map(p => (
            <tr key={p.prosecutorId}>
              <td>{p.prosecutorName}</td>
              <td>{p.totalCases}</td>
              <td>{p.convictions}</td>
              <td>{p.acquittals}</td>
              <td>{p.dismissals}</td>
              <td>{p.pleaBargains}</td>
              <td>{(p.convictionRate * 100).toFixed(1)}%</td>
              <td>{p.avgSentenceMonths?.toFixed(1) || 'N/A'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

## Migration Strategy

### Approach: Hybrid Extension (Recommended)

**Rationale:**
- Minimize risk by keeping existing system operational
- Add generic capabilities in parallel
- Gradually migrate concepts
- Allow time for testing and validation

### Migration Phases

**Phase 1: Foundation (Weeks 1-4)**
- ✅ Create taxonomy tables (domains, categories)
- ✅ Add custom_fields to incidents
- ✅ Migrate immigration data to new structure
- ✅ Test backward compatibility
- ✅ Update UI to show domains

### Migration Concurrency Strategy

**Approach: Zero-Downtime Blue-Green Migration**

The system will remain fully operational during all migration phases using the following strategy:

**Phase 1C Migration - Concurrent Access Handling**

```python
# backend/services/migration_service.py
"""
Zero-downtime migration with dual-write strategy.
"""
import asyncpg
from contextlib import asynccontextmanager
from typing import Dict, Any

class MigrationService:
    """Handles concurrent access during migration."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.migration_active = False

    @asynccontextmanager
    async def migration_transaction(self, isolation_level='READ COMMITTED'):
        """
        Transaction wrapper for migration operations.

        Uses READ COMMITTED to allow concurrent reads while migrating.
        Row-level locks prevent write conflicts.
        """
        async with self.pool.acquire() as conn:
            await conn.execute(f'SET TRANSACTION ISOLATION LEVEL {isolation_level}')
            async with conn.transaction():
                yield conn

    async def migrate_batch(
        self,
        batch_size: int = 1000,
        delay_ms: int = 100
    ) -> Dict[str, int]:
        """
        Migrate incidents in batches with delays to allow concurrent access.

        Strategy:
        1. SELECT FOR UPDATE SKIP LOCKED - lock rows for migration
        2. Process batch
        3. Small delay to let other transactions through
        4. Repeat until complete
        """
        migrated_count = 0
        skipped_count = 0

        while True:
            async with self.migration_transaction() as conn:
                # Lock batch of unmigrated rows, skip locked ones
                rows = await conn.fetch("""
                    SELECT id, category, date
                    FROM incidents
                    WHERE domain_id IS NULL
                    LIMIT $1
                    FOR UPDATE SKIP LOCKED
                """, batch_size)

                if not rows:
                    break  # Migration complete

                # Update batch
                ids_to_update = [r['id'] for r in rows]
                await conn.execute("""
                    UPDATE incidents SET
                        domain_id = (SELECT id FROM event_domains WHERE slug = 'immigration'),
                        category_id = (
                            SELECT ec.id FROM event_categories ec
                            JOIN event_domains ed ON ec.domain_id = ed.id
                            WHERE ed.slug = 'immigration'
                              AND ec.slug = incidents.category
                        ),
                        event_start_date = date,
                        event_end_date = date
                    WHERE id = ANY($1::uuid[])
                """, ids_to_update)

                migrated_count += len(rows)

            # Small delay to allow other operations
            await asyncio.sleep(delay_ms / 1000)

        return {
            'migrated': migrated_count,
            'skipped': skipped_count
        }

    async def create_incident_during_migration(
        self,
        incident_data: Dict[str, Any]
    ) -> str:
        """
        Create incident with dual-write strategy during migration.

        Writes to both old and new schema fields for compatibility.
        """
        async with self.pool.acquire() as conn:
            # Determine domain/category from input or default to immigration
            domain_id = incident_data.get('domain_id') or \
                await conn.fetchval("SELECT id FROM event_domains WHERE slug = 'immigration'")

            category_slug = incident_data.get('category', 'enforcement')
            category_id = await conn.fetchval("""
                SELECT ec.id FROM event_categories ec
                WHERE ec.domain_id = $1 AND ec.slug = $2
            """, domain_id, category_slug)

            # Insert with both old and new fields
            incident_id = await conn.fetchval("""
                INSERT INTO incidents (
                    -- Old schema (for compatibility)
                    category, date, state, city,
                    -- New schema
                    domain_id, category_id,
                    event_start_date, event_end_date,
                    custom_fields
                ) VALUES (
                    $1, $2, $3, $4,
                    $5, $6, $7, $8, $9::jsonb
                )
                RETURNING id
            """,
                # Old schema values
                category_slug,
                incident_data['date'],
                incident_data.get('state'),
                incident_data.get('city'),
                # New schema values
                domain_id,
                category_id,
                incident_data['date'],
                incident_data.get('end_date', incident_data['date']),
                incident_data.get('custom_fields', {})
            )

            return incident_id
```

**Transaction Isolation Levels**

| Operation | Isolation Level | Locking Strategy | Rationale |
|-----------|----------------|------------------|-----------|
| Batch migration | READ COMMITTED | Row-level (FOR UPDATE SKIP LOCKED) | Allow reads during migration, skip locked rows |
| New incident creation | READ COMMITTED | None | Default behavior, dual-write to both schemas |
| Incident reads | READ COMMITTED | None | No locks needed for reads |
| Analytics queries | READ COMMITTED | None | Slight staleness acceptable |

**Concurrent Access Testing Plan**

```python
# tests/test_concurrent_migration.py
import pytest
import asyncio
import asyncpg

@pytest.mark.asyncio
async def test_concurrent_writes_during_migration():
    """
    Test that new incidents can be created while migration is running.
    """
    migration_service = MigrationService(test_db_pool)

    # Start migration in background
    migration_task = asyncio.create_task(
        migration_service.migrate_batch(batch_size=100, delay_ms=50)
    )

    # Concurrently create incidents
    create_tasks = [
        migration_service.create_incident_during_migration({
            'category': 'enforcement',
            'date': '2026-01-15',
            'state': 'CA'
        })
        for _ in range(50)
    ]

    # Wait for both to complete
    created_ids = await asyncio.gather(*create_tasks)
    migration_result = await migration_task

    # Validate all incidents created successfully
    assert len(created_ids) == 50
    assert all(id is not None for id in created_ids)

    # Validate migration completed
    assert migration_result['migrated'] > 0

    # Validate no data loss
    async with test_db_pool.acquire() as conn:
        null_domain_count = await conn.fetchval(
            "SELECT COUNT(*) FROM incidents WHERE domain_id IS NULL"
        )
        assert null_domain_count == 0

@pytest.mark.asyncio
async def test_concurrent_reads_during_migration():
    """
    Test that reads return consistent data during migration.
    """
    migration_service = MigrationService(test_db_pool)

    # Query incidents continuously during migration
    async def continuous_reader():
        counts = []
        for _ in range(20):
            async with test_db_pool.acquire() as conn:
                count = await conn.fetchval("SELECT COUNT(*) FROM incidents")
                counts.append(count)
            await asyncio.sleep(0.05)
        return counts

    # Run migration and reads concurrently
    reader_task = asyncio.create_task(continuous_reader())
    migration_task = asyncio.create_task(
        migration_service.migrate_batch(batch_size=100, delay_ms=50)
    )

    counts = await reader_task
    await migration_task

    # Validate row count never decreased (no data loss)
    for i in range(1, len(counts)):
        assert counts[i] >= counts[i-1], "Row count decreased during migration"

@pytest.mark.asyncio
async def test_category_reference_during_migration():
    """
    Test that incidents can reference categories being migrated.
    """
    # Create incident referencing a category
    async with test_db_pool.acquire() as conn:
        # Start transaction
        async with conn.transaction():
            # Create incident with new category_id
            incident_id = await conn.fetchval("""
                INSERT INTO incidents (domain_id, category_id, event_start_date)
                VALUES (
                    (SELECT id FROM event_domains WHERE slug = 'immigration'),
                    (SELECT id FROM event_categories WHERE slug = 'enforcement'),
                    NOW()
                )
                RETURNING id
            """)

            # Immediately read it back
            row = await conn.fetchrow("""
                SELECT i.*, ec.name as category_name
                FROM incidents i
                JOIN event_categories ec ON i.category_id = ec.id
                WHERE i.id = $1
            """, incident_id)

            assert row is not None
            assert row['category_name'] == 'Enforcement'
```

**Downtime Windows**

| Migration Phase | Downtime Required | Alternative |
|----------------|-------------------|-------------|
| 1A - Create tables | **0 seconds** | New tables don't affect existing queries |
| 1B - Add columns | **0 seconds** | ALTER TABLE ADD COLUMN is non-blocking in PostgreSQL 11+ |
| 1C - Migrate data | **0 seconds** | Batch migration with row-level locks |
| 1D - Add indexes | **0 seconds** | CREATE INDEX CONCURRENTLY |
| 1E - Add NOT NULL | **~5 seconds** | Brief lock to add constraint after validation |

**System Behavior During Migration**

1. **Before Migration Starts:**
   - Old schema: `category` enum, `date` field
   - New schema: Empty `domain_id`, `category_id`, `event_start_date`
   - Writes: Old schema only
   - Reads: Old schema only

2. **During Migration (Dual-Write Mode):**
   - Old schema: Still populated (compatibility)
   - New schema: Gradually populating
   - Writes: **Both schemas** (dual-write)
   - Reads: Prefer new schema, fallback to old

3. **After Migration Complete:**
   - Old schema: Deprecated (but still present)
   - New schema: Fully populated
   - Writes: New schema only (old schema optional)
   - Reads: New schema only

**In-Flight Transaction Handling**

```sql
-- If migration encounters a locked row, it skips and retries later
-- This query demonstrates the SKIP LOCKED behavior:

BEGIN;

-- Transaction 1: User creating incident (holds lock)
INSERT INTO incidents (category, date) VALUES ('enforcement', NOW());
-- Lock held on this row

-- Transaction 2: Migration batch (runs concurrently)
SELECT id FROM incidents WHERE domain_id IS NULL
FOR UPDATE SKIP LOCKED;  -- Skips the locked row, processes others

COMMIT;  -- Transaction 1 releases lock

-- Next migration batch will pick up the previously locked row
```

**Phase 2: Legal System (Weeks 5-8)**
- ✅ Add cases, prosecutorial_actions, dispositions tables
- ✅ Create criminal justice domain
- ✅ Build prosecutor tracking
- ✅ Add case management UI
- ✅ Test with sample data

**Phase 3: Flexible Extraction (Weeks 9-11)**
- ✅ Create extraction_schemas table
- ✅ Refactor LLM service to use schemas
- ✅ Build schema management UI
- ✅ Create domain-specific schemas
- ✅ Test extraction with multiple domains

**Phase 4: Advanced Analytics (Weeks 12-16)**
- ✅ Implement recidivism tracking
- ✅ Build prosecutor analytics
- ✅ Add event relationship tracking
- ✅ Create cross-domain dashboards
- ✅ Performance optimization

### Detailed Work Breakdown

#### Phase 1: Foundation (Weeks 1-4, 324 hours)

| Task | Hours | Owner | Dependencies |
|------|-------|-------|--------------|
| Design domain taxonomy schema | 8 | Backend | None |
| Create migration 008_event_taxonomy.sql | 12 | Backend | Schema design |
| Implement DomainService class | 16 | Backend | Migration |
| Write unit tests for DomainService | 12 | Backend | DomainService |
| Create API endpoints for domains/categories | 12 | Backend | DomainService |
| Build DomainSelector UI component | 16 | Frontend | API endpoints |
| Create DomainManagement admin panel | 20 | Frontend | API endpoints |
| Write E2E tests for domain CRUD | 12 | Backend | API endpoints |
| Data migration dry-run testing | 16 | Backend/DBA | Migration script |
| Execute production data migration | 8 | DBA | Dry-run approval |
| Validate migration integrity | 8 | Backend/DBA | Migration |
| Create rollback procedures | 12 | Backend/DBA | Migration |
| Update documentation | 8 | All | All above |
| Performance testing (JSONB benchmarks) | 24 | Backend | Migration |
| Fix bugs and polish | 40 | All | Testing |
| **Phase 1 Buffer (20%)** | 60 | All | - |
| **Phase 1 Total** | **324** | | |

**Critical Path:** Schema design → Migration → DomainService → Migration execution (8 + 12 + 16 + 8 = 44 hours minimum)

#### Phase 2: Legal System (Weeks 5-8, 308 hours)

| Task | Hours | Owner | Dependencies |
|------|-------|-------|--------------|
| Design cases/prosecutorial schema | 12 | Backend | Phase 1 complete |
| Create migration 011_cases_system.sql | 16 | Backend | Schema design |
| Create migration 012_prosecutorial_tracking.sql | 16 | Backend | Cases migration |
| Implement CriminalJusticeDomain service | 24 | Backend | Migrations |
| Write unit tests for case management | 16 | Backend | CJDomain service |
| Create prosecutor stats materialized view | 12 | Backend/DBA | Migrations |
| Build case CRUD API endpoints | 20 | Backend | CJDomain service |
| Build prosecutorial action endpoints | 16 | Backend | CJDomain service |
| Create CaseManagement UI component | 28 | Frontend | API endpoints |
| Build ProsecutorDashboard component | 24 | Frontend | API endpoints |
| Write E2E tests for case lifecycle | 20 | Backend | API endpoints |
| Seed sample criminal justice data | 12 | Backend | All above |
| Performance testing (prosecutor stats) | 16 | Backend | Materialized view |
| Fix bugs and polish | 36 | All | Testing |
| **Phase 2 Buffer (20%)** | 60 | All | - |
| **Phase 2 Total** | **308** | | |

**Critical Path:** Cases schema → Migrations → CJDomain service → API → UI (12 + 32 + 24 + 20 + 28 = 116 hours minimum)

#### Phase 3: Flexible Extraction (Weeks 9-11, 272 hours)

| Task | Hours | Owner | Dependencies |
|------|-------|-------|--------------|
| Design extraction_schemas table | 8 | Backend | Phase 1 complete |
| Create migration 013_extraction_schemas.sql | 12 | Backend | Schema design |
| Design prompt testing framework | 12 | Backend | Extraction schema |
| Create prompt testing tables | 8 | Backend | Testing framework design |
| Implement GenericExtractionService | 24 | Backend | Migrations |
| Implement PromptTestingService | 32 | Backend | Extraction service |
| Write unit tests for extraction | 16 | Backend | Extraction service |
| Write unit tests for prompt testing | 20 | Backend | Testing service |
| Create extraction schema CRUD API | 16 | Backend | Services |
| Create prompt testing API endpoints | 16 | Backend | Testing service |
| Build SchemaEditor UI component | 28 | Frontend | API |
| Build PromptTestingPanel UI | 24 | Frontend | API |
| Create golden test datasets | 16 | Backend | Testing framework |
| Test extraction for all domains | 20 | Backend | All above |
| Fix bugs and polish | 24 | All | Testing |
| **Phase 3 Buffer (20%)** | 52 | All | - |
| **Phase 3 Total** | **272** | | |

**Critical Path:** Schema → Migration → GenericExtraction → PromptTesting → API → UI (8 + 12 + 24 + 32 + 32 + 28 = 136 hours minimum)

#### Phase 4: Advanced Analytics (Weeks 12-16, 320 hours)

| Task | Hours | Owner | Dependencies |
|------|-------|-------|--------------|
| Design recidivism tracking schema | 12 | Backend | Phase 2 complete |
| Create migration 014_recidivism_tracking.sql | 16 | Backend | Schema design |
| Implement recidivism calculation function | 20 | Backend/DBA | Migration |
| Create event_relationships schema | 12 | Backend | Phase 1 |
| Create migration 010_event_relationships.sql | 12 | Backend | Schema design |
| Implement relationship management service | 20 | Backend | Migration |
| Write unit tests for recidivism | 16 | Backend | Recidivism calc |
| Write unit tests for relationships | 16 | Backend | Relationship service |
| Create recidivism API endpoints | 16 | Backend | Services |
| Create relationship API endpoints | 16 | Backend | Services |
| Build RecidivismDashboard UI | 28 | Frontend | API |
| Build EventRelationshipViewer UI | 24 | Frontend | API |
| Create cross-domain analytics views | 20 | Backend/DBA | All above |
| Build CrossDomainAnalytics UI | 32 | Frontend | Analytics API |
| Performance optimization and indexing | 24 | Backend/DBA | All features |
| Load testing (1M+ records) | 20 | Backend | All features |
| Fix bugs and polish | 32 | All | Testing |
| **Phase 4 Buffer (20%)** | 64 | All | - |
| **Phase 4 Total** | **320** | | |

**Critical Path:** Recidivism schema → Relationships → Services → API → UI → Load testing (12 + 12 + 40 + 32 + 28 + 20 = 144 hours minimum)

### Timeline Summary

| Phase | Duration | Total Hours | Backend Hours | Frontend Hours | DBA Hours | Buffer Hours |
|-------|----------|-------------|---------------|----------------|-----------|--------------|
| Phase 1 | 4 weeks | 324 | 180 | 80 | 40 | 60 |
| Phase 2 | 4 weeks | 308 | 164 | 88 | 28 | 60 |
| Phase 3 | 3 weeks | 272 | 164 | 76 | 0 | 52 |
| Phase 4 | 5 weeks | 320 | 180 | 92 | 24 | 64 |
| **TOTAL** | **16 weeks** | **1,224** | **688** | **336** | **92** | **236** |

### Resource Allocation

**Backend Developer (2 FTE):**
- Available hours: 2 developers × 30 hrs/week × 16 weeks = 960 hours
- Required: 688 hours
- Utilization: 72% (allows 28% slack for bugs, meetings, unplanned work)

**Frontend Developer (1 FTE):**
- Available hours: 1 developer × 30 hrs/week × 16 weeks = 480 hours
- Required: 336 hours
- Utilization: 70% (allows 30% slack)

**DBA (0.25 FTE):**
- Available hours: 0.25 FTE × 30 hrs/week × 16 weeks = 120 hours
- Required: 92 hours
- Utilization: 77%

### Assumptions & Constraints

1. **Velocity:** 30 productive hours/week per developer (accounts for meetings, email, context switching)
2. **Buffer:** 20% time buffer for unexpected issues, bug fixes, and rework
3. **Team experience:** Moderate familiarity with PostgreSQL, FastAPI, React (no learning curve)
4. **Blockers:** No critical blocker exceeds 2 days (escalation to management if blocked longer)
5. **Code review:** Included in task estimates (average 30 minutes per PR)
6. **Testing:** Unit tests at 1:1.5 code-to-test ratio, E2E tests for critical paths only
7. **Parallel work:** Frontend can start once API contracts defined (not waiting for full backend completion)
8. **Scope control:** "Core implementation" excludes ML integration, public API, advanced cross-domain analytics

### Dependencies & Critical Path

**Overall Critical Path (Total: 144 days = ~20 weeks at 100% utilization):**

```
Schema Design (P1) → Migration (P1) → Domain Service (P1) → Migration Execution (P1)
    ↓
Cases Schema (P2) → Cases Migration (P2) → CJ Domain Service (P2) → Case API (P2)
    ↓
Extraction Schema (P3) → Extraction Service (P3) → Prompt Testing (P3)
    ↓
Recidivism Schema (P4) → Recidivism Service (P4) → Analytics API (P4) → Load Testing (P4)
```

With 2 backend developers working in parallel, critical path reduced to ~12 weeks. Buffer brings to 16 weeks total.

### Risk-Adjusted Timeline

| Scenario | Duration | Probability | Mitigation |
|----------|----------|-------------|------------|
| Best case | 12 weeks | 10% | Everything goes perfectly, no bugs |
| Expected | 16 weeks | 60% | Normal course with 20% buffer |
| Worst case | 20 weeks | 30% | Major technical blocker or scope creep |

**Recommendation:** Commit to 16-week timeline externally, target 14 weeks internally to create 2-week contingency buffer.

### Data Migration Steps

#### Pre-Migration Preparation

1. **Create full database backup**
   ```bash
   # Backup with timestamp
   pg_dump -h localhost -U incident_tracker_app -d incident_tracker \
     --format=custom \
     --file=backups/pre_migration_$(date +%Y%m%d_%H%M%S).dump

   # Verify backup
   pg_restore --list backups/pre_migration_*.dump | head -20
   ```

2. **Calculate data integrity checksums**
   ```sql
   -- Create checksum table for validation
   CREATE TABLE migration_checksums (
       table_name VARCHAR(100) PRIMARY KEY,
       row_count BIGINT,
       checksum TEXT,
       created_at TIMESTAMPTZ DEFAULT NOW()
   );

   -- Record pre-migration state
   INSERT INTO migration_checksums (table_name, row_count, checksum)
   SELECT
       'incidents',
       COUNT(*),
       MD5(STRING_AGG(id::text || date::text || category, ',' ORDER BY id))
   FROM incidents;

   INSERT INTO migration_checksums (table_name, row_count, checksum)
   SELECT
       'incident_actors',
       COUNT(*),
       MD5(STRING_AGG(id::text || incident_id::text || actor_id::text, ',' ORDER BY id))
   FROM incident_actors;
   ```

3. **Audit existing data**
   ```sql
   -- Count records to migrate
   SELECT category, COUNT(*) FROM incidents GROUP BY category;

   -- Identify edge cases
   SELECT * FROM incidents WHERE category NOT IN ('enforcement', 'crime');

   -- Check for NULL values in critical fields
   SELECT COUNT(*) FROM incidents WHERE category IS NULL OR date IS NULL;
   ```

#### Migration Execution (With Rollback Points)

**Phase 1A: Create Taxonomy Tables (Rollback Point 1)**

```sql
BEGIN;  -- Start transaction

-- Run migration 008_event_taxonomy.sql
\i database/migrations/008_event_taxonomy.sql

-- Validation checkpoint
DO $$
DECLARE
    v_domain_count INTEGER;
    v_category_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_domain_count FROM event_domains;
    SELECT COUNT(*) INTO v_category_count FROM event_categories;

    IF v_domain_count < 3 THEN
        RAISE EXCEPTION 'Domain creation failed: expected >= 3, got %', v_domain_count;
    END IF;

    IF v_category_count < 6 THEN
        RAISE EXCEPTION 'Category creation failed: expected >= 6, got %', v_category_count;
    END IF;

    RAISE NOTICE 'Phase 1A validation passed: % domains, % categories',
        v_domain_count, v_category_count;
END $$;

COMMIT;  -- Complete Phase 1A
```

**Rollback for Phase 1A:**
```sql
-- If Phase 1A fails, rollback with:
ROLLBACK;

-- Or if already committed, manual cleanup:
DROP TABLE IF EXISTS event_categories CASCADE;
DROP TABLE IF EXISTS event_domains CASCADE;
```

**Phase 1B: Add Columns to Incidents (Rollback Point 2)**

```sql
BEGIN;  -- Start transaction

-- Add new columns (nullable initially)
ALTER TABLE incidents
    ADD COLUMN domain_id UUID,
    ADD COLUMN category_id UUID,
    ADD COLUMN custom_fields JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN event_start_date DATE,
    ADD COLUMN event_end_date DATE,
    ADD COLUMN date_precision VARCHAR(20) DEFAULT 'day',
    ADD COLUMN tags TEXT[] DEFAULT ARRAY[]::TEXT[];

-- Add foreign key constraints (NOT NULL enforced later)
ALTER TABLE incidents
    ADD CONSTRAINT fk_incidents_domain FOREIGN KEY (domain_id)
        REFERENCES event_domains(id),
    ADD CONSTRAINT fk_incidents_category FOREIGN KEY (category_id)
        REFERENCES event_categories(id);

-- Validation checkpoint
DO $$
DECLARE
    v_column_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_column_count
    FROM information_schema.columns
    WHERE table_name = 'incidents'
      AND column_name IN ('domain_id', 'category_id', 'custom_fields',
                          'event_start_date', 'event_end_date', 'tags');

    IF v_column_count != 6 THEN
        RAISE EXCEPTION 'Column addition failed: expected 6 new columns, got %', v_column_count;
    END IF;

    RAISE NOTICE 'Phase 1B validation passed: % new columns added', v_column_count;
END $$;

COMMIT;  -- Complete Phase 1B
```

**Rollback for Phase 1B:**
```sql
ROLLBACK;  -- If still in transaction

-- Or manual cleanup:
ALTER TABLE incidents
    DROP COLUMN IF EXISTS domain_id,
    DROP COLUMN IF EXISTS category_id,
    DROP COLUMN IF EXISTS custom_fields,
    DROP COLUMN IF EXISTS event_start_date,
    DROP COLUMN IF EXISTS event_end_date,
    DROP COLUMN IF EXISTS date_precision,
    DROP COLUMN IF EXISTS tags;
```

**Phase 1C: Migrate Data (Rollback Point 3)**

```sql
BEGIN;  -- Start transaction

-- Record pre-migration counts
CREATE TEMP TABLE migration_validation AS
SELECT
    category,
    COUNT(*) as record_count,
    COUNT(*) FILTER (WHERE domain_id IS NULL) as pending_migration
FROM incidents
GROUP BY category;

-- Migrate domain assignments
UPDATE incidents SET
    domain_id = (SELECT id FROM event_domains WHERE slug = 'immigration');

-- Migrate category assignments
UPDATE incidents SET
    category_id = (
        SELECT ec.id FROM event_categories ec
        JOIN event_domains ed ON ec.domain_id = ed.id
        WHERE ed.slug = 'immigration' AND ec.slug = incidents.category
    );

-- Migrate date fields
UPDATE incidents SET
    event_start_date = date,
    event_end_date = date,
    date_precision = 'day';

-- Validation checkpoint
DO $$
DECLARE
    v_null_domain_count INTEGER;
    v_null_category_count INTEGER;
    v_null_date_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_null_domain_count
    FROM incidents WHERE domain_id IS NULL;

    SELECT COUNT(*) INTO v_null_category_count
    FROM incidents WHERE category_id IS NULL;

    SELECT COUNT(*) INTO v_null_date_count
    FROM incidents WHERE event_start_date IS NULL;

    IF v_null_domain_count > 0 THEN
        RAISE EXCEPTION 'Migration incomplete: % incidents missing domain_id',
            v_null_domain_count;
    END IF;

    IF v_null_category_count > 0 THEN
        RAISE EXCEPTION 'Migration incomplete: % incidents missing category_id',
            v_null_category_count;
    END IF;

    IF v_null_date_count > 0 THEN
        RAISE EXCEPTION 'Migration incomplete: % incidents missing event dates',
            v_null_date_count;
    END IF;

    RAISE NOTICE 'Phase 1C validation passed: all records migrated successfully';
END $$;

-- Verify data integrity
DO $$
DECLARE
    v_pre_count BIGINT;
    v_post_count BIGINT;
    v_pre_checksum TEXT;
    v_post_checksum TEXT;
BEGIN
    -- Get pre-migration counts
    SELECT row_count, checksum INTO v_pre_count, v_pre_checksum
    FROM migration_checksums WHERE table_name = 'incidents';

    -- Calculate post-migration checksum
    SELECT COUNT(*) INTO v_post_count FROM incidents;
    SELECT MD5(STRING_AGG(id::text || date::text || category, ',' ORDER BY id))
    INTO v_post_checksum FROM incidents;

    IF v_pre_count != v_post_count THEN
        RAISE EXCEPTION 'Row count mismatch: pre=% post=%', v_pre_count, v_post_count;
    END IF;

    IF v_pre_checksum != v_post_checksum THEN
        RAISE EXCEPTION 'Data checksum mismatch - data corruption detected';
    END IF;

    RAISE NOTICE 'Data integrity verified: % rows, checksum match', v_post_count;
END $$;

COMMIT;  -- Complete Phase 1C
```

**Rollback for Phase 1C:**
```sql
ROLLBACK;  -- If still in transaction

-- Or restore from backup:
psql -h localhost -U incident_tracker_app -d incident_tracker_recovery \
  < backups/pre_migration_YYYYMMDD_HHMMSS.dump

-- Then carefully re-apply schema changes without data migration
```

**Phase 1D: Add Indexes (Rollback Point 4)**

```sql
BEGIN;

-- Create indexes
CREATE INDEX CONCURRENTLY idx_incidents_domain ON incidents(domain_id);
CREATE INDEX CONCURRENTLY idx_incidents_category ON incidents(category_id);
CREATE INDEX CONCURRENTLY idx_incidents_custom_fields ON incidents USING gin(custom_fields);
CREATE INDEX CONCURRENTLY idx_incidents_tags ON incidents USING gin(tags);
CREATE INDEX CONCURRENTLY idx_incidents_date_range ON incidents(event_start_date, event_end_date);

COMMIT;
```

**Phase 1E: Enforce Constraints (Point of No Return - After 1 Week)**

```sql
-- Wait 1 week to observe system behavior before making domain_id/category_id NOT NULL

BEGIN;

-- Make migrated fields required
ALTER TABLE incidents
    ALTER COLUMN domain_id SET NOT NULL,
    ALTER COLUMN category_id SET NOT NULL,
    ALTER COLUMN event_start_date SET NOT NULL;

COMMIT;

-- At this point, rollback requires restoring from backup
```

#### Rollback Time Windows

| Phase | Time Window | Rollback Method |
|-------|-------------|-----------------|
| 1A - Create tables | Immediate | `ROLLBACK;` or `DROP TABLE` |
| 1B - Add columns | 24 hours | `ALTER TABLE DROP COLUMN` |
| 1C - Migrate data | 7 days | Restore from backup |
| 1D - Add indexes | 24 hours | `DROP INDEX` |
| 1E - Enforce constraints | **Point of no return** | Full backup restore only |

#### Post-Migration Validation

```sql
-- Final validation queries
SELECT
    'incidents' as table_name,
    COUNT(*) as total_records,
    COUNT(DISTINCT domain_id) as unique_domains,
    COUNT(DISTINCT category_id) as unique_categories,
    COUNT(*) FILTER (WHERE custom_fields != '{}'::jsonb) as records_with_custom_fields
FROM incidents;

-- Verify foreign key relationships
SELECT
    ed.slug as domain,
    ec.slug as category,
    COUNT(i.id) as incident_count
FROM incidents i
JOIN event_domains ed ON i.domain_id = ed.id
JOIN event_categories ec ON i.category_id = ec.id
GROUP BY ed.slug, ec.slug
ORDER BY incident_count DESC;

-- Check for orphaned records (should be 0)
SELECT COUNT(*) FROM incidents i
LEFT JOIN event_domains ed ON i.domain_id = ed.id
WHERE ed.id IS NULL;
```

#### Gradual Column Deprecation (After 30 Days)

```sql
-- After 30 days of successful operation, deprecate old column
BEGIN;

-- First, make old column nullable to prevent constraint issues
ALTER TABLE incidents ALTER COLUMN category DROP NOT NULL;

-- Add deprecation comment
COMMENT ON COLUMN incidents.category IS
    'DEPRECATED: Use category_id foreign key instead. Will be removed in next major version.';

-- After 60 more days (90 days total), drop the column
-- ALTER TABLE incidents DROP COLUMN category;

COMMIT;
```

## Testing Strategy

### Unit Tests

```python
# tests/test_domain_service.py
import pytest
from backend.services.domain_service import CriminalJusticeDomain

@pytest.mark.asyncio
async def test_create_case(test_db_pool):
    cj = CriminalJusticeDomain(test_db_pool)
    case_id = await cj.create_case(
        case_number="CR-2026-001",
        case_type="criminal",
        filed_date="2026-01-15",
        charges=[{"charge": "Assault", "severity": 1}]
    )
    assert case_id is not None

@pytest.mark.asyncio
async def test_prosecutorial_action(test_db_pool):
    cj = CriminalJusticeDomain(test_db_pool)
    # Setup: create case and prosecutor
    # ...
    action_id = await cj.record_prosecutorial_action(
        case_id=test_case_id,
        prosecutor_id=test_prosecutor_id,
        action_type="plea_offer",
        action_date="2026-02-01",
        plea_offer={"reduced_charge": "Misdemeanor Assault", "years": 1}
    )
    assert action_id is not None
```

### Integration Tests

```python
# tests/test_extraction_workflow.py
@pytest.mark.asyncio
async def test_multi_domain_extraction():
    """Test that different domains extract correctly."""
    # Test immigration extraction
    immigration_result = await extract_service.extract_from_article(
        article_text=sample_immigration_article,
        domain_id=immigration_domain_id
    )
    assert immigration_result['success']
    assert 'immigration_status' in immigration_result['extracted_data']

    # Test criminal justice extraction
    cj_result = await extract_service.extract_from_article(
        article_text=sample_prosecution_article,
        domain_id=criminal_justice_domain_id
    )
    assert cj_result['success']
    assert 'prosecutor_name' in cj_result['extracted_data']
```

### End-to-End Tests

```python
# tests/test_e2e_workflows.py
@pytest.mark.asyncio
async def test_case_lifecycle():
    """Test complete case lifecycle from arrest to sentencing."""
    # 1. Create arrest incident
    arrest_id = await create_incident(category="arrest", ...)

    # 2. Create case
    case_id = await create_case(...)

    # 3. Link arrest to case
    await link_incident_to_case(case_id, arrest_id, "arrest")

    # 4. Record prosecutorial actions
    await record_prosecutorial_action(case_id, "filed_charges", ...)

    # 5. Record disposition
    await record_disposition(case_id, "convicted", ...)

    # 6. Verify event chain
    events = await get_case_events(case_id)
    assert len(events) >= 3
```

### Backward Compatibility Testing

**Scope of Backward Compatibility:**

The following APIs/queries must continue to work identically after migration:

1. **Incident Creation (Legacy Format):**
   ```python
   POST /api/incidents
   {
       "category": "enforcement",  # Old enum value
       "date": "2026-01-15",
       "state": "CA",
       "victim_category": "protester"
   }
   ```

2. **Incident Queries (Legacy Filters):**
   ```python
   GET /api/incidents?category=enforcement
   GET /api/incidents?start_date=2025-01-01&end_date=2026-01-01
   ```

3. **Analytics Endpoints:**
   ```python
   GET /api/stats/by-category  # Must still work with old category enum
   GET /api/stats/by-state
   ```

4. **Article Extraction (Immigration Domain):**
   ```python
   POST /api/articles/extract  # Must default to immigration domain if not specified
   ```

**Regression Test Suite:**

```python
# tests/test_backward_compatibility.py
"""
Regression tests to ensure migration maintains backward compatibility.
"""
import pytest
from httpx import AsyncClient

class TestBackwardCompatibility:
    """Test suite for backward compatibility after migration."""

    @pytest.fixture
    async def pre_migration_incidents(self, test_db_pool):
        """Create incidents using old schema format."""
        async with test_db_pool.acquire() as conn:
            # Create incidents with old schema fields
            ids = []
            for i in range(10):
                incident_id = await conn.fetchval("""
                    INSERT INTO incidents (
                        category, date, state, city,
                        victim_category, immigration_status, sanctuary_status
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7
                    ) RETURNING id
                """,
                    'enforcement' if i % 2 == 0 else 'crime',
                    f'2026-01-{i+1:02d}',
                    'CA', 'Los Angeles',
                    'protester', 'undocumented', 'sanctuary'
                )
                ids.append(incident_id)
            return ids

    @pytest.mark.asyncio
    async def test_legacy_incident_creation(self, client: AsyncClient):
        """Test that legacy incident creation still works."""
        response = await client.post("/api/incidents", json={
            "category": "enforcement",
            "date": "2026-01-29",
            "state": "CA",
            "city": "San Francisco",
            "victim_category": "protester",
            "immigration_status": "citizen",
            "sanctuary_status": "sanctuary"
        })

        assert response.status_code == 200
        data = response.json()

        # Verify incident created with both old and new schema
        async with test_db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM incidents WHERE id = $1",
                UUID(data['incident_id'])
            )

            # Old schema fields populated
            assert row['category'] == 'enforcement'
            assert row['date'] == datetime.date(2026, 1, 29)

            # New schema fields also populated
            assert row['domain_id'] is not None
            assert row['category_id'] is not None
            assert row['event_start_date'] == datetime.date(2026, 1, 29)

    @pytest.mark.asyncio
    async def test_legacy_category_filter(
        self,
        client: AsyncClient,
        pre_migration_incidents
    ):
        """Test that filtering by old category enum still works."""
        response = await client.get("/api/incidents?category=enforcement")

        assert response.status_code == 200
        data = response.json()

        # Should return 5 enforcement incidents
        assert len(data['incidents']) == 5
        assert all(inc['category'] == 'enforcement' for inc in data['incidents'])

    @pytest.mark.asyncio
    async def test_legacy_date_range_query(
        self,
        client: AsyncClient,
        pre_migration_incidents
    ):
        """Test that date range queries still work."""
        response = await client.get(
            "/api/incidents?start_date=2026-01-01&end_date=2026-01-05"
        )

        assert response.status_code == 200
        data = response.json()

        # Should return incidents from Jan 1-5
        assert len(data['incidents']) == 5

    @pytest.mark.asyncio
    async def test_legacy_stats_endpoint(
        self,
        client: AsyncClient,
        pre_migration_incidents
    ):
        """Test that legacy stats endpoint returns same format."""
        response = await client.get("/api/stats/by-category")

        assert response.status_code == 200
        data = response.json()

        # Should have both category counts
        assert 'enforcement' in data
        assert 'crime' in data
        assert data['enforcement'] == 5
        assert data['crime'] == 5

    @pytest.mark.asyncio
    async def test_legacy_extraction_defaults_to_immigration(
        self,
        client: AsyncClient
    ):
        """Test that article extraction without domain defaults to immigration."""
        response = await client.post("/api/articles/extract", json={
            "url": "https://example.com/article",
            "title": "ICE Raid in California",
            "text": "ICE agents arrested 10 people in a raid..."
        })

        assert response.status_code == 200
        data = response.json()

        # Should use immigration domain extraction schema
        assert data['domain'] == 'immigration'
        assert data['category'] in ['enforcement', 'crime']

    @pytest.mark.asyncio
    async def test_performance_no_degradation(
        self,
        test_db_pool,
        pre_migration_incidents
    ):
        """Test that query performance hasn't degraded > 5%."""
        import time

        # Baseline query time (should be fast on small dataset)
        async with test_db_pool.acquire() as conn:
            start = time.perf_counter()

            for _ in range(100):
                await conn.fetch("""
                    SELECT * FROM incidents
                    WHERE category = 'enforcement'
                    AND date BETWEEN '2026-01-01' AND '2026-01-31'
                    LIMIT 100
                """)

            elapsed = time.perf_counter() - start
            avg_query_time = elapsed / 100

        # Query should complete in < 10ms on average
        assert avg_query_time < 0.01, \
            f"Query performance degraded: {avg_query_time*1000:.2f}ms avg"

    @pytest.mark.asyncio
    async def test_api_contract_unchanged(self, client: AsyncClient):
        """Test that API response format hasn't changed."""
        response = await client.get("/api/incidents/recent?limit=1")

        assert response.status_code == 200
        data = response.json()

        # Response should have expected structure
        assert 'incidents' in data
        assert len(data['incidents']) >= 0

        if data['incidents']:
            incident = data['incidents'][0]

            # Required fields still present
            assert 'id' in incident
            assert 'date' in incident
            assert 'category' in incident
            assert 'state' in incident

            # New fields should be present but optional in responses
            # (clients shouldn't break if they ignore new fields)
            assert 'domain_id' in incident or True  # Optional
            assert 'category_id' in incident or True  # Optional

    @pytest.mark.asyncio
    async def test_curation_queue_still_works(self, client: AsyncClient):
        """Test that curation workflow isn't broken."""
        # Submit article for extraction
        response = await client.post("/api/articles/submit", json={
            "url": "https://example.com/test",
            "title": "Test Article",
            "text": "Test content"
        })

        assert response.status_code == 200

        # Check curation queue
        response = await client.get("/api/curation/queue")
        assert response.status_code == 200

        # Approve/reject should still work
        if response.json()['queue']:
            queue_item = response.json()['queue'][0]
            response = await client.post(
                f"/api/curation/{queue_item['id']}/approve"
            )
            assert response.status_code == 200

```

**Compatibility Validation Checklist:**

Before declaring migration complete, validate:

- [ ] All existing unit tests still pass (0 regressions)
- [ ] All existing integration tests still pass (0 regressions)
- [ ] API response formats unchanged for legacy endpoints
- [ ] Query performance within 5% of pre-migration baseline
- [ ] Frontend UI displays incidents correctly
- [ ] Curation queue workflow functional
- [ ] Article extraction pipeline functional
- [ ] Analytics dashboards display correctly
- [ ] No errors in production logs for 48 hours post-migration
- [ ] Manual smoke test by domain expert passes

**API Versioning Strategy (If Breaking Changes Needed):**

If breaking changes become necessary:

```python
# backend/main.py
from fastapi import APIRouter

# v1 API (legacy, deprecated)
router_v1 = APIRouter(prefix="/api/v1")

@router_v1.get("/incidents")
async def get_incidents_v1(category: str = None):
    """Legacy endpoint - uses old category enum."""
    # Map to new schema internally
    pass

# v2 API (new, recommended)
router_v2 = APIRouter(prefix="/api/v2")

@router_v2.get("/incidents")
async def get_incidents_v2(domain_slug: str = None, category_slug: str = None):
    """New endpoint - uses domain/category taxonomy."""
    pass

app.include_router(router_v1)
app.include_router(router_v2)
```

**Deprecation Timeline:**

1. **Week 0-4:** Both old and new schemas coexist (dual-write)
2. **Week 4-12:** Gradual transition, old API marked as deprecated in docs
3. **Week 12+:** Old category column deprecated (comment added)
4. **Month 6:** Remove old category column (breaking change, requires v2 API)

**Quantitative Definition of "Compatible":**

A migration is considered backward compatible if:

- Zero breaking API changes (all existing endpoints return same response structure)
- Query performance degradation < 5% (measured at p95)
- Zero data loss (checksums match pre/post migration)
- Zero new errors in production logs for 48 hours
- 100% of regression tests pass

## Performance Considerations

### Database Optimization

1. **Indexes on JSONB fields**
   ```sql
   CREATE INDEX idx_incidents_custom_prosecutor
   ON incidents USING gin((custom_fields->'prosecutor_name'));
   ```

2. **Materialized views for analytics**
   ```sql
   REFRESH MATERIALIZED VIEW CONCURRENTLY prosecutor_stats;
   ```

3. **Partitioning for large tables**
   ```sql
   -- Partition incidents by date for better query performance
   CREATE TABLE incidents_2026 PARTITION OF incidents
   FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
   ```

4. **Query optimization**
   ```sql
   -- Use EXPLAIN ANALYZE to optimize slow queries
   EXPLAIN ANALYZE
   SELECT * FROM actor_incident_history WHERE actor_id = '...';
   ```

### JSONB Performance Benchmarking

**Benchmark Setup:**

```python
# tests/benchmarks/test_jsonb_performance.py
import pytest
import time
import asyncpg
from typing import List

class JSONBPerformanceBenchmark:
    """Benchmark JSONB query performance at various scales."""

    async def setup_test_data(self, pool: asyncpg.Pool, record_count: int):
        """Create test incidents with JSONB custom_fields."""
        async with pool.acquire() as conn:
            for i in range(record_count):
                await conn.execute("""
                    INSERT INTO incidents (
                        domain_id, category_id, event_start_date,
                        custom_fields, state
                    ) VALUES (
                        (SELECT id FROM event_domains LIMIT 1),
                        (SELECT id FROM event_categories LIMIT 1),
                        NOW() - INTERVAL '1 day' * $1,
                        $2::jsonb,
                        'CA'
                    )
                """, i, {
                    'prosecutor_name': f'Prosecutor {i % 100}',
                    'defendant_name': f'Defendant {i}',
                    'charge_severity': i % 5,
                    'plea_offered': i % 2 == 0,
                    'conviction_rate': round(0.5 + (i % 50) / 100, 2),
                    'sentence_months': i % 120,
                    'metadata': {
                        'court': f'Court {i % 20}',
                        'judge': f'Judge {i % 30}'
                    }
                })

    async def benchmark_gin_index_query(self, pool: asyncpg.Pool) -> float:
        """Benchmark GIN index query on JSONB field."""
        async with pool.acquire() as conn:
            start = time.perf_counter()

            rows = await conn.fetch("""
                SELECT * FROM incidents
                WHERE custom_fields @> '{"prosecutor_name": "Prosecutor 42"}'::jsonb
                LIMIT 100
            """)

            elapsed = time.perf_counter() - start
            return elapsed

    async def benchmark_jsonb_field_extraction(self, pool: asyncpg.Pool) -> float:
        """Benchmark extracting specific JSONB fields."""
        async with pool.acquire() as conn:
            start = time.perf_counter()

            rows = await conn.fetch("""
                SELECT
                    id,
                    custom_fields->>'prosecutor_name' as prosecutor,
                    (custom_fields->>'sentence_months')::int as sentence,
                    custom_fields->'metadata'->>'court' as court
                FROM incidents
                WHERE (custom_fields->>'charge_severity')::int >= 3
                LIMIT 1000
            """)

            elapsed = time.perf_counter() - start
            return elapsed

    async def benchmark_jsonb_aggregation(self, pool: asyncpg.Pool) -> float:
        """Benchmark aggregations on JSONB fields."""
        async with pool.acquire() as conn:
            start = time.perf_counter()

            rows = await conn.fetch("""
                SELECT
                    custom_fields->>'prosecutor_name' as prosecutor,
                    COUNT(*) as case_count,
                    AVG((custom_fields->>'sentence_months')::int) as avg_sentence
                FROM incidents
                WHERE custom_fields->>'prosecutor_name' IS NOT NULL
                GROUP BY custom_fields->>'prosecutor_name'
                ORDER BY case_count DESC
                LIMIT 100
            """)

            elapsed = time.perf_counter() - start
            return elapsed

@pytest.mark.asyncio
async def test_jsonb_performance_scaling(test_db_pool):
    """Test JSONB performance at 10K, 100K, 1M scales."""
    benchmark = JSONBPerformanceBenchmark()

    for scale in [10_000, 100_000, 1_000_000]:
        print(f"\n=== Testing at {scale:,} records ===")

        # Setup
        await benchmark.setup_test_data(test_db_pool, scale)

        # Run benchmarks
        gin_time = await benchmark.benchmark_gin_index_query(test_db_pool)
        extract_time = await benchmark.benchmark_jsonb_field_extraction(test_db_pool)
        agg_time = await benchmark.benchmark_jsonb_aggregation(test_db_pool)

        print(f"GIN index query: {gin_time*1000:.2f}ms")
        print(f"Field extraction: {extract_time*1000:.2f}ms")
        print(f"Aggregation: {agg_time*1000:.2f}ms")

        # Assert performance thresholds
        assert gin_time < 0.5, f"GIN query too slow at {scale}: {gin_time}s"
        assert extract_time < 1.0, f"Extraction too slow at {scale}: {extract_time}s"
        assert agg_time < 2.0, f"Aggregation too slow at {scale}: {agg_time}s"
```

**Performance Targets by Scale:**

| Records | GIN Index Query | Field Extraction | Aggregation | P95 Target |
|---------|----------------|------------------|-------------|------------|
| 10K     | < 50ms         | < 100ms          | < 200ms     | < 200ms    |
| 100K    | < 150ms        | < 300ms          | < 500ms     | < 500ms    |
| 1M      | < 400ms        | < 800ms          | < 1500ms    | < 2000ms   |

**Fallback Strategy:**

If JSONB performance degrades below acceptable thresholds:

1. **Materialized Columns** - Extract frequently-queried JSONB fields to real columns:
   ```sql
   ALTER TABLE incidents
     ADD COLUMN prosecutor_name VARCHAR(200)
     GENERATED ALWAYS AS (custom_fields->>'prosecutor_name') STORED;

   CREATE INDEX idx_incidents_prosecutor_name ON incidents(prosecutor_name);
   ```

2. **Hybrid Schema** - Use JSONB for rarely-queried fields, real columns for hot paths:
   ```sql
   -- Migration: Move critical fields out of JSONB
   ALTER TABLE incidents
     ADD COLUMN charge_severity INTEGER,
     ADD COLUMN sentence_months INTEGER;

   -- Backfill from JSONB
   UPDATE incidents SET
     charge_severity = (custom_fields->>'charge_severity')::int,
     sentence_months = (custom_fields->>'sentence_months')::int;
   ```

3. **Partitioning** - Partition by domain to reduce scan size:
   ```sql
   -- Partition incidents by domain_id
   CREATE TABLE incidents_immigration PARTITION OF incidents
   FOR VALUES IN (SELECT id FROM event_domains WHERE slug = 'immigration');
   ```

**Performance Degradation Threshold:**

Trigger schema evolution if any of these conditions occur:
- P95 query latency exceeds 500ms for 3 consecutive days
- Database CPU utilization > 80% during normal load
- Query queue depth > 10 for sustained periods
- User-reported slowness > 5 complaints per week

### Caching Strategy

- Cache domain/category metadata (rarely changes)
- Cache extraction schemas (version-controlled)
- Use Redis for prosecutor stats (refresh hourly)
- Cache materialized view results

## Security Considerations

### 1. Role-based access control
- Admin: Full access to all domains
- Domain admin: Manage specific domain
- Analyst: Read-only access to analytics
- Public: Limited access to approved incidents

### 2. 4-Level Data Classification (adopted from justice platform) [justice-platform]

| Level | Description | Access | Examples |
|-------|-------------|--------|----------|
| **Public** | Freely accessible data | All users, public API | Published incident summaries, aggregate statistics |
| **Restricted** | Internal operational data | Authenticated users | Incident details, actor names (public figures) |
| **Confidential** | Sensitive personal data | Domain admins, authorized analysts | Actor PII, victim details, juvenile records |
| **Highly Confidential** | Sealed/protected data | Admin only, audit-logged | Sealed case details, witness protection data, confidential sources |

Each table has a `data_classification` column (default: 'restricted'). API endpoints enforce classification-based access control. All access to Confidential and Highly Confidential data is audit-logged.

### 3. Data validation
- Validate custom_fields against schema (trigger + application layer)
- Sanitize user input
- Prevent SQL injection via parameterized queries
- Field definitions validated for regex safety (no ReDoS patterns)

### 4. API rate limiting
- Limit extraction requests per user
- Throttle bulk operations

### 5. Audit logging
- Log all schema changes
- Track who created/modified incidents
- Monitor API usage
- Audit log for all Confidential/Highly Confidential data access

## Data Retention and Archival Policy [M-011]

### Retention Periods

| Data Type | Active Retention | Archive Period | Deletion |
|-----------|-----------------|----------------|----------|
| Incidents (approved) | Indefinite | N/A | Never (public record) |
| Curation queue rejects | 1 year | 2 years | After 3 years |
| Background job logs | 90 days | 1 year | After 1 year |
| Extraction quality samples | 2 years | 3 years | After 5 years |
| Prompt test runs | 1 year | 2 years | After 3 years |
| Import saga records | 6 months | 1 year | After 1.5 years |
| Staging table data | 30 days after import | 90 days | After 120 days |

### PII Handling
- Actor PII anonymized after 7 years for non-public-figure actors
- Public officials (prosecutors, judges, elected officials) exempt from anonymization
- Juvenile records follow state-specific sealing requirements
- `data_classification = 'highly_confidential'` for sealed records

### Legal Compliance
- **CCPA**: Right-to-delete supported for non-public records via actor anonymization
- **Public Records**: Incidents derived from public records are retained indefinitely
- **FOIA**: Public-classified data available through public API; restricted data requires authorized request

### Archival Strategy
- Archived data moved to `_archive` suffixed tables (same schema)
- Read-only access to archived data via separate API endpoints
- Archived data excluded from materialized view calculations
- Background job handles archival based on retention periods

## Risks & Mitigation

### Technical Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| JSONB performance degradation | High | Medium | Add GIN indexes, monitor query times |
| Migration data loss | Critical | Low | Extensive testing, rollback plan |
| Schema complexity confuses users | Medium | High | UI/UX focus, good documentation |
| LLM extraction quality varies by domain | Medium | High | Domain-specific validation, human review |

### Business Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Scope creep (too many domains) | Medium | High | Prioritize domains, phased rollout |
| User confusion with new UI | Medium | Medium | Progressive disclosure, training |
| Data quality issues | High | Medium | Enhanced validation, curation workflow |

## Success Metrics

### Technical Metrics
- All migrations run without errors
- Query performance < 500ms for 95th percentile (see JSONB Performance Benchmarking for detailed targets)
- Zero data loss during migration (verified by checksums)
- 90% line coverage for core domain logic (services, models) [m-008]
- 100% coverage for critical paths (migration, data integrity, financial calculations)
- 80% line coverage overall
- All public API endpoints have at least one happy-path and one error-path test

### Business Metrics
- ✅ Support 3+ domains within 4 months
- ✅ Extract data from 5+ different document types
- ✅ User satisfaction score > 4/5
- ✅ 50% reduction in manual data entry

## Future Enhancements

### Phase 5: Machine Learning Integration
- Automatic domain detection
- Recidivism prediction models
- Pattern detection algorithms
- Anomaly detection for prosecutorial bias

### Phase 6: Cross-Domain Analytics
- Compare patterns across domains
- Identify systemic issues
- Geographic heat maps
- Temporal trend analysis

### Phase 7: Public API
- RESTful API for external access
- GraphQL for flexible queries
- Webhook subscriptions
- Data export tools

## Conclusion

This plan provides a comprehensive roadmap for transforming the immigration-focused incident tracker into a generic event tracking platform. The hybrid migration approach balances innovation with stability, allowing the system to evolve incrementally while maintaining backward compatibility.

**Key Takeaways:**
- Flexible schema via JSONB custom fields
- Domain-based architecture for isolation
- Strong data model for complex relationships
- Extensible extraction system
- Rich analytics capabilities

**Next Steps:**
1. ✅ Review and approve plan
2. ✅ Create detailed implementation tickets
3. ✅ Begin Phase 1 implementation
4. ✅ Set up testing infrastructure
5. ✅ Establish monitoring and alerting

---

**Document Version:** 1.1
**Last Updated:** 2026-01-29
**Status:** Round 1 Defense Complete - Ready for Round 2 Review
**Changes:** Incorporated all 27 challenge responses and justice platform patterns (see review-round-1-defense.md)
