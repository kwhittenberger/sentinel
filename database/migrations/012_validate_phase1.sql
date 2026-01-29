-- Migration 012: Phase 1 Validation
-- Run after migrations 009-011 to verify data migration integrity.
-- This is a read-only validation script — it SELECTs and raises errors, never modifies data.

-- ============================================================================
-- 1. DOMAIN ASSIGNMENT VALIDATION
-- ============================================================================

-- Every incident must have a domain_id after migration 009
DO $$
DECLARE
    v_orphan_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_orphan_count
    FROM incidents
    WHERE domain_id IS NULL;

    IF v_orphan_count > 0 THEN
        RAISE WARNING 'VALIDATION FAILED: % incidents have NULL domain_id', v_orphan_count;
    ELSE
        RAISE NOTICE 'PASS: All incidents have domain_id assigned';
    END IF;
END $$;

-- Every incident must have a category_id after migration 009
DO $$
DECLARE
    v_orphan_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_orphan_count
    FROM incidents
    WHERE category_id IS NULL;

    IF v_orphan_count > 0 THEN
        RAISE WARNING 'VALIDATION FAILED: % incidents have NULL category_id', v_orphan_count;
    ELSE
        RAISE NOTICE 'PASS: All incidents have category_id assigned';
    END IF;
END $$;

-- All domain_id values must reference valid event_domains
DO $$
DECLARE
    v_invalid_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_invalid_count
    FROM incidents i
    LEFT JOIN event_domains ed ON i.domain_id = ed.id
    WHERE i.domain_id IS NOT NULL AND ed.id IS NULL;

    IF v_invalid_count > 0 THEN
        RAISE WARNING 'VALIDATION FAILED: % incidents reference non-existent domain_id', v_invalid_count;
    ELSE
        RAISE NOTICE 'PASS: All incident domain_id references are valid';
    END IF;
END $$;

-- All category_id values must reference valid event_categories
DO $$
DECLARE
    v_invalid_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_invalid_count
    FROM incidents i
    LEFT JOIN event_categories ec ON i.category_id = ec.id
    WHERE i.category_id IS NOT NULL AND ec.id IS NULL;

    IF v_invalid_count > 0 THEN
        RAISE WARNING 'VALIDATION FAILED: % incidents reference non-existent category_id', v_invalid_count;
    ELSE
        RAISE NOTICE 'PASS: All incident category_id references are valid';
    END IF;
END $$;


-- ============================================================================
-- 2. EVENT DATE MIGRATION VALIDATION
-- ============================================================================

-- event_start_date should be populated from the date column
DO $$
DECLARE
    v_total INTEGER;
    v_with_date INTEGER;
    v_with_start_date INTEGER;
    v_mismatch_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_total FROM incidents;
    SELECT COUNT(*) INTO v_with_date FROM incidents WHERE date IS NOT NULL;
    SELECT COUNT(*) INTO v_with_start_date FROM incidents WHERE event_start_date IS NOT NULL;

    RAISE NOTICE 'Date migration: % total incidents, % with date, % with event_start_date',
        v_total, v_with_date, v_with_start_date;

    -- Check that all incidents with a date also got event_start_date
    SELECT COUNT(*) INTO v_mismatch_count
    FROM incidents
    WHERE date IS NOT NULL AND event_start_date IS NULL;

    IF v_mismatch_count > 0 THEN
        RAISE WARNING 'VALIDATION FAILED: % incidents have date but no event_start_date', v_mismatch_count;
    ELSE
        RAISE NOTICE 'PASS: All dated incidents have event_start_date populated';
    END IF;
END $$;


-- ============================================================================
-- 3. ACTOR ROLE TYPE MIGRATION VALIDATION
-- ============================================================================

-- Every incident_actor should have a role_type_id
DO $$
DECLARE
    v_orphan_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_orphan_count
    FROM incident_actors
    WHERE role_type_id IS NULL;

    IF v_orphan_count > 0 THEN
        RAISE WARNING 'VALIDATION FAILED: % incident_actors have NULL role_type_id', v_orphan_count;
    ELSE
        RAISE NOTICE 'PASS: All incident_actors have role_type_id assigned';
    END IF;
END $$;

-- All role_type_id values must reference valid actor_role_types
DO $$
DECLARE
    v_invalid_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_invalid_count
    FROM incident_actors ia
    LEFT JOIN actor_role_types art ON ia.role_type_id = art.id
    WHERE ia.role_type_id IS NOT NULL AND art.id IS NULL;

    IF v_invalid_count > 0 THEN
        RAISE WARNING 'VALIDATION FAILED: % incident_actors reference non-existent role_type_id', v_invalid_count;
    ELSE
        RAISE NOTICE 'PASS: All incident_actors role_type_id references are valid';
    END IF;
