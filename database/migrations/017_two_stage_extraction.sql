-- Migration 017: Two-Stage Extraction Pipeline
-- Adds article_extractions (Stage 1 IR storage), schema_extraction_results (Stage 2 output),
-- and extends extraction_schemas and ingested_articles for two-stage pipeline support.

-- ============================================================================
-- 1. NEW TABLE: article_extractions (Stage 1 IR)
-- ============================================================================

CREATE TABLE article_extractions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    article_id UUID NOT NULL REFERENCES ingested_articles(id) ON DELETE CASCADE,
    extraction_data JSONB NOT NULL,            -- Full Stage 1 IR (entities, events, legal, quotes)
    classification_hints JSONB DEFAULT '[]',   -- [{domain_slug, category_slug, confidence}]
    entity_count INTEGER,
    event_count INTEGER,
    overall_confidence DECIMAL(3,2),
    extraction_notes TEXT,
    stage1_schema_version INTEGER NOT NULL DEFAULT 1,
    stage1_prompt_hash VARCHAR(64),            -- SHA256 of prompt used (staleness detection)
    provider VARCHAR(50),
    model VARCHAR(100),
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_ms INTEGER,
    status VARCHAR(20) DEFAULT 'completed' CHECK (status IN ('pending','completed','failed','stale')),
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_article_extractions_article ON article_extractions(article_id);
CREATE INDEX idx_article_extractions_status ON article_extractions(status);
CREATE INDEX idx_article_extractions_classification ON article_extractions USING gin(classification_hints);

-- Auto-update timestamp
CREATE TRIGGER update_article_extractions_timestamp
    BEFORE UPDATE ON article_extractions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- ============================================================================
-- 2. NEW TABLE: schema_extraction_results (Stage 2 per-schema output)
-- ============================================================================

CREATE TABLE schema_extraction_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    article_extraction_id UUID NOT NULL REFERENCES article_extractions(id) ON DELETE CASCADE,
    schema_id UUID NOT NULL REFERENCES extraction_schemas(id),
    article_id UUID NOT NULL REFERENCES ingested_articles(id),
    extracted_data JSONB NOT NULL,             -- Domain-specific structured output
    confidence DECIMAL(3,2),
    validation_errors JSONB DEFAULT '[]',
    provider VARCHAR(50),
    model VARCHAR(100),
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_ms INTEGER,
    used_original_text BOOLEAN DEFAULT FALSE,  -- True if Stage 2 needed raw article fallback
    stage1_version INTEGER,
    status VARCHAR(20) DEFAULT 'completed' CHECK (status IN ('pending','completed','failed','superseded')),
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(article_extraction_id, schema_id)
);

CREATE INDEX idx_schema_results_extraction ON schema_extraction_results(article_extraction_id);
CREATE INDEX idx_schema_results_schema ON schema_extraction_results(schema_id);
CREATE INDEX idx_schema_results_article ON schema_extraction_results(article_id);

-- Auto-update timestamp
CREATE TRIGGER update_schema_extraction_results_timestamp
    BEFORE UPDATE ON schema_extraction_results
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- ============================================================================
-- 3. ALTER extraction_schemas: add schema_type and input_format
-- ============================================================================

ALTER TABLE extraction_schemas
    ADD COLUMN schema_type VARCHAR(20) DEFAULT 'legacy'
        CHECK (schema_type IN ('stage1', 'stage2', 'legacy')),
    ADD COLUMN input_format VARCHAR(20) DEFAULT 'article_text'
        CHECK (input_format IN ('article_text', 'stage1_output', 'both'));

-- Backfill existing schemas
UPDATE extraction_schemas SET schema_type = 'legacy', input_format = 'article_text';

-- ============================================================================
-- 4. ALTER ingested_articles: track pipeline type and latest extraction
-- ============================================================================

ALTER TABLE ingested_articles
    ADD COLUMN latest_extraction_id UUID REFERENCES article_extractions(id),
    ADD COLUMN extraction_pipeline VARCHAR(20) DEFAULT 'legacy'
        CHECK (extraction_pipeline IN ('legacy', 'two_stage'));

-- ============================================================================
-- 5. SEED: Stage 1 comprehensive extraction schema
-- ============================================================================

