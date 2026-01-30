-- Migration 024: Task performance metrics
-- Records per-task execution data and periodic aggregates for the Job Dashboard.

CREATE TABLE task_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID REFERENCES background_jobs(id) ON DELETE SET NULL,
    task_name VARCHAR(100) NOT NULL,
    queue VARCHAR(50) NOT NULL DEFAULT 'default',
    status VARCHAR(20) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    duration_ms INTEGER NOT NULL,
    error TEXT,
    items_processed INTEGER DEFAULT 0,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_task_metrics_task_name ON task_metrics(task_name);
CREATE INDEX idx_task_metrics_created_at ON task_metrics(created_at DESC);
CREATE INDEX idx_task_metrics_status ON task_metrics(status);

CREATE TABLE task_metrics_aggregate (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    task_name VARCHAR(100) NOT NULL,
    total_runs INTEGER DEFAULT 0,
    successful INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    avg_duration_ms INTEGER,
    p95_duration_ms INTEGER,
    total_items_processed INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(period_start, task_name)
);

CREATE INDEX idx_task_metrics_agg_period ON task_metrics_aggregate(period_start DESC);
CREATE INDEX idx_task_metrics_agg_task ON task_metrics_aggregate(task_name);
