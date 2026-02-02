#!/usr/bin/env python3
"""
Ensure all articles have proper merge_info from the two-stage pipeline.

1. Two-stage articles missing merge_info: reconstruct from stored stage2 results.
2. Legacy pipeline articles: reset to 'pending' so the batch extraction endpoint
   reprocesses them through the full two-stage pipeline.

Usage:
    python scripts/backfill_merge_info.py          # dry-run (default)
    python scripts/backfill_merge_info.py --apply   # actually update the database
"""

import asyncio
import json
import sys
import os
from decimal import Decimal
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(Path(__file__).parent.parent)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from backend.database import fetch, execute
from backend.services.stage2_selector import select_and_merge_stage2


def serialize_row(row) -> dict:
    """Convert a DB row to a JSON-safe dict for select_and_merge_stage2."""
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "hex"):
            d[k] = str(v)
        elif hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, Decimal):
            d[k] = float(v)
    return d


# ---------------------------------------------------------------------------
# Step 1: Reconstruct merge_info for two-stage articles
# ---------------------------------------------------------------------------

async def get_two_stage_missing_merge_info():
    """Two-stage articles whose extracted_data lacks merge_info."""
    return await fetch("""
        SELECT ia.id, ia.title, ia.status
        FROM ingested_articles ia
        WHERE ia.extraction_pipeline = 'two_stage'
          AND ia.extracted_data IS NOT NULL
          AND (ia.extracted_data->>'merge_info') IS NULL
        ORDER BY ia.created_at DESC
    """)


async def get_stage2_results_for_article(article_id):
    """Fetch stage2 results with schema metadata."""
    return await fetch("""
        SELECT
            ser.id,
            ser.schema_id,
            ser.extracted_data,
            ser.confidence,
            es.name as schema_name,
            ed.slug as domain_slug,
            ec.slug as category_slug
        FROM schema_extraction_results ser
        JOIN extraction_schemas es ON ser.schema_id = es.id
        LEFT JOIN event_domains ed ON es.domain_id = ed.id
        LEFT JOIN event_categories ec ON es.category_id = ec.id
        WHERE ser.article_id = $1::uuid
          AND ser.status = 'completed'
        ORDER BY ser.confidence DESC NULLS LAST
    """, str(article_id))


async def reconstruct_merge_info(apply: bool) -> dict:
    """Reconstruct merge_info for two-stage articles from their stage2 results.

    Articles with no stage2 results are collected for reset in step 2.
    """
    articles = await get_two_stage_missing_merge_info()
    print(f"  Found {len(articles)} two-stage articles missing merge_info")

    stats = {"updated": 0, "no_results": 0, "errors": 0}
    needs_reextraction = []

    for article in articles:
        article_id = article["id"]
        title = (article.get("title") or "(untitled)")[:60]

        try:
            stage2_rows = await get_stage2_results_for_article(article_id)
            if not stage2_rows:
                needs_reextraction.append(article)
                stats["no_results"] += 1
                continue

            stage2_results = [serialize_row(r) for r in stage2_rows]
            merged = select_and_merge_stage2(stage2_results)

            if not merged or not merged.get("merge_info"):
                needs_reextraction.append(article)
                stats["no_results"] += 1
                continue

            merge_info = merged["merge_info"]
            source_count = len(merge_info.get("sources", []))
            schema_ids = [s["schema_id"] for s in merge_info.get("sources", []) if s.get("schema_id")]

            label = "UPDATE" if apply else "WOULD UPDATE"
            print(f"    {label} {article_id} ({title}) — {source_count} sources, schemas={schema_ids}")

            if apply:
                await execute("""
                    UPDATE ingested_articles
                    SET extracted_data = jsonb_set(
                            extracted_data, '{merge_info}', $2::jsonb
                        ),
                        updated_at = NOW()
                    WHERE id = $1
                """, article_id, json.dumps(merge_info, default=str))

            stats["updated"] += 1

        except Exception as e:
            print(f"    ERROR {article_id} ({title}): {e}")
            stats["errors"] += 1

    return stats, needs_reextraction


