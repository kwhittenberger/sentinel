-- Migration 033: Unify data sources
-- Replaces rss_feeds with the existing sources table by adding scheduling columns,
-- seeding legacy data, and dropping rss_feeds.

-- Step 1: Add scheduling columns to sources table
ALTER TABLE sources ADD COLUMN IF NOT EXISTS interval_minutes INTEGER DEFAULT 60;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS last_fetched TIMESTAMP WITH TIME ZONE;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS last_error TEXT;

-- Step 2: Seed all legacy sources (idempotent — only if table is empty)
DO $$
BEGIN
  IF (SELECT count(*) FROM sources) = 0 THEN

    -- Tier 1 - Official government sources
    INSERT INTO sources (id, name, source_type, tier, url, fetcher_class, fetcher_config, interval_minutes, is_active, created_at)
    VALUES (
        uuid_generate_v4(),
        'ICE Detainee Death Reporting',
        'government',
        '1',
        'https://www.ice.gov/detain/detainee-death-reporting',
        'ICEGovSource',
        '{}',
        10080,
        true,
        NOW()
    );

    INSERT INTO sources (id, name, source_type, tier, url, fetcher_class, fetcher_config, interval_minutes, is_active, created_at)
    VALUES (
        uuid_generate_v4(),
        'AILA Deaths at Adult Detention Centers',
        'government',
        '1',
        'https://www.aila.org/library/deaths-at-adult-detention-centers',
        'AILASource',
        '{}',
        10080,
        true,
        NOW()
    );

    -- Tier 2 - Investigative journalism
    INSERT INTO sources (id, name, source_type, tier, url, fetcher_class, fetcher_config, interval_minutes, is_active, created_at)
    VALUES (
        uuid_generate_v4(),
        'The Trace ICE Shootings Tracker',
        'investigative',
        '2',
        'https://www.thetrace.org/2025/12/immigration-ice-shootings-guns-tracker/',
        'TheTraceSource',
        '{}',
        4320,
        true,
        NOW()
    );

    INSERT INTO sources (id, name, source_type, tier, url, fetcher_class, fetcher_config, interval_minutes, is_active, created_at)
    VALUES (
        uuid_generate_v4(),
        'NBC News ICE Shootings List',
        'investigative',
        '2',
        'https://www.nbcnews.com/news/us-news/ice-shootings-list-border-patrol-trump-immigration-operations-rcna254202',
        'NBCShootingsSource',
        '{}',
        4320,
        true,
        NOW()
    );

    INSERT INTO sources (id, name, source_type, tier, url, fetcher_class, fetcher_config, interval_minutes, is_active, created_at)
    VALUES (
        uuid_generate_v4(),
        'ProPublica US Citizens Investigation',
        'investigative',
        '2',
        'https://www.propublica.org/article/immigration-dhs-american-citizens-arrested-detained-against-will',
        NULL,
        '{}',
        10080,
        true,
        NOW()
    );

    -- Tier 3 - Systematic news search / APIs
    INSERT INTO sources (id, name, source_type, tier, url, fetcher_class, fetcher_config, interval_minutes, is_active, created_at)
    VALUES (
        uuid_generate_v4(),
        'News API',
        'news',
        '3',
        'https://newsapi.org/v2/everything',
        'NewsAPISource',
        '{"api_key_env_var": "NEWS_API_KEY", "search_terms": ["ICE arrest", "immigration enforcement", "deportation incident"]}',
        1440,
        true,
        NOW()
    );

    INSERT INTO sources (id, name, source_type, tier, url, fetcher_class, fetcher_config, interval_minutes, is_active, created_at)
    VALUES (
        uuid_generate_v4(),
        'GDELT Project',
        'news',
        '3',
        'https://api.gdeltproject.org/api/v2/doc/doc',
        'GDELTSource',
        '{"search_terms": ["ICE enforcement", "immigration raid", "border patrol shooting"]}',
        1440,
        true,
        NOW()
    );

  END IF;
END $$;

-- Step 3: Drop the rss_feeds table (superseded by sources)
DROP TABLE IF EXISTS rss_feeds;
