"""Celery tasks for article enrichment (batch_enrich + cross_reference_enrich)."""

import logging

from celery.exceptions import SoftTimeLimitExceeded

from backend.celery_app import (
    app,
    BATCH_ENRICH_MAX_RETRIES,
    BATCH_ENRICH_RETRY_BACKOFF,
    BATCH_ENRICH_RETRY_BACKOFF_MAX,
    ENRICH_MAX_RETRIES,
    ENRICH_RETRY_BACKOFF,
    ENRICH_RETRY_BACKOFF_MAX,
)
from backend.tasks.db import (
    async_fetch,
    async_execute,
    async_update_progress,
    run_task,
)

logger = logging.getLogger(__name__)


async def _async_batch_enrich_handler(job_id: str, params: dict) -> dict:
    """Enrich articles with full content (mirrors _run_batch_enrich_job)."""
    import httpx

    limit = params.get("limit", 50)

    articles = await async_fetch(
        """
        SELECT id, source_url, content
        FROM ingested_articles
        WHERE status = 'pending'
          AND (content IS NULL OR LENGTH(content) < 500)
        ORDER BY fetched_at DESC
        LIMIT $1
        """,
        limit,
    )

    if not articles:
        return {"message": "No articles to enrich", "enriched": 0}

    total = len(articles)
    enriched = 0

    async with httpx.AsyncClient() as client:
        for i, article in enumerate(articles):
            await async_update_progress(
                job_id, i, total, f"Enriching article {i + 1}/{total}"
            )

            try:
                response = await client.get(
                    article["source_url"], timeout=30, follow_redirects=True
                )
                if response.status_code == 200:
                    content = response.text[:50000]
                    await async_execute(
                        """
                        UPDATE ingested_articles
                        SET content = $1
                        WHERE id = $2
                        """,
                        content,
                        article["id"],
                    )
                    enriched += 1

            except Exception as e:
                logger.warning(f"Failed to enrich article {article['id']}: {e}")

    await async_update_progress(job_id, total, total, "Completed")
    return {"message": f"Enriched {enriched}/{total} articles", "enriched": enriched}


async def _async_enrichment_handler(job_id: str, params: dict) -> dict:
    """Cross-reference enrichment (mirrors _run_enrichment_job)."""
    from backend.services.enrichment_service import get_enrichment_service

    service = get_enrichment_service()

    strategy = params.get("strategy", "cross_incident")
    limit = params.get("limit", 100)
    target_fields = params.get("target_fields")
    auto_apply = params.get("auto_apply", strategy == "cross_incident")
    min_confidence = params.get("min_confidence", 0.7)

    enrichment_params = {
        "limit": limit,
        "target_fields": target_fields,
        "auto_apply": auto_apply,
        "min_confidence": min_confidence,
    }

    result = await service.run_enrichment(
        strategy=strategy,
        params=enrichment_params,
        job_id=job_id,
        progress_callback=lambda p, t, m: async_update_progress(job_id, p, t, m),
    )

    return {
        "message": (
            f"Enrichment complete: {result.incidents_enriched}/{result.total_incidents} "
            f"incidents enriched, {result.fields_filled} fields filled"
        ),
        "run_id": result.run_id,
        "strategy": result.strategy,
        "incidents_enriched": result.incidents_enriched,
        "fields_filled": result.fields_filled,
        "errors": result.errors,
    }


@app.task(
    bind=True,
    name="backend.tasks.enrichment_tasks.run_batch_enrich",
    acks_late=True,
    soft_time_limit=600,
    time_limit=720,
    max_retries=BATCH_ENRICH_MAX_RETRIES,
    autoretry_for=(ConnectionError,),
    retry_backoff=BATCH_ENRICH_RETRY_BACKOFF,
    retry_backoff_max=BATCH_ENRICH_RETRY_BACKOFF_MAX,
)
def run_batch_enrich(self, job_id: str, params: dict):
    """Enrich articles with additional data."""
    try:
        return run_task(job_id, self.request.id, _async_batch_enrich_handler, params)
    except SoftTimeLimitExceeded:
        raise


@app.task(
    bind=True,
    name="backend.tasks.enrichment_tasks.run_enrichment",
    acks_late=True,
    soft_time_limit=1800,
    time_limit=1920,
    max_retries=ENRICH_MAX_RETRIES,
    autoretry_for=(ConnectionError,),
    retry_backoff=ENRICH_RETRY_BACKOFF,
    retry_backoff_max=ENRICH_RETRY_BACKOFF_MAX,
)
def run_enrichment(self, job_id: str, params: dict):
    """Run cross-reference enrichment on incidents."""
    try:
        return run_task(job_id, self.request.id, _async_enrichment_handler, params)
    except SoftTimeLimitExceeded:
        raise
