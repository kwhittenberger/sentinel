-- Migration 030: Domain-level relevance gate for Stage 1 extraction
--
-- Adds relevance_scope column to event_domains so each domain can define
-- LLM-readable criteria for what makes an article topically relevant.
-- Updates Stage 1 prompt to evaluate domain relevance as part of extraction.

BEGIN;

-- 1. Add relevance_scope column (nullable for backward compatibility)
ALTER TABLE event_domains ADD COLUMN IF NOT EXISTS relevance_scope TEXT;

-- 2. Seed relevance scopes for existing domains
UPDATE event_domains SET relevance_scope =
    'Must be a US incident involving individuals with non-citizen immigration status AND involve ICE/CBP/ERO or immigration-status-centric crime reporting. Not general immigration policy debate. Not events outside the US.'
WHERE slug = 'immigration';

UPDATE event_domains SET relevance_scope =
    'Must be US criminal proceedings where at least one person has non-citizen immigration status, OR where ICE/CBP are directly involved. General crime news without immigration nexus is not relevant.'
WHERE slug = 'criminal_justice';

UPDATE event_domains SET relevance_scope =
    'Must be US civil rights incidents directly related to immigration enforcement, immigration policy, or treatment of immigrants by government/law enforcement. General civil rights without immigration nexus is not relevant.'
WHERE slug = 'civil_rights';

-- 3. Update Stage 1 system prompt to include domain relevance evaluation
UPDATE extraction_schemas SET
    system_prompt = 'You are an expert entity and event extraction system. Your job is to produce a comprehensive, structured intermediate representation (IR) from news articles.

You extract ALL entities (persons, organizations, locations), ALL events, legal data, direct quotes, and policy context. You also provide classification hints for downstream processing.

RULES:
1. Every entity gets a unique ID (p1, p2... for persons; o1, o2... for organizations; l1, l2... for locations)
2. Events reference entity IDs via participants and location_id
3. Extract ALL events mentioned, not just the primary one
4. classification_hints indicate which downstream schemas should process this article
5. Confidence scores: 1.0 = verbatim, 0.8-0.9 = clearly stated, 0.6-0.7 = strongly implied, 0.4-0.5 = reasonable inference, below 0.4 = weak
6. Always return valid JSON matching the IR schema exactly

DOMAIN RELEVANCE:
You MUST evaluate whether the article is topically relevant to each configured domain.
For each domain listed in the user prompt, assess whether the article falls within that domain''s relevance scope.
Return a domain_relevance array with one entry per configured domain containing:
- domain_slug: the domain identifier
- is_relevant: true/false
- confidence: how confident you are in the relevance assessment (0.0 to 1.0)
- reasoning: brief explanation of why the article is or is not relevant to this domain

An article that is off-topic for ALL domains should still have full entity extraction, but every domain_relevance entry will have is_relevant=false.',

    user_prompt_template = 'Extract all entities, events, and structured data from this article into the intermediate representation format.

DOMAIN RELEVANCE CRITERIA:
Evaluate the article against each of these domain-specific relevance scopes:
{domain_relevance_criteria}

ARTICLE TEXT:
{article_text}

Return JSON with this exact structure:
{
  "article_meta": { "primary_topic": "...", "article_type": "news|court_document|press_release|opinion" },
  "domain_relevance": [
    {"domain_slug": "...", "is_relevant": true, "confidence": 0.95, "reasoning": "..."}
  ],
  "classification_hints": [
    {"domain_slug": "...", "category_slug": "...", "confidence": 0.0}
  ],
  "entities": {
    "persons": [{ "id": "p1", "name": "...", "roles": ["defendant","victim","officer",...], "age": null, "gender": null, "nationality": null, "immigration_status": null, "criminal_history": { "prior_arrests": null, "prior_convictions": null, "prior_deportations": null, "gang_affiliation": null }, "mentioned_in_events": ["e1"] }],
    "organizations": [{ "id": "o1", "name": "...", "org_type": "federal_agency|local_police|court|advocacy|other", "mentioned_in_events": ["e1"] }],
    "locations": [{ "id": "l1", "name": "...", "city": null, "county": null, "state": null, "address": null, "location_type": null, "mentioned_in_events": ["e1"] }]
  },
  "events": [
    { "id": "e1", "event_type": "arrest|prosecution|trial|sentencing|incarceration|release|protest|police_force|civil_rights_violation|litigation|crime|enforcement|deportation|detention|raid", "date": "YYYY-MM-DD or null", "date_approximate": false, "location_id": "l1", "description": "...", "participants": [{"entity_id": "p1", "role": "arrested|arresting_agency|defendant|prosecutor|judge|victim|witness|protester|officer"}], "charges": [], "outcome": null, "is_primary_event": true }
  ],
  "legal_data": { "case_numbers": [], "charges": [{"charge": "...", "severity": "felony|misdemeanor|infraction", "statute": null}], "dispositions": [{"charge": "...", "outcome": "convicted|acquitted|dismissed|plea|pending"}], "sentences": [{"type": "prison|probation|fine|restitution|community_service", "duration": null, "amount": null}] },
  "quotes": [{ "text": "...", "speaker": "...", "speaker_entity_id": "o1 or p1" }],
  "policy_context": { "sanctuary_jurisdiction": null, "ice_detainer_status": "issued|honored|ignored|not_applicable|unknown", "relevant_policies": [] },
  "source_attributions": ["ICE press release", "court records", ...],
  "extraction_confidence": 0.87,
  "extraction_notes": "..."
}',
    updated_at = NOW()
WHERE schema_type = 'stage1' AND is_active = TRUE;

COMMIT;
