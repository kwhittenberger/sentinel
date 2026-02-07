# Data Dictionary

This document maps Sentinel's business concepts to their database representations. For the complete column-level schema, see `database/schema.sql`.

---

## Data Model Overview

Sentinel uses three coexisting data layers, introduced incrementally:

| Layer | Model | Status | Key Tables |
|-------|-------|--------|------------|
| **Layer 1** | Person-centric | Legacy | `persons`, `incident_persons` |
| **Layer 2** | Event-centric | Active (preferred) | `actors`, `incident_actors`, `events`, `incident_events` |
| **Layer 3** | Case-centric | Active | `cases`, `charges`, `dispositions`, `bail_decisions` |

All three layers share the core `incidents` table as their central entity.

```
Sources  -->  Ingested Articles  -->  Extractions  -->  Incidents
                                                          |
                                     +--------------------+--------------------+
                                     |                    |                    |
                                   Actors              Events               Cases
                                     |                                        |
                              Actor Relations                          Charges / Dispositions
```

---

## Core Entities

### Incident

**Business definition:** A discrete real-world event that has been reviewed and approved for tracking. Incidents are the central entity in the system -- articles, actors, events, and cases all connect through incidents.

**Table:** `incidents`

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `category` | ENUM | `enforcement` or `crime` (legacy discriminator) |
| `domain_id` | UUID FK | Event domain (e.g., "Criminal Justice", "Immigration") |
| `category_id` | UUID FK | Event category within the domain |
| `date` | DATE | When the incident occurred |
| `date_precision` | VARCHAR | `day`, `month`, or `year` -- how precise the date is |
| `incident_type_id` | UUID FK | References `incident_types` (e.g., homicide, assault, raid_injury) |
| `state` | VARCHAR | US state where the incident occurred |
| `city` | VARCHAR | City (nullable) |
| `latitude` / `longitude` | DECIMAL | Geocoded coordinates for map display |
| `title` | VARCHAR | Short summary of the incident |
| `description` | TEXT | Detailed narrative |
| `source_tier` | ENUM | Source reliability: `1` (highest) through `4` (lowest) |
| `source_url` | TEXT | Primary source article URL (unique constraint) |
| `extraction_confidence` | DECIMAL | 0.00-1.00 confidence from LLM extraction |
| `curation_status` | ENUM | Workflow state (see lifecycle below) |
| `custom_fields` | JSONB | Flexible per-category fields |
| `tags` | TEXT[] | Freeform tags for categorization |

**Lifecycle:** `pending` -> `in_review` -> `approved` / `rejected` / `error`

Only `approved` incidents appear in the public dashboard (via `incidents_summary` view).

**Key relationships:**
- `incident_types` -- classifies the type with a severity weight
- `incident_actors` -- links actors to the incident with roles
- `incident_events` -- groups incidents into broader events
- `incident_sources` -- multiple source articles per incident
- `case_incidents` -- links to legal cases
- `event_relationships` -- directional relationships between incidents (e.g., "led_to", "same_arrest")

---

### Article (Ingested Article)

**Business definition:** A raw news article fetched from an RSS feed or other source, awaiting extraction and curation. Articles flow through the pipeline: fetch -> extract -> deduplicate -> auto-approve or queue for review.

**Table:** `ingested_articles`

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `source_id` | UUID FK | The `sources` entry this was fetched from |
| `source_name` | VARCHAR | Denormalized source name for display |
| `source_url` | TEXT | Original article URL (unique -- prevents re-ingestion) |
| `title` | VARCHAR | Article headline |
| `content` | TEXT | Full article text (used for LLM extraction) |
| `content_hash` | VARCHAR | MD5 hash for content-level deduplication |
| `published_date` | DATE | When the article was published |
| `fetched_at` | TIMESTAMPTZ | When Sentinel downloaded the article |
| `relevance_score` | DECIMAL | 0.00-1.00 relevance to tracked domains |
| `extracted_data` | JSONB | Legacy one-shot extraction output |
| `extraction_confidence` | DECIMAL | Confidence from legacy extraction |
| `extraction_pipeline` | VARCHAR | `legacy` or `two_stage` -- which extraction path was used |
| `latest_extraction_id` | UUID FK | Points to the most recent `article_extractions` row (two-stage) |
| `status` | ENUM | Curation workflow state |
| `incident_id` | UUID FK | Linked incident (set when article is approved into an incident) |
| `extraction_error_count` | INTEGER | Number of failed extraction attempts |
| `last_extraction_error` | TEXT | Most recent error message |
| `extraction_error_category` | VARCHAR | `permanent` or transient -- permanent errors skip retries |

