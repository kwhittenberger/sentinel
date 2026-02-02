-- Migration 025: Add merge_info columns for stage2 selection/merge metadata
-- Stores information about which schemas were merged and how for each config

ALTER TABLE comparison_articles
    ADD COLUMN config_a_merge_info JSONB,
    ADD COLUMN config_b_merge_info JSONB;
