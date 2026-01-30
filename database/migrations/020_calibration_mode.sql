-- Migration 020: Calibration mode for model comparisons
-- Enables side-by-side extraction on real articles without a pre-built golden dataset.
-- Human review of calibration articles produces golden extractions that can be
-- saved as a new test dataset for subsequent scored comparisons.

-- Make dataset_id nullable (calibration mode has no upfront dataset)
ALTER TABLE prompt_test_comparisons
    ALTER COLUMN dataset_id DROP NOT NULL;

-- Add calibration columns
ALTER TABLE prompt_test_comparisons
    ADD COLUMN mode VARCHAR(20) NOT NULL DEFAULT 'dataset'
        CHECK (mode IN ('dataset', 'calibration')),
    ADD COLUMN output_dataset_id UUID REFERENCES prompt_test_datasets(id),
    ADD COLUMN article_count INTEGER,
    ADD COLUMN article_filters JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN reviewed_count INTEGER DEFAULT 0,
    ADD COLUMN total_articles INTEGER DEFAULT 0;

-- Per-article extractions and review decisions for calibration
CREATE TABLE comparison_articles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    comparison_id UUID NOT NULL REFERENCES prompt_test_comparisons(id) ON DELETE CASCADE,
    article_id UUID NOT NULL REFERENCES ingested_articles(id),

    -- Snapshot of article content
    article_title VARCHAR(500),
    article_content TEXT,
    article_source_url TEXT,
    article_published_date DATE,

    -- Config A result
    config_a_extraction JSONB,
    config_a_confidence DECIMAL(3, 2),
    config_a_duration_ms INTEGER,
    config_a_error TEXT,

    -- Config B result
    config_b_extraction JSONB,
    config_b_confidence DECIMAL(3, 2),
    config_b_duration_ms INTEGER,
    config_b_error TEXT,

    -- Human review
    review_status VARCHAR(20) DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'reviewed', 'skipped')),
    chosen_config VARCHAR(1) CHECK (chosen_config IN ('A', 'B')),
    golden_extraction JSONB,
    reviewer_notes TEXT,
    reviewed_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(comparison_id, article_id)
);

CREATE INDEX idx_comparison_articles_comp ON comparison_articles(comparison_id);
CREATE INDEX idx_comparison_articles_review ON comparison_articles(review_status);

-- Grants
GRANT SELECT, INSERT, UPDATE, DELETE ON comparison_articles TO sentinel;