**Lifecycle:** `pending` -> `in_review` -> `approved` (linked to incident) / `rejected` / `error`

**Key indexes:**
- `idx_articles_extractable` -- partial index for articles eligible for extraction (pending, has content, not permanently errored, under 3 errors)
- `idx_ingested_curation_queue` -- optimized for the curation UI sort order

---

### Extraction (Two-Stage Pipeline)

**Business definition:** The LLM-powered extraction system analyzes article text in two stages. Stage 1 produces a domain-agnostic intermediate representation (entities, events, relationships). Stage 2 maps that IR into domain-specific structured data using extraction schemas.

#### Stage 1: Article Extraction

**Table:** `article_extractions`

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `article_id` | UUID FK | The ingested article that was processed |
| `extraction_data` | JSONB | The intermediate representation (entities, events, locations, dates) |
| `classification_hints` | JSONB | Domain/category hints for Stage 2 routing |
| `entity_count` | INTEGER | Number of entities extracted |
| `event_count` | INTEGER | Number of events extracted |
| `overall_confidence` | DECIMAL | 0.00-1.00 extraction confidence |
| `provider` / `model` | VARCHAR | Which LLM provider and model performed the extraction |
| `input_tokens` / `output_tokens` | INTEGER | Token usage for cost tracking |
| `latency_ms` | INTEGER | Extraction duration |
| `status` | VARCHAR | `pending`, `completed`, `failed`, `stale` |

#### Stage 2: Schema Extraction Result

**Table:** `schema_extraction_results`

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `article_extraction_id` | UUID FK | The Stage 1 extraction this builds on |
| `schema_id` | UUID FK | Which `extraction_schemas` definition was applied |
| `article_id` | UUID FK | Back-reference to the original article |
| `extracted_data` | JSONB | Domain-specific structured output (dates, actors, charges, etc.) |
| `confidence` | DECIMAL | 0.00-1.00 per-schema confidence |
| `validation_errors` | JSONB | Array of field-level validation failures |
| `used_original_text` | BOOLEAN | Whether Stage 2 also read the raw article (not just Stage 1 IR) |
| `status` | VARCHAR | `pending`, `completed`, `failed`, `superseded` |

**Relationship:** One article -> one Stage 1 extraction -> many Stage 2 results (one per applicable schema).

#### Extraction Schema

**Table:** `extraction_schemas`

Defines the LLM prompts, field requirements, and quality thresholds for a specific domain+category combination. Versioned, with production/active flags.

| Column | Type | Description |
|--------|------|-------------|
| `schema_type` | VARCHAR | `stage1`, `stage2`, or `legacy` |
| `input_format` | VARCHAR | What the schema expects: `article_text`, `stage1_output`, or `both` |
| `is_production` | BOOLEAN | Only one production schema per domain+category (enforced by unique index) |
| `required_fields` / `optional_fields` | JSONB | Field requirement definitions |
| `confidence_thresholds` | JSONB | Per-field minimum confidence values |

---

### Actor

**Business definition:** A person, organization, agency, or group involved in one or more incidents. Actors are the preferred entity model (Layer 2), replacing the legacy `persons` table.

