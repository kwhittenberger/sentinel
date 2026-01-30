"""
WebSocket manager for real-time job status broadcasting.

Maintains a set of connected clients and broadcasts job snapshots every 2 seconds.
Immediate notifications are sent when jobs are created or cancelled via notify_job_changed().
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

_JOB_COLS = """id, job_type, status, progress, total, message,
    created_at, started_at, completed_at, error,
    celery_task_id, retry_count, max_retries, queue, priority"""


def _serialize_job(row: dict) -> dict:
    """Convert a database row to a JSON-safe dict."""
    job = dict(row)
    job["id"] = str(job["id"])
    for field in ("created_at", "started_at", "completed_at"):
        if job.get(field):
            job[field] = job[field].isoformat()
    return job


class JobUpdateManager:
    """Broadcasts job status to connected WebSocket clients."""

    def __init__(self):
        self._connections: set[WebSocket] = set()
        self._broadcast_task: asyncio.Task | None = None
        self._last_snapshot: str = "[]"

    async def start(self):
        """Start the background broadcast loop."""
        self._broadcast_task = asyncio.create_task(self._broadcast_loop())
        logger.info("JobUpdateManager started")

    async def stop(self):
        """Stop the broadcast loop and close all connections."""
        if self._broadcast_task:
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass
            self._broadcast_task = None

        for ws in list(self._connections):
            try:
                await ws.close()
            except Exception:
                pass
        self._connections.clear()
        logger.info("JobUpdateManager stopped")

    async def connect(self, ws: WebSocket):
        """Accept a new WebSocket connection and send the initial snapshot."""
        await ws.accept()
        self._connections.add(ws)
        logger.debug(f"WS client connected ({len(self._connections)} total)")

        # Send initial snapshot
        try:
            snapshot = await self._fetch_jobs()
            await ws.send_text(json.dumps({
                "type": "jobs_snapshot",
                "jobs": snapshot,
            }))
        except Exception as exc:
            logger.warning(f"Failed to send initial snapshot: {exc}")

    async def disconnect(self, ws: WebSocket):
        """Remove a disconnected client."""
        self._connections.discard(ws)
        logger.debug(f"WS client disconnected ({len(self._connections)} total)")

    async def notify_job_changed(self, job_id: str):
        """Immediately broadcast a single job update (e.g. on create/cancel)."""
        if not self._connections:
            return
        try:
            from backend.database import fetch
            rows = await fetch(
                f"SELECT {_JOB_COLS} FROM background_jobs WHERE id = $1::uuid",
                job_id,
            )
            if rows:
                job = _serialize_job(rows[0])
                msg = json.dumps({"type": "job_updated", "job": job})
                await self._send_to_all(msg)
        except Exception as exc:
            logger.warning(f"notify_job_changed failed: {exc}")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _broadcast_loop(self):
        """Every 2s, fetch active + recent jobs and broadcast if changed."""
        while True:
            try:
                await asyncio.sleep(2)
                if not self._connections:
                    continue

                jobs = await self._fetch_jobs()
                payload = json.dumps(jobs, sort_keys=True)

                if payload != self._last_snapshot:
                    self._last_snapshot = payload
                    msg = json.dumps({"type": "jobs_update", "jobs": jobs})
                    await self._send_to_all(msg)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"Broadcast loop error: {exc}")
                await asyncio.sleep(5)

    async def _fetch_jobs(self) -> list[dict]:
        """Return active jobs + most recent 20 completed/failed."""
        from backend.database import fetch

        cutoff = datetime.utcnow() - timedelta(hours=24)
        rows = await fetch(f"""
            (SELECT {_JOB_COLS} FROM background_jobs
             WHERE status IN ('pending', 'running')
             ORDER BY created_at DESC)
            UNION ALL
            (SELECT {_JOB_COLS} FROM background_jobs
             WHERE status IN ('completed', 'failed', 'cancelled')
               AND created_at > $1
             ORDER BY completed_at DESC NULLS LAST
             LIMIT 20)
        """, cutoff)

        return [_serialize_job(r) for r in rows]

    async def _send_to_all(self, message: str):
        """Send a message to all connected clients, removing dead ones."""
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.discard(ws)


# Module-level singleton
job_update_manager = JobUpdateManager()
