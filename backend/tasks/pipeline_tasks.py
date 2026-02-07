"""Celery task for full pipeline (fetch + enrich + extract)."""

import logging

from celery.exceptions import SoftTimeLimitExceeded

from backend.celery_app import (
    app,
    PIPELINE_MAX_RETRIES,
    PIPELINE_RETRY_BACKOFF,
    PIPELINE_RETRY_BACKOFF_MAX,
)
from backend.tasks.db import (
    async_update_progress,
    run_task,
)
from backend.tasks.fetch_tasks import _async_fetch_handler
from backend.tasks.enrichment_tasks import _async_batch_enrich_handler
from backend.tasks.extraction_tasks import _async_process_handler

logger = logging.getLogger(__name__)


async def _async_full_pipeline_handler(job_id: str, params: dict) -> dict:
    """Run complete pipeline: fetch, enrich, extract (mirrors _run_full_pipeline_job)."""
    results = {}

    await async_update_progress(job_id, 0, 3, "Step 1/3: Fetching articles...")
    fetch_result = await _async_fetch_handler(job_id, params)
    results["fetch"] = fetch_result

    await async_update_progress(job_id, 1, 3, "Step 2/3: Enriching articles...")
    enrich_result = await _async_batch_enrich_handler(job_id, params)
    results["enrich"] = enrich_result

    await async_update_progress(job_id, 2, 3, "Step 3/3: Extracting data...")
    extract_result = await _async_process_handler(job_id, params)
    results["extract"] = extract_result

    await async_update_progress(job_id, 3, 3, "Pipeline completed")
    return {
        "message": (
            f"Pipeline complete: fetched {fetch_result.get('fetched', 0)}, "
            f"extracted {extract_result.get('processed', 0)}"
        ),
        "results": results,
    }


@app.task(
    bind=True,
    name="backend.tasks.pipeline_tasks.run_full_pipeline",
    acks_late=True,
    soft_time_limit=3600,
    time_limit=3720,
    max_retries=PIPELINE_MAX_RETRIES,
    autoretry_for=(ConnectionError,),
    retry_backoff=PIPELINE_RETRY_BACKOFF,
    retry_backoff_max=PIPELINE_RETRY_BACKOFF_MAX,
)
def run_full_pipeline(self, job_id: str, params: dict):
    """Run complete pipeline: fetch, enrich, extract."""
    try:
        return run_task(job_id, self.request.id, _async_full_pipeline_handler, params)
    except SoftTimeLimitExceeded:
        raise
