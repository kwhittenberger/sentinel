-- Migration 036: Expand optional_fields to match extraction schema.
--
-- The LLM extraction schema supports many more fields than were originally
-- seeded in migration 028.  This adds every extractable field that isn't
-- already listed as required, keeping required_fields unchanged.

-- ============================================================================
-- Immigration → Enforcement
-- ============================================================================
UPDATE event_categories
SET optional_fields = '[
    "city",
    "description",
    "officer_involved",
    "agency",
    "victim_name",
    "victim_age",
    "charges",
    "sentence",
    "extraction_notes"
]'::jsonb,
    updated_at = NOW()
WHERE slug = 'enforcement'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'immigration');

-- ============================================================================
-- Immigration → Crime
-- required_fields also updated: offender_immigration_status moved to optional
-- (required = minimum for schema determination, not domain-level importance)
-- ============================================================================
UPDATE event_categories
SET required_fields = '["date", "state", "incident_type"]'::jsonb,
    optional_fields = '[
    "city",
    "description",
    "offender_name",
    "offender_age",
    "offender_immigration_status",
    "offender_gender",
    "offender_nationality",
    "offender_country_of_origin",
    "entry_method",
    "prior_deportations",
    "prior_arrests",
    "prior_convictions",
    "gang_affiliated",
    "gang_name",
    "cartel_connection",
    "ice_detainer_status",
    "ice_detainer_ignored",
    "was_released_sanctuary",
    "was_released_bail",
    "crime_victim_count",
    "crime_victim_names",
    "involves_fatality",
    "outcome_category",
    "charges",
    "sentence",
    "extraction_notes"
]'::jsonb,
    updated_at = NOW()
WHERE slug = 'crime'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'immigration');

-- ============================================================================
-- Criminal Justice — expand all categories
-- ============================================================================
UPDATE event_categories
SET optional_fields = '[
    "city",
    "description",
    "charges",
    "defendant_name",
    "person_name",
    "arresting_agency",
    "arrest_type",
    "bond_amount",
    "immigration_status",
    "prior_arrests",
    "prior_convictions",
    "extraction_notes"
]'::jsonb,
    updated_at = NOW()
WHERE slug = 'arrest'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'criminal_justice');

UPDATE event_categories
SET optional_fields = '[
    "city",
    "description",
    "charges",
    "defendant_name",
    "prosecutor_name",
    "court_name",
    "case_number",
    "plea",
    "bail_amount",
    "extraction_notes"
]'::jsonb,
    updated_at = NOW()
WHERE slug = 'prosecution'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'criminal_justice');

UPDATE event_categories
SET optional_fields = '[
    "city",
    "description",
    "charges",
    "verdict",
    "judge_name",
    "jury_type",
    "court_name",
    "case_number",
    "defendant_name",
    "defense_attorney",
    "extraction_notes"
]'::jsonb,
    updated_at = NOW()
WHERE slug = 'trial'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'criminal_justice');

UPDATE event_categories
SET optional_fields = '[
    "city",
    "description",
    "sentence",
    "charges",
    "defendant_name",
    "judge_name",
    "court_name",
    "case_number",
    "sentence_type",
    "sentence_duration",
    "restitution",
    "extraction_notes"
]'::jsonb,
    updated_at = NOW()
WHERE slug = 'sentencing'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'criminal_justice');

UPDATE event_categories
SET optional_fields = '[
    "city",
    "description",
    "facility_name",
    "facility_type",
    "person_name",
    "charges",
    "sentence_duration",
    "security_level",
    "extraction_notes"
]'::jsonb,
    updated_at = NOW()
WHERE slug = 'incarceration'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'criminal_justice');

UPDATE event_categories
SET optional_fields = '[
    "city",
    "description",
    "person_name",
    "release_type",
    "conditions",
    "parole_officer",
    "time_served",
    "charges",
    "extraction_notes"
]'::jsonb,
    updated_at = NOW()
WHERE slug = 'release'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'criminal_justice');

-- ============================================================================
-- Civil Rights — expand all categories
-- ============================================================================
UPDATE event_categories
SET optional_fields = '[
    "city",
    "description",
    "organizer",
    "participant_count",
    "target",
    "protest_type",
    "outcome",
    "arrests_count",
    "injuries_count",
    "extraction_notes"
]'::jsonb,
    updated_at = NOW()
WHERE slug = 'protest'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'civil_rights');

UPDATE event_categories
SET optional_fields = '[
    "city",
    "description",
    "officer_name",
    "officer_badge",
    "victim_name",
    "victim_age",
    "agency",
    "force_type",
    "outcome_category",
    "body_camera",
    "extraction_notes"
]'::jsonb,
    updated_at = NOW()
WHERE slug = 'police_force'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'civil_rights');

UPDATE event_categories
SET optional_fields = '[
    "city",
    "description",
    "violation_type",
    "agency",
    "victim_name",
    "victim_age",
    "perpetrator_name",
    "perpetrator_agency",
    "outcome",
    "extraction_notes"
]'::jsonb,
    updated_at = NOW()
WHERE slug = 'civil_rights_violation'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'civil_rights');

UPDATE event_categories
SET optional_fields = '[
    "city",
    "description",
    "case_name",
    "case_number",
    "court_name",
    "plaintiff",
    "defendant",
    "filing_date",
    "ruling",
    "damages_sought",
    "extraction_notes"
]'::jsonb,
    updated_at = NOW()
WHERE slug = 'litigation'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'civil_rights');
