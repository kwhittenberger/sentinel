-- Migration 011: Event Relationships
-- Adds links between related incidents with type semantics and cycle detection.
-- Part of Phase 1: Foundation for the Generic Event Tracking System.

-- ============================================================================
-- 1. RELATIONSHIP TYPE DEFINITIONS
-- ============================================================================

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
    ('retried_as', 'Source is retried as target', TRUE, 'retrial_of'),
    ('same_case', 'Events are part of same legal case', FALSE, NULL);


-- ============================================================================
-- 2. EVENT RELATIONSHIPS TABLE
-- ============================================================================

CREATE TABLE event_relationships (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    target_incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    relationship_type VARCHAR(50) NOT NULL REFERENCES relationship_types(name),
    sequence_order INTEGER,
    case_id UUID,  -- Group events in same case (FK added when cases table exists)
    description TEXT,
    confidence DECIMAL(3,2) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    created_by VARCHAR(20) DEFAULT 'manual',  -- 'manual' or 'ai'
    created_at TIMESTAMPTZ DEFAULT NOW(),

    CHECK (source_incident_id != target_incident_id),
    UNIQUE(source_incident_id, target_incident_id, relationship_type)
);

CREATE INDEX idx_event_rel_source ON event_relationships(source_incident_id);
CREATE INDEX idx_event_rel_target ON event_relationships(target_incident_id);
CREATE INDEX idx_event_rel_case ON event_relationships(case_id);
CREATE INDEX idx_event_rel_type ON event_relationships(relationship_type);


-- ============================================================================
-- 3. CYCLE DETECTION TRIGGER
-- ============================================================================

-- Prevents A -> B -> C -> A temporal loops in directional relationships
CREATE OR REPLACE FUNCTION check_relationship_cycle()
RETURNS TRIGGER AS $$
DECLARE
    v_max_depth INTEGER := 20;
    v_has_cycle BOOLEAN;
    v_is_directional BOOLEAN;
BEGIN
    -- Only check directional relationships for cycles
    SELECT is_directional INTO v_is_directional
    FROM relationship_types
    WHERE name = NEW.relationship_type;

    IF v_is_directional IS TRUE THEN
        WITH RECURSIVE chain AS (
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


-- ============================================================================
-- 4. GRANTS
-- ============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON relationship_types TO incident_tracker_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON event_relationships TO incident_tracker_app;

COMMENT ON TABLE relationship_types IS 'Definitions for event relationship semantics (directional, inverse pairs)';
COMMENT ON TABLE event_relationships IS 'Links between related incidents with type and confidence';