INSERT INTO extraction_schemas (
    domain_id, category_id, name, description,
    schema_type, input_format,
    system_prompt, user_prompt_template,
    model_name, temperature, max_tokens,
    required_fields, optional_fields, field_definitions,
    is_active, is_production
) VALUES (
    NULL, NULL,
    'Stage 1: Comprehensive Entity Extraction',
    'Extracts all entities, events, legal data, quotes, and classification hints from raw article text. Produces a graph-structured intermediate representation for downstream Stage 2 schemas.',
    'stage1', 'article_text',
    -- system_prompt
    E'You are an expert entity and event extraction system. Your job is to produce a comprehensive, structured intermediate representation (IR) from news articles.\n\nYou extract ALL entities (persons, organizations, locations), ALL events, legal data, direct quotes, and policy context. You also provide classification hints for downstream processing.\n\nRULES:\n1. Every entity gets a unique ID (p1, p2... for persons; o1, o2... for organizations; l1, l2... for locations)\n2. Events reference entity IDs via participants and location_id\n3. Extract ALL events mentioned, not just the primary one\n4. classification_hints indicate which downstream schemas should process this article\n5. Confidence scores: 1.0 = verbatim, 0.8-0.9 = clearly stated, 0.6-0.7 = strongly implied, 0.4-0.5 = reasonable inference, below 0.4 = weak\n6. Always return valid JSON matching the IR schema exactly',
    -- user_prompt_template
    E'Extract all entities, events, and structured data from this article into the intermediate representation format.\n\nARTICLE TEXT:\n{article_text}\n\nReturn JSON with this exact structure:\n{\n  "article_meta": { "primary_topic": "...", "article_type": "news|court_document|press_release|opinion" },\n  "classification_hints": [\n    {"domain_slug": "...", "category_slug": "...", "confidence": 0.0}\n  ],\n  "entities": {\n    "persons": [{ "id": "p1", "name": "...", "roles": ["defendant","victim","officer",...], "age": null, "gender": null, "nationality": null, "immigration_status": null, "criminal_history": { "prior_arrests": null, "prior_convictions": null, "prior_deportations": null, "gang_affiliation": null }, "mentioned_in_events": ["e1"] }],\n    "organizations": [{ "id": "o1", "name": "...", "org_type": "federal_agency|local_police|court|advocacy|other", "mentioned_in_events": ["e1"] }],\n    "locations": [{ "id": "l1", "name": "...", "city": null, "county": null, "state": null, "address": null, "location_type": null, "mentioned_in_events": ["e1"] }]\n  },\n  "events": [\n    { "id": "e1", "event_type": "arrest|prosecution|trial|sentencing|incarceration|release|protest|police_force|civil_rights_violation|litigation|crime|enforcement|deportation|detention|raid", "date": "YYYY-MM-DD or null", "date_approximate": false, "location_id": "l1", "description": "...", "participants": [{"entity_id": "p1", "role": "arrested|arresting_agency|defendant|prosecutor|judge|victim|witness|protester|officer"}], "charges": [], "outcome": null, "is_primary_event": true }\n  ],\n  "legal_data": { "case_numbers": [], "charges": [{"charge": "...", "severity": "felony|misdemeanor|infraction", "statute": null}], "dispositions": [{"charge": "...", "outcome": "convicted|acquitted|dismissed|plea|pending"}], "sentences": [{"type": "prison|probation|fine|restitution|community_service", "duration": null, "amount": null}] },\n  "quotes": [{ "text": "...", "speaker": "...", "speaker_entity_id": "o1 or p1" }],\n  "policy_context": { "sanctuary_jurisdiction": null, "ice_detainer_status": "issued|honored|ignored|not_applicable|unknown", "relevant_policies": [] },\n  "source_attributions": ["ICE press release", "court records", ...],\n  "extraction_confidence": 0.87,\n  "extraction_notes": "..."\n}',
    -- model config
    'claude-sonnet-4-5', 0.3, 8000,
    -- fields
    '["entities", "events", "classification_hints"]'::jsonb,
    '["legal_data", "quotes", "policy_context", "source_attributions"]'::jsonb,
    '{}'::jsonb,
    TRUE, TRUE
);

-- ============================================================================
-- 6. SEED: Stage 2 schemas (11 categories)
-- ============================================================================

-- Helper: get domain/category IDs
-- We use subqueries to reference event_domains/event_categories by slug.

