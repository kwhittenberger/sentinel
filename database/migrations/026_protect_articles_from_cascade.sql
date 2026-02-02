-- Migration 026: Protect ingested_articles from downstream cascade
--
-- Problem: ingested_articles are source data that should never be deleted by
-- cleaning downstream tables. The FK from ingested_articles.incident_id → incidents(id)
-- with NO ACTION means TRUNCATE incidents CASCADE will also truncate ingested_articles.
--
-- Fix: Change outbound FKs from ingested_articles to SET NULL so that
-- deleting/truncating downstream tables nulls the references instead of
-- cascading destructively.

BEGIN;

-- 1. ingested_articles.incident_id → incidents(id)
-- Currently: NO ACTION (blocks delete AND gets swept by TRUNCATE CASCADE)
-- Change to: SET NULL (deleting incident nulls the reference)
ALTER TABLE ingested_articles
    DROP CONSTRAINT ingested_articles_incident_id_fkey,
    ADD CONSTRAINT ingested_articles_incident_id_fkey
        FOREIGN KEY (incident_id) REFERENCES incidents(id) ON DELETE SET NULL;

-- 2. ingested_articles.latest_extraction_id → article_extractions(id)
-- Currently: NO ACTION
-- Change to: SET NULL (clearing extractions nulls the back-reference)
ALTER TABLE ingested_articles
    DROP CONSTRAINT ingested_articles_latest_extraction_id_fkey,
    ADD CONSTRAINT ingested_articles_latest_extraction_id_fkey
        FOREIGN KEY (latest_extraction_id) REFERENCES article_extractions(id) ON DELETE SET NULL;

-- 3. ingested_articles.source_id → sources(id)
-- Currently: NO ACTION
-- Change to: SET NULL (deleting a source nulls the reference)
ALTER TABLE ingested_articles
    DROP CONSTRAINT ingested_articles_source_id_fkey,
    ADD CONSTRAINT ingested_articles_source_id_fkey
        FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL;

COMMIT;