# ---------------------------------------------------------------------------
# Step 2: Reset articles that need full re-extraction
# ---------------------------------------------------------------------------

async def get_legacy_articles():
    """Articles that were never processed through the two-stage pipeline."""
    return await fetch("""
        SELECT ia.id, ia.title, ia.status, ia.extraction_pipeline
        FROM ingested_articles ia
        WHERE (ia.extraction_pipeline IS NULL OR ia.extraction_pipeline = 'legacy')
          AND ia.status != 'pending'
        ORDER BY ia.created_at DESC
    """)


async def reset_articles_for_reextraction(
    apply: bool,
    incomplete_two_stage: list,
) -> dict:
    """Reset articles to pending so they go through the full two-stage pipeline.

    Combines:
    - Legacy-pipeline articles (never went through two-stage)
    - Two-stage articles with no usable stage2 results (incomplete extraction)
    """
    legacy = await get_legacy_articles()

    all_articles = legacy + incomplete_two_stage
    if not all_articles:
        print("  No articles need re-extraction")
        return {"legacy": 0, "incomplete_two_stage": 0}

    print(f"  Found {len(legacy)} legacy-pipeline + "
          f"{len(incomplete_two_stage)} incomplete two-stage = "
          f"{len(all_articles)} total needing re-extraction")

    article_ids = [a["id"] for a in all_articles]

    # Show a sample
    for a in all_articles[:15]:
        title = (a.get("title") or "(untitled)")[:60]
        source = "legacy" if a in legacy else "incomplete"
        print(f"    {'RESET' if apply else 'WOULD RESET'} {a['id']} "
              f"[{a.get('status', '?')}, {source}] ({title})")
    if len(all_articles) > 15:
        print(f"    ... and {len(all_articles) - 15} more")

    if apply:
        # Clean up any orphaned stage1/stage2 rows for these articles
        await execute("""
            DELETE FROM schema_extraction_results
            WHERE article_id = ANY($1::uuid[])
        """, article_ids)
        await execute("""
            DELETE FROM article_extractions
            WHERE article_id = ANY($1::uuid[])
        """, article_ids)

        # Reset articles to pending with cleared extraction state
        await execute("""
            UPDATE ingested_articles
            SET status = 'pending',
                extracted_data = NULL,
                extraction_confidence = NULL,
                extracted_at = NULL,
                extraction_pipeline = NULL,
                extraction_error_count = 0,
                last_extraction_error = NULL,
                last_extraction_error_at = NULL,
                extraction_error_category = NULL,
                latest_extraction_id = NULL,
                updated_at = NOW()
            WHERE id = ANY($1::uuid[])
        """, article_ids)

    return {"legacy": len(legacy), "incomplete_two_stage": len(incomplete_two_stage)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run(apply: bool):
    # Step 1: backfill merge_info where stage2 results exist
    print("Step 1: Reconstruct merge_info for two-stage articles")
    merge_stats, incomplete = await reconstruct_merge_info(apply)
    print(f"  Result: {merge_stats['updated']} {'updated' if apply else 'would update'}, "
          f"{merge_stats['no_results']} have no stage2 results, "
          f"{merge_stats['errors']} errors\n")

    # Step 2: reset everything that needs full re-extraction
    print("Step 2: Reset articles needing re-extraction")
    reset_stats = await reset_articles_for_reextraction(apply, incomplete)
    total_reset = reset_stats["legacy"] + reset_stats["incomplete_two_stage"]
    print(f"  Result: {total_reset} {'reset' if apply else 'would reset'} "
          f"({reset_stats['legacy']} legacy, "
          f"{reset_stats['incomplete_two_stage']} incomplete two-stage)\n")

    if not apply and (merge_stats["updated"] > 0 or total_reset > 0):
        print("Run with --apply to persist changes.")
        if total_reset > 0:
            print("After applying, run batch extraction to process the reset articles.")


def main():
    apply = "--apply" in sys.argv
    if apply:
        print("=== APPLY MODE — database will be modified ===\n")
    else:
        print("=== DRY-RUN MODE (pass --apply to persist) ===\n")

    asyncio.run(run(apply))


if __name__ == "__main__":
    main()