-- 6a. Immigration / Enforcement
INSERT INTO extraction_schemas (
    domain_id, category_id, name, description,
    schema_type, input_format,
    system_prompt, user_prompt_template,
    model_name, temperature, max_tokens,
    required_fields, optional_fields,
    is_active
) VALUES (
    (SELECT id FROM event_domains WHERE slug = 'immigration'),
    (SELECT id FROM event_categories WHERE slug = 'enforcement'),
    'Stage 2: Immigration Enforcement',
    'Extracts enforcement incident details from Stage 1 IR + article text.',
    'stage2', 'both',
    E'You are extracting structured data about ICE/CBP enforcement incidents that harmed non-immigrants (protesters, journalists, bystanders, US citizens, officers).\n\nYou receive:\n1. A Stage 1 intermediate representation (entities, events, legal data) already extracted\n2. The original article text for disambiguation\n\nUse Stage 1 entities/events as your primary source. Only consult the original article when Stage 1 data is ambiguous or incomplete.\n\nReturn valid JSON matching the required schema.',
    E'Using the Stage 1 extraction and original article, extract enforcement incident data.\n\nSTAGE 1 EXTRACTION:\n{stage1_output}\n\nORIGINAL ARTICLE:\n{article_text}\n\nReturn JSON:\n{\n  "date": "YYYY-MM-DD",\n  "state": "XX (2-letter)",\n  "city": null,\n  "incident_type": "death_in_custody|shooting|taser|pepper_spray|physical_force|vehicle_pursuit|raid_injury|medical_neglect|wrongful_detention|property_damage|protest_clash|journalist_interference",\n  "victim_category": "detainee|enforcement_target|protester|journalist|bystander|us_citizen_collateral|officer|multiple",\n  "outcome_category": "death|serious_injury|minor_injury|no_injury|unknown",\n  "agency": "ICE|CBP|HSI|other",\n  "victim_name": null,\n  "victim_age": null,\n  "officer_involved": true,\n  "description": "2-3 sentence summary",\n  "charges": [],\n  "confidence": 0.0,\n  "extraction_notes": ""\n}',
    'claude-sonnet-4-5', 0.3, 4000,
    '["date", "state", "incident_type", "victim_category", "outcome_category", "agency"]'::jsonb,
    '["victim_name", "victim_age", "officer_involved", "city", "description", "charges"]'::jsonb,
    TRUE
);

-- 6b. Immigration / Crime
INSERT INTO extraction_schemas (
    domain_id, category_id, name, description,
    schema_type, input_format,
    system_prompt, user_prompt_template,
    model_name, temperature, max_tokens,
    required_fields, optional_fields,
    is_active
) VALUES (
    (SELECT id FROM event_domains WHERE slug = 'immigration'),
    (SELECT id FROM event_categories WHERE slug = 'crime'),
    'Stage 2: Immigration Crime',
    'Extracts crime incident details committed by individuals with immigration status issues.',
    'stage2', 'both',
    E'You are extracting structured data about crimes committed by individuals with immigration status issues.\n\nYou receive Stage 1 IR + original article. Use Stage 1 entities as primary source.\n\nFocus on: offender identity, immigration status, criminal history, gang/cartel connections, ICE detainer status, and policy failures.\n\nReturn valid JSON.',
    E'Using the Stage 1 extraction and original article, extract crime incident data.\n\nSTAGE 1 EXTRACTION:\n{stage1_output}\n\nORIGINAL ARTICLE:\n{article_text}\n\nReturn JSON:\n{\n  "date": "YYYY-MM-DD",\n  "state": "XX",\n  "city": null,\n  "incident_type": "homicide|assault|robbery|dui_fatality|sexual_assault|kidnapping|gang_activity|drug_trafficking|human_trafficking|fraud|identity_theft|illegal_reentry|child_abuse",\n  "offender_name": "REQUIRED",\n  "offender_age": null,\n  "offender_gender": "male|female|unknown",\n  "offender_nationality": null,\n  "immigration_status": "undocumented|visa_overstay|DACA|TPS|legal_resident|unknown",\n  "prior_deportations": 0,\n  "prior_arrests": null,\n  "prior_convictions": null,\n  "gang_affiliated": false,\n  "gang_name": null,\n  "ice_detainer_ignored": false,\n  "was_released_sanctuary": false,\n  "was_released_bail": false,\n  "charges": [],\n  "crime_victim_count": null,\n  "involves_fatality": false,\n  "outcome_category": "death|serious_injury|minor_injury|no_injury|unknown",\n  "description": "2-3 sentence summary",\n  "confidence": 0.0,\n  "extraction_notes": ""\n}',
    'claude-sonnet-4-5', 0.3, 4000,
    '["date", "state", "incident_type", "offender_name", "immigration_status"]'::jsonb,
    '["offender_age", "offender_gender", "offender_nationality", "prior_deportations", "gang_affiliated", "ice_detainer_ignored", "charges", "crime_victim_count", "involves_fatality"]'::jsonb,
    TRUE
);

