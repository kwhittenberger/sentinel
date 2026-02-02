#!/usr/bin/env python3
"""
Ensure all articles have proper merge_info and are fully processed.

1. Two-stage articles missing merge_info: reconstruct from stored stage2 results.
2. Legacy/incomplete articles: reset to 'pending' for full re-extraction.
3. Re-evaluate all 'in_review' articles: auto-approve eligible ones, create incidents.

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
                # Some articles have extracted_data as a JSON string scalar
                # rather than a JSONB object — parse and replace the whole value
                current = await fetch(
                    "SELECT extracted_data FROM ingested_articles WHERE id = $1",
                    article_id,
                )
                if current:
                    ed = current[0]["extracted_data"]
                    if isinstance(ed, str):
                        try:
                            ed = json.loads(ed)
                        except (json.JSONDecodeError, TypeError):
                            ed = {}
                    if not isinstance(ed, dict):
                        ed = {}
                    ed["merge_info"] = merge_info
                    await execute("""
                        UPDATE ingested_articles
                        SET extracted_data = $2::jsonb, updated_at = NOW()
                        WHERE id = $1
                    """, article_id, json.dumps(ed, default=str))

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
# Step 3: Re-evaluate in_review articles and auto-approve eligible ones
# ---------------------------------------------------------------------------

async def reevaluate_in_review(apply: bool) -> dict:
    """Re-run auto-approval on all in_review articles.

    Articles that now pass (e.g., because offender_immigration_status is no
    longer required) get approved and incidents are created.
    """
    from datetime import datetime
    from uuid import UUID as _UUID
    from backend.services.auto_approval import get_auto_approval_service, normalize_extracted_fields
    from backend.services.incident_creation_service import get_incident_creation_service
    from backend.services.stage2_selector import resolve_category_from_merge_info

    rows = await fetch("""
        SELECT id, title, content, source_url, published_date,
               extracted_data, extraction_confidence
        FROM ingested_articles
        WHERE status = 'in_review'
          AND extracted_data IS NOT NULL
          AND extraction_confidence IS NOT NULL
        ORDER BY extraction_confidence DESC
    """)
    print(f"  Found {len(rows)} articles in 'in_review'")

    if not rows:
        return {"approved": 0, "rejected": 0, "still_review": 0, "errors": 0}

    approval_service = get_auto_approval_service()
    incident_service = get_incident_creation_service()

    stats = {"approved": 0, "rejected": 0, "still_review": 0, "errors": 0}

    for row in rows:
        article_id = str(row["id"])
        title = (row.get("title") or "(untitled)")[:60]
        extracted_data = row.get("extracted_data") or {}
        if isinstance(extracted_data, str):
            extracted_data = json.loads(extracted_data)

        merge_info = extracted_data.pop("merge_info", None)
        if isinstance(merge_info, str):
            try:
                merge_info = json.loads(merge_info)
            except (json.JSONDecodeError, TypeError):
                merge_info = None
        category = resolve_category_from_merge_info(merge_info, extracted_data)

        extracted_data = normalize_extracted_fields(extracted_data)

        decision = await approval_service.evaluate_async(
            dict(row), extracted_data, category=category
        )

        if decision.decision == "auto_approve":
            label = "APPROVE" if apply else "WOULD APPROVE"
            print(f"    {label} {article_id} ({title}) — {decision.reason}")

            if apply:
                try:
                    article_dict = {
                        "id": article_id,
                        "title": row.get("title"),
                        "source_url": row.get("source_url"),
                        "published_date": str(row["published_date"]) if row.get("published_date") else None,
                        "extraction_confidence": row.get("extraction_confidence"),
                    }
                    inc_result = await incident_service.create_incident_from_extraction(
                        extracted_data=extracted_data,
                        article=article_dict,
                        category=category,
                        merge_info=merge_info,
                    )
                    incident_id = inc_result["incident_id"]
                    await execute("""
                        UPDATE ingested_articles
                        SET status = 'approved', incident_id = $1, reviewed_at = $2
                        WHERE id = $3
                    """, _UUID(incident_id), datetime.utcnow(), row["id"])
                except Exception as e:
                    print(f"      ERROR creating incident: {e}")
                    stats["errors"] += 1
                    continue

            stats["approved"] += 1

        elif decision.decision == "auto_reject":
            label = "REJECT" if apply else "WOULD REJECT"
            print(f"    {label} {article_id} ({title}) — {decision.reason}")

            if apply:
                await execute("""
                    UPDATE ingested_articles
                    SET status = 'rejected', rejection_reason = $1, reviewed_at = $2
                    WHERE id = $3
                """, decision.reason[:400], datetime.utcnow(), row["id"])

            stats["rejected"] += 1

        else:
            stats["still_review"] += 1

    return stats


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

    # Step 3: re-evaluate in_review articles through auto-approval
    print("Step 3: Re-evaluate in_review articles")
    eval_stats = await reevaluate_in_review(apply)
    print(f"  Result: {eval_stats['approved']} {'approved' if apply else 'would approve'}, "
          f"{eval_stats['rejected']} {'rejected' if apply else 'would reject'}, "
          f"{eval_stats['still_review']} still need review, "
          f"{eval_stats['errors']} errors\n")

    if not apply and (merge_stats["updated"] > 0 or total_reset > 0 or eval_stats["approved"] > 0):
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
