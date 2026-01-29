-- Migration 016: Recidivism Tracking & Advanced Analytics
-- Adds actor incident history, recidivism analysis, defendant lifecycle,
-- staging tables for ETL, and migration rollback log.
-- Part of Phase 4: Advanced Analytics.

-- ============================================================================
-- 1. ACTOR INCIDENT HISTORY VIEW
-- ============================================================================

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
WHERE ia.role_type_id IN (
    SELECT id FROM actor_role_types WHERE slug IN ('defendant', 'offender', 'arrestee')
);

-- ============================================================================
-- 2. RECIDIVISM ANALYSIS MATERIALIZED VIEW
-- ============================================================================

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

-- Register for automated refresh
INSERT INTO materialized_view_refresh_config
    (view_name, refresh_interval_minutes, staleness_tolerance_minutes)
VALUES
    ('recidivism_analysis', 360, 720);

-- ============================================================================
-- 3. RECIDIVISM INDICATOR FUNCTION
-- ============================================================================

-- WARNING: This is a HEURISTIC indicator, NOT a validated risk assessment instrument.
-- FOR INFORMATIONAL USE ONLY. Not validated for judicial decision-making.
-- Must not be used for automated decision-making without proper validation.
-- Known limitations: no demographic normalization, no offense-type weighting,
-- no validation study performed, potential for demographic bias.
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

    -- Heuristic model — NOT validated for any decision-making
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
        TRUE,
        'heuristic-v1'::VARCHAR(20),
        'FOR INFORMATIONAL USE ONLY. Heuristic indicator not validated for judicial decision-making. Potential for demographic bias.'::TEXT;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 4. DEFENDANT LIFECYCLE TIMELINE VIEW
-- ============================================================================

CREATE VIEW defendant_lifecycle_timeline AS
WITH lifecycle_events AS (
    SELECT
        a.id as actor_id,
        a.canonical_name,
        i.id as incident_id,
        c.id as case_id,
        c.case_number,
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
        COALESCE(
            i.event_start_date,
            pa.action_date::timestamptz,
            d.disposition_date::timestamptz,
            ch.event_date
        ) as event_date
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
    WHERE ia.role_type_id IN (
        SELECT id FROM actor_role_types WHERE slug IN ('defendant', 'offender', 'arrestee')
    )
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

-- ============================================================================
-- 5. STAGING TABLES FOR ETL
-- ============================================================================

-- Import saga orchestration
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

-- Staging incidents
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

-- Staging actors
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

-- ============================================================================
-- 6. MIGRATION ROLLBACK LOG
-- ============================================================================

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
-- 7. GRANTS
-- ============================================================================

GRANT SELECT ON actor_incident_history TO incident_tracker_app;
GRANT SELECT ON recidivism_analysis TO incident_tracker_app;
GRANT SELECT ON defendant_lifecycle_timeline TO incident_tracker_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON import_sagas TO incident_tracker_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON staging_incidents TO incident_tracker_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON staging_actors TO incident_tracker_app;
GRANT SELECT, INSERT ON migration_rollback_log TO incident_tracker_app;