END $$;

-- Check for 'unknown' role mappings (indicates migration gaps)
DO $$
DECLARE
    v_unknown_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_unknown_count
    FROM incident_actors ia
    JOIN actor_role_types art ON ia.role_type_id = art.id
    WHERE art.slug = 'unknown';

    IF v_unknown_count > 0 THEN
        RAISE WARNING 'NOTICE: % incident_actors mapped to "unknown" role type — manual review recommended', v_unknown_count;
    ELSE
        RAISE NOTICE 'PASS: No incident_actors mapped to unknown role type';
    END IF;
END $$;


-- ============================================================================
-- 4. SEED DATA VALIDATION
-- ============================================================================

-- Verify expected domains exist
DO $$
DECLARE
    v_domain_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_domain_count
    FROM event_domains
    WHERE slug IN ('immigration', 'criminal_justice', 'civil_rights');

    IF v_domain_count < 3 THEN
        RAISE WARNING 'VALIDATION FAILED: Expected 3 seed domains, found %', v_domain_count;
    ELSE
        RAISE NOTICE 'PASS: All 3 seed domains present';
    END IF;
END $$;

-- Verify relationship types exist
DO $$
DECLARE
    v_type_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_type_count FROM relationship_types;

    IF v_type_count < 10 THEN
        RAISE WARNING 'VALIDATION FAILED: Expected >= 10 relationship types, found %', v_type_count;
    ELSE
        RAISE NOTICE 'PASS: % relationship types present', v_type_count;
    END IF;
END $$;

-- Verify actor role types exist
DO $$
DECLARE
    v_role_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_role_count FROM actor_role_types;

    IF v_role_count < 22 THEN
        RAISE WARNING 'VALIDATION FAILED: Expected >= 22 actor role types, found %', v_role_count;
    ELSE
        RAISE NOTICE 'PASS: % actor role types present', v_role_count;
    END IF;
END $$;


-- ============================================================================
-- 5. CATEGORY DISTRIBUTION SUMMARY
-- ============================================================================

-- Show distribution of incidents across domains and categories
DO $$
DECLARE
    r RECORD;
BEGIN
    RAISE NOTICE '--- Incident Distribution by Domain ---';
    FOR r IN
        SELECT ed.name, ed.slug, COUNT(i.id) as cnt
        FROM event_domains ed
        LEFT JOIN incidents i ON i.domain_id = ed.id
        GROUP BY ed.name, ed.slug
        ORDER BY cnt DESC
    LOOP
        RAISE NOTICE '  %: % incidents', r.name, r.cnt;
    END LOOP;

    RAISE NOTICE '--- Incident Distribution by Category ---';
    FOR r IN
        SELECT ec.name, ed.slug as domain_slug, COUNT(i.id) as cnt
        FROM event_categories ec
        JOIN event_domains ed ON ec.domain_id = ed.id
        LEFT JOIN incidents i ON i.category_id = ec.id
        GROUP BY ec.name, ed.slug
        ORDER BY cnt DESC
    LOOP
        RAISE NOTICE '  %/%: % incidents', r.domain_slug, r.name, r.cnt;
    END LOOP;
END $$;


-- ============================================================================
-- 6. TRIGGER VALIDATION
-- ============================================================================

-- Verify cycle detection trigger exists on event_relationships
DO $$
DECLARE
    v_trigger_exists BOOLEAN;
BEGIN
    SELECT EXISTS(
        SELECT 1
        FROM information_schema.triggers
        WHERE trigger_name = 'trigger_check_relationship_cycle'
          AND event_object_table = 'event_relationships'
    ) INTO v_trigger_exists;

    IF v_trigger_exists THEN
        RAISE NOTICE 'PASS: Cycle detection trigger exists on event_relationships';
    ELSE
        RAISE WARNING 'VALIDATION FAILED: Cycle detection trigger missing on event_relationships';
    END IF;
END $$;

-- Verify custom field validation trigger exists
DO $$
DECLARE
    v_trigger_exists BOOLEAN;
BEGIN
    SELECT EXISTS(
        SELECT 1
        FROM information_schema.triggers
        WHERE trigger_name = 'trigger_validate_custom_fields'
          AND event_object_table = 'incidents'
    ) INTO v_trigger_exists;

    IF v_trigger_exists THEN
        RAISE NOTICE 'PASS: Custom field validation trigger exists on incidents';
    ELSE
        RAISE WARNING 'VALIDATION FAILED: Custom field validation trigger missing on incidents';
    END IF;
END $$;


COMMENT ON EXTENSION "uuid-ossp" IS 'Phase 1 validation complete — review NOTICE/WARNING output above';
