# Extraction Pipelines

This document describes how Sentinel processes articles from raw RSS content into structured incident data. The system has three extraction paths, two deduplication layers, a confidence-based approval system, and a human curation workflow.

---

## Table of Contents

1. [Pipeline Overview](#pipeline-overview)
2. [Legacy Pipeline (One-Shot)](#legacy-pipeline-one-shot)
3. [Two-Stage Pipeline (Preferred)](#two-stage-pipeline-preferred)
4. [Orchestrator Pipeline (Configurable)](#orchestrator-pipeline-configurable)
5. [Duplicate Detection](#duplicate-detection)
6. [Auto-Approval Logic](#auto-approval-logic)
7. [Curation Workflow](#curation-workflow)
8. [Decision Flowcharts](#decision-flowcharts)
9. [Key Files Reference](#key-files-reference)

---

## Pipeline Overview

Sentinel processes news articles through a multi-step pipeline that extracts structured incident data using LLM analysis. Three extraction paths exist, reflecting the system's evolution:

| Pipeline | Status | When to Use | Data Storage |
|----------|--------|-------------|--------------|
| **Legacy (one-shot)** | Maintained | Older code paths, simple extractions | `ingested_articles.extracted_data` |
| **Two-stage** | **Preferred** | New work, complex multi-domain articles | `article_extractions` + `schema_extraction_results` |
| **Orchestrator** | Available | Type-specific configurable processing | Database-backed stage configs |

All three paths share the same duplicate detection and auto-approval subsystems. The pipeline mode is recorded in `ingested_articles.extraction_pipeline` (value: `'legacy'` or `'two_stage'`).

### Why Three Pipelines Exist

The **legacy pipeline** was the original implementation: a single LLM call produces a flat JSON extraction. It works well for simple articles but struggles with multi-incident or multi-domain content.

The **two-stage pipeline** was added to improve extraction quality. Stage 1 produces a reusable intermediate representation (IR) of all entities, events, and relationships. Stage 2 runs domain-specific schemas against the IR to produce structured output. This separation means Stage 1 only runs once per article, and multiple Stage 2 schemas can extract different facets (enforcement, crime, civil rights) from the same IR.

The **orchestrator pipeline** wraps both extraction approaches in a configurable, database-backed stage system. It enables per-incident-type pipeline configuration (different stages, thresholds, and prompts for different domains).

### Common Flow

Regardless of which extraction path is used, every article passes through:

```
RSS Feed
   |
   v
Fetch Article Content
   |
   v
Duplicate Detection -----> [DUPLICATE] --> Skip
   |
   | (not duplicate)
   v
LLM Extraction (legacy OR two-stage)
   |
   v
Auto-Approval Evaluation
   |
   +---> [AUTO_APPROVE]  --> Incident created automatically
   +---> [NEEDS_REVIEW]  --> Curation queue (human review)
   +---> [AUTO_REJECT]   --> Rejected, archived
```

---

## Legacy Pipeline (One-Shot)

**Entry point:** `LLMExtractor.extract()` in `backend/services/llm_extraction.py`

### How It Works

1. Article text (title + content) is sent to Claude in a single LLM call
2. The prompt includes the full extraction schema and category-specific instructions
3. The LLM returns a JSON object with `is_relevant`, `category`, and `incident` fields
4. The response is parsed and stored as `extracted_data` on the article

### Data Flow

```
Article text (title + content)
   |
   v
get_extraction_prompt()  -- builds category-aware user prompt
get_system_prompt()      -- selects enforcement vs crime system prompt
   |
   v
LLM Call (Claude Sonnet, max_tokens=2000)
   |
   v
parse_llm_json()  -- strips markdown fences, parses JSON
   |
   v
Result: {
    success: bool,
    is_relevant: bool,
    category: "enforcement" | "crime",
    extracted_data: { date, state, city, incident_type, ... },
    confidence: float,
    field_confidence: { date: float, state: float, ... },
    required_fields_met: bool,
    missing_fields: [...]
}
```

### Data Storage

- **Table:** `ingested_articles`
- **Column:** `extracted_data` (JSONB) -- flat JSON with all extraction fields
- **Pipeline marker:** `extraction_pipeline = 'legacy'`

### Category-Specific Extraction

The legacy pipeline supports two incident categories with different prompts and required fields:

| Category | Required Fields | Focus |
|----------|----------------|-------|
| **Enforcement** | date, state, incident_type, victim_category, outcome_category | Victim details, officer involvement, agency |
| **Crime** | date, state, incident_type, offender_immigration_status | Offender details, criminal history, deportation status |

### Universal Extraction Variant

`LLMExtractor.extract_universal()` is a category-agnostic extraction that captures all entities regardless of domain. It returns actors, events, policy context, and sources cited. Used when the category is unknown or when multi-category extraction is needed.

### When It Is Used

- Articles with `extraction_pipeline = 'legacy'` (or NULL)
- Fallback when no database-backed prompt is configured
- The `ExtractionStage._legacy_extraction()` orchestrator fallback
- Direct calls via `extract_incident_from_article()` convenience function

---

## Two-Stage Pipeline (Preferred)

**Entry point:** `TwoStageExtractionService.run_full_pipeline()` in `backend/services/two_stage_extraction.py`

### Architecture

The two-stage pipeline separates extraction into a reusable intermediate representation (Stage 1) and domain-specific structured output (Stage 2):

```
Article text
   |
   v
+----------------------------------+
| STAGE 1: Comprehensive IR        |
| - All entities (persons, orgs,   |
|   locations)                     |
| - All events with timestamps     |
| - Legal data (charges, case IDs) |
| - Classification hints           |
| - Domain relevance assessment    |
+----------------------------------+
   |
   | Stored in: article_extractions
   |
   v
+----------------------------------+
| Schema Auto-Selection            |
| - Match classification_hints     |
|   to active Stage 2 schemas      |
| - Domain relevance gate          |
| - Confidence threshold >= 0.3    |
+----------------------------------+
   |
   | (one or more schemas selected)
   |
   v
+----------------------------------+     +----------------------------------+
| STAGE 2: Schema A               |     | STAGE 2: Schema B               |
| (e.g., immigration/enforcement) |     | (e.g., criminal_justice/arrest)  |
| - Receives Stage 1 IR + article |     | - Receives Stage 1 IR + article  |
| - Produces domain-specific JSON  |     | - Produces domain-specific JSON  |
+----------------------------------+     +----------------------------------+
   |                                        |
   | Stored in: schema_extraction_results   |
   v                                        v
+----------------------------------+
| Stage 2 Selection & Merging      |
| - Entity-clustered grouping      |
| - Domain-priority-aware selection|
| - Complementary schema merging   |
+----------------------------------+
   |
   v
Merged extracted_data --> auto-approval
```

### Stage 1: Comprehensive Entity Extraction

**Purpose:** Extract a reusable intermediate representation (IR) capturing everything in the article.

**Process:**
1. Load the active `stage1` schema from `extraction_schemas` table
2. Inject domain relevance criteria from `event_domains` into the prompt
3. Send article text to the LLM (default model: `claude-sonnet-4-5`, max_tokens: 8000)
4. Parse JSON response with truncation recovery (JSON repair for `max_tokens` cutoffs)
5. If truncated, retry with doubled token limit and a focused prompt
6. Store results in `article_extractions` with summary statistics

**Stage 1 Output Structure:**
- `entities.persons[]` -- people mentioned with roles, demographics
- `entities.organizations[]` -- agencies, companies, courts
- `entities.locations[]` -- places with coordinates
- `events[]` -- timestamped events with participants
- `classification_hints[]` -- suggested domain/category pairs with confidence
- `domain_relevance[]` -- per-domain relevance assessment
- `extraction_confidence` -- overall confidence score
- `extraction_notes` -- free-text notes about the extraction

**Data Storage:**
- **Table:** `article_extractions`
- **Key columns:** `extraction_data` (JSONB), `classification_hints` (JSONB), `entity_count`, `event_count`, `overall_confidence`, `status`
- **Link:** `ingested_articles.latest_extraction_id` points to the most recent Stage 1 result

### Stage 2: Domain-Specific Schema Extraction

**Purpose:** Transform the Stage 1 IR into structured, domain-specific output using configurable schemas.

**Schema Auto-Selection:**
1. Read `classification_hints` from Stage 1 (pairs of domain_slug + category_slug + confidence)
2. Filter hints below confidence threshold (0.3)
3. Apply domain relevance gate: only schemas whose domain is marked relevant proceed
4. Match hints against active `stage2` schemas in `extraction_schemas` table
5. Matching uses domain+category pairs with fuzzy slug normalization (handles hyphens vs underscores, combined slugs)

**Process:**
1. For each matched schema, build a prompt from the schema's `system_prompt` and `user_prompt_template`
2. Inject Stage 1 JSON (`{stage1_output}`) and original article text (`{article_text}`) into the template
3. Run all matched schemas in parallel via `asyncio.gather`
4. Validate each result against the schema's field definitions
5. Calculate per-result confidence scores
6. Store results in `schema_extraction_results`

**Data Storage:**
- **Table:** `schema_extraction_results`
- **Key columns:** `extracted_data` (JSONB), `confidence`, `validation_errors` (JSONB), `status`
- **Unique constraint:** `(article_extraction_id, schema_id)` -- one result per schema per extraction
- **Supports re-extraction:** old results marked `'superseded'`, new results inserted

### Stage 2 Selection and Merging

After Stage 2 produces one or more results, the `stage2_selector` module picks and merges the best output.

**Selection Algorithm:**
1. Filter results below minimum confidence (0.3)
2. Cluster results by primary entity name (fuzzy name matching)
3. Pick the best cluster, preferring clusters containing Immigration-domain results with confidence >= 0.5
4. If the cluster has a single result, return it directly
5. If multiple results, merge them:
   - **Base:** Highest domain-priority result in the cluster
   - **Supplements:** Other results fill in null/empty fields from the base
   - Base values are never overwritten

**Domain Priority Hierarchy:**
| Domain | Priority Score |
|--------|---------------|
| Immigration | 100 |
| Criminal Justice | 50 |
| Civil Rights | 25 |
| Other | 10 |

**Merge Output:**
```
{
    "extracted_data": { ... merged fields ... },
    "confidence": float,
    "merge_info": {
        "sources": [
            { "schema_name": "...", "domain_slug": "...", "category_slug": "...", "role": "base" },
            { "schema_name": "...", "role": "supplement", "fields_contributed": [...] }
        ],
        "cluster_entity": "John Doe",
        "merged": true,
        "schemas_merged": 2
    }
}
```

### Category Resolution

The `resolve_category_from_merge_info()` function determines the final incident category using a priority chain:

1. `merge_info.sources[0].category_slug` (most authoritative -- from schema selection)
2. `extracted_data.category` (flat field from extraction)
3. `extracted_data.categories[]` list (look for enforcement/crime)
4. Field-signature inference (presence of CJ fields, enforcement fields, immigration fields)
5. Default (`'crime'`)

---

## Orchestrator Pipeline (Configurable)

**Entry point:** `PipelineOrchestrator.execute()` in `backend/services/pipeline_orchestrator.py`

The orchestrator wraps extraction, deduplication, and approval into a configurable, database-backed stage system. Each incident type can have its own pipeline configuration.

### Available Stages

Stages execute in order. Each receives a `PipelineContext` and returns a `StageExecutionResult` with one of: `CONTINUE`, `SKIP`, `REJECT`, or `ERROR`.

| Order | Stage | Slug | Purpose |
|-------|-------|------|---------|
| 10 | URLDedupeStage | `url_dedupe` | Check for duplicate URLs in ingested_articles and incidents |
| 20 | ContentDedupeStage | `content_dedupe` | Title/content similarity matching using PostgreSQL `pg_trgm` |
| 30 | RelevanceStage | `relevance` | Keyword-based or AI-based relevance screening |
| 40 | ClassificationStage | `classification` | Classify article into incident type (enforcement/crime/CJ/CR) |
| 50 | ExtractionStage | `extraction` | LLM extraction (database prompts or legacy fallback) |
| 60 | EntityResolutionStage | `entity_resolution` | Match extracted entities to existing actors |
| 70 | ValidationStage | `validation` | Validate extracted fields (dates, states, confidence ranges) |
| 80 | AutoApprovalStage | `auto_approval` | Evaluate for auto-approve, auto-reject, or needs-review |
| 90 | PatternDetectionStage | `pattern_detection` | Detect temporal, geographic, and actor clusters |
| 100 | CrossReferenceStage | `cross_reference` | Link to related events and incidents |
| 110 | EnrichmentStage | `enrichment` | Fill missing fields from related incidents |

### Configuration

Pipeline stages are configured per incident type in the database:
- `pipeline_stages` -- defines available stages with default order and active status
- `incident_type_pipeline_config` -- per-incident-type overrides (enabled, order, config, prompt_id)

### Stage Error Handling

- `CONTINUE` -- proceed to next stage normally
- `SKIP` -- stop pipeline, article marked as duplicate/irrelevant (not an error)
- `REJECT` -- stop pipeline, article rejected
- `ERROR` -- log the error and continue to the next stage (fail-open by default)

---

## Duplicate Detection

**Service:** `DuplicateDetector` in `backend/services/duplicate_detection.py`

Duplicate detection runs at two points: during ingestion (in-memory against recent articles) and at approval time (against the database).

### Four Strategies (Priority Order)

Strategies are evaluated in order; the first match wins. This means a URL match short-circuits the more expensive content and entity comparisons.

```
New Article
   |
   v
1. URL Match ---------> Exact source_url equality
   | (no match)          Confidence: 1.0
   v
2. Title Match -------> Jaccard similarity on word tokens
   | (no match)          Threshold: 0.75 (default)
   v
3. Content Match -----> MinHash fingerprinting (3-word shingles)
   | (no match)          Threshold: 0.85 (default)
   v
4. Entity Match ------> Structured entity comparison
   | (no match)          (name, date, state, incident_type)
   v
Not a duplicate
```

### Strategy Details

**1. URL Match**
- Exact string equality on `url` or `source_url`
- Confidence: 1.0 (certain)
- Cheapest check, runs first

**2. Title Match**
- Normalizes text (lowercase, remove punctuation, collapse whitespace)
- Tokenizes into word sets, dropping words with 2 or fewer characters
- Computes Jaccard similarity between token sets
- Threshold: `DUPLICATE_TITLE_SIMILARITY` = **0.75**
- Catches rephrased headlines from syndicated/wire content

**3. Content Match**
- Creates 3-word shingles (n-grams) from article body
- Hashes shingles with MD5 (truncated to 32 bits)
- Selects the 100 smallest hashes as a MinHash sketch
- Computes Jaccard similarity between sketches
- Threshold: `DUPLICATE_CONTENT_SIMILARITY` = **0.85**
- Catches near-identical body text even with different headlines

**4. Entity Match**
- Extracts key entities from both articles: offender_name, victim_name, incident_type, state, date
- Compares entities using cascading fuzzy matching:
  - **Name matching:** Exact (1.0) > substring (0.95) > name-parts (first+last, 0.8-1.0) > token Jaccard (0.7+)
  - **Date proximity:** Within 30-day window, confidence decays linearly from 1.0 to 0.5
  - **Related types:** Synonym groups (murder/homicide/manslaughter) count as 0.5 match at 0.7 confidence
  - **City bonus:** Matching city adds 0.2 to confidence (not to match count)
- **Decision tiers** (first matching tier wins):
  - **Strong:** Name matched AND >= 2 total fields
  - **Breadth:** >= 3 fields matched AND avg confidence >= 0.7
  - **Standard:** >= 2 fields matched AND avg confidence >= 0.6

### Similarity Thresholds Summary

| Threshold | Value | Source Constant |
|-----------|-------|-----------------|
| Title similarity | 0.75 | `DUPLICATE_TITLE_SIMILARITY` |
| Content similarity | 0.85 | `DUPLICATE_CONTENT_SIMILARITY` |
| Name similarity | 0.70 | `DUPLICATE_NAME_SIMILARITY` |
| Date window (days) | 30 | `DUPLICATE_ENTITY_DATE_WINDOW` |
| Content dedupe (orchestrator) title | 0.85 | `CONTENT_DEDUPE_TITLE_THRESHOLD` |
| Content dedupe (orchestrator) content | 0.80 | `CONTENT_DEDUPE_CONTENT_THRESHOLD` |

### Database-Level Deduplication (Approval Time)

`find_duplicate_incident()` runs at approval time to catch cross-source duplicates in the `incidents` table. It uses three strategies:

1. **URL match** against `incidents.source_url` (confidence 1.0)
2. **Description match** against `incidents.description` (only if > 50 chars, confidence 1.0)
3. **Entity match** via SQL pre-filter (state + date window) then Python fuzzy name matching against both the `actors` table and legacy `incidents.victim_name` column

### Known Limitations

- Title matching can false-positive on short titles with common words
- Content fingerprinting is unreliable for very short articles (< 30 words)
- Entity matching requires at least two matching fields
- Character-level name Jaccard can false-positive on short surnames
- In-memory detector is O(n) with no indexing

---

## Auto-Approval Logic

**Service:** `AutoApprovalService` in `backend/services/auto_approval.py`

### Decision Flow

```
Extracted data
   |
   v
Is relevant? ----NO----> AUTO_REJECT (if enabled)
   |
   | YES
   v
Confidence < 0.30? ----> AUTO_REJECT (below reject threshold)
   |
   | NO
   v
Missing required fields? ----> NEEDS_REVIEW
   |
   | All present
   v
Low field-level confidence? ----> NEEDS_REVIEW
   |
   | All fields above threshold
   v
Crime severity < 2? ----> AUTO_REJECT (too low severity)
   |
   | Severity acceptable
   v
Confidence >= category threshold? ----> AUTO_APPROVE (if severity >= min)
   |
   | Below threshold
   v
Confidence >= 0.50? ----> NEEDS_REVIEW (moderate confidence)
   |
   | Below 0.50
   v
NEEDS_REVIEW (default)
```

### Confidence Tiers

| Tier | Confidence Range | Action |
|------|-----------------|--------|
| **HIGH** | >= category threshold (85-90%) | Auto-approve candidates |
| **MEDIUM** | 50% -- category threshold | Quick human review |
| **LOW** | 30% -- 50% | Full manual review |
| **REJECT** | < 30% | Auto-reject |

### Domain-Specific Thresholds

| Category | Auto-Approve | Required Fields | Field Confidence | Severity Gate |
|----------|-------------|-----------------|------------------|---------------|
| **Default** | >= 85% | date, state | >= 70% | >= 5 |
| **Enforcement** | >= 90% | date, state, incident_type, victim_category, outcome_category | >= 75% | >= 1 |
| **Crime** | >= 85% | date, state, incident_type | >= 70% | >= 5 |
| **Domain (CJ/CR)** | >= 85% | date, state | >= 70% | Disabled (0) |

Enforcement incidents use **higher scrutiny** (90% threshold, more required fields, higher per-field confidence) because they involve government actions affecting individuals.

Crime incidents use the **standard threshold** (85%) and require fewer fields.

Domain categories (Criminal Justice, Civil Rights) use **minimal required fields** because each schema defines its own field set -- the LLM confidence score (which already blends field completeness) is the primary quality gate.

### Severity Scoring

Incident types are mapped to a 0-10 severity scale:

| Severity | Incident Types |
|----------|---------------|
| 10 | homicide, murder |
| 9 | manslaughter, sexual_assault, human_trafficking |
| 8 | kidnapping, dui_fatality, death_in_custody, death, fatal |
| 7 | shooting, stabbing, arson |
| 6 | carjacking, assault, battery, physical_force, raid_injury |
| 5 | robbery, drug_trafficking, gang_activity, burglary, theft, fraud, dui, detention, arrest, deportation, raid, illegal_reentry |
| 4 | protest_clash, property_damage |
| 3 | other (default) |

For auto-approval:
- Standard/Crime: Must have severity >= 5
- Enforcement: Must have severity >= 1 (raids/arrests are not crimes)
- Domain categories: Severity gate disabled

For auto-reject:
- Standard/Crime: Severity < 2 triggers auto-reject
- Domain categories: Severity gate disabled (threshold = 0)

### Field Normalization

Before evaluation, `normalize_extracted_fields()` handles structural differences between extraction schemas:
- Flattens `location.state` / `location.city` to top-level `state` / `city`
- Infers `incident_type` from `charges[]`, `violation_type`, `case_type`, or `event_type`
- Normalizes `immigration_status` to `offender_immigration_status`
- Normalizes `confidence` to `overall_confidence`

### Configuration Sources

Thresholds can come from three sources (priority order):
1. **Database:** `incident_type_pipeline_config` thresholds for specific incident types (via `IncidentTypeService`)
2. **Database:** `event_categories.required_fields` loaded at startup (via `load_category_configs_from_db()`)
3. **Static:** Hardcoded defaults in `backend/services/thresholds.py`

All threshold constants are centralized in `backend/services/thresholds.py`.

---

## Curation Workflow

### Queue Tiers

Auto-approval decisions route articles into three tiers:

```
+-------------------+     +-------------------+     +-------------------+
| AUTO-APPROVE      |     | QUICK REVIEW      |     | FULL REVIEW       |
| Confidence >= 85% |     | Confidence 50-85% |     | Confidence < 50%  |
| (90% enforcement) |     |                   |     |                   |
| All required       |     | Some fields may   |     | Major gaps or     |
| fields present     |     | need verification |     | low confidence    |
+-------------------+     +-------------------+     +-------------------+
        |                         |                         |
        v                         v                         v
  Incident created          Human reviews            Human reviews
  automatically             extraction data          full article +
                            and confirms             extraction data
```

### Curation Queue

The `curation_queue` table tracks articles awaiting human review. Articles in the queue have:
- `curation_status` on `ingested_articles` (pending, approved, rejected, archived)
- Associated extraction data (legacy `extracted_data` or two-stage `article_extractions` + `schema_extraction_results`)
- Confidence scores and missing field information

### Approve/Reject Flow

**Approval:**
1. Curator reviews extracted data in the Curation Queue or Batch Processing UI
2. Curator can edit extracted fields before approving
3. On approval, the system checks for database-level duplicates via `find_duplicate_incident()`
4. If no duplicate found, an incident record is created in the `incidents` table
5. Actors are resolved/created in the `actors` table and linked via `incident_actors`
6. The article's `curation_status` is updated to `'approved'`

**Rejection:**
1. Curator marks the article as not relevant or incorrect extraction
2. The article's `curation_status` is updated to `'rejected'`
3. No incident record is created

### Batch Processing

The `BatchProcessing` component in the frontend provides tiered confidence queues:
- **High confidence:** Articles that nearly auto-approved, needing minimal review
- **Medium confidence:** Articles requiring field-level verification
- **Low confidence:** Articles requiring full review of the source article

---

## Decision Flowcharts

### Complete Pipeline Decision Flow

```
                          +------------------+
                          |  Article Fetched |
                          |  from RSS Feed   |
                          +--------+---------+
                                   |
                          +--------v---------+
                          | Duplicate Check  |
                          | (URL/Title/      |
                          |  Content/Entity) |
                          +--------+---------+
                                   |
                     +-------------+-------------+
                     |                           |
                [DUPLICATE]                 [NOT DUPLICATE]
                     |                           |
                     v                           v
                Skip article          +----------+---------+
                                      | Determine pipeline |
                                      | mode               |
                                      +----------+---------+
                                                 |
                          +----------------------+--------------------+
                          |                                           |
                    [LEGACY]                                    [TWO-STAGE]
                          |                                           |
                          v                                           v
               +----------+--------+                    +-------------+----------+
               | Single LLM call   |                    | Stage 1: Extract IR    |
               | extract()         |                    | (entities, events,     |
               +----------+--------+                    |  classification hints) |
                          |                             +-------------+----------+
                          |                                           |
                          |                             +-------------v----------+
                          |                             | Auto-select Stage 2    |
                          |                             | schemas from hints     |
                          |                             +-------------+----------+
                          |                                           |
                          |                             +-------------v----------+
                          |                             | Stage 2: Run schemas   |
                          |                             | in parallel            |
                          |                             +-------------+----------+
                          |                                           |
                          |                             +-------------v----------+
                          |                             | Select & merge best    |
                          |                             | Stage 2 result         |
                          |                             +-------------+----------+
                          |                                           |
                          +---------------------+---------------------+
                                                |
                                       +--------v---------+
                                       | Auto-Approval    |
                                       | Evaluation       |
                                       +--------+---------+
                                                |
                         +----------------------+--------------------+
                         |                      |                    |
                   [AUTO_APPROVE]         [NEEDS_REVIEW]       [AUTO_REJECT]
                         |                      |                    |
                         v                      v                    v
                  Create incident         Add to curation      Archive article
                  automatically           queue for human
                                          review
```

### Two-Stage Schema Selection Flow

```
Stage 1 classification_hints[]
   |
   v
Filter hints with confidence >= 0.3
   |
   v
Domain relevance gate:
   Has domain_relevance data?
   |
   +-- YES --> Only keep domains where is_relevant=true AND confidence >= 0.5
   |            Filter hints to only relevant domains
   |
   +-- NO  --> Skip gate (legacy v1 extraction)
   |
   v
Match against active Stage 2 schemas:
   For each hint (domain_slug, category_slug):
   |
   +-- Exact match? (domain + category)  --> Include schema
   +-- Combined slug match? (domain_category == hint)  --> Include schema
   +-- Domain-only match? (same domain, any category)  --> Include schema
   +-- Prefix match? (hint starts with domain_)  --> Include schema
   |
   v
Run matched schemas in parallel
```

### Auto-Approval Evaluation Flow

```
                    +------------------+
                    | Extraction Data  |
                    +--------+---------+
                             |
                    +--------v---------+
                    | Normalize fields |
                    | (flatten nested, |
                    |  infer missing)  |
                    +--------+---------+
                             |
                    +--------v---------+
                    | is_relevant?     +---NO---> AUTO_REJECT
                    +--------+---------+          "Not relevant"
                             |
                             | YES
                    +--------v---------+
                    | confidence       |
                    | < 0.30?          +---YES--> AUTO_REJECT
                    +--------+---------+          "Below threshold"
                             |
                             | NO
                    +--------v---------+
                    | Missing required |
                    | fields?          +---YES--> NEEDS_REVIEW
                    +--------+---------+          "Missing: X, Y"
                             |
                             | NO
                    +--------v---------+
                    | Any field conf   |
                    | < threshold?     +---YES--> NEEDS_REVIEW
                    +--------+---------+          "Low conf: X, Y"
                             |
                             | NO
                    +--------v---------+
                    | Severity < max   |
                    | reject?          +---YES--> AUTO_REJECT
                    +--------+---------+          "Severity too low"
                             |
                             | NO
                    +--------v---------+
                    | confidence >=    |
                    | category thresh? +---YES--> Check severity >= min
                    +--------+---------+          |
                             |               +----+----+
                             | NO            |         |
                             |          [>= min]  [< min]
                    +--------v---------+     |         |
                    | confidence       |     v         v
                    | >= 0.50?         | AUTO_APPROVE  NEEDS_REVIEW
                    +--------+---------+
                             |
                        +----+----+
                        |         |
                   [>= 0.50]  [< 0.50]
                        |         |
                        v         v
                 NEEDS_REVIEW  NEEDS_REVIEW
                 "Moderate"    "Default"
```

---

## Key Files Reference

### Core Pipeline

| File | Purpose |
|------|---------|
| `backend/services/unified_pipeline.py` | Top-level orchestrator: routes to legacy, two-stage, or configurable pipeline |
| `backend/services/llm_extraction.py` | Legacy one-shot LLM extraction (extract, triage, universal) |
| `backend/services/two_stage_extraction.py` | Two-stage pipeline: Stage 1 IR + Stage 2 schema extraction |
| `backend/services/stage2_selector.py` | Stage 2 result selection with entity-aware merging |
| `backend/services/pipeline_orchestrator.py` | Configurable stage-based pipeline with database-backed config |

### Supporting Services

| File | Purpose |
|------|---------|
| `backend/services/auto_approval.py` | Confidence-based auto-approval with category-specific thresholds |
| `backend/services/duplicate_detection.py` | Four-strategy duplicate detection (URL, title, content, entity) |
| `backend/services/thresholds.py` | Centralized threshold constants (single source of truth) |
| `backend/services/extraction_prompts.py` | Prompt templates and schemas for LLM extraction |
| `backend/services/prompt_manager.py` | Database-backed prompt management |
| `backend/services/incident_type_service.py` | Per-type threshold and schema configuration |
| `backend/utils/llm_parsing.py` | JSON parsing utilities for LLM responses |
| `backend/utils/state_normalizer.py` | State code normalization |

### Orchestrator Pipeline Stages

| File | Stage Slug | Purpose |
|------|-----------|---------|
| `backend/pipeline/stages/url_dedupe.py` | `url_dedupe` | Database URL dedup |
| `backend/pipeline/stages/content_dedupe.py` | `content_dedupe` | Title/content similarity via pg_trgm |
| `backend/pipeline/stages/relevance.py` | `relevance` | Keyword and AI relevance screening |
| `backend/pipeline/stages/classification.py` | `classification` | Rule-based incident type classification |
| `backend/pipeline/stages/extraction.py` | `extraction` | LLM extraction with prompt manager integration |
| `backend/pipeline/stages/entity_resolution.py` | `entity_resolution` | Actor matching and creation |
| `backend/pipeline/stages/validation.py` | `validation` | Field validation (dates, states, ranges) |
| `backend/pipeline/stages/auto_approval.py` | `auto_approval` | Auto-approval with type-specific thresholds |
| `backend/pipeline/stages/pattern_detection.py` | `pattern_detection` | Temporal, geographic, actor clustering |
| `backend/pipeline/stages/cross_reference.py` | `cross_reference` | Event and incident linking |
| `backend/pipeline/stages/enrichment.py` | `enrichment` | Fill missing fields from related data |

### Database Tables

| Table | Role |
|-------|------|
| `ingested_articles` | Source articles with `extracted_data` (legacy) and `extraction_pipeline` marker |
| `article_extractions` | Stage 1 IR results with classification hints |
| `schema_extraction_results` | Stage 2 per-schema structured output |
| `extraction_schemas` | Schema definitions (stage1/stage2) with prompts and field configs |
| `incidents` | Approved incident records |
| `actors` | Resolved entity records (persons, organizations, agencies) |
| `incident_actors` | Many-to-many: incidents to actors with roles |
| `curation_queue` | Human review queue |
| `pipeline_stages` | Orchestrator stage definitions |
| `incident_type_pipeline_config` | Per-type pipeline stage overrides |
| `event_domains` | Domain definitions with relevance scope |
| `event_categories` | Category definitions with required fields |
