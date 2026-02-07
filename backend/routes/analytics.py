"""
Analytics route module.
Extracted from main.py — stats comparison, sanctuary correlation, and admin analytics.
"""

from fastapi import APIRouter, Query
from typing import Optional

from backend.routes._shared import USE_DATABASE

router = APIRouter(tags=["Analytics"])


@router.get("/api/stats/comparison")
async def get_comparison_stats(
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
):
    """Get comparison statistics between enforcement and crime incidents."""
    from backend.main import filter_incidents, filter_incidents_async

    if USE_DATABASE:
        incidents = await filter_incidents_async(date_start=date_start, date_end=date_end)
    else:
        incidents = filter_incidents(date_start=date_start, date_end=date_end)

    enforcement = [i for i in incidents if i.get('category', 'enforcement') == 'enforcement']
    crime = [i for i in incidents if i.get('category') == 'crime']

    enforcement_deaths = sum(1 for i in enforcement if i.get('is_death'))
    crime_deaths = sum(1 for i in crime if i.get('is_death'))

    # By state
    by_state = {}
    for inc in incidents:
        state = inc.get('state')
        if not state:
            continue
        if state not in by_state:
            by_state[state] = {
                'name': state,
                'enforcement_incidents': 0,
                'crime_incidents': 0,
                'enforcement_deaths': 0,
                'crime_deaths': 0,
            }
        cat = inc.get('category', 'enforcement')
        if cat == 'enforcement':
            by_state[state]['enforcement_incidents'] += 1
            if inc.get('is_death'):
                by_state[state]['enforcement_deaths'] += 1
        else:
            by_state[state]['crime_incidents'] += 1
            if inc.get('is_death'):
                by_state[state]['crime_deaths'] += 1

    return {
        "enforcement_incidents": len(enforcement),
        "crime_incidents": len(crime),
        "enforcement_deaths": enforcement_deaths,
        "crime_deaths": crime_deaths,
        "by_jurisdiction": list(by_state.values()),
    }


@router.get("/api/stats/sanctuary")
async def get_sanctuary_correlation(
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
):
    """Get sanctuary policy correlation analysis."""
    from backend.main import filter_incidents, filter_incidents_async

    if USE_DATABASE:
        incidents = await filter_incidents_async(date_start=date_start, date_end=date_end)
    else:
        incidents = filter_incidents(date_start=date_start, date_end=date_end)

    # Group by sanctuary status
    by_status = {
        'sanctuary': {'incidents': 0, 'deaths': 0, 'non_immigrant': 0},
        'anti_sanctuary': {'incidents': 0, 'deaths': 0, 'non_immigrant': 0},
        'neutral': {'incidents': 0, 'deaths': 0, 'non_immigrant': 0},
        'unknown': {'incidents': 0, 'deaths': 0, 'non_immigrant': 0},
    }

    for inc in incidents:
        status = inc.get('state_sanctuary_status', 'unknown') or 'unknown'
        if status not in by_status:
            status = 'unknown'

        by_status[status]['incidents'] += 1
        if inc.get('is_death'):
            by_status[status]['deaths'] += 1
        if inc.get('is_non_immigrant'):
            by_status[status]['non_immigrant'] += 1

    return {
        "by_sanctuary_status": by_status,
        "total_incidents": len(incidents),
    }