-- 6c. Criminal Justice / Arrest
INSERT INTO extraction_schemas (
    domain_id, category_id, name, description,
    schema_type, input_format,
    system_prompt, user_prompt_template,
    model_name, temperature, max_tokens,
    required_fields, optional_fields,
    is_active
) VALUES (
    (SELECT id FROM event_domains WHERE slug = 'criminal_justice'),
    (SELECT id FROM event_categories WHERE slug = 'arrest'),
    'Stage 2: Criminal Justice Arrest',
    'Extracts arrest event details from Stage 1 IR.',
    'stage2', 'both',
    E'You are extracting structured arrest data. Use Stage 1 IR entities/events as primary source, original article for disambiguation.\n\nReturn valid JSON.',
    E'Extract arrest event data.\n\nSTAGE 1 EXTRACTION:\n{stage1_output}\n\nORIGINAL ARTICLE:\n{article_text}\n\nReturn JSON:\n{\n  "date": "YYYY-MM-DD",\n  "location": {"city": null, "state": "XX", "county": null},\n  "person_name": "REQUIRED",\n  "person_age": null,\n  "charges": ["charge1", "charge2"],\n  "arresting_agency": "ICE|CBP|local_police|sheriff|state_police|FBI|other",\n  "bail_amount": null,\n  "bail_status": "set|denied|released_or|released_pr|unknown",\n  "arrest_context": "warrant|traffic_stop|raid|workplace|courthouse|other",\n  "immigration_related": false,\n  "confidence": 0.0,\n  "extraction_notes": ""\n}',
    'claude-sonnet-4-5', 0.3, 3000,
    '["date", "person_name", "charges", "arresting_agency"]'::jsonb,
    '["person_age", "bail_amount", "bail_status", "arrest_context", "immigration_related", "location"]'::jsonb,
    TRUE
);

-- 6d. Criminal Justice / Prosecution (update existing or insert new stage2)
INSERT INTO extraction_schemas (
    domain_id, category_id, name, description,
    schema_type, input_format,
    system_prompt, user_prompt_template,
    model_name, temperature, max_tokens,
    required_fields, optional_fields,
    is_active
) VALUES (
    (SELECT id FROM event_domains WHERE slug = 'criminal_justice'),
    (SELECT id FROM event_categories WHERE slug = 'prosecution'),
    'Stage 2: Criminal Justice Prosecution',
    'Extracts prosecution event details from Stage 1 IR.',
    'stage2', 'both',
    E'You are extracting structured prosecution data. Use Stage 1 IR as primary source.\n\nReturn valid JSON.',
    E'Extract prosecution event data.\n\nSTAGE 1 EXTRACTION:\n{stage1_output}\n\nORIGINAL ARTICLE:\n{article_text}\n\nReturn JSON:\n{\n  "prosecutor_name": null,\n  "prosecutor_office": null,\n  "defendant_name": "REQUIRED",\n  "defendant_age": null,\n  "charges": ["charge1"],\n  "disposition": "convicted|acquitted|dismissed|plea_deal|pending|mistrial",\n  "plea_offer": null,\n  "amended_charges": [],\n  "reasoning": null,\n  "filing_date": null,\n  "court_name": null,\n  "jurisdiction": null,\n  "confidence": 0.0,\n  "extraction_notes": ""\n}',
    'claude-sonnet-4-5', 0.3, 3000,
    '["defendant_name", "charges", "disposition"]'::jsonb,
    '["prosecutor_name", "prosecutor_office", "plea_offer", "amended_charges", "reasoning", "filing_date", "court_name"]'::jsonb,
    TRUE
);

