-- Migration 014: Prosecutorial Tracking
-- Adds prosecutorial actions, bail decisions, dispositions, and prosecutor stats.
-- Part of Phase 2: Cases & Legal Tracking.

-- ============================================================================
-- 1. PROSECUTORIAL ACTIONS
-- ============================================================================

CREATE TABLE prosecutorial_actions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    prosecutor_id UUID REFERENCES actors(id),
    prosecutor_name VARCHAR(200),

    action_type VARCHAR(40) NOT NULL
        CHECK (action_type IN (
            'filed_charges', 'amended_charges', 'plea_offer',
            'dismissed', 'trial_decision', 'sentencing_recommendation',
            'bail_recommendation', 'diversion_offer', 'nolle_prosequi'
        )),
    action_date DATE NOT NULL DEFAULT CURRENT_DATE,

    -- Details
    description TEXT,
    reasoning TEXT,
    legal_basis TEXT,
    justification TEXT,

    -- Oversight
    supervisor_reviewed BOOLEAN DEFAULT FALSE,
    supervisor_name VARCHAR(200),

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_pros_actions_case ON prosecutorial_actions(case_id);
CREATE INDEX idx_pros_actions_prosecutor ON prosecutorial_actions(prosecutor_id);
CREATE INDEX idx_pros_actions_type ON prosecutorial_actions(action_type);
CREATE INDEX idx_pros_actions_date ON prosecutorial_actions(action_date);


-- ============================================================================
-- 2. PROSECUTOR ACTION ↔ CHARGE LINKING
-- ============================================================================

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


-- ============================================================================
-- 3. BAIL DECISIONS
-- ============================================================================

CREATE TABLE bail_decisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    judge_id UUID REFERENCES actors(id),
    judge_name VARCHAR(200),

    decision_type VARCHAR(30) NOT NULL
        CHECK (decision_type IN (
            'initial_bail', 'bail_modification',
            'bail_revocation', 'release_on_recognizance'
        )),
    decision_date DATE NOT NULL DEFAULT CURRENT_DATE,

    -- Bail terms
    bail_amount DECIMAL(12,2),
    bail_type VARCHAR(30)
        CHECK (bail_type IN (
            'cash', 'surety', 'property', 'unsecured',
            'personal_recognizance', 'no_bail'
        )),
    conditions TEXT,

    -- Risk assessment context
    flight_risk_assessed VARCHAR(10) CHECK (flight_risk_assessed IN ('low', 'medium', 'high')),
    danger_to_public_assessed VARCHAR(10) CHECK (danger_to_public_assessed IN ('low', 'medium', 'high')),
    prior_record_considered BOOLEAN DEFAULT FALSE,
    community_ties_considered BOOLEAN DEFAULT FALSE,
    risk_factors_notes TEXT,

    -- Prosecution and defense positions
    prosecution_position TEXT,
    prosecution_requested_amount DECIMAL(12,2),
    defense_position TEXT,
    defense_requested_amount DECIMAL(12,2),

    -- Decision rationale
    decision_rationale TEXT,

    -- Outcome
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


-- ============================================================================
-- 4. DISPOSITIONS
-- ============================================================================

CREATE TABLE dispositions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    charge_id UUID REFERENCES charges(id) ON DELETE SET NULL,  -- NULL = case-level disposition
    judge_id UUID REFERENCES actors(id),
    judge_name VARCHAR(200),

    disposition_type VARCHAR(30) NOT NULL
        CHECK (disposition_type IN (
            'convicted', 'acquitted', 'dismissed', 'plea',
            'mistrial', 'nolle_prosequi', 'deferred_adjudication', 'diverted'
        )),
    disposition_date DATE NOT NULL DEFAULT CURRENT_DATE,

    -- Incarceration
    total_jail_days INTEGER,
    jail_days_suspended INTEGER,
    jail_days_served INTEGER,
    incarceration_start_date DATE,
    projected_release_date DATE,
    actual_release_date DATE,
    incarceration_facility VARCHAR(200),

    -- Probation
    probation_days INTEGER,
    probation_start_date DATE,
    probation_end_date DATE,
    probation_conditions JSONB,

    -- Financial
    fine_amount DECIMAL(12,2),
    fine_amount_paid DECIMAL(12,2),
    restitution_amount DECIMAL(12,2),
    restitution_amount_paid DECIMAL(12,2),
    court_costs DECIMAL(12,2),

    -- Community service
    community_service_hours INTEGER,
    community_service_hours_completed INTEGER,

    -- Treatment / programs
    ordered_programs JSONB,  -- Array of program names/IDs
    substance_abuse_treatment_ordered BOOLEAN DEFAULT FALSE,
    mental_health_treatment_ordered BOOLEAN DEFAULT FALSE,

    -- Compliance
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
-- 5. PROSECUTOR STATS (MATERIALIZED VIEW)
-- ============================================================================