**Table:** `actors`

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `canonical_name` | VARCHAR | Primary display name |
| `actor_type` | ENUM | `person`, `organization`, `agency`, `group` |
| `aliases` | TEXT[] | Alternative names for entity resolution |
| `date_of_birth` / `date_of_death` | DATE | For person actors |
| `gender` | VARCHAR | For person actors |
| `nationality` | VARCHAR | Country of origin |
| `immigration_status` | VARCHAR | Current immigration status |
| `is_government_entity` | BOOLEAN | Government affiliation flag |
| `is_law_enforcement` | BOOLEAN | Law enforcement affiliation flag |
| `parent_org_id` | UUID FK | Hierarchical org structure (self-referencing) |
| `confidence_score` | DECIMAL | Entity resolution confidence |
| `is_merged` | BOOLEAN | `true` if this actor was merged into another |
| `merged_from` | UUID[] | IDs of actors that were merged into this one |
| `profile_data` | JSONB | Additional structured profile information |

**Key relationships:**
- `incident_actors` -- links to incidents with typed roles (victim, offender, witness, officer, etc.)
- `actor_relations` -- relationships between actors (alias_of, member_of, employed_by, etc.)
- `case_actors` -- links to legal cases with role types
- `actor_role_types` -- extensible role definitions (replaces the fixed `actor_role` enum)

**Views:**
- `actors_summary` -- actor with incident count and roles played
- `actor_domain_appearances` -- cross-domain actor tracking
- `actor_incident_history` -- chronological incident timeline per actor

#### Legacy: Person

**Table:** `persons` (Layer 1, superseded by `actors`)

Still used by some import scripts. Has a simpler model without `actor_type` or organization support. Connected to incidents via `incident_persons` (instead of `incident_actors`).

---

### Event

**Business definition:** A broader occurrence that groups multiple related incidents. For example, a protest event may encompass several individual incidents (arrests, clashes, property damage).

**Table:** `events`

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `name` | VARCHAR | Event title |
| `event_type` | VARCHAR | Free-form type classification |
| `start_date` / `end_date` | DATE | Event time span |
| `ongoing` | BOOLEAN | Whether the event is still active |
| `primary_state` / `primary_city` | VARCHAR | Primary location |
| `geographic_scope` | VARCHAR | Local, regional, national, etc. |
| `ai_analysis` | JSONB | LLM-generated analysis of the event |
| `ai_summary` | TEXT | LLM-generated summary |
| `tags` | TEXT[] | Freeform tags |

**Key relationships:**
- `incident_events` -- links incidents to events with sequence ordering and assignment confidence

**View:** `events_summary` -- event with incident count and date range.

---

### Case

**Business definition:** A legal case tracked through the justice system, from filing through disposition. Cases connect incidents (arrest, hearing, trial) to legal outcomes (charges, pleas, sentencing).

**Table:** `cases`

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `case_number` | VARCHAR | Court case number (unique per jurisdiction) |
| `case_type` | VARCHAR | Type of case (criminal, civil, etc.) |
| `jurisdiction` | VARCHAR | Court jurisdiction |
| `court_name` | VARCHAR | Specific court |
| `filed_date` / `closed_date` | DATE | Case timeline |
| `status` | VARCHAR | `active`, `closed`, `appealed`, `dismissed`, `sealed` |
| `data_classification` | VARCHAR | `public`, `restricted`, `sealed`, `expunged` |
| `domain_id` / `category_id` | UUID FK | Event taxonomy classification |

**Key relationships:**
- `case_incidents` -- links incidents to cases with roles (arrest, arraignment, hearing, trial, sentencing, appeal)
- `case_actors` -- participants in the case (defendant, prosecutor, judge, etc.)
- `charges` -- criminal charges filed within the case
- `dispositions` -- case outcomes (convicted, acquitted, dismissed, plea, etc.)
- `prosecutorial_actions` -- prosecutorial decisions (filing, amendment, plea offers, etc.)
- `bail_decisions` -- bail rulings with amounts and conditions
- `case_jurisdictions` -- jurisdiction transfers

### Charge

**Table:** `charges`

