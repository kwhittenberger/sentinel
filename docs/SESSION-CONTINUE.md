# Session Continuation: Pipeline Comparison UX

## What was completed

### Merged Extraction View (fully working)
The admin panel now has a single "Extraction" nav item with four tabs:
- **Schemas** — CRUD for extraction schemas (stage1, stage2, legacy)
- **Pipeline Explorer** — Load article, run full Stage 1 + Stage 2, inspect results
- **Datasets** — Create/manage golden test datasets and test cases
- **Pipeline Testing** — Run full-pipeline comparisons across model configs

### Pipeline-Oriented Testing (backend working, UX needs improvement)
- `POST /api/admin/prompt-tests/pipeline-calibrations` creates and runs a pipeline comparison
- Runs the full two-stage extraction pipeline (Stage 1 + auto-selected Stage 2 schemas) for each article with two model configurations
- Results stored in `comparison_articles` with stage1/stage2 JSONB columns
- Articles list, review modal with Choose A/B, golden extraction editing — all functional

### Bugs fixed during implementation
1. **Event loop blocking** — `LLMRouter.call()` is synchronous (uses sync Anthropic/OpenAI SDKs). Fixed by wrapping with `asyncio.to_thread()` in `two_stage_extraction.py`
2. **Modal CSS** — `.modal-content` inside `.modal-overlay` had no background. Added `.modal-overlay > .modal-content` CSS rule in `AdminPanel.css`
3. **JSONB string deserialization** — asyncpg returns JSONB columns as strings. Added `json.loads()` guard in `run_stage2()`
4. **Classification hint slug mismatch** — LLM generates hyphenated slugs (e.g. `immigration-enforcement`) but DB uses underscores with separate domain/category. Added fuzzy matching with normalization and domain-only fallback in `_auto_select_schemas()`
5. **Provider dropdown not populating** — API returns `{"models": {...}}` but frontend read `data.anthropic` instead of `data.models.anthropic`

## What needs work next: Comparison Review UX

The `CalibrationReviewModal` currently shows a raw JSON dump for each config's extraction. This is not useful for human review. The UX needs to be redesigned to present the extraction data in a structured, human-readable format.

### Current state
When reviewing a pipeline comparison article, the modal shows:
- Article title, URL, content snippet
- Collapsible Stage 1 IR comparison (raw JSON)
- Collapsible Stage 2 Results summary (schema name + confidence per config)
- Side-by-side Config A / Config B panels with raw JSON extraction
- Choose A / Choose B buttons
- Golden extraction editor (JSON textarea)
- Notes field

### What it should show instead
The extraction data is structured (dates, locations, names, charges, etc.) and should be rendered as readable fields, not JSON. For example:

```
Config A (anthropic/claude-sonnet-4)         Config B (ollama/llama4-scout)
──────────────────────────────────           ──────────────────────────────
Date: 2026-01-23                             Date: 2026-01-23
State: AZ                                    State: AZ
City: Tucson                                 City: Tuscon [typo]
Type: enforcement                            Type: arrest
Victim: Maria Lopez, 35                     Offender: Jose Garcia
Agency: ICE                                  Agency: ICE
Confidence: 87%                              Confidence: 62%

[Choose A]                                   [Choose B]
```

Key design considerations:
- Each Stage 2 schema has different required/optional fields (defined in `extraction_schemas.field_definitions`)
- Should show field-level differences highlighted (like a diff)
- Stage 1 IR could show entity/event counts as a summary bar instead of raw JSON
- Stage 2 per-schema results should be shown individually, not just the "best" one
- The golden extraction editor should be a structured form, not a JSON textarea
- Consider showing the original article text alongside with relevant passages highlighted

### Key files
- `frontend/src/PromptTestRunner.tsx` — `CalibrationReviewModal` (line ~1705), `ComparisonDetail` (line ~855)
- `frontend/src/PromptTestRunner.tsx` — `CalibrationArticle` interface has all the data fields
- `backend/services/prompt_testing.py` — `list_calibration_articles()` returns the article data
- `backend/services/two_stage_extraction.py` — `_auto_select_schemas()` determines which Stage 2 schemas run

### Database state
- Migration 021 is applied (pipeline comparison columns)
- Existing pipeline comparison data may be in `comparison_articles` from test runs

### Additional issue: Duplicate articles in calibration
The article selection query in `run_pipeline_calibration` (`prompt_testing.py` ~line 1247) does `ORDER BY fetched_at DESC LIMIT N` with no deduplication. Syndicated stories appear as separate rows in `ingested_articles` (same title, different source URLs — e.g. 19 copies of "Police arrest protesters at airport..."). The query needs `DISTINCT ON (title)` or similar content-based deduplication so calibration tests get diverse articles.

### Additional issue: LLM call timeouts
The `LLMRouter.call()` has no timeout. Large models (e.g. llama4-scout 109B) can hang indefinitely on long articles, stalling the pipeline comparison. Need to add a timeout parameter to `asyncio.to_thread()` calls or to the provider `call()` methods. The OpenAI client (used for Ollama) supports a `timeout` kwarg; Anthropic SDK also supports timeouts.

### Architecture notes
- `LLMRouter.call()` is synchronous — always use `asyncio.to_thread()` when calling from async context
- asyncpg returns JSONB columns as strings — always `json.loads()` before using as dict
- Classification hint slugs from LLM may not match DB slugs exactly — `_auto_select_schemas` handles normalization
