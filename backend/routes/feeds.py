"""
Feed management routes.
Extracted from main.py — manages data sources (RSS feeds, etc.).
"""

from typing import Optional
from fastapi import APIRouter, Body, HTTPException

from backend.routes._shared import USE_DATABASE

router = APIRouter(tags=["Feeds"])


@router.get("/api/admin/feeds")
async def list_feeds():
    """List all data sources."""
    if not USE_DATABASE:
        # Return static sources from config
        from data_pipeline.config import SOURCES

        return {
            "feeds": [
                {"name": name, "enabled": config.enabled, "tier": config.tier}
                for name, config in SOURCES.items()
            ]
        }

    from backend.database import fetch

    rows = await fetch("""
        SELECT id, name, url, source_type, tier, fetcher_class,
               interval_minutes, is_active, last_fetched, last_error, created_at
        FROM sources
        ORDER BY tier, name
    """)

    feeds = []
    for row in rows:
        feed = dict(row)
        feed['id'] = str(feed['id'])
        feed['active'] = feed.pop('is_active')
        # Cast tier enum to int for frontend
        feed['tier'] = int(feed['tier']) if feed.get('tier') else 3
        for field in ['last_fetched', 'created_at']:
            if feed.get(field):
                feed[field] = feed[field].isoformat()
        feeds.append(feed)

    return {"feeds": feeds}


@router.post("/api/admin/feeds")
async def create_feed(
    name: str = Body(..., embed=True),
    url: str = Body(..., embed=True),
    source_type: str = Body("news", embed=True),
    tier: int = Body(3, embed=True),
    interval_minutes: int = Body(60, embed=True),
):
    """Create a new data source."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute
    import uuid
    from datetime import datetime, timezone

    feed_id = uuid.uuid4()
    await execute("""
        INSERT INTO sources (id, name, url, source_type, tier, interval_minutes, is_active, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, true, $7)
    """, feed_id, name, url, source_type, str(tier), interval_minutes, datetime.now(timezone.utc))

    return {"success": True, "feed_id": str(feed_id)}


@router.put("/api/admin/feeds/{feed_id}")
async def update_feed(feed_id: str, updates: dict = Body(...)):
    """Update an RSS feed."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute
    import uuid

    try:
        feed_uuid = uuid.UUID(feed_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid feed ID format")

    allowed_fields = ['name', 'url', 'source_type', 'tier', 'fetcher_class', 'fetcher_config', 'interval_minutes', 'is_active']
    # Map frontend field names to DB column names
    field_map = {'active': 'is_active'}
    set_clauses = []
    params = []
    param_num = 1

    for field in list(updates.keys()):
        db_field = field_map.get(field, field)
        if db_field in allowed_fields:
            set_clauses.append(f"{db_field} = ${param_num}")
            value = updates[field]
            # Cast tier to string for the enum column
            if db_field == 'tier':
                value = str(value)
            params.append(value)
            param_num += 1

    if not set_clauses:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    params.append(feed_uuid)
    query = f"UPDATE sources SET {', '.join(set_clauses)} WHERE id = ${param_num}"
    await execute(query, *params)

    return {"success": True}


@router.delete("/api/admin/feeds/{feed_id}")
async def delete_feed(feed_id: str):
    """Delete an RSS feed."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute
    import uuid

    try:
        feed_uuid = uuid.UUID(feed_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid feed ID format")

    await execute("DELETE FROM sources WHERE id = $1", feed_uuid)
    return {"success": True}


@router.post("/api/admin/feeds/{feed_id}/fetch")
async def fetch_feed(feed_id: str):
    """Manually fetch a specific data source."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import fetch, execute
    import uuid as uuid_mod

    try:
        feed_uuid = uuid_mod.UUID(feed_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid feed ID format")

    rows = await fetch("SELECT id, name, url, source_type, fetcher_class FROM sources WHERE id = $1", feed_uuid)
    if not rows:
        raise HTTPException(status_code=404, detail="Source not found")

    source = dict(rows[0])
    source_type = source.get('source_type', '')

    # Only RSS/news sources with URLs can be fetched via feedparser right now
    if source_type in ('news',) and source.get('url') and not source.get('fetcher_class'):
        try:
            import feedparser
            import httpx
            response_data = httpx.get(source['url'], timeout=30)
            parsed = feedparser.parse(response_data.text)
            count = len(parsed.entries) if parsed.entries else 0
            from datetime import datetime, timezone
            await execute("UPDATE sources SET last_fetched = $1, last_error = NULL WHERE id = $2", datetime.now(timezone.utc), feed_uuid)
            return {"success": True, "message": f"Fetched {count} entries from {source['name']}"}
        except Exception as e:
            from datetime import datetime, timezone
            await execute("UPDATE sources SET last_error = $1 WHERE id = $2", str(e), feed_uuid)
            return {"success": False, "message": f"Fetch failed: {e}"}
    else:
        fetcher = source.get('fetcher_class') or 'none'
        return {"success": True, "message": f"Fetch initiated for {source['name']} (fetcher: {fetcher} — not yet integrated)"}


@router.post("/api/admin/feeds/{feed_id}/toggle")
async def toggle_feed(feed_id: str, active: bool = Body(..., embed=True)):
    """Enable or disable a feed."""
    if not USE_DATABASE:
        raise HTTPException(status_code=501, detail="Database not enabled")

    from backend.database import execute
    import uuid

    try:
        feed_uuid = uuid.UUID(feed_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid feed ID format")

    await execute("UPDATE sources SET is_active = $1 WHERE id = $2", active, feed_uuid)
    return {"success": True, "active": active}
