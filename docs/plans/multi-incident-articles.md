# Session Prompt: Multi-Incident Article Workflow

## Problem

Many ingested articles describe **multiple distinct incidents** in a single piece of content. Examples:
- A roundup article listing several arrests across different cities
- A crime report covering both the original offense and a separate prior offense by the same person
- An article about a policy change that references 3-4 specific incidents as examples

The current pipeline assumes **1 article = 1 incident**:
- `ingested_articles.incident_id` is a single FK → one incident per article
- `extracted_data` is a single JSONB blob → one extraction result
- The curation UI (BatchProcessing) shows one set of fields per article
- Approving creates exactly one incident

This means curators either lose data (only capture the "primary" incident) or resort to workarounds (manually creating incidents and copy-pasting).

## Current Architecture Constraints

### What already supports multi-incident
- `incident_sources` table: many-to-many between incidents and source URLs — an incident can already have multiple source articles
- Two-stage extraction: Stage 1 IR already captures multiple actors and events — the structure is there, it's just collapsed into one incident at approval time
- `incident_relations` table: can link related incidents after creation

### What blocks multi-incident
- `ingested_articles.incident_id` — single FK, can only point to one incident
- `approve_article()` endpoint — creates exactly one incident from one set of extracted_data
- BatchProcessing UI — shows one edit form, one approve button
- `extracted_data` JSONB — flat structure, no concept of "incident 1 vs incident 2"

## Design Questions to Resolve

1. **Where does splitting happen?**
   - During LLM extraction (prompt asks for array of incidents)?
   - During curation (human identifies and splits)?
   - Both? (LLM suggests splits, human confirms)

2. **Data model for pre-approval splits**
   - New table `article_incident_drafts` (article_id, draft_index, extracted_data)?
   - Or extend `extracted_data` to hold an array of incident objects?
   - Or use `article_extractions` (already exists for two-stage) with multiple rows per article?

3. **Curation UX**
   - Tabbed interface? ("Incident 1 | Incident 2 | + Add")
   - Split button that duplicates current extraction into two editable drafts?
   - How to handle shared fields (article source, published date) vs per-incident fields (location, actors, charges)?

4. **Approval flow**
   - Approve all drafts at once, or individually?
   - What happens to `ingested_articles.incident_id` — pick the first? Drop the FK? Add a junction table?
   - Should related incidents auto-link via `incident_relations`?

5. **Extraction pipeline changes**
   - Should the LLM prompt explicitly ask "how many distinct incidents are described?"
   - Add an `incident_count` or `contains_multiple_incidents` flag to Stage 1 IR?
   - Re-extraction: if an article was already extracted as single-incident, can we re-extract as multi?

## Suggested Approach (to evaluate)

### Phase 1: Manual split in curation UI
- Add a "Split Incident" button in BatchProcessing detail panel
- Duplicates current `editData` into a tabbed draft interface
- Curator edits each tab independently (different locations, actors, dates)
- Each tab approves as a separate incident
- All resulting incidents auto-linked via `incident_relations` with type `'same_source'`
- `ingested_articles.incident_id` points to the first; others linked via `incident_sources`

### Phase 2: LLM-assisted split detection
- Add `incident_count` field to Stage 1 extraction prompt
- If >1, Stage 2 produces an array of incident objects instead of one
- Pre-populate the tabbed draft interface with LLM-suggested splits
- Curator reviews/adjusts before approving

### Phase 3: Automated handling
- Auto-split high-confidence multi-incident extractions
- Each sub-incident goes through normal auto-approve/curation flow independently

## Starting Point for Tomorrow

1. Read this document and the current approval flow in `backend/routes/curation.py:approve_article` (line ~1400)
2. Read `frontend/src/BatchProcessing.tsx` — the detail panel and `handleApprove`
3. Decide on Phase 1 data model (new table vs extended JSONB vs multiple article_extractions rows)
4. Plan the UI: tabbed drafts within the existing SplitPane detail panel
5. Implement Phase 1 end-to-end before considering LLM changes