| Column | Type | Description |
|--------|------|-------------|
| `charge_number` | INTEGER | Ordinal within the case |
| `charge_code` | VARCHAR | Statutory charge code |
| `charge_description` | TEXT | Human-readable charge text |
| `charge_level` | VARCHAR | `felony`, `misdemeanor`, `infraction`, `violation` |
| `status` | VARCHAR | `filed`, `amended`, `reduced`, `dismissed`, `convicted`, `acquitted` |
| `is_violent_crime` | BOOLEAN | Violence flag for analytics |
| `jail_days` / `probation_days` / `fine_amount` | Various | Sentencing details |

**History:** `charge_history` tracks all changes to a charge (amendments, reductions, dismissals) with the actor who made the change and the reason.

### Disposition

**Table:** `dispositions`

| Column | Type | Description |
|--------|------|-------------|
| `disposition_type` | VARCHAR | `convicted`, `acquitted`, `dismissed`, `plea`, `mistrial`, `nolle_prosequi`, `deferred_adjudication`, `diverted` |
| `disposition_date` | DATE | When the disposition was entered |
| `total_jail_days` / `probation_days` | INTEGER | Sentencing terms |
| `fine_amount` / `restitution_amount` | DECIMAL | Financial penalties |
| `compliance_status` | VARCHAR | `pending`, `compliant`, `non_compliant`, `completed`, `revoked` |

---

### Queue Item (Curation Queue)

**Business definition:** An article awaiting human review in the curation workflow. High-confidence articles may be auto-approved; medium and low confidence articles require manual curation.

**View:** `curation_queue` (not a table -- a view over `ingested_articles`)

| Column | Source | Description |
|--------|--------|-------------|
| `id` | `ingested_articles.id` | Article ID |
| `title` | `ingested_articles.title` | Article headline |
| `source_name` | `ingested_articles.source_name` | Publishing source |
| `source_url` | `ingested_articles.source_url` | Original URL |
| `published_date` | `ingested_articles.published_date` | Publication date |
| `relevance_score` | `ingested_articles.relevance_score` | Domain relevance (0-1) |
| `extraction_confidence` | `ingested_articles.extraction_confidence` | LLM confidence (0-1) |
| `extracted_data` | `ingested_articles.extracted_data` | Legacy extraction output |
| `status` | `ingested_articles.status` | `pending` or `in_review` |

**Ordering:** Sorted by relevance score (descending), then fetch time (descending).

**Confidence tiers:**

| Tier | Confidence | Workflow |
|------|------------|----------|
| HIGH | >= 0.85 | Auto-approval candidate |
| MEDIUM | 0.50 - 0.85 | Quick human review |
| LOW | < 0.50 | Full manual review |

Enforcement incidents use a higher threshold (0.90) for auto-approval.

---

## Supporting Entities

### Source

**Table:** `sources`

News outlets, government agencies, and other data sources. Each source has a reliability tier (1-4), fetcher configuration, and scheduling parameters for automated RSS polling.

| Column | Type | Description |
|--------|------|-------------|
| `tier` | ENUM | `1` (government/official), `2` (major news), `3` (local/regional), `4` (social/unverified) |
| `reliability_score` | DECIMAL | 0.00-1.00 computed reliability |
| `fetcher_class` / `fetcher_config` | VARCHAR/JSONB | Pluggable fetcher implementation and settings |
| `interval_minutes` | INTEGER | How often to poll this source (default: 60) |
| `last_fetched` / `last_error` | TIMESTAMPTZ/TEXT | Fetch status tracking |

### Jurisdiction

**Table:** `jurisdictions`

Geographic jurisdictions (states, counties, cities) with sanctuary policy data. Hierarchical via `parent_jurisdiction_id`.

| Column | Type | Description |
|--------|------|-------------|
| `jurisdiction_type` | VARCHAR | `state`, `county`, `city` |
| `state_code` | CHAR(2) | Two-letter state code |
| `fips_code` | VARCHAR | Federal FIPS geographic code |
| `state_sanctuary_status` | VARCHAR | State-level sanctuary policy |
| `local_sanctuary_status` | VARCHAR | Local sanctuary policy |
| `detainer_policy` | VARCHAR | ICE detainer cooperation policy |

### Incident Type

**Table:** `incident_types`

