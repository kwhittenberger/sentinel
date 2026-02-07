#!/usr/bin/env python3
"""
One-time cleanup script for duplicate incidents.

Finds duplicates by:
  1. Same source_url (exact URL duplicates)
  2. Entity-based: same actor name + state + date within 7 days

For each duplicate group, keeps the oldest incident, reassigns article refs,
and deletes the extras.

Usage:
    python scripts/cleanup_duplicate_incidents.py          # Dry-run (default)
    python scripts/cleanup_duplicate_incidents.py --apply   # Actually delete
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

import asyncpg

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://sentinel:devpassword@localhost:5433/sentinel",
)


async def find_url_duplicates(conn: asyncpg.Connection) -> list[dict]:
    """Find groups of incidents sharing the same source_url."""
    rows = await conn.fetch("""
        SELECT source_url, array_agg(id ORDER BY created_at ASC) AS ids,
               count(*) AS cnt
        FROM incidents
        WHERE source_url IS NOT NULL
        GROUP BY source_url
        HAVING count(*) > 1
        ORDER BY count(*) DESC
    """)
    groups = []
    for row in rows:
        groups.append({
            "reason": f"URL duplicate: {row['source_url']}",
            "keep_id": row["ids"][0],
            "delete_ids": list(row["ids"][1:]),
        })
    return groups


async def find_entity_duplicates(conn: asyncpg.Connection) -> list[dict]:
    """Find incidents with the same actor name + state + date within 7 days."""
    rows = await conn.fetch("""
        WITH actor_incidents AS (
            SELECT i.id AS incident_id, i.date, i.state, i.created_at,
                   a.canonical_name, ia.role
            FROM incidents i
            JOIN incident_actors ia ON i.id = ia.incident_id
            JOIN actors a ON ia.actor_id = a.id
            WHERE a.canonical_name IS NOT NULL
              AND LENGTH(a.canonical_name) > 2
              AND i.state IS NOT NULL
              AND i.date IS NOT NULL
        )
        SELECT a1.canonical_name, a1.state,
               a1.incident_id AS id1, a2.incident_id AS id2,
               a1.date AS date1, a2.date AS date2,
               a1.created_at AS created1, a2.created_at AS created2
        FROM actor_incidents a1
        JOIN actor_incidents a2
          ON LOWER(a1.canonical_name) = LOWER(a2.canonical_name)
         AND a1.state = a2.state
         AND a1.incident_id < a2.incident_id
         AND ABS(a1.date - a2.date) <= 7
        ORDER BY a1.canonical_name, a1.date
    """)

    # Build deduplicated groups: keep oldest per cluster
    seen_delete: set[str] = set()
    groups = []
    for row in rows:
        id1 = str(row["id1"])
        id2 = str(row["id2"])
        if id2 in seen_delete:
            continue
        # Keep the one created first
        if row["created1"] <= row["created2"]:
            keep, delete = id1, id2
        else:
            keep, delete = id2, id1
        seen_delete.add(delete)
        groups.append({
            "reason": (
                f"Entity duplicate: {row['canonical_name']} in {row['state']} "
                f"({row['date1']} vs {row['date2']})"
            ),
            "keep_id": keep,
            "delete_ids": [delete],
        })
    return groups


async def apply_cleanup(conn: asyncpg.Connection, groups: list[dict], dry_run: bool):
    """Reassign article references and delete duplicate incidents."""
    import uuid as _uuid

    total_deleted = 0
    total_reassigned = 0
    deleted_ids: set[str] = set()  # Track already-deleted incidents

    for group in groups:
        keep_id = str(group["keep_id"])
        for del_id_raw in group["delete_ids"]:
            del_id = str(del_id_raw)

            # Skip if already deleted in a prior group
            if del_id in deleted_ids:
                continue

            # If the keep target was itself deleted, skip (articles were
            # already reassigned or nulled by the prior deletion)
            if keep_id in deleted_ids:
                logger.warning(
                    "Keep target %s was already deleted, skipping %s",
                    keep_id, del_id,
                )
                continue

            if dry_run:
                logger.info(
                    "[DRY RUN] Would delete incident %s (keep %s) — %s",
                    del_id, keep_id, group["reason"],
                )
            else:
                keep_uuid = _uuid.UUID(keep_id)
                del_uuid = _uuid.UUID(del_id)

                # Reassign article references
                result = await conn.execute("""
                    UPDATE ingested_articles
                    SET incident_id = $1
                    WHERE incident_id = $2
                """, keep_uuid, del_uuid)
                reassigned = int(result.split()[-1]) if result else 0
                total_reassigned += reassigned

                # Delete dependent rows first
                await conn.execute(
                    "DELETE FROM incident_events WHERE incident_id = $1", del_uuid
                )
                await conn.execute(
                    "DELETE FROM incident_actors WHERE incident_id = $1", del_uuid
                )
                await conn.execute(
                    "DELETE FROM incidents WHERE id = $1", del_uuid
                )
                deleted_ids.add(del_id)
                total_deleted += 1
                logger.info(
                    "Deleted incident %s (reassigned %d articles to %s) — %s",
                    del_id, reassigned, keep_id, group["reason"],
                )

    return total_deleted, total_reassigned


async def main():
    parser = argparse.ArgumentParser(description="Clean up duplicate incidents")
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually delete duplicates (default is dry-run)",
    )
    args = parser.parse_args()
    dry_run = not args.apply

    if dry_run:
        logger.info("=== DRY RUN MODE (use --apply to execute) ===")

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        url_groups = await find_url_duplicates(conn)
        entity_groups = await find_entity_duplicates(conn)

        all_groups = url_groups + entity_groups
        total_dupes = sum(len(g["delete_ids"]) for g in all_groups)

        logger.info(
            "Found %d URL duplicate groups (%d incidents to remove)",
            len(url_groups), sum(len(g["delete_ids"]) for g in url_groups),
        )
        logger.info(
            "Found %d entity duplicate groups (%d incidents to remove)",
            len(entity_groups), sum(len(g["delete_ids"]) for g in entity_groups),
        )
        logger.info("Total duplicates to remove: %d", total_dupes)

        if not all_groups:
            logger.info("No duplicates found. Nothing to do.")
            return

        deleted, reassigned = await apply_cleanup(conn, all_groups, dry_run)

        if not dry_run:
            logger.info(
                "Cleanup complete: deleted %d incidents, reassigned %d articles",
                deleted, reassigned,
            )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
