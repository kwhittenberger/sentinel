#!/usr/bin/env python3
"""
One-time script to reprocess all existing incidents through universal extraction.
This will:
1. Fetch article content from source URLs
2. Run universal extraction to get actors, events, etc.
3. Store extracted actors in incident_actors table
4. Store extracted events in incident_events table
"""

import asyncio
import sys
import os
from pathlib import Path
from uuid import UUID, uuid4
from datetime import datetime

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(Path(__file__).parent.parent)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not required if env vars already set

import httpx
from backend.database import fetch, execute

# Import extraction services
from backend.services.llm_extraction import LLMExtractor
from backend.services.extraction_prompts import (
    UNIVERSAL_SYSTEM_PROMPT,
    get_universal_extraction_prompt,
    UNIVERSAL_EXTRACTION_SCHEMA
)


async def fetch_article_content(url: str) -> str | None:
    """Fetch article content from URL."""
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; IncidentTracker/1.0)"
            })
            response.raise_for_status()
            return response.text
    except Exception as e:
        print(f"  Failed to fetch {url}: {e}")
        return None


async def extract_from_content(extractor: LLMExtractor, content: str, title: str = "", max_retries: int = 3) -> dict | None:
    """Run universal extraction on content with retry logic."""
    # Combine title and content for better context
    full_text = f"Title: {title}\n\n{content}" if title else content

    # Truncate if too long (Claude has context limits)
    if len(full_text) > 50000:
        full_text = full_text[:50000] + "\n\n[Content truncated...]"

    for attempt in range(max_retries):
        try:
            result = extractor.extract_universal(full_text)

            # Check for extraction errors
            if result and not result.get("success", True):
                error_msg = result.get('error', 'Unknown error')
                if 'rate_limit' in error_msg.lower() and attempt < max_retries - 1:
                    wait_time = 60 * (attempt + 1)  # 60s, 120s, 180s
                    print(f"  Rate limited, waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                print(f"  Extraction error: {error_msg}")
                return None

            return result
        except Exception as e:
            error_str = str(e)
            if 'rate_limit' in error_str.lower() and attempt < max_retries - 1:
                wait_time = 60 * (attempt + 1)
                print(f"  Rate limited, waiting {wait_time}s...")
                await asyncio.sleep(wait_time)
                continue
            print(f"  Extraction failed: {e}")
            return None

    return None


async def get_or_create_actor(actor_data: dict) -> UUID | None:
    """Find or create an actor, return their ID."""
    name = actor_data.get("name", "").strip()
    if not name or name.lower() in ("unknown", "unnamed", "n/a"):
        return None

    actor_type = actor_data.get("actor_type", "person")

    # Try to find existing actor by name
    existing = await fetch("""
        SELECT id FROM actors
        WHERE canonical_name ILIKE $1
        OR $1 ILIKE ANY(aliases)
        LIMIT 1
    """, name)

    if existing:
        return UUID(str(existing[0]["id"]))

    # Create new actor
    actor_id = uuid4()
    await execute("""
        INSERT INTO actors (id, canonical_name, actor_type, created_at)
        VALUES ($1, $2, $3, NOW())
    """, actor_id, name, actor_type)

    return actor_id


async def get_or_create_event(event_data: dict, incident: dict) -> UUID | None:
    """Find or create an event, return its ID."""
    name = event_data.get("event_name", "").strip()
    if not name:
        return None

    # Try to find existing event by name
    existing = await fetch("""
        SELECT id FROM events
        WHERE name ILIKE $1
        LIMIT 1
    """, name)

    if existing:
        return UUID(str(existing[0]["id"]))

    # Create new event
    event_id = uuid4()
    await execute("""
        INSERT INTO events (id, name, event_type, start_date, primary_state, created_at)
        VALUES ($1, $2, $3, $4, $5, NOW())
    """,
        event_id,
        name,
        event_data.get("event_type"),
        incident.get("date"),
        incident.get("state")
    )

    return event_id


async def link_actor_to_incident(incident_id: UUID, actor_id: UUID, roles: list[str]):
    """Link an actor to an incident with their roles."""
    for role in roles:
        # Map role to enum value
        role_map = {
            "victim": "victim",
            "offender": "offender",
            "officer": "officer",
            "witness": "witness",
            "arresting_agency": "arresting_agency",
            "reporting_agency": "reporting_agency",
            "bystander": "bystander",
            "organizer": "organizer",
            "participant": "participant"
        }
        db_role = role_map.get(role.lower(), "participant")

        try:
            await execute("""
                INSERT INTO incident_actors (id, incident_id, actor_id, role, assigned_by, created_at)
                VALUES ($1, $2, $3, $4, 'ai', NOW())
                ON CONFLICT (incident_id, actor_id, role) DO NOTHING
            """, uuid4(), incident_id, actor_id, db_role)
        except Exception as e:
            print(f"    Failed to link actor: {e}")


async def link_event_to_incident(incident_id: UUID, event_id: UUID):
    """Link an event to an incident."""
    try:
        await execute("""
            INSERT INTO incident_events (id, incident_id, event_id, assigned_by, created_at)
            VALUES ($1, $2, $3, 'ai', NOW())
            ON CONFLICT (incident_id, event_id) DO NOTHING
        """, uuid4(), incident_id, event_id)
    except Exception as e:
        print(f"    Failed to link event: {e}")


async def process_incident(extractor: LLMExtractor, incident: dict, dry_run: bool = False) -> bool:
    """Process a single incident through universal extraction."""
    incident_id = UUID(str(incident["id"]))
    source_url = incident.get("source_url")
    title = incident.get("title", "") or ""

    title_display = title[:60] if title else "(no title)"
    print(f"\nProcessing: {title_display}...")

    if not source_url:
        print("  No source URL, skipping")
        return False

    # Fetch article content
    content = await fetch_article_content(source_url)
    if not content:
        return False

    # Run universal extraction
    result = await extract_from_content(extractor, content, title)
    if not result:
        print("  Extraction returned no result")
        return False

    if not isinstance(result, dict):
        print(f"  Unexpected result type: {type(result)}")
        return False

    if not result.get("is_relevant", True):
        print("  Marked as not relevant by extraction")
        return False

    actors = result.get("actors") or []
    events = result.get("events") or []

    print(f"  Found {len(actors)} actors, {len(events)} events")

    if dry_run:
        for actor in actors:
            print(f"    Actor: {actor.get('name')} ({actor.get('actor_type')}) - {actor.get('roles', [])}")
        for event in events:
            print(f"    Event: {event.get('event_name')} ({event.get('event_type')})")
        return True

    # Store actors and link to incident
    for actor_data in actors:
        actor_id = await get_or_create_actor(actor_data)
        if actor_id:
            roles = actor_data.get("roles", ["participant"])
            await link_actor_to_incident(incident_id, actor_id, roles)

    # Store events and link to incident
    for event_data in events:
        event_id = await get_or_create_event(event_data, incident)
        if event_id:
            await link_event_to_incident(incident_id, event_id)

    return True


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Reprocess incidents through universal extraction")
    parser.add_argument("--dry-run", action="store_true", help="Don't save changes, just show what would be extracted")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of incidents to process (0 = all)")
    parser.add_argument("--category", choices=["enforcement", "crime"], help="Only process specific category")
    parser.add_argument("--skip-existing", action="store_true", help="Skip incidents that already have linked actors")
    args = parser.parse_args()

    print("=" * 60)
    print("Incident Reprocessing Script")
    print("=" * 60)

    if args.dry_run:
        print("DRY RUN MODE - no changes will be saved")

    # Build query
    conditions = ["source_url IS NOT NULL", "source_url != ''"]
    params = []

    if args.category:
        conditions.append(f"category = ${len(params) + 1}")
        params.append(args.category)

    if args.skip_existing:
        conditions.append("""
            NOT EXISTS (
                SELECT 1 FROM incident_actors ia WHERE ia.incident_id = incidents.id
            )
        """)

    query = f"""
        SELECT id, title, source_url, date, state, category
        FROM incidents
        WHERE {' AND '.join(conditions)}
        ORDER BY date DESC
    """

    if args.limit > 0:
        query += f" LIMIT {args.limit}"

    incidents = await fetch(query, *params)
    print(f"\nFound {len(incidents)} incidents to process")

    if not incidents:
        print("Nothing to process")
        return

    # Initialize extractor
    extractor = LLMExtractor()

    success_count = 0
    error_count = 0

    for i, incident in enumerate(incidents):
        print(f"\n[{i+1}/{len(incidents)}]", end="")
        try:
            if await process_incident(extractor, dict(incident), dry_run=args.dry_run):
                success_count += 1
            else:
                error_count += 1
        except Exception as e:
            print(f"  Error: {e}")
            error_count += 1

        # Rate limiting - wait longer to avoid API rate limits
        await asyncio.sleep(3)  # 3 seconds between requests to stay under rate limits

    print("\n" + "=" * 60)
    print(f"Complete: {success_count} success, {error_count} errors")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
