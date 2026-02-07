"""
Background job and metrics routes.
Extracted from main.py — job CRUD, WebSocket updates, Celery metrics.
"""

import uuid
import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Query, HTTPException, Body, WebSocket, WebSocketDisconnect

from backend.routes._shared import USE_DATABASE, USE_CELERY

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Jobs"])


# =====================
# Job Queue Endpoints
# =====================


@router.get("/api/admin/jobs")
async def list_jobs(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
):
    """List background jobs."""
    if not USE_DATABASE:
        return {"jobs": [], "total": 0}

    from backend.database import fetch

    _JOB_COLS = """id, job_type, status, progress, total, message,
            created_at, started_at, completed_at, error,
            celery_task_id, retry_count, max_retries, queue, priority"""

    if status:
        query = f"""
            SELECT {_JOB_COLS}
            FROM background_jobs
            WHERE status = $1
            ORDER BY created_at DESC
            LIMIT $2
        """
        rows = await fetch(query, status, limit)
    else:
        query = f"""
            SELECT {_JOB_COLS}
            FROM background_jobs
            ORDER BY created_at DESC
            LIMIT $1
        """
        rows = await fetch(query, limit)

    jobs = []
    for row in rows:
        job = dict(row)
        job['id'] = str(job['id'])
        for field in ['created_at', 'started_at', 'completed_at']:
            if job.get(field):
                job[field] = job[field].isoformat()
        jobs.append(job)

    return {"jobs": jobs, "total": len(jobs)}


def _dispatch_celery_task(job_type: str, job_id: str, params: dict):
    """Send a job to the appropriate Celery task queue."""
    from backend.tasks.fetch_tasks import run_fetch
    from backend.tasks.extraction_tasks import run_process, run_batch_extract
    from backend.tasks.enrichment_tasks import run_batch_enrich, run_enrichment
    from backend.tasks.pipeline_tasks import run_full_pipeline

    _TASK_MAP = {
        "fetch": run_fetch,
        "process": run_process,
        "batch_extract": run_batch_extract,
        "batch_enrich": run_batch_enrich,
        "cross_reference_enrich": run_enrichment,
        "full_pipeline": run_full_pipeline,
    }

    task_fn = _TASK_MAP.get(job_type)
    if task_fn is None:
        logger.warning(f"No Celery task mapped for job_type={job_type}")
        return
    task_fn.delay(job_id, params)


@router.post("/api/admin/jobs")
async def create_job(
    job_type: str = Body(..., embed=True),
    params: Optional[dict] = Body(None, embed=True),
):
    """Create a new background job."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute

    # Map job_type to Celery queue name
    _QUEUE_MAP = {
        "fetch": "fetch",
        "process": "extraction",
        "batch_extract": "extraction",
        "batch_enrich": "enrichment",
        "cross_reference_enrich": "enrichment",
        "full_pipeline": "default",
    }

    job_id = uuid.uuid4()
    queue = _QUEUE_MAP.get(job_type, "default")

    await execute("""
        INSERT INTO background_jobs (id, job_type, status, params, created_at, queue)
        VALUES ($1, $2, 'pending', $3, $4, $5)
    """, job_id, job_type, params or {}, datetime.utcnow(), queue)

    if USE_CELERY:
        _dispatch_celery_task(job_type, str(job_id), params or {})

    # Notify WebSocket clients
    from backend.jobs_ws import job_update_manager
    await job_update_manager.notify_job_changed(str(job_id))

    return {"success": True, "job_id": str(job_id)}


@router.get("/api/admin/jobs/{job_id}")
async def get_job(job_id: str):
    """Get job status and details."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import fetch

    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    rows = await fetch("""
        SELECT * FROM background_jobs WHERE id = $1
    """, job_uuid)

    if not rows:
        raise HTTPException(status_code=404, detail="Job not found")

    job = dict(rows[0])
    job['id'] = str(job['id'])
    for field in ['created_at', 'started_at', 'completed_at']:
        if job.get(field):
            job[field] = job[field].isoformat()

    return job


