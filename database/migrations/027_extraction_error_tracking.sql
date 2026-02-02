-- Migration 027: Add extraction error tracking columns to ingested_articles
--
-- Tracks per-article extraction failures so batch processing can skip
-- permanently-failed articles and avoid infinite retry loops.

ALTER TABLE ingested_articles
    ADD COLUMN IF NOT EXISTS extraction_error_count INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_extraction_error TEXT,
    ADD COLUMN IF NOT EXISTS last_extraction_error_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS extraction_error_category VARCHAR(20);

-- Partial index for efficiently querying extractable articles:
-- pending articles that haven't permanently failed and haven't hit the retry limit
CREATE INDEX IF NOT EXISTS idx_articles_extractable
    ON ingested_articles (published_date DESC NULLS LAST)
    WHERE status = 'pending'
      AND content IS NOT NULL
      AND (extraction_error_category IS NULL OR extraction_error_category != 'permanent')
      AND extraction_error_count < 3;