Classification of incidents with severity weights. Seeded with 21 types across enforcement and crime categories. Supports hierarchy via `parent_type_id` and per-type pipeline configuration.

### Event Domain / Event Category

**Tables:** `event_domains`, `event_categories`

Two-level taxonomy for classifying incidents. Domains are top-level groupings (e.g., "Criminal Justice", "Immigration", "Civil Rights"). Categories are hierarchical within domains and define required/optional custom fields.

### Background Job

**Table:** `background_jobs`

Tracks long-running operations (batch extraction, enrichment runs, data imports). Integrates with Celery via `celery_task_id`. The Job Manager UI displays these.

| Column | Type | Description |
|--------|------|-------------|
| `job_type` | VARCHAR | Type of job (e.g., `batch_extract`, `enrichment`, `pipeline`) |
| `status` | VARCHAR | `pending`, `running`, `completed`, `failed`, `cancelled` |
| `progress` / `total` | INTEGER | Completion tracking |
| `queue` | VARCHAR | Celery queue name |
| `retry_count` / `max_retries` | INTEGER | Retry state |

---

## Materialized Views

These are pre-computed analytics that require periodic refresh.

| View | Description | Refresh Needed |
|------|-------------|----------------|
| `prosecutor_stats` | Per-prosecutor case counts, conviction rates, average sentences | After new dispositions |
| `recidivism_analysis` | Per-actor recidivism patterns (incident frequency, progression) | After new incidents |

Configuration in `materialized_view_refresh_config` table.

---

## Key Views

| View | Purpose |
|------|---------|
| `incidents_summary` | Approved incidents with computed severity scores. Primary dashboard data source. |
| `curation_queue` | Pending/in-review articles sorted by relevance. Powers the curation UI. |
| `events_summary` | Events with incident counts and date ranges. |
| `actors_summary` | Non-merged actors with incident counts and roles. |
| `active_prompts` | Currently active LLM prompts. |
| `prompt_performance` | Prompt execution metrics (success rate, latency, token usage). |
| `token_usage_by_day` | Daily token consumption by prompt (last 90 days). |
| `token_cost_summary` | Estimated USD cost by prompt and model (last 30 days). |
| `provider_performance` | LLM provider comparison (last 30 days). |
| `actor_incident_history` | Chronological incident timeline per actor (defendants/offenders). |
| `defendant_lifecycle_timeline` | Full case lifecycle phases (arrest through sentencing). |

---

## Enum Reference

| Enum | Values | Used By |
|------|--------|---------|
| `incident_category` | `enforcement`, `crime` | `incidents.category` |
| `source_tier` | `1`, `2`, `3`, `4` | `incidents.source_tier`, `sources.tier` |
| `curation_status` | `pending`, `in_review`, `approved`, `rejected`, `error` | `incidents`, `ingested_articles` |
| `actor_type` | `person`, `organization`, `agency`, `group` | `actors.actor_type` |
| `actor_role` | `victim`, `offender`, `witness`, `officer`, `arresting_agency`, `reporting_agency`, `bystander`, `organizer`, `participant` | `incident_actors.role` |
| `relation_type` | `duplicate`, `related`, `follow_up`, `same_event`, `caused_by`, `response_to`, `involves_same_actor`, `escalation_of` | `incident_relations` |
| `incident_scale` | `single`, `small`, `medium`, `large`, `mass` | `incidents.incident_scale` |
| `prompt_type` | `extraction`, `classification`, `entity_resolution`, `pattern_detection`, `summarization`, `analysis` | `prompts.prompt_type` |
| `prompt_status` | `draft`, `active`, `testing`, `deprecated`, `archived` | `prompts.status` |
| `field_type` | `string`, `text`, `integer`, `decimal`, `boolean`, `date`, `datetime`, `enum`, `array`, `reference` | `field_definitions` |
| `person_role` | `victim`, `offender`, `witness`, `officer` | `incident_persons` (legacy) |
| `actor_relation_type` | `alias_of`, `member_of`, `affiliated_with`, `employed_by`, `family_of`, `associated_with` | `actor_relations` |
