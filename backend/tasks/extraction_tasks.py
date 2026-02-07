"""Celery tasks for LLM extraction (process + batch_extract)."""

import asyncio
import logging

from celery.exceptions import SoftTimeLimitExceeded

from backend.celery_app import (
    app,
    EXTRACT_MAX_RETRIES,
    EXTRACT_RETRY_BACKOFF,
    EXTRACT_RETRY_BACKOFF_MAX,
    EXTRACT_MANUAL_RETRY_BASE,
    BATCH_EXTRACT_MAX_RETRIES,
    BATCH_EXTRACT_RETRY_BACKOFF,
    BATCH_EXTRACT_RETRY_BACKOFF_MAX,
    BATCH_EXTRACT_MANUAL_RETRY_BASE,
)
from backend.tasks.db import (
    async_fetch,
    async_execute,
    async_update_progress,
    run_task,
)

logger = logging.getLogger(__name__)


async def _async_process_handler(job_id: str, params: dict) -> dict:
    """Process pending articles with LLM extraction (mirrors _run_process_job)."""
    from backend.services import get_extractor

    limit = params.get("limit", 50)

    articles = await async_fetch(
        """
        SELECT id, title, content
        FROM ingested_articles
        WHERE status = 'pending'
          AND extracted_data IS NULL
        ORDER BY fetched_at DESC
        LIMIT $1
        """,
        limit,
    )

    if not articles:
        return {"message": "No articles to process", "processed": 0}

    extractor = get_extractor()
    if not extractor.is_available():
        return {"message": "LLM extractor not available", "processed": 0}

    total = len(articles)
    processed = 0

    for i, article in enumerate(articles):
        await async_update_progress(
            job_id, i, total, f"Processing article {i + 1}/{total}"
        )

        try:
            full_text = (
                f"{article['title']}\n\n{article['content']}"
                if article["title"]
                else article["content"]
            )
            result = extractor.extract(full_text or "")

            await async_execute(
                """
                UPDATE ingested_articles
                SET extracted_data = $1,
                    extraction_confidence = $2,
                    relevance_score = $3
                WHERE id = $4
                """,
                result,
                result.get("confidence"),
                1.0 if result.get("is_relevant") else 0.0,
                article["id"],
            )
            processed += 1

        except Exception as e:
            logger.warning(f"Failed to process article {article['id']}: {e}")

    await async_update_progress(job_id, total, total, "Completed")
    return {"message": f"Processed {processed}/{total} articles", "processed": processed}


async def _async_batch_extract_handler(job_id: str, params: dict) -> dict:
    """Run universal extraction on pending articles (mirrors _run_batch_extract_job)."""
    from backend.services import get_extractor

    limit = params.get("limit", 1000)

    articles = await async_fetch(
        """
        SELECT id, title, content, source_url
        FROM ingested_articles
        WHERE status = 'pending'
          AND content IS NOT NULL
          AND (extracted_data->>'success' IS NULL OR extracted_data->>'success' != 'true')
        ORDER BY fetched_at ASC
        LIMIT $1
        """,
        limit,
    )

    if not articles:
        return {"message": "No articles to extract", "processed": 0}

    extractor = get_extractor()
    if not extractor.is_available():
        return {"message": "LLM extractor not available", "processed": 0}

    total = len(articles)
    processed = 0
    relevant = 0
    errors = 0

    for i, article in enumerate(articles):
        await async_update_progress(
            job_id,
            i,
            total,
            f"Extracting {i + 1}/{total}: {article['title'][:50]}...",
        )

        try:
            full_text = (
                f"{article['title']}\n\n{article['content']}"
                if article["title"]
                else article["content"]
            )
            result = await extractor.extract_universal_async(full_text or "")

            if result.get("success", True):
                await async_execute(
                    """
                    UPDATE ingested_articles
                    SET extracted_data = $1,
                        extraction_confidence = $2,
                        relevance_score = $3
                    WHERE id = $4
                    """,
                    result,
                    result.get("confidence", 0.5),
                    1.0 if result.get("is_relevant") else 0.0,
                    article["id"],
                )
                processed += 1
                if result.get("is_relevant"):
                    relevant += 1
            else:
                errors += 1
                logger.warning(
                    f"Extraction failed for {article['id']}: {result.get('error')}"
                )

        except Exception as e:
            errors += 1
            logger.warning(f"Failed to extract article {article['id']}: {e}")

        # Rate limiting for LLM API
        await asyncio.sleep(2)

    await async_update_progress(
        job_id, total, total, f"Completed: {processed} extracted, {relevant} relevant"
    )
    return {
        "message": f"Extracted {processed}/{total} articles ({relevant} relevant, {errors} errors)",
        "processed": processed,
        "relevant": relevant,
        "errors": errors,
    }


@app.task(
    bind=True,
    name="backend.tasks.extraction_tasks.run_process",
    acks_late=True,
    soft_time_limit=600,
    time_limit=720,
    max_retries=EXTRACT_MAX_RETRIES,
    autoretry_for=(ConnectionError,),
    retry_backoff=EXTRACT_RETRY_BACKOFF,
    retry_backoff_max=EXTRACT_RETRY_BACKOFF_MAX,
)
def run_process(self, job_id: str, params: dict):
    """Process pending articles with LLM extraction."""
    from backend.services.llm_errors import LLMError, ErrorCategory

    try:
        return run_task(job_id, self.request.id, _async_process_handler, params)
    except SoftTimeLimitExceeded:
        raise
    except LLMError as e:
        if e.category == ErrorCategory.PERMANENT:
            logger.error("Permanent LLM error in run_process, failing task: %s", e)
            raise  # Don't retry
        # Transient/partial — retry with backoff
        logger.warning("Transient LLM error in run_process, retrying: %s", e)
        raise self.retry(exc=e, countdown=EXTRACT_MANUAL_RETRY_BASE * (self.request.retries + 1))


@app.task(
    bind=True,
    name="backend.tasks.extraction_tasks.run_batch_extract",
    acks_late=True,
    soft_time_limit=3600,
    time_limit=3720,
    max_retries=BATCH_EXTRACT_MAX_RETRIES,
    autoretry_for=(ConnectionError,),
    retry_backoff=BATCH_EXTRACT_RETRY_BACKOFF,
    retry_backoff_max=BATCH_EXTRACT_RETRY_BACKOFF_MAX,
)
def run_batch_extract(self, job_id: str, params: dict):
    """Batch extract articles with universal extraction."""
    from backend.services.llm_errors import LLMError, ErrorCategory

    try:
        return run_task(job_id, self.request.id, _async_batch_extract_handler, params)
    except SoftTimeLimitExceeded:
        raise
    except LLMError as e:
        if e.category == ErrorCategory.PERMANENT:
            logger.error("Permanent LLM error in run_batch_extract, failing task: %s", e)
            raise  # Don't retry
        logger.warning("Transient LLM error in run_batch_extract, retrying: %s", e)
        raise self.retry(exc=e, countdown=BATCH_EXTRACT_MANUAL_RETRY_BASE * (self.request.retries + 1))
