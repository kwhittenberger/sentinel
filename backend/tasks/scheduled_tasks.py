"""Scheduled Celery tasks: periodic fetch and stale-job watchdog."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from backend.celery_app import app
from backend.tasks.db import (
    async_fetch,
    async_execute,
    async_mark_job_started,
    async_mark_job_completed,
    async_mark_job_failed,
)

logger = logging.getLogger(__name__)


# Force fresh pool per asyncio.run() — import the module-level reset
import backend.tasks.db as _db


async def _async_scheduled_fetch() -> dict:
    """Create a background_jobs row and run a fetch job triggered by beat."""
    job_id = str(uuid.uuid4())

    await async_execute(
        """
        INSERT INTO background_jobs (id, job_type, status, params, created_at, queue)
        VALUES ($1::uuid, 'fetch', 'pending', $2, $3, 'fetch')
        """,
        job_id,
        {},
        datetime.now(timezone.utc),
    )

    await async_mark_job_started(job_id, "beat-scheduled")

    try:
        from backend.tasks.fetch_tasks import _async_fetch_handler

        result = await _async_fetch_handler(job_id, {})
        await async_mark_job_completed(job_id, result.get("message", "Completed"))
        return result
    except Exception as exc:
        await async_mark_job_failed(job_id, str(exc))
        raise


async def _async_cleanup_stale_jobs() -> dict:
    """Watchdog: detect stale running jobs and optionally retry them."""
    stale_jobs = await async_fetch("""
        SELECT id, job_type, retry_count, max_retries
        FROM background_jobs
        WHERE status = 'running'
          AND started_at < NOW() - INTERVAL '2 hours'
    """)

    marked_failed = 0
    retried = 0

    for job in stale_jobs:
        job_id = str(job["id"])
        retry_count = job.get("retry_count") or 0
        max_retries = job.get("max_retries") or 3

        if retry_count < max_retries:
            await async_execute(
                """
                UPDATE background_jobs
                SET status = 'pending',
                    retry_count = retry_count + 1,
                    error = 'Worker crash detected (stale timeout) - retrying',
                    celery_task_id = NULL,
                    started_at = NULL
                WHERE id = $1::uuid
                """,
                job_id,
            )
            retried += 1
            logger.warning(
                f"Stale job {job_id} ({job['job_type']}) reset to pending "
                f"(retry {retry_count + 1}/{max_retries})"
            )
        else:
            await async_execute(
                """
                UPDATE background_jobs
                SET status = 'failed',
                    completed_at = $1,
                    error = 'Worker crash detected (stale timeout)'
                WHERE id = $2::uuid
                """,
                datetime.now(timezone.utc),
                job_id,
            )
            marked_failed += 1
            logger.error(
                f"Stale job {job_id} ({job['job_type']}) marked failed "
                f"(exhausted {max_retries} retries)"
            )

    cleanup_result = await async_execute("""
        DELETE FROM background_jobs
        WHERE status IN ('completed', 'failed', 'cancelled')
          AND completed_at < NOW() - INTERVAL '30 days'
    """)

    return {
        "stale_found": len(stale_jobs),
        "marked_failed": marked_failed,
        "retried": retried,
        "cleanup": str(cleanup_result),
    }


@app.task(
    bind=True,
    name="backend.tasks.scheduled_tasks.scheduled_fetch",
    acks_late=True,
    soft_time_limit=300,
    time_limit=360,
)
def scheduled_fetch(self):
    """Hourly RSS fetch triggered by Celery Beat."""
    logger.info("Scheduled fetch starting")
    _db._pool = None  # Force fresh pool
    try:
        result = asyncio.run(_async_scheduled_fetch())
        logger.info(f"Scheduled fetch completed: {result}")
        return result
    except Exception as exc:
        logger.error(f"Scheduled fetch failed: {exc}")
        raise


@app.task(
    bind=True,
    name="backend.tasks.scheduled_tasks.cleanup_stale_jobs",
    acks_late=True,
    soft_time_limit=60,
    time_limit=120,
)
def cleanup_stale_jobs(self):
    """Watchdog: find stale running jobs and mark them failed or retry."""
    logger.info("Stale job cleanup starting")
    _db._pool = None  # Force fresh pool
    try:
        result = asyncio.run(_async_cleanup_stale_jobs())
        logger.info(f"Stale job cleanup completed: {result}")
        return result
    except Exception as exc:
        logger.error(f"Stale job cleanup failed: {exc}")
        raise


async def _async_aggregate_metrics() -> dict:
    """Aggregate raw task_metrics into 5-minute period buckets."""
    # Find the latest aggregated period to avoid re-processing
    latest = await async_fetch("""
        SELECT MAX(period_end) AS latest FROM task_metrics_aggregate
    """)
    # Default: aggregate from 24h ago if no prior aggregation
    from_time = latest[0]["latest"] if latest and latest[0]["latest"] else None
    if from_time is None:
        from_time = datetime.now(timezone.utc) - __import__("datetime").timedelta(hours=24)

    result = await async_execute("""
        INSERT INTO task_metrics_aggregate
            (period_start, period_end, task_name,
             total_runs, successful, failed,
             avg_duration_ms, p95_duration_ms, total_items_processed)
        SELECT
            date_trunc('hour', completed_at)
                + INTERVAL '5 min' * FLOOR(EXTRACT(MINUTE FROM completed_at) / 5)
                AS period_start,
            date_trunc('hour', completed_at)
                + INTERVAL '5 min' * (FLOOR(EXTRACT(MINUTE FROM completed_at) / 5) + 1)
                AS period_end,
            task_name,
            COUNT(*),
            COUNT(*) FILTER (WHERE status = 'completed'),
            COUNT(*) FILTER (WHERE status = 'failed'),
            AVG(duration_ms)::INTEGER,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)::INTEGER,
            SUM(items_processed)
        FROM task_metrics
        WHERE completed_at > $1
        GROUP BY period_start, period_end, task_name
        ON CONFLICT (period_start, task_name) DO UPDATE SET
            total_runs = EXCLUDED.total_runs,
            successful = EXCLUDED.successful,
            failed = EXCLUDED.failed,
            avg_duration_ms = EXCLUDED.avg_duration_ms,
            p95_duration_ms = EXCLUDED.p95_duration_ms,
            total_items_processed = EXCLUDED.total_items_processed
    """, from_time)

    return {"status": "aggregated", "result": str(result)}


@app.task(
    bind=True,
    name="backend.tasks.scheduled_tasks.aggregate_metrics",
    acks_late=True,
    soft_time_limit=60,
    time_limit=120,
)
def aggregate_metrics(self):
    """Periodically aggregate task_metrics into summary buckets."""
    logger.info("Metrics aggregation starting")
    _db._pool = None  # Force fresh pool
    try:
        result = asyncio.run(_async_aggregate_metrics())
        logger.info(f"Metrics aggregation completed: {result}")
        return result
    except Exception as exc:
        logger.error(f"Metrics aggregation failed: {exc}")
        raise