@router.get("/api/admin/analytics/overview")
async def get_analytics_overview(
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
):
    """Get overview analytics for the admin dashboard."""
    from backend.main import get_all_incidents, load_incidents

    if USE_DATABASE:
        incidents = await get_all_incidents()
        from backend.database import fetch

        # Get queue stats
        queue_stats = await fetch("""
            SELECT status, COUNT(*) as count
            FROM ingested_articles
            GROUP BY status
        """)
        queue_by_status = {row["status"]: row["count"] for row in queue_stats}
    else:
        incidents = load_incidents()
        queue_by_status = {"pending": 0, "approved": 0, "rejected": 0}

    # Apply date filters to incidents
    if date_start:
        incidents = [i for i in incidents if (i.get('date') or '') >= date_start]
    if date_end:
        incidents = [i for i in incidents if (i.get('date') or '') <= date_end]

    total = len(incidents)
    enforcement = sum(1 for i in incidents if i.get('category', 'enforcement') == 'enforcement')
    crime = sum(1 for i in incidents if i.get('category') == 'crime')
    deaths = sum(1 for i in incidents if i.get('is_death'))
    states = len(set(i.get('state') for i in incidents if i.get('state')))

    return {
        "total_incidents": total,
        "enforcement_incidents": enforcement,
        "crime_incidents": crime,
        "total_deaths": deaths,
        "states_affected": states,
        "queue_stats": queue_by_status,
        "ingested_total": sum(queue_by_status.values()),
        "approved_total": queue_by_status.get("approved", 0),
        "rejected_total": queue_by_status.get("rejected", 0),
        "pending_review": queue_by_status.get("pending", 0),
    }


@router.get("/api/admin/analytics/conversion")
async def get_conversion_funnel(
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
):
    """Get conversion funnel statistics."""
    if not USE_DATABASE:
        return {"funnel": []}

    from backend.database import fetch

    # Get article counts by status
    query = """
        SELECT
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE relevance_score > 0.5) as relevant,
            COUNT(*) FILTER (WHERE status = 'approved') as approved,
            COUNT(*) FILTER (WHERE status = 'rejected') as rejected,
            COUNT(*) FILTER (WHERE status = 'pending') as pending
        FROM ingested_articles
    """
    rows = await fetch(query)

    if rows:
        stats = dict(rows[0])
        return {
            "funnel": [
                {"stage": "Ingested", "count": stats["total"]},
                {"stage": "Relevant", "count": stats["relevant"]},
                {"stage": "Approved", "count": stats["approved"]},
            ],
            "rejected": stats["rejected"],
            "pending": stats["pending"],
        }

    return {"funnel": [], "rejected": 0, "pending": 0}


@router.get("/api/admin/analytics/sources")
async def get_source_analytics(
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
):
    """Get analytics broken down by source."""
    if not USE_DATABASE:
        return {"sources": []}

    from backend.database import fetch

    query = """
        SELECT
            source_name,
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE status = 'approved') as approved,
            COUNT(*) FILTER (WHERE status = 'rejected') as rejected,
            AVG(extraction_confidence) as avg_confidence
        FROM ingested_articles
        GROUP BY source_name
        ORDER BY total DESC
        LIMIT 20
    """
    rows = await fetch(query)

    sources = []
    for row in rows:
        sources.append({
            "source_name": row.get("source_name") or "Unknown",
            "total": row["total"],
            "approved": row["approved"],
            "rejected": row["rejected"],
            "avg_confidence": float(row["avg_confidence"]) if row.get("avg_confidence") else None,
            "approval_rate": row["approved"] / row["total"] if row["total"] > 0 else 0,
        })

    return {"sources": sources}


@router.get("/api/admin/analytics/geographic")
async def get_geographic_analytics(
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
):
    """Get analytics broken down by state."""
    from backend.main import get_all_incidents, load_incidents

    if USE_DATABASE:
        incidents = await get_all_incidents()
    else:
        incidents = load_incidents()

    if date_start:
        incidents = [i for i in incidents if (i.get('date') or '') >= date_start]
    if date_end:
        incidents = [i for i in incidents if (i.get('date') or '') <= date_end]

    by_state = {}
    for inc in incidents:
        state = inc.get('state')
        if not state:
            continue
        if state not in by_state:
            by_state[state] = {
                'state': state,
                'total': 0,
                'enforcement': 0,
                'crime': 0,
                'deaths': 0,
            }
        by_state[state]['total'] += 1
        cat = inc.get('category', 'enforcement')
        if cat == 'enforcement':
            by_state[state]['enforcement'] += 1
        else:
            by_state[state]['crime'] += 1
        if inc.get('is_death'):
            by_state[state]['deaths'] += 1

    return {"states": list(by_state.values())}
