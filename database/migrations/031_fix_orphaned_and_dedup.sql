-- Fix orphaned articles: articles that have an incident_id but are still 'in_review'
UPDATE ingested_articles
SET status = 'approved'
WHERE incident_id IS NOT NULL
  AND status = 'in_review';

-- Prevent future duplicate incidents from the same source URL
CREATE UNIQUE INDEX IF NOT EXISTS idx_incidents_source_url_unique
    ON incidents (source_url)
    WHERE source_url IS NOT NULL;
