-- Migration 022: Article deduplication cleanup and ingestion guard support
--
-- Problem: ingested_articles has massive syndication duplication (1459 → ~1051 unique).
-- Same stories appear 10-50x from different local news stations with identical titles
-- and/or identical content but different source_urls. Existing dedup is URL-only.
--
-- This migration:
-- 1. Adds content_hash column and populates it
-- 2. Cleans FK references from dependent tables (comparison_articles,
--    schema_extraction_results, article_extractions) for duplicate rows
-- 3. Deletes exact-title duplicates (keeps row with extracted_data, or earliest fetched_at)
-- 4. Deletes content-hash duplicates (same retention logic)
-- 5. Adds index for fast hash lookups
--
-- Tables with FKs to ingested_articles: article_extractions, comparison_articles,
-- enrichment_log, extraction_quality_samples, prompt_executions, schema_extraction_results.
-- Additionally, ingested_articles.latest_extraction_id references article_extractions
-- (circular FK), so that must be nulled before deleting article_extractions rows.

-- 1. Add content_hash column
ALTER TABLE ingested_articles ADD COLUMN IF NOT EXISTS content_hash VARCHAR(32);

-- 2. Populate content_hash for existing rows
UPDATE ingested_articles SET content_hash = md5(content) WHERE content IS NOT NULL AND content_hash IS NULL;

-- ==============================
-- PASS 1: Title dedup
-- ==============================

-- 3a. Delete comparison_articles referencing title duplicates
DELETE FROM comparison_articles
WHERE article_id NOT IN (
    SELECT DISTINCT ON (title) id
    FROM ingested_articles
    ORDER BY title,
             (CASE WHEN extracted_data IS NOT NULL THEN 0 ELSE 1 END),
             fetched_at ASC
);

-- 3b. Delete schema_extraction_results referencing title duplicates
DELETE FROM schema_extraction_results
WHERE article_id NOT IN (
    SELECT DISTINCT ON (title) id
    FROM ingested_articles
    ORDER BY title,
             (CASE WHEN extracted_data IS NOT NULL THEN 0 ELSE 1 END),
             fetched_at ASC
);

-- 3c. Null out latest_extraction_id on duplicate articles (circular FK to article_extractions)
WITH keepers AS (
    SELECT DISTINCT ON (title) id
    FROM ingested_articles
    ORDER BY title,
             (CASE WHEN extracted_data IS NOT NULL THEN 0 ELSE 1 END),
             fetched_at ASC
)
UPDATE ingested_articles SET latest_extraction_id = NULL
WHERE id NOT IN (SELECT id FROM keepers) AND latest_extraction_id IS NOT NULL;

-- 3d. Delete article_extractions referencing title duplicates
DELETE FROM article_extractions
WHERE article_id NOT IN (
    SELECT DISTINCT ON (title) id
    FROM ingested_articles
    ORDER BY title,
             (CASE WHEN extracted_data IS NOT NULL THEN 0 ELSE 1 END),
             fetched_at ASC
);

-- 3e. Delete the title-duplicate rows
DELETE FROM ingested_articles
WHERE id NOT IN (
    SELECT DISTINCT ON (title) id
    FROM ingested_articles
    ORDER BY title,
             (CASE WHEN extracted_data IS NOT NULL THEN 0 ELSE 1 END),
             fetched_at ASC
);

-- ==============================
-- PASS 2: Content-hash dedup
-- ==============================

-- 4a. Delete comparison_articles referencing content-hash duplicates
WITH keepers AS (
    SELECT DISTINCT ON (content_hash) id
    FROM ingested_articles
    WHERE content_hash IS NOT NULL
    ORDER BY content_hash,
             (CASE WHEN extracted_data IS NOT NULL THEN 0 ELSE 1 END),
             fetched_at ASC
),
dupes AS (
    SELECT id FROM ingested_articles WHERE content_hash IS NOT NULL AND id NOT IN (SELECT id FROM keepers)
)
DELETE FROM comparison_articles WHERE article_id IN (SELECT id FROM dupes);

-- 4b. Delete schema_extraction_results referencing content-hash duplicates
WITH keepers AS (
    SELECT DISTINCT ON (content_hash) id
    FROM ingested_articles
    WHERE content_hash IS NOT NULL
    ORDER BY content_hash,
             (CASE WHEN extracted_data IS NOT NULL THEN 0 ELSE 1 END),
             fetched_at ASC
),
dupes AS (
    SELECT id FROM ingested_articles WHERE content_hash IS NOT NULL AND id NOT IN (SELECT id FROM keepers)
)
DELETE FROM schema_extraction_results WHERE article_id IN (SELECT id FROM dupes);

-- 4c. Null out latest_extraction_id on content-hash duplicates
WITH keepers AS (
    SELECT DISTINCT ON (content_hash) id
    FROM ingested_articles
    WHERE content_hash IS NOT NULL
    ORDER BY content_hash,
             (CASE WHEN extracted_data IS NOT NULL THEN 0 ELSE 1 END),
             fetched_at ASC
),
dupes AS (
    SELECT id FROM ingested_articles WHERE content_hash IS NOT NULL AND id NOT IN (SELECT id FROM keepers)
)
UPDATE ingested_articles SET latest_extraction_id = NULL
WHERE id IN (SELECT id FROM dupes) AND latest_extraction_id IS NOT NULL;

-- 4d. Delete article_extractions referencing content-hash duplicates
WITH keepers AS (
    SELECT DISTINCT ON (content_hash) id
    FROM ingested_articles
    WHERE content_hash IS NOT NULL
    ORDER BY content_hash,
             (CASE WHEN extracted_data IS NOT NULL THEN 0 ELSE 1 END),
             fetched_at ASC
),
dupes AS (
    SELECT id FROM ingested_articles WHERE content_hash IS NOT NULL AND id NOT IN (SELECT id FROM keepers)
)
DELETE FROM article_extractions WHERE article_id IN (SELECT id FROM dupes);

-- 4e. Delete the content-hash duplicate rows
DELETE FROM ingested_articles
WHERE content_hash IS NOT NULL
  AND id NOT IN (
    SELECT DISTINCT ON (content_hash) id
    FROM ingested_articles
    WHERE content_hash IS NOT NULL
    ORDER BY content_hash,
             (CASE WHEN extracted_data IS NOT NULL THEN 0 ELSE 1 END),
             fetched_at ASC
);

-- 5. Index for fast hash lookups
CREATE INDEX IF NOT EXISTS idx_ingested_content_hash ON ingested_articles(content_hash)
    WHERE content_hash IS NOT NULL;
