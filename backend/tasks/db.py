"""
Worker-local asyncpg pool and job status helpers for Celery tasks.

Each Celery worker process gets its own asyncpg connection pool, created lazily
on first use per event loop. Since each asyncio.run() creates a fresh loop,
the pool is reset between task invocations and re-created on first use.

Tasks should call run_task() which wraps the full lifecycle
(mark_started -> handler -> mark_completed/failed) in a single asyncio.run().
"""

import asyncio
import json
import os
import logging
from datetime import datetime, timezone
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://sentinel:devpassword@localhost:5433/sentinel",
)

# Worker-local pool (one per worker process)
_pool: Optional[asyncpg.Pool] = None


async def _init_connection(conn: asyncpg.Connection):
    """Register JSON codecs on each connection (mirrors backend/database.py)."""
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
    await conn.set_type_codec(
        "json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def get_pool() -> asyncpg.Pool:
    """Get or create the asyncpg pool for the current event loop.

    Each asyncio.run() creates a new event loop, so we recreate the pool
    whenever the loop changes.
    """
    global _pool
    if _pool is not None:
        # Pool exists but may be from a previous (now closed) event loop.
        # asyncpg pools are bound to the loop they were created on.
        try:
            # Quick check: can we still use it?
            await _pool.execute("SELECT 1")
        except Exception:
            logger.info("Stale asyncpg pool detected, recreating")
            try:
                _pool.terminate()
            except Exception:
                pass
            _pool = None

    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=5,
            command_timeout=60,
            init=_init_connection,
        )
        logger.info("Worker asyncpg pool created")
    return _pool


async def close_pool():
    """Close the worker-local pool (called on worker shutdown)."""
    global _pool
    if _pool is not None:
        try:
            await _pool.close()
        except Exception:
            pass
        _pool = None
        logger.info("Worker asyncpg pool closed")


# ---------------------------------------------------------------------------
# Async helpers (called inside asyncio.run from tasks)
# ---------------------------------------------------------------------------


async def async_mark_job_started(job_id: str, celery_task_id: str):
    """Mark a background_jobs row as running with the Celery task ID."""
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE background_jobs
        SET status = 'running',
            started_at = $1,
            celery_task_id = $2
        WHERE id = $3::uuid
        """,
        datetime.now(timezone.utc),
        celery_task_id,
        job_id,
    )


async def async_mark_job_completed(job_id: str, message: str = "Completed"):
    """Mark a background_jobs row as completed."""
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE background_jobs
        SET status = 'completed',
            completed_at = $1,
            message = $2
        WHERE id = $3::uuid
        """,
        datetime.now(timezone.utc),
        message,
        job_id,
    )


async def async_mark_job_failed(job_id: str, error: str):
    """Mark a background_jobs row as failed."""
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE background_jobs
        SET status = 'failed',
            completed_at = $1,
            error = $2
        WHERE id = $3::uuid
        """,
        datetime.now(timezone.utc),
        error,
        job_id,
    )


async def async_update_progress(job_id: str, progress: int, total: int, message: str):
    """Update progress counters on a running job."""
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE background_jobs
        SET progress = $1,
            total = $2,
            message = $3
        WHERE id = $4::uuid
        """,
        progress,
        total,
        message,
        job_id,
    )


async def async_increment_retry(job_id: str):
    """Increment retry_count on a job."""
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE background_jobs
        SET retry_count = retry_count + 1
        WHERE id = $1::uuid
        """,
        job_id,
    )


async def async_fetch(query: str, *args):
    """Run an arbitrary SELECT and return rows."""
    pool = await get_pool()
    return await pool.fetch(query, *args)


async def async_execute(query: str, *args):
    """Run an arbitrary statement."""
    pool = await get_pool()
    return await pool.execute(query, *args)


# ---------------------------------------------------------------------------
# Single-loop task runner
# ---------------------------------------------------------------------------


async def _record_task_metric(
    job_id: str,
    task_name: str,
    queue: str,
    status: str,
    started_at: datetime,
    completed_at: datetime,
    error: Optional[str] = None,
    items_processed: int = 0,
    metadata: Optional[dict] = None,
):
    """Record a task execution metric row."""
    try:
        pool = await get_pool()
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        await pool.execute(
            """
            INSERT INTO task_metrics
                (job_id, task_name, queue, status, started_at, completed_at,
                 duration_ms, error, items_processed, metadata)
            VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            job_id,
            task_name,
            queue,
            status,
            started_at,
            completed_at,
            duration_ms,
            error,
            items_processed,
            metadata or {},
        )
    except Exception as exc:
        logger.warning(f"Failed to record task metric: {exc}")


async def _run_task_lifecycle(
    job_id: str,
    celery_task_id: str,
    handler,
    params: dict,
) -> dict:
    """Run the full task lifecycle in a single event loop.

    mark_started -> handler(job_id, params) -> mark_completed or mark_failed.
    This avoids creating multiple event loops (which breaks asyncpg pools).
    Also records execution metrics in task_metrics.
    """
    started_at = datetime.now(timezone.utc)
    await async_mark_job_started(job_id, celery_task_id)

    # Resolve task name and queue from the job row
    task_name = "unknown"
    queue = "default"
    try:
        pool = await get_pool()
        row = await pool.fetchrow(
            "SELECT job_type, queue FROM background_jobs WHERE id = $1::uuid", job_id
        )
        if row:
            task_name = row["job_type"]
            queue = row.get("queue") or "default"
    except Exception:
        pass

    try:
        result = await handler(job_id, params)
        completed_at = datetime.now(timezone.utc)
        await async_mark_job_completed(job_id, result.get("message", "Completed"))

        items = result.get("items_processed") or result.get("total", 0)
        await _record_task_metric(
            job_id, task_name, queue, "completed",
            started_at, completed_at,
            items_processed=items,
            metadata={"handler_result_keys": list(result.keys())},
        )
        return result
    except Exception as exc:
        completed_at = datetime.now(timezone.utc)
        await async_mark_job_failed(job_id, str(exc))
        await _record_task_metric(
            job_id, task_name, queue, "failed",
            started_at, completed_at,
            error=str(exc),
        )
        raise


def run_task(job_id: str, celery_task_id: str, handler, params: dict) -> dict:
    """Sync entry point: run the full task lifecycle in one asyncio.run() call."""
    global _pool
    _pool = None  # Force fresh pool for this event loop
    return asyncio.run(
        _run_task_lifecycle(job_id, celery_task_id, handler, params)
    )