-- 6e. Criminal Justice / Trial
INSERT INTO extraction_schemas (
    domain_id, category_id, name, description,
    schema_type, input_format,
    system_prompt, user_prompt_template,
    model_name, temperature, max_tokens,
    required_fields, optional_fields,
    is_active
) VALUES (
    (SELECT id FROM event_domains WHERE slug = 'criminal_justice'),
    (SELECT id FROM event_categories WHERE slug = 'trial'),
    'Stage 2: Criminal Justice Trial',
    'Extracts trial event details from Stage 1 IR.',
    'stage2', 'both',
    E'You are extracting structured trial data. Use Stage 1 IR as primary source.\n\nReturn valid JSON.',
    E'Extract trial event data.\n\nSTAGE 1 EXTRACTION:\n{stage1_output}\n\nORIGINAL ARTICLE:\n{article_text}\n\nReturn JSON:\n{\n  "defendant_name": "REQUIRED",\n  "trial_date": "YYYY-MM-DD",\n  "court_name": null,\n  "verdict": "guilty|not_guilty|hung_jury|mistrial|pending",\n  "judge_name": null,\n  "jury_type": "jury|bench|grand_jury",\n  "charges_tried": [],\n  "key_testimony": null,\n  "trial_duration_days": null,\n  "confidence": 0.0,\n  "extraction_notes": ""\n}',
    'claude-sonnet-4-5', 0.3, 3000,
    '["defendant_name", "trial_date", "court_name", "verdict"]'::jsonb,
    '["judge_name", "jury_type", "charges_tried", "key_testimony", "trial_duration_days"]'::jsonb,
    TRUE
);

-- 6f. Criminal Justice / Sentencing
INSERT INTO extraction_schemas (
    domain_id, category_id, name, description,
    schema_type, input_format,
    system_prompt, user_prompt_template,
    model_name, temperature, max_tokens,
    required_fields, optional_fields,
    is_active
) VALUES (
    (SELECT id FROM event_domains WHERE slug = 'criminal_justice'),
    (SELECT id FROM event_categories WHERE slug = 'sentencing'),
    'Stage 2: Criminal Justice Sentencing',
    'Extracts sentencing event details from Stage 1 IR.',
    'stage2', 'both',
    E'You are extracting structured sentencing data. Use Stage 1 IR as primary source.\n\nReturn valid JSON.',
    E'Extract sentencing event data.\n\nSTAGE 1 EXTRACTION:\n{stage1_output}\n\nORIGINAL ARTICLE:\n{article_text}\n\nReturn JSON:\n{\n  "defendant_name": "REQUIRED",\n  "sentencing_date": "YYYY-MM-DD",\n  "sentence": "e.g. 15 years prison",\n  "judge_name": null,\n  "guidelines_range": null,\n  "departure_reason": null,\n  "restitution": null,\n  "charges_sentenced": [],\n  "court_name": null,\n  "confidence": 0.0,\n  "extraction_notes": ""\n}',
    'claude-sonnet-4-5', 0.3, 3000,
    '["defendant_name", "sentencing_date", "sentence", "judge_name"]'::jsonb,
    '["guidelines_range", "departure_reason", "restitution", "charges_sentenced", "court_name"]'::jsonb,
    TRUE
);

-- 6g. Criminal Justice / Incarceration
INSERT INTO extraction_schemas (
    domain_id, category_id, name, description,
    schema_type, input_format,
    system_prompt, user_prompt_template,
    model_name, temperature, max_tokens,
    required_fields, optional_fields,
    is_active
) VALUES (
    (SELECT id FROM event_domains WHERE slug = 'criminal_justice'),
    (SELECT id FROM event_categories WHERE slug = 'incarceration'),
    'Stage 2: Criminal Justice Incarceration',
    'Extracts incarceration event details from Stage 1 IR.',
    'stage2', 'both',
    E'You are extracting structured incarceration data. Use Stage 1 IR as primary source.\n\nReturn valid JSON.',
    E'Extract incarceration event data.\n\nSTAGE 1 EXTRACTION:\n{stage1_output}\n\nORIGINAL ARTICLE:\n{article_text}\n\nReturn JSON:\n{\n  "person_name": "REQUIRED",\n  "facility_name": null,\n  "facility_type": "federal_prison|state_prison|county_jail|detention_center|other",\n  "date": "YYYY-MM-DD",\n  "sentence_remaining": null,\n  "charges": [],\n  "confidence": 0.0,\n  "extraction_notes": ""\n}',
    'claude-sonnet-4-5', 0.3, 3000,
    '["person_name", "facility_name", "date"]'::jsonb,
    '["facility_type", "sentence_remaining", "charges"]'::jsonb,
    TRUE
);