@router.delete("/api/admin/jobs/{job_id}")
async def cancel_job(job_id: str):
    """Cancel a pending or running job."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute, fetch as db_fetch

    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    # If Celery mode, revoke the task before updating DB
    if USE_CELERY:
        rows = await db_fetch(
            "SELECT celery_task_id FROM background_jobs WHERE id = $1", job_uuid
        )
        if rows and rows[0].get("celery_task_id"):
            from backend.celery_app import app as celery_app

            celery_app.control.revoke(
                rows[0]["celery_task_id"], terminate=True, signal="SIGTERM"
            )

    result = await execute("""
        UPDATE background_jobs
        SET status = 'cancelled', completed_at = $1
        WHERE id = $2 AND status IN ('pending', 'running')
    """, datetime.utcnow(), job_uuid)

    # Notify WebSocket clients
    from backend.jobs_ws import job_update_manager
    await job_update_manager.notify_job_changed(job_id)

    return {"success": True, "cancelled": job_id}


@router.delete("/api/admin/jobs/{job_id}/delete")
async def hard_delete_job(job_id: str):
    """Hard-delete a terminal-state job (completed, failed, cancelled)."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute, fetch as db_fetch

    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    rows = await db_fetch(
        "SELECT status FROM background_jobs WHERE id = $1", job_uuid
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Job not found")

    if rows[0]["status"] in ("pending", "running"):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete active job. Cancel it first.",
        )

    await execute("DELETE FROM background_jobs WHERE id = $1", job_uuid)
    return {"success": True, "deleted": job_id}


@router.post("/api/admin/jobs/{job_id}/retry")
async def retry_job(job_id: str):
    """Re-create a failed job with the same type and params."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute, fetch as db_fetch

    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    rows = await db_fetch(
        "SELECT job_type, params, queue FROM background_jobs WHERE id = $1",
        job_uuid,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Job not found")

    original = rows[0]
    new_id = uuid.uuid4()
    queue = original.get("queue") or "default"

    await execute("""
        INSERT INTO background_jobs (id, job_type, status, params, created_at, queue)
        VALUES ($1, $2, 'pending', $3, $4, $5)
    """, new_id, original["job_type"], original.get("params") or {}, datetime.utcnow(), queue)

    if USE_CELERY:
        _dispatch_celery_task(original["job_type"], str(new_id), original.get("params") or {})

    from backend.jobs_ws import job_update_manager
    await job_update_manager.notify_job_changed(str(new_id))

    return {"success": True, "new_job_id": str(new_id)}


@router.post("/api/admin/jobs/{job_id}/unstick")
async def unstick_job(job_id: str):
    """Reset a stale running job back to pending and re-dispatch."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute, fetch as db_fetch

    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    rows = await db_fetch(
        "SELECT status, job_type, params, queue, celery_task_id FROM background_jobs WHERE id = $1",
        job_uuid,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Job not found")

    job = rows[0]
    if job["status"] != "running":
        raise HTTPException(status_code=409, detail="Only running jobs can be unstuck")

    # Revoke the old Celery task if possible
    if USE_CELERY and job.get("celery_task_id"):
        from backend.celery_app import app as celery_app
        celery_app.control.revoke(job["celery_task_id"], terminate=True, signal="SIGTERM")

    await execute("""
        UPDATE background_jobs
        SET status = 'pending',
            started_at = NULL,
            celery_task_id = NULL,
            error = 'Unstuck by admin',
            retry_count = COALESCE(retry_count, 0) + 1
        WHERE id = $1
    """, job_uuid)

    # Re-dispatch
    if USE_CELERY:
        _dispatch_celery_task(job["job_type"], job_id, job.get("params") or {})

    from backend.jobs_ws import job_update_manager
    await job_update_manager.notify_job_changed(job_id)

    return {"success": True, "unstuck": job_id}


# =====================
# WebSocket: Job Updates
# =====================


@router.websocket("/ws/jobs")
async def websocket_jobs(ws: WebSocket):
    """Real-time job status stream."""
    from backend.jobs_ws import job_update_manager

    await job_update_manager.connect(ws)
    try:
        while True:
            # Keep connection alive; client may send pings
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await job_update_manager.disconnect(ws)


# =====================
# Metrics Endpoints
# =====================


@router.get("/api/metrics/overview")
async def metrics_overview():
    """Queue and worker stats via Celery inspect (cached 5s)."""
    if not USE_CELERY:
        return {
            "queues": {},
            "workers": {},
            "totals": {"active_tasks": 0, "reserved_tasks": 0, "total_workers": 0},
        }
    from backend.metrics import get_metrics_overview
    return await get_metrics_overview()


@router.get("/api/metrics/task-performance")
async def metrics_task_performance(period: str = Query("24h")):
    """Per-task performance stats from task_metrics table."""
    if not USE_DATABASE:
        return {"tasks": []}

    # Parse period string (e.g. "24h", "7d")
    hours = 24
    if period.endswith("h"):
        hours = int(period[:-1])
    elif period.endswith("d"):
        hours = int(period[:-1]) * 24

    from backend.metrics import get_task_performance
    return await get_task_performance(hours)
