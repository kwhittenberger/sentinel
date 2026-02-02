-- Add 'error' to curation_status enum for articles that fail during processing.
-- Distinct from 'rejected' (human decision) — errors are system failures that may be retryable.
ALTER TYPE curation_status ADD VALUE IF NOT EXISTS 'error';
