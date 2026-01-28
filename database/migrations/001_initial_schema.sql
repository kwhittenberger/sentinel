-- Migration 001: Initial Schema
-- This migration creates the base tables for the unified incident tracker

-- Run the main schema
\i /app/database/schema.sql

-- Add migration tracking table
CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(255) PRIMARY KEY,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Record this migration
INSERT INTO schema_migrations (version) VALUES ('001_initial_schema');
