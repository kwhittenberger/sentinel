-- Migration 013: Cases System
-- Adds case tracking, charges, charge history, jurisdictions, and external system mapping.
-- Part of Phase 2: Cases & Legal Tracking.

-- ============================================================================
-- 1. CASES TABLE
-- ============================================================================

CREATE TABLE cases (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_number VARCHAR(100),
    case_type VARCHAR(50) NOT NULL,  -- criminal, civil, immigration, administrative
    jurisdiction VARCHAR(200),
    court_name VARCHAR(200),
    filed_date DATE,
    closed_date DATE,
    status VARCHAR(30) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'closed', 'appealed', 'dismissed', 'sealed')),

    -- Taxonomy link
    domain_id UUID REFERENCES event_domains(id),
    category_id UUID REFERENCES event_categories(id),

    -- Flexible data
    custom_fields JSONB DEFAULT '{}',
    data_classification VARCHAR(30) DEFAULT 'public'
        CHECK (data_classification IN ('public', 'restricted', 'sealed', 'expunged')),

    -- Metadata
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Case number unique within jurisdiction
    UNIQUE(case_number, jurisdiction)
);

CREATE INDEX idx_cases_case_number ON cases(case_number);
CREATE INDEX idx_cases_case_type ON cases(case_type);
CREATE INDEX idx_cases_status ON cases(status);
CREATE INDEX idx_cases_filed_date ON cases(filed_date);
CREATE INDEX idx_cases_jurisdiction ON cases(jurisdiction);
CREATE INDEX idx_cases_domain ON cases(domain_id);
CREATE INDEX idx_cases_category ON cases(category_id);


-- ============================================================================
-- 2. CHARGES TABLE
-- ============================================================================

CREATE TABLE charges (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    charge_number INTEGER NOT NULL,  -- Sequence within case (Count 1, Count 2, etc.)
    charge_code VARCHAR(50),  -- Statute reference (e.g. "RCW 9A.36.021")
    charge_description TEXT NOT NULL,
    charge_level VARCHAR(20) NOT NULL DEFAULT 'misdemeanor'
        CHECK (charge_level IN ('felony', 'misdemeanor', 'infraction', 'violation')),
    charge_class VARCHAR(10),  -- e.g. 'A', 'B', 'C' for felony classes
    severity INTEGER,  -- Numeric severity for sorting/comparison

    -- Charge lifecycle
    status VARCHAR(30) NOT NULL DEFAULT 'filed'
        CHECK (status IN ('filed', 'amended', 'reduced', 'dismissed', 'convicted', 'acquitted')),
    is_violent_crime BOOLEAN DEFAULT FALSE,
    is_original BOOLEAN DEFAULT TRUE,  -- FALSE if result of amendment/reduction

    -- Per-charge sentencing (populated after disposition)
    jail_days INTEGER,
    probation_days INTEGER,
    fine_amount DECIMAL(12,2),
    restitution_amount DECIMAL(12,2),
    community_service_hours INTEGER,

    -- Metadata
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(case_id, charge_number)
);

CREATE INDEX idx_charges_case ON charges(case_id);
CREATE INDEX idx_charges_status ON charges(status);
CREATE INDEX idx_charges_code ON charges(charge_code);
CREATE INDEX idx_charges_violent ON charges(is_violent_crime) WHERE is_violent_crime = TRUE;


-- ============================================================================
-- 3. CHARGE HISTORY (AUDIT TRAIL)
-- ============================================================================

CREATE TABLE charge_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    charge_id UUID NOT NULL REFERENCES charges(id) ON DELETE CASCADE,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    event_type VARCHAR(30) NOT NULL
        CHECK (event_type IN (
            'filed', 'amended', 'reduced', 'dismissed',
            'convicted', 'acquitted', 'reinstated', 'sealed'
        )),
    actor_type VARCHAR(30)
        CHECK (actor_type IN ('prosecutor', 'judge', 'defense_attorney', 'system', 'clerk')),
    actor_name VARCHAR(200),
    actor_id UUID REFERENCES actors(id),

    -- Change details
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


-- ============================================================================
-- 4. CASE JURISDICTIONS (MULTI-JURISDICTION SUPPORT)
-- ============================================================================

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


-- ============================================================================
-- 5. EXTERNAL SYSTEM IDS
-- ============================================================================

CREATE TABLE external_system_ids (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type VARCHAR(30) NOT NULL
        CHECK (entity_type IN ('case', 'incident', 'actor', 'charge')),
    entity_id UUID NOT NULL,
    system_name VARCHAR(100) NOT NULL,  -- e.g. 'king_county_courts', 'socrata', 'fbi_ucr'
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


-- ============================================================================
-- 6. CASE ↔ INCIDENT LINKING
-- ============================================================================

CREATE TABLE case_incidents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    incident_role VARCHAR(30) NOT NULL DEFAULT 'related'
        CHECK (incident_role IN (
            'arrest', 'arraignment', 'hearing', 'trial',
            'sentencing', 'appeal', 'related', 'evidence'
        )),
    sequence_order INTEGER,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(case_id, incident_id, incident_role)
);

CREATE INDEX idx_case_incidents_case ON case_incidents(case_id);
CREATE INDEX idx_case_incidents_incident ON case_incidents(incident_id);
CREATE INDEX idx_case_incidents_role ON case_incidents(incident_role);


-- ============================================================================
-- 7. CASE ↔ ACTOR LINKING
-- ============================================================================

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


-- ============================================================================
-- 8. AUTO-UPDATE TIMESTAMPS
-- ============================================================================

CREATE OR REPLACE FUNCTION update_case_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_case_updated
BEFORE UPDATE ON cases
FOR EACH ROW
EXECUTE FUNCTION update_case_timestamp();

CREATE TRIGGER trigger_charge_updated
BEFORE UPDATE ON charges
FOR EACH ROW
EXECUTE FUNCTION update_case_timestamp();


-- ============================================================================
-- 9. GRANTS
-- ============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON cases TO incident_tracker_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON charges TO incident_tracker_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON charge_history TO incident_tracker_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON case_jurisdictions TO incident_tracker_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON external_system_ids TO incident_tracker_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON case_incidents TO incident_tracker_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON case_actors TO incident_tracker_app;

COMMENT ON TABLE cases IS 'Legal case records with jurisdiction and status tracking';
COMMENT ON TABLE charges IS 'Individual charges within a case with lifecycle tracking';
COMMENT ON TABLE charge_history IS 'Audit trail for charge modifications (filed/amended/dismissed/etc)';
COMMENT ON TABLE case_jurisdictions IS 'Multi-jurisdiction support for transferred/concurrent cases';
COMMENT ON TABLE external_system_ids IS 'Cross-system ID mapping for deduplication across external systems';
COMMENT ON TABLE case_incidents IS 'Links incidents to legal cases with role semantics';
COMMENT ON TABLE case_actors IS 'Links actors to legal cases with role assignments';