CREATE MATERIALIZED VIEW prosecutor_stats AS
SELECT
    pa.prosecutor_id,
    COALESCE(a.canonical_name, pa.prosecutor_name, 'Unknown') AS prosecutor_name,

    -- Case counts
    COUNT(DISTINCT pa.case_id) AS total_cases,
    COUNT(DISTINCT d_conv.case_id) AS convictions,
    COUNT(DISTINCT d_acq.case_id) AS acquittals,
    COUNT(DISTINCT d_dis.case_id) AS dismissals,
    COUNT(DISTINCT d_plea.case_id) AS plea_bargains,

    -- Rates
    CASE
        WHEN COUNT(DISTINCT pa.case_id) > 0
        THEN ROUND(COUNT(DISTINCT d_conv.case_id)::DECIMAL / COUNT(DISTINCT pa.case_id), 3)
        ELSE 0
    END AS conviction_rate,

    -- Charge modifications
    COUNT(DISTINCT CASE WHEN pa.action_type = 'amended_charges' THEN pa.id END) AS charges_amended,
    COUNT(DISTINCT CASE WHEN pa.action_type = 'dismissed' THEN pa.id END) AS charges_dismissed_count,

    -- Bail
    AVG(CASE WHEN pa.action_type = 'bail_recommendation' THEN bd.prosecution_requested_amount END) AS avg_bail_requested,

    -- Sentencing
    AVG(d_sent.total_jail_days) AS avg_sentence_days,

    -- Data quality
    ROUND(
        (COUNT(DISTINCT pa.case_id) FILTER (WHERE pa.reasoning IS NOT NULL))::DECIMAL /
        GREATEST(COUNT(DISTINCT pa.case_id), 1) * 100, 1
    ) AS data_completeness_pct,

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


-- ============================================================================
-- 6. AUTO-UPDATE TIMESTAMPS
-- ============================================================================

CREATE TRIGGER trigger_pros_action_updated
BEFORE UPDATE ON prosecutorial_actions
FOR EACH ROW
EXECUTE FUNCTION update_case_timestamp();

CREATE TRIGGER trigger_bail_updated
BEFORE UPDATE ON bail_decisions
FOR EACH ROW
EXECUTE FUNCTION update_case_timestamp();

CREATE TRIGGER trigger_disposition_updated
BEFORE UPDATE ON dispositions
FOR EACH ROW
EXECUTE FUNCTION update_case_timestamp();


-- ============================================================================
-- 7. GRANTS
-- ============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON prosecutorial_actions TO sentinel;
GRANT SELECT, INSERT, UPDATE, DELETE ON prosecutor_action_charges TO sentinel;
GRANT SELECT, INSERT, UPDATE, DELETE ON bail_decisions TO sentinel;
GRANT SELECT, INSERT, UPDATE, DELETE ON dispositions TO sentinel;
GRANT SELECT ON prosecutor_stats TO sentinel;

COMMENT ON TABLE prosecutorial_actions IS 'Tracks prosecutor decisions throughout case lifecycle';
COMMENT ON TABLE prosecutor_action_charges IS 'Links prosecutorial actions to affected charges';
COMMENT ON TABLE bail_decisions IS 'Bail hearing decisions with risk assessment context';
COMMENT ON TABLE dispositions IS 'Case outcomes with granular sentencing, probation, and compliance tracking';
COMMENT ON MATERIALIZED VIEW prosecutor_stats IS 'Aggregated prosecutor performance metrics (refresh periodically)';
