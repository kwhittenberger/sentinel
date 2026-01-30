"""
Queue and worker metrics via Celery inspect API.

Results are cached for 5 seconds to avoid hammering the broker.
All inspect calls are run via asyncio.to_thread() since they are synchronous.
"""

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_cache: dict[str, Any] = {}
_cache_ts: dict[str, float] = {}
_CACHE_TTL = 5.0  # seconds


def _get_cached(key: str):
    """Return cached value if still fresh, else None."""
    ts = _cache_ts.get(key, 0)
    if time.monotonic() - ts < _CACHE_TTL:
        return _cache.get(key)
    return None


def _set_cached(key: str, value: Any):
    _cache[key] = value
    _cache_ts[key] = time.monotonic()


def _sync_inspect_overview() -> dict:
    """Synchronous Celery inspect (runs in thread)."""
    from backend.celery_app import app as celery_app

    inspector = celery_app.control.inspect()
    active = inspector.active() or {}
    reserved = inspector.reserved() or {}
    stats = inspector.stats() or {}

    queues: dict[str, dict] = {}
    workers: dict[str, dict] = {}
    total_active = 0
    total_reserved = 0

    for worker_name, task_list in active.items():
        count = len(task_list)
        total_active += count
        # Determine which queues this worker handles
        for task_info in task_list:
            q = task_info.get("delivery_info", {}).get("routing_key", "default")
            queues.setdefault(q, {"active": 0, "reserved": 0, "workers": []})
            queues[q]["active"] += 1
            if worker_name not in queues[q]["workers"]:
                queues[q]["workers"].append(worker_name)

        worker_stats = stats.get(worker_name, {})
        tasks_completed = sum(
            worker_stats.get("total", {}).values()
        ) if isinstance(worker_stats.get("total"), dict) else 0
        workers[worker_name] = {
            "status": "busy" if count > 0 else "idle",
            "active_tasks": count,
            "tasks_completed": tasks_completed,
        }

    for worker_name, task_list in reserved.items():
        count = len(task_list)
        total_reserved += count
        for task_info in task_list:
            q = task_info.get("delivery_info", {}).get("routing_key", "default")
            queues.setdefault(q, {"active": 0, "reserved": 0, "workers": []})
            queues[q]["reserved"] += 1
            if worker_name not in queues[q]["workers"]:
                queues[q]["workers"].append(worker_name)

        if worker_name not in workers:
            worker_stats = stats.get(worker_name, {})
            tasks_completed = sum(
                worker_stats.get("total", {}).values()
            ) if isinstance(worker_stats.get("total"), dict) else 0
            workers[worker_name] = {
                "status": "idle",
                "active_tasks": 0,
                "tasks_completed": tasks_completed,
            }

    # Ensure known queues appear even when empty
    for q_name in ("default", "fetch", "extraction", "enrichment"):
        queues.setdefault(q_name, {"active": 0, "reserved": 0, "workers": []})

    return {
        "queues": queues,
        "workers": workers,
        "totals": {
            "active_tasks": total_active,
            "reserved_tasks": total_reserved,
            "total_workers": len(workers),
        },
    }


async def get_metrics_overview() -> dict:
    """Return queue/worker overview (cached 5s)."""
    cached = _get_cached("overview")
    if cached is not None:
        return cached
    try:
        result = await asyncio.to_thread(_sync_inspect_overview)
        _set_cached("overview", result)
        return result
    except Exception as exc:
        logger.error(f"Celery inspect failed: {exc}")
        return {
            "queues": {},
            "workers": {},
            "totals": {"active_tasks": 0, "reserved_tasks": 0, "total_workers": 0},
            "error": str(exc),
        }


async def get_task_performance(period_hours: int = 24) -> dict:
    """Return per-task performance stats from task_metrics_aggregate or raw metrics."""
    from backend.database import fetch

    rows = await fetch("""
        SELECT
            task_name,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'completed') AS successful,
            COUNT(*) FILTER (WHERE status = 'failed') AS failed,
            AVG(duration_ms)::INTEGER AS avg_duration_ms,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)::INTEGER AS p95_duration_ms,
            SUM(items_processed) AS total_items
        FROM task_metrics
        WHERE created_at > NOW() - ($1 || ' hours')::INTERVAL
        GROUP BY task_name
        ORDER BY total DESC
    """, str(period_hours))

    tasks = []
    for r in rows:
        tasks.append({
            "name": r["task_name"],
            "total": r["total"],
            "successful": r["successful"],
            "failed": r["failed"],
            "avg_duration_ms": r["avg_duration_ms"],
            "p95_duration_ms": r["p95_duration_ms"],
            "total_items": r["total_items"] or 0,
        })

    return {"tasks": tasks}
