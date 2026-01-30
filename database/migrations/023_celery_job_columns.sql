-- Migration 023: Add Celery job queue columns to background_jobs
-- Supports Celery task tracking, retry logic, queue routing, and scheduling.

ALTER TABLE background_jobs
  ADD COLUMN IF NOT EXISTS celery_task_id VARCHAR(255),
  ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS max_retries INTEGER DEFAULT 3,
  ADD COLUMN IF NOT EXISTS queue VARCHAR(50) DEFAULT 'default',
  ADD COLUMN IF NOT EXISTS priority INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX IF NOT EXISTS idx_bg_jobs_celery_task ON background_jobs(celery_task_id);
CREATE INDEX IF NOT EXISTS idx_bg_jobs_scheduled ON background_jobs(scheduled_at)
    WHERE scheduled_at IS NOT NULL;
