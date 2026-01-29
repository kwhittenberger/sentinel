"""Background job executor service."""
import asyncio
import uuid
from datetime import datetime
from typing import Optional, Callable, Dict, Any
import logging

logger = logging.getLogger(__name__)


class JobExecutor:
    """Executes background jobs from the database queue."""

    def __init__(self):
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self._current_job_id: Optional[str] = None

    async def start(self):
        """Start the job executor background loop."""
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Job executor started")

    async def stop(self):
        """Stop the job executor."""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Job executor stopped")

    async def _run_loop(self):
        """Main loop that polls for and executes jobs."""
        from backend.database import fetch, execute

        while self.running:
            try:
                # Look for pending jobs
                rows = await fetch("""
                    SELECT id, job_type, params
                    FROM background_jobs
                    WHERE status = 'pending'
                    ORDER BY created_at ASC
                    LIMIT 1
                """)

                if rows:
                    job = rows[0]
                    job_id = job['id']
                    job_type = job['job_type']
                    params = job.get('params') or {}

                    self._current_job_id = str(job_id)
                    logger.info(f"Starting job {job_id}: {job_type}")

                    # Mark as running
                    await execute("""
                        UPDATE background_jobs
                        SET status = 'running', started_at = $1
                        WHERE id = $2
                    """, datetime.utcnow(), job_id)

                    try:
                        # Execute the job
                        result = await self._execute_job(job_type, params, job_id)

                        # Mark as completed
                        await execute("""
                            UPDATE background_jobs
                            SET status = 'completed', completed_at = $1, message = $2
                            WHERE id = $3
                        """, datetime.utcnow(), result.get('message', 'Completed'), job_id)

                        logger.info(f"Job {job_id} completed: {result}")

                    except Exception as e:
                        logger.error(f"Job {job_id} failed: {e}")
                        await execute("""
                            UPDATE background_jobs
                            SET status = 'failed', completed_at = $1, error = $2
                            WHERE id = $3
                        """, datetime.utcnow(), str(e), job_id)

                    self._current_job_id = None

                else:
                    # No jobs, wait before polling again
                    await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Job executor error: {e}")
                await asyncio.sleep(10)

    async def _execute_job(self, job_type: str, params: Dict[str, Any], job_id: uuid.UUID) -> Dict[str, Any]:
        """Execute a job based on its type."""
        from backend.database import fetch, execute

        if job_type == 'fetch':
            return await self._run_fetch_job(params, job_id)
        elif job_type == 'process':
            return await self._run_process_job(params, job_id)
        elif job_type == 'batch_extract':
            return await self._run_batch_extract_job(params, job_id)
        elif job_type == 'batch_enrich':
            return await self._run_batch_enrich_job(params, job_id)
        elif job_type == 'full_pipeline':
            return await self._run_full_pipeline_job(params, job_id)
        elif job_type == 'cross_reference_enrich':
            return await self._run_enrichment_job(params, job_id)
        else:
            raise ValueError(f"Unknown job type: {job_type}")

    async def _update_progress(self, job_id: uuid.UUID, progress: int, total: int, message: str):
        """Update job progress."""
        from backend.database import execute
        await execute("""
            UPDATE background_jobs
            SET progress = $1, total = $2, message = $3
            WHERE id = $4
        """, progress, total, message, job_id)

    async def _run_fetch_job(self, params: Dict[str, Any], job_id: uuid.UUID) -> Dict[str, Any]:
        """Fetch articles from RSS feeds."""
        from backend.database import fetch, execute
        import feedparser
        import httpx
        from datetime import datetime

        # Get active feeds
        feeds = await fetch("""
            SELECT id, name, url, feed_type
            FROM rss_feeds
            WHERE active = true
        """)

        if not feeds:
            return {"message": "No active feeds configured", "fetched": 0}

        total_fetched = 0
        total_feeds = len(feeds)

        for i, feed in enumerate(feeds):
            await self._update_progress(job_id, i, total_feeds, f"Fetching {feed['name']}...")

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(feed['url'], timeout=30)
                    parsed = feedparser.parse(response.text)

                for entry in parsed.entries[:20]:  # Limit per feed
                    # Check if already exists
                    existing = await fetch("""
                        SELECT id FROM ingested_articles WHERE source_url = $1
                    """, entry.get('link', ''))

                    if not existing and entry.get('link'):
                        article_id = uuid.uuid4()
                        await execute("""
                            INSERT INTO ingested_articles (
                                id, source_url, title, content, source_name,
                                published_date, fetched_at, status
                            ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending')
                        """,
                            article_id,
                            entry.get('link', ''),
                            entry.get('title', '')[:500],
                            entry.get('summary', entry.get('description', ''))[:10000],
                            feed['name'],
                            datetime.utcnow(),  # TODO: parse entry.published
                            datetime.utcnow()
                        )
                        total_fetched += 1

                # Update last_fetched
                await execute("""
                    UPDATE rss_feeds SET last_fetched = $1 WHERE id = $2
                """, datetime.utcnow(), feed['id'])

            except Exception as e:
                logger.warning(f"Failed to fetch feed {feed['name']}: {e}")

        await self._update_progress(job_id, total_feeds, total_feeds, "Completed")
        return {"message": f"Fetched {total_fetched} articles from {total_feeds} feeds", "fetched": total_fetched}

    async def _run_process_job(self, params: Dict[str, Any], job_id: uuid.UUID) -> Dict[str, Any]:
        """Process pending articles with LLM extraction."""
        from backend.database import fetch, execute
        from backend.services import get_extractor

        limit = params.get('limit', 50)

        # Get pending articles without extraction
        articles = await fetch("""
            SELECT id, title, content
            FROM ingested_articles
            WHERE status = 'pending'
              AND extracted_data IS NULL
            ORDER BY fetched_at DESC
            LIMIT $1
        """, limit)

        if not articles:
            return {"message": "No articles to process", "processed": 0}

        extractor = get_extractor()
        if not extractor.is_available():
            return {"message": "LLM extractor not available", "processed": 0}

        total = len(articles)
        processed = 0

        for i, article in enumerate(articles):
            await self._update_progress(job_id, i, total, f"Processing article {i+1}/{total}")

            try:
                full_text = f"{article['title']}\n\n{article['content']}" if article['title'] else article['content']
                result = extractor.extract(full_text or "")

                await execute("""
                    UPDATE ingested_articles
                    SET extracted_data = $1,
                        extraction_confidence = $2,
                        relevance_score = $3
                    WHERE id = $4
                """,
                    result,
                    result.get('confidence'),
                    1.0 if result.get('is_relevant') else 0.0,
                    article['id']
                )
                processed += 1

            except Exception as e:
                logger.warning(f"Failed to process article {article['id']}: {e}")

        await self._update_progress(job_id, total, total, "Completed")
        return {"message": f"Processed {processed}/{total} articles", "processed": processed}

    async def _run_batch_extract_job(self, params: Dict[str, Any], job_id: uuid.UUID) -> Dict[str, Any]:
        """Run universal extraction on all pending articles."""
        from backend.database import fetch, execute
        from backend.services import get_extractor

        limit = params.get('limit', 1000)  # Default to processing many

        # Get pending articles that need extraction
        articles = await fetch("""
            SELECT id, title, content, source_url
            FROM ingested_articles
            WHERE status = 'pending'
              AND content IS NOT NULL
              AND (extracted_data->>'success' IS NULL OR extracted_data->>'success' != 'true')
            ORDER BY fetched_at ASC
            LIMIT $1
        """, limit)

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
            await self._update_progress(job_id, i, total, f"Extracting {i+1}/{total}: {article['title'][:50]}...")

            try:
                full_text = f"{article['title']}\n\n{article['content']}" if article['title'] else article['content']
                # Use async version for tracking
                result = await extractor.extract_universal_async(full_text or "")

                if result.get('success', True):
                    await execute("""
                        UPDATE ingested_articles
                        SET extracted_data = $1,
                            extraction_confidence = $2,
                            relevance_score = $3
                        WHERE id = $4
                    """,
                        result,
                        result.get('confidence', 0.5),
                        1.0 if result.get('is_relevant') else 0.0,
                        article['id']
                    )
                    processed += 1
                    if result.get('is_relevant'):
                        relevant += 1
                else:
                    errors += 1
                    logger.warning(f"Extraction failed for {article['id']}: {result.get('error')}")

            except Exception as e:
                errors += 1
                logger.warning(f"Failed to extract article {article['id']}: {e}")

            # Rate limiting to avoid API limits
            await asyncio.sleep(2)

        await self._update_progress(job_id, total, total, f"Completed: {processed} extracted, {relevant} relevant")
        return {
            "message": f"Extracted {processed}/{total} articles ({relevant} relevant, {errors} errors)",
            "processed": processed,
            "relevant": relevant,
            "errors": errors
        }

    async def _run_batch_enrich_job(self, params: Dict[str, Any], job_id: uuid.UUID) -> Dict[str, Any]:
        """Enrich articles with additional data (fetch full content, etc.)."""
        from backend.database import fetch, execute
        import httpx

        limit = params.get('limit', 50)

        # Get articles with minimal content
        articles = await fetch("""
            SELECT id, source_url, content
            FROM ingested_articles
            WHERE status = 'pending'
              AND (content IS NULL OR LENGTH(content) < 500)
            ORDER BY fetched_at DESC
            LIMIT $1
        """, limit)

        if not articles:
            return {"message": "No articles to enrich", "enriched": 0}

        total = len(articles)
        enriched = 0

        async with httpx.AsyncClient() as client:
            for i, article in enumerate(articles):
                await self._update_progress(job_id, i, total, f"Enriching article {i+1}/{total}")

                try:
                    # Fetch full content from source URL
                    response = await client.get(article['source_url'], timeout=30, follow_redirects=True)
                    if response.status_code == 200:
                        # Basic content extraction (would use readability in production)
                        content = response.text[:50000]

                        await execute("""
                            UPDATE ingested_articles
                            SET content = $1
                            WHERE id = $2
                        """, content, article['id'])
                        enriched += 1

                except Exception as e:
                    logger.warning(f"Failed to enrich article {article['id']}: {e}")

        await self._update_progress(job_id, total, total, "Completed")
        return {"message": f"Enriched {enriched}/{total} articles", "enriched": enriched}

    async def _run_full_pipeline_job(self, params: Dict[str, Any], job_id: uuid.UUID) -> Dict[str, Any]:
        """Run complete pipeline: fetch, enrich, extract."""
        results = {}

        await self._update_progress(job_id, 0, 3, "Step 1/3: Fetching articles...")
        fetch_result = await self._run_fetch_job(params, job_id)
        results['fetch'] = fetch_result

        await self._update_progress(job_id, 1, 3, "Step 2/3: Enriching articles...")
        enrich_result = await self._run_batch_enrich_job(params, job_id)
        results['enrich'] = enrich_result

        await self._update_progress(job_id, 2, 3, "Step 3/3: Extracting data...")
        extract_result = await self._run_process_job(params, job_id)
        results['extract'] = extract_result

        await self._update_progress(job_id, 3, 3, "Pipeline completed")
        return {
            "message": f"Pipeline complete: fetched {fetch_result.get('fetched', 0)}, extracted {extract_result.get('processed', 0)}",
            "results": results
        }

    async def _run_enrichment_job(self, params: Dict[str, Any], job_id: uuid.UUID) -> Dict[str, Any]:
        """Run cross-reference enrichment on incidents with missing data."""
        from backend.services.enrichment_service import get_enrichment_service

        service = get_enrichment_service()

        strategy = params.get('strategy', 'cross_incident')
        limit = params.get('limit', 100)
        target_fields = params.get('target_fields')
        auto_apply = params.get('auto_apply', strategy == 'cross_incident')
        min_confidence = params.get('min_confidence', 0.7)

        enrichment_params = {
            'limit': limit,
            'target_fields': target_fields,
            'auto_apply': auto_apply,
            'min_confidence': min_confidence,
        }

        result = await service.run_enrichment(
            strategy=strategy,
            params=enrichment_params,
            job_id=job_id,
            progress_callback=lambda p, t, m: self._update_progress(job_id, p, t, m),
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


# Global executor instance
_executor: Optional[JobExecutor] = None


def get_executor() -> JobExecutor:
    global _executor
    if _executor is None:
        _executor = JobExecutor()
    return _executor
