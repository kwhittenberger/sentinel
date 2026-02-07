"""Celery tasks for RSS feed fetching."""

import hashlib
import logging
import uuid
from datetime import datetime

from celery.exceptions import SoftTimeLimitExceeded

from backend.celery_app import app
from backend.tasks.db import (
    async_fetch,
    async_execute,
    async_update_progress,
    run_task,
)

logger = logging.getLogger(__name__)


async def _async_fetch_handler(job_id: str, params: dict) -> dict:
    """Fetch articles from RSS feeds (async, mirrors JobExecutor._run_fetch_job)."""
    import feedparser
    import httpx

    feeds = await async_fetch("""
        SELECT id, name, url, source_type, fetcher_class
        FROM sources
        WHERE is_active = true
    """)

    if not feeds:
        return {"message": "No active sources configured", "fetched": 0}

    total_fetched = 0
    total_feeds = len(feeds)

    for i, feed in enumerate(feeds):
        await async_update_progress(
            job_id, i, total_feeds, f"Fetching {feed['name']}..."
        )

        # Only use feedparser for sources without a custom fetcher_class
        if feed.get("fetcher_class"):
            logger.info(f"Skipping {feed['name']} — fetcher {feed['fetcher_class']} not yet integrated")
            continue

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(feed["url"], timeout=30)
                parsed = feedparser.parse(response.text)

            for entry in parsed.entries[:20]:
                link = entry.get("link", "")
                if not link:
                    continue

                existing = await async_fetch(
                    "SELECT id FROM ingested_articles WHERE source_url = $1", link
                )
                if existing:
                    continue

                raw_content = entry.get("summary", entry.get("description", ""))[:10000]
                if raw_content:
                    content_hash = hashlib.md5(raw_content.encode()).hexdigest()
                    hash_exists = await async_fetch(
                        "SELECT id FROM ingested_articles WHERE content_hash = $1",
                        content_hash,
                    )
                    if hash_exists:
                        continue
                else:
                    content_hash = None

                article_id = uuid.uuid4()
                await async_execute(
                    """
                    INSERT INTO ingested_articles (
                        id, source_id, source_url, title, content, content_hash, source_name,
                        published_date, fetched_at, status
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'pending')
                    """,
                    article_id,
                    feed["id"],
                    link,
                    entry.get("title", "")[:500],
                    raw_content,
                    content_hash,
                    feed["name"],
                    datetime.utcnow(),
                    datetime.utcnow(),
                )
                total_fetched += 1

            await async_execute(
                "UPDATE sources SET last_fetched = $1, last_error = NULL WHERE id = $2",
                datetime.utcnow(),
                feed["id"],
            )

        except Exception as e:
            logger.warning(f"Failed to fetch source {feed['name']}: {e}")
            await async_execute(
                "UPDATE sources SET last_error = $1 WHERE id = $2",
                str(e),
                feed["id"],
            )

    await async_update_progress(job_id, total_feeds, total_feeds, "Completed")
    return {
        "message": f"Fetched {total_fetched} articles from {total_feeds} feeds",
        "fetched": total_fetched,
    }


@app.task(
    bind=True,
    name="backend.tasks.fetch_tasks.run_fetch",
    acks_late=True,
    soft_time_limit=300,
    time_limit=360,
    max_retries=5,
    autoretry_for=(ConnectionError,),
    retry_backoff=60,
    retry_backoff_max=600,
)
def run_fetch(self, job_id: str, params: dict):
    """Fetch articles from RSS feeds."""
    try:
        return run_task(job_id, self.request.id, _async_fetch_handler, params)
    except SoftTimeLimitExceeded:
        raise