-- 6h. Criminal Justice / Release
INSERT INTO extraction_schemas (
    domain_id, category_id, name, description,
    schema_type, input_format,
    system_prompt, user_prompt_template,
    model_name, temperature, max_tokens,
    required_fields, optional_fields,
    is_active
) VALUES (
    (SELECT id FROM event_domains WHERE slug = 'criminal_justice'),
    (SELECT id FROM event_categories WHERE slug = 'release'),
    'Stage 2: Criminal Justice Release',
    'Extracts release event details from Stage 1 IR.',
    'stage2', 'both',
    E'You are extracting structured release data. Use Stage 1 IR as primary source.\n\nReturn valid JSON.',
    E'Extract release event data.\n\nSTAGE 1 EXTRACTION:\n{stage1_output}\n\nORIGINAL ARTICLE:\n{article_text}\n\nReturn JSON:\n{\n  "person_name": "REQUIRED",\n  "release_date": "YYYY-MM-DD",\n  "release_reason": "bail|bond|served_sentence|parole|court_order|ice_detainer_ignored|other",\n  "conditions": null,\n  "bond_amount": null,\n  "detainer_status": "honored|ignored|none|unknown",\n  "releasing_facility": null,\n  "confidence": 0.0,\n  "extraction_notes": ""\n}',
    'claude-sonnet-4-5', 0.3, 3000,
    '["person_name", "release_date", "release_reason"]'::jsonb,
    '["conditions", "bond_amount", "detainer_status", "releasing_facility"]'::jsonb,
    TRUE
);

-- 6i. Civil Rights / Protest
INSERT INTO extraction_schemas (
    domain_id, category_id, name, description,
    schema_type, input_format,
    system_prompt, user_prompt_template,
    model_name, temperature, max_tokens,
    required_fields, optional_fields,
    is_active
) VALUES (
    (SELECT id FROM event_domains WHERE slug = 'civil_rights'),
    (SELECT id FROM event_categories WHERE slug = 'protest'),
    'Stage 2: Civil Rights Protest',
    'Extracts protest event details from Stage 1 IR.',
    'stage2', 'both',
    E'You are extracting structured protest data. Use Stage 1 IR as primary source.\n\nReturn valid JSON.',
    E'Extract protest event data.\n\nSTAGE 1 EXTRACTION:\n{stage1_output}\n\nORIGINAL ARTICLE:\n{article_text}\n\nReturn JSON:\n{\n  "date": "YYYY-MM-DD",\n  "location": {"city": null, "state": "XX", "address": null},\n  "event_description": "REQUIRED",\n  "participant_count": null,\n  "organizer_names": [],\n  "police_response": null,\n  "arrests_count": null,\n  "injuries_count": null,\n  "cause": null,\n  "confidence": 0.0,\n  "extraction_notes": ""\n}',
    'claude-sonnet-4-5', 0.3, 3000,
    '["date", "event_description", "participant_count"]'::jsonb,
    '["organizer_names", "police_response", "arrests_count", "injuries_count", "cause", "location"]'::jsonb,
    TRUE
);

