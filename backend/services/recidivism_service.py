"""
Recidivism & Analytics Service.

Provides actor incident history, recidivism analysis, recidivism indicator
calculation, defendant lifecycle timeline, and staging/ETL management.
"""

import json
import logging
from typing import Optional, Dict, Any, List
from decimal import Decimal
from datetime import datetime

logger = logging.getLogger(__name__)


class RecidivismService:
    """Service for recidivism tracking and advanced analytics."""

    # --- Actor Incident History ---

    async def get_actor_history(self, actor_id: str) -> List[Dict[str, Any]]:
        from backend.database import fetch

        rows = await fetch(
            """SELECT * FROM actor_incident_history
               WHERE actor_id = $1::uuid
               ORDER BY incident_date""",
            actor_id,
        )
        return [self._serialize(r) for r in rows]

    # --- Recidivism Analysis ---

    async def list_recidivists(
        self,
        min_incidents: int = 2,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        from backend.database import fetch, fetchrow

        offset = (page - 1) * page_size

        count_row = await fetchrow(
            """SELECT COUNT(*) as total FROM recidivism_analysis
               WHERE total_incidents >= $1""",
            min_incidents,
        )
        total = count_row["total"] if count_row else 0

        rows = await fetch(
            """SELECT * FROM recidivism_analysis
               WHERE total_incidents >= $1
               ORDER BY total_incidents DESC
               LIMIT $2 OFFSET $3""",
            min_incidents,
            page_size,
            offset,
        )

        return {
            "actors": [self._serialize(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_recidivism_stats(self, actor_id: str) -> Optional[Dict[str, Any]]:
        from backend.database import fetchrow

        row = await fetchrow(
            "SELECT * FROM recidivism_analysis WHERE actor_id = $1::uuid",
            actor_id,
        )
        return self._serialize(row) if row else None

    async def get_recidivism_indicator(self, actor_id: str) -> Dict[str, Any]:
        from backend.database import fetchrow

        row = await fetchrow(
            "SELECT * FROM calculate_recidivism_indicator($1::uuid)",
            actor_id,
        )
        if not row:
            return {
                "actor_id": actor_id,
                "indicator_score": 0.0,
                "is_preliminary": True,
                "model_version": "heuristic-v1",
                "disclaimer": "No data available.",
            }
        return {
            "actor_id": actor_id,
            "indicator_score": float(row["indicator_score"]),
            "is_preliminary": row["is_preliminary"],
            "model_version": row["model_version"],
            "disclaimer": row["disclaimer"],
        }

    async def get_full_recidivism_profile(self, actor_id: str) -> Dict[str, Any]:
        """Get combined history, stats, and indicator for an actor."""
        history = await self.get_actor_history(actor_id)
        stats = await self.get_recidivism_stats(actor_id)
        indicator = await self.get_recidivism_indicator(actor_id)

        return {
            "actor_id": actor_id,
            "incident_history": history,
            "recidivism_stats": stats,
            "indicator": indicator,
        }

    # --- Defendant Lifecycle ---

    async def get_defendant_lifecycle(self, actor_id: str) -> List[Dict[str, Any]]:
        from backend.database import fetch

        rows = await fetch(
            """SELECT * FROM defendant_lifecycle_timeline
               WHERE actor_id = $1::uuid
               ORDER BY case_id, lifecycle_phase""",
            actor_id,
        )
        return [self._serialize(r) for r in rows]

    # --- Refresh ---

    async def refresh_recidivism_analysis(self) -> Dict[str, Any]:
        from backend.database import execute

        await execute("REFRESH MATERIALIZED VIEW CONCURRENTLY recidivism_analysis")
        await execute(
            """UPDATE materialized_view_refresh_config SET
                   last_refresh_at = NOW(),
                   last_refresh_status = 'success'
               WHERE view_name = 'recidivism_analysis'"""
        )
        return {"success": True, "message": "Recidivism analysis refreshed"}

    # --- Summary Analytics ---

    async def get_analytics_summary(self) -> Dict[str, Any]:
        from backend.database import fetchrow

        summary = await fetchrow(
            """SELECT
                   COUNT(*) as total_recidivists,
                   AVG(total_incidents) as avg_incidents,
                   MAX(total_incidents) as max_incidents,
                   AVG(avg_days_between_incidents) as avg_days_between,
                   AVG(total_days_span) as avg_total_span_days
               FROM recidivism_analysis"""
        )

        if not summary or summary["total_recidivists"] == 0:
            return {
                "total_recidivists": 0,
                "avg_incidents": 0,
                "max_incidents": 0,
                "avg_days_between": 0,
                "avg_total_span_days": 0,
            }

        return {
            "total_recidivists": summary["total_recidivists"],
            "avg_incidents": round(float(summary["avg_incidents"] or 0), 1),
            "max_incidents": summary["max_incidents"],
            "avg_days_between": round(float(summary["avg_days_between"] or 0), 0),
            "avg_total_span_days": round(float(summary["avg_total_span_days"] or 0), 0),
        }

    # --- Import Sagas ---

    async def list_import_sagas(
        self,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        from backend.database import fetch, fetchrow

        conditions = []
        params: list = []
        idx = 1

        if status:
            conditions.append(f"s.status = ${idx}")
            params.append(status)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * page_size

        count_row = await fetchrow(
            f"SELECT COUNT(*) as total FROM import_sagas s {where}", *params
        )
        total = count_row["total"] if count_row else 0

        rows = await fetch(
            f"""SELECT * FROM import_sagas s {where}
                ORDER BY s.created_at DESC
                LIMIT ${idx} OFFSET ${idx + 1}""",
            *params,
            page_size,
            offset,
        )

        return {
            "sagas": [self._serialize(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def create_import_saga(self, data: Dict[str, Any]) -> Dict[str, Any]:
        from backend.database import fetchrow

        row = await fetchrow(
            """INSERT INTO import_sagas (saga_type, source_system, total_steps)
               VALUES ($1, $2, $3) RETURNING *""",
            data["saga_type"],
            data["source_system"],
            data.get("total_steps"),
        )
        return self._serialize(row)

    async def update_import_saga(
        self, saga_id: str, data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        from backend.database import fetchrow

        sets = []
        params: list = []
        idx = 1

        for field in [
            "status", "current_step", "total_records", "valid_records",
            "invalid_records", "duplicate_records", "imported_records",
            "error_message", "retry_count",
        ]:
            if field in data:
                sets.append(f"{field} = ${idx}")
                params.append(data[field])
                idx += 1

        if "error_details" in data:
            sets.append(f"error_details = ${idx}::jsonb")
            params.append(json.dumps(data["error_details"]))
            idx += 1

        if "steps_completed" in data:
            sets.append(f"steps_completed = ${idx}::jsonb")
            params.append(json.dumps(data["steps_completed"]))
            idx += 1

        if data.get("status") in ("completed", "failed", "cancelled", "rolled_back"):
            sets.append("completed_at = NOW()")

        if not sets:
            return None

        sets.append("updated_at = NOW()")
        params.append(saga_id)

        row = await fetchrow(
            f"""UPDATE import_sagas SET {', '.join(sets)}
                WHERE id = ${idx}::uuid RETURNING *""",
            *params,
        )
        return self._serialize(row) if row else None

    # --- Helpers ---

    def _serialize(self, row) -> Dict[str, Any]:
        if not row:
            return {}
        d = dict(row)
        for k, v in d.items():
            if hasattr(v, "hex"):
                d[k] = str(v)
            elif isinstance(v, datetime):
                d[k] = v.isoformat()
            elif isinstance(v, Decimal):
                d[k] = float(v)
            elif isinstance(v, list):
                d[k] = [str(x) if hasattr(x, "hex") else x for x in v]
        return d


_instance: Optional[RecidivismService] = None


def get_recidivism_service() -> RecidivismService:
    global _instance
    if _instance is None:
        _instance = RecidivismService()
    return _instance
