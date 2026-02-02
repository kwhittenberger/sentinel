-- Migration 028: Populate required_fields for each event category.
--
-- These define the minimum fields needed for an extraction to create a valid
-- incident.  Auto-approval and incident creation read from this column so that
-- each schema controls its own validation rules.
--
-- The legacy trigger_validate_custom_fields checked required_fields against
-- custom_fields JSONB, but required_fields now refers to main incident columns.
-- Python-level validation in incident_creation_service handles this instead.
ALTER TABLE incidents DISABLE TRIGGER trigger_validate_custom_fields;

-- Immigration → Enforcement  (higher scrutiny)
UPDATE event_categories
SET required_fields = '["date", "state", "incident_type", "victim_category", "outcome_category"]'::jsonb,
    optional_fields = '["city", "description", "officer_involved", "agency", "victim_name", "victim_age"]'::jsonb,
    updated_at = NOW()
WHERE slug = 'enforcement'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'immigration');

-- Immigration → Crime
UPDATE event_categories
SET required_fields = '["date", "state", "incident_type", "offender_immigration_status"]'::jsonb,
    optional_fields = '["city", "description", "offender_name", "offender_age", "charges", "prior_deportations", "gang_affiliated"]'::jsonb,
    updated_at = NOW()
WHERE slug = 'crime'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'immigration');

-- Criminal Justice categories — minimal: date + state
-- CJ schemas define their own extraction fields; the LLM confidence score
-- already incorporates per-schema field completeness.

UPDATE event_categories
SET required_fields = '["date", "state"]'::jsonb,
    optional_fields = '["city", "description", "charges", "defendant_name", "person_name", "arresting_agency"]'::jsonb,
    updated_at = NOW()
WHERE slug = 'arrest'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'criminal_justice');

UPDATE event_categories
SET required_fields = '["date", "state"]'::jsonb,
    optional_fields = '["city", "description", "charges", "defendant_name", "prosecutor_name", "court_name"]'::jsonb,
    updated_at = NOW()
WHERE slug = 'prosecution'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'criminal_justice');

UPDATE event_categories
SET required_fields = '["date", "state"]'::jsonb,
    optional_fields = '["city", "charges", "verdict", "judge_name", "jury_type", "court_name"]'::jsonb,
    updated_at = NOW()
WHERE slug = 'trial'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'criminal_justice');

UPDATE event_categories
SET required_fields = '["date", "state"]'::jsonb,
    optional_fields = '["city", "sentence", "charges", "defendant_name", "judge_name"]'::jsonb,
    updated_at = NOW()
WHERE slug = 'sentencing'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'criminal_justice');

UPDATE event_categories
SET required_fields = '["date", "state"]'::jsonb,
    optional_fields = '["city", "facility_name", "person_name", "charges"]'::jsonb,
    updated_at = NOW()
WHERE slug = 'incarceration'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'criminal_justice');

UPDATE event_categories
SET required_fields = '["date", "state"]'::jsonb,
    optional_fields = '["city", "person_name", "release_type", "conditions"]'::jsonb,
    updated_at = NOW()
WHERE slug = 'release'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'criminal_justice');

-- Civil Rights categories — minimal: date + state

UPDATE event_categories
SET required_fields = '["date", "state"]'::jsonb,
    optional_fields = '["city", "description", "organizer", "participant_count", "target"]'::jsonb,
    updated_at = NOW()
WHERE slug = 'protest'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'civil_rights');

UPDATE event_categories
SET required_fields = '["date", "state"]'::jsonb,
    optional_fields = '["city", "description", "officer_name", "victim_name", "agency"]'::jsonb,
    updated_at = NOW()
WHERE slug = 'police_force'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'civil_rights');

UPDATE event_categories
SET required_fields = '["date", "state"]'::jsonb,
    optional_fields = '["city", "description", "violation_type", "agency", "victim_name"]'::jsonb,
    updated_at = NOW()
WHERE slug = 'civil_rights_violation'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'civil_rights');

UPDATE event_categories
SET required_fields = '["date", "state"]'::jsonb,
    optional_fields = '["city", "case_name", "court_name", "plaintiff", "defendant", "filing_date"]'::jsonb,
    updated_at = NOW()
WHERE slug = 'litigation'
  AND domain_id = (SELECT id FROM event_domains WHERE slug = 'civil_rights');