-- 6j. Civil Rights / Police Force
INSERT INTO extraction_schemas (
    domain_id, category_id, name, description,
    schema_type, input_format,
    system_prompt, user_prompt_template,
    model_name, temperature, max_tokens,
    required_fields, optional_fields,
    is_active
) VALUES (
    (SELECT id FROM event_domains WHERE slug = 'civil_rights'),
    (SELECT id FROM event_categories WHERE slug = 'police_force'),
    'Stage 2: Civil Rights Police Force',
    'Extracts police use-of-force event details from Stage 1 IR.',
    'stage2', 'both',
    E'You are extracting structured police use-of-force data. Use Stage 1 IR as primary source.\n\nReturn valid JSON.',
    E'Extract police force event data.\n\nSTAGE 1 EXTRACTION:\n{stage1_output}\n\nORIGINAL ARTICLE:\n{article_text}\n\nReturn JSON:\n{\n  "date": "YYYY-MM-DD",\n  "location": {"city": null, "state": "XX"},\n  "force_type": "shooting|taser|pepper_spray|baton|physical|vehicle|other",\n  "subject_name": null,\n  "outcome_severity": "death|serious_injury|minor_injury|no_injury|unknown",\n  "officer_name": null,\n  "officer_agency": null,\n  "body_camera_status": "on|off|not_equipped|unknown",\n  "subject_armed": null,\n  "description": null,\n  "confidence": 0.0,\n  "extraction_notes": ""\n}',
    'claude-sonnet-4-5', 0.3, 3000,
    '["date", "force_type", "subject_name", "outcome_severity"]'::jsonb,
    '["officer_name", "officer_agency", "body_camera_status", "subject_armed", "description", "location"]'::jsonb,
    TRUE
);

-- 6k. Civil Rights / Civil Rights Violation
INSERT INTO extraction_schemas (
    domain_id, category_id, name, description,
    schema_type, input_format,
    system_prompt, user_prompt_template,
    model_name, temperature, max_tokens,
    required_fields, optional_fields,
    is_active
) VALUES (
    (SELECT id FROM event_domains WHERE slug = 'civil_rights'),
    (SELECT id FROM event_categories WHERE slug = 'civil_rights_violation'),
    'Stage 2: Civil Rights Violation',
    'Extracts civil rights violation details from Stage 1 IR.',
    'stage2', 'both',
    E'You are extracting structured civil rights violation data. Use Stage 1 IR as primary source.\n\nReturn valid JSON.',
    E'Extract civil rights violation data.\n\nSTAGE 1 EXTRACTION:\n{stage1_output}\n\nORIGINAL ARTICLE:\n{article_text}\n\nReturn JSON:\n{\n  "date": "YYYY-MM-DD",\n  "location": {"city": null, "state": "XX"},\n  "violation_type": "unlawful_search|unlawful_detention|excessive_force|discrimination|retaliation|due_process|other",\n  "victim_description": null,\n  "amendment": "1st|4th|5th|8th|14th|other",\n  "agency": null,\n  "legal_action": null,\n  "description": null,\n  "confidence": 0.0,\n  "extraction_notes": ""\n}',
    'claude-sonnet-4-5', 0.3, 3000,
    '["date", "violation_type", "victim_description"]'::jsonb,
    '["amendment", "agency", "legal_action", "description", "location"]'::jsonb,
    TRUE
);

-- 6l. Civil Rights / Litigation
INSERT INTO extraction_schemas (
    domain_id, category_id, name, description,
    schema_type, input_format,
    system_prompt, user_prompt_template,
    model_name, temperature, max_tokens,
    required_fields, optional_fields,
    is_active
) VALUES (
    (SELECT id FROM event_domains WHERE slug = 'civil_rights'),
    (SELECT id FROM event_categories WHERE slug = 'litigation'),
    'Stage 2: Civil Rights Litigation',
    'Extracts litigation event details from Stage 1 IR.',
    'stage2', 'both',
    E'You are extracting structured litigation data. Use Stage 1 IR as primary source.\n\nReturn valid JSON.',
    E'Extract litigation event data.\n\nSTAGE 1 EXTRACTION:\n{stage1_output}\n\nORIGINAL ARTICLE:\n{article_text}\n\nReturn JSON:\n{\n  "case_name": "REQUIRED",\n  "court": null,\n  "filing_date": "YYYY-MM-DD",\n  "legal_claims": [],\n  "plaintiff": null,\n  "defendant": null,\n  "damages_sought": null,\n  "settlement": null,\n  "appeal_status": null,\n  "judge_name": null,\n  "case_status": "filed|pending|settled|dismissed|appealed|decided",\n  "confidence": 0.0,\n  "extraction_notes": ""\n}',
    'claude-sonnet-4-5', 0.3, 3000,
    '["case_name", "court", "filing_date", "legal_claims"]'::jsonb,
    '["plaintiff", "defendant", "damages_sought", "settlement", "appeal_status", "judge_name", "case_status"]'::jsonb,
    TRUE
);
