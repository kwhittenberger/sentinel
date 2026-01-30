"""
Criminal Justice Domain service.

Provides CRUD operations for cases, charges, charge history,
prosecutorial actions, bail decisions, and dispositions.
"""

import json
import logging
from typing import Optional, List, Dict, Any
from uuid import UUID

logger = logging.getLogger(__name__)


class CriminalJusticeService:
    """Service for managing cases and legal tracking."""

    # --- Cases ---

    async def list_cases(
        self,
        status: Optional[str] = None,
        case_type: Optional[str] = None,
        jurisdiction: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        from backend.database import fetch, fetchrow

        conditions = []
        params: list = []
        idx = 1

        if status:
            conditions.append(f"c.status = ${idx}")
            params.append(status)
            idx += 1
        if case_type:
            conditions.append(f"c.case_type = ${idx}")
            params.append(case_type)
            idx += 1
        if jurisdiction:
            conditions.append(f"c.jurisdiction ILIKE ${idx}")
            params.append(f"%{jurisdiction}%")
            idx += 1
        if search:
            conditions.append(f"(c.case_number ILIKE ${idx} OR c.notes ILIKE ${idx})")
            params.append(f"%{search}%")
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_row = await fetchrow(
            f"SELECT COUNT(*) as total FROM cases c {where}", *params
        )
        total = count_row["total"] if count_row else 0

        offset = (page - 1) * page_size
        params.extend([page_size, offset])

        rows = await fetch(f"""
            SELECT c.*, ed.slug as domain_slug, ec.slug as category_slug
            FROM cases c
            LEFT JOIN event_domains ed ON c.domain_id = ed.id
            LEFT JOIN event_categories ec ON c.category_id = ec.id
            {where}
            ORDER BY c.filed_date DESC NULLS LAST, c.created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
        """, *params)

        return {
            "cases": [self._serialize_case(r) for r in rows],
            "total": total,
            "page": page,
            "total_pages": (total + page_size - 1) // page_size,
        }

    async def get_case(self, case_id: UUID) -> Optional[dict]:
        from backend.database import fetchrow

        row = await fetchrow("""
            SELECT c.*, ed.slug as domain_slug, ec.slug as category_slug
            FROM cases c
            LEFT JOIN event_domains ed ON c.domain_id = ed.id
            LEFT JOIN event_categories ec ON c.category_id = ec.id
            WHERE c.id = $1
        """, case_id)
        return self._serialize_case(row) if row else None

    async def create_case(self, data: Dict[str, Any]) -> dict:
        from backend.database import fetchrow

        row = await fetchrow("""
            INSERT INTO cases (
                case_number, case_type, jurisdiction, court_name,
                filed_date, status, domain_id, category_id,
                custom_fields, data_classification, notes
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11)
            RETURNING *
        """,
            data.get("case_number"),
            data["case_type"],
            data.get("jurisdiction"),
            data.get("court_name"),
            data.get("filed_date"),
            data.get("status", "active"),
            data.get("domain_id"),
            data.get("category_id"),
            data.get("custom_fields", {}),
            data.get("data_classification", "public"),
            data.get("notes"),
        )
        logger.info(f"Created case: {data.get('case_number')}")
        return self._serialize_case(row)

    async def update_case(self, case_id: UUID, data: Dict[str, Any]) -> Optional[dict]:
        from backend.database import fetchrow

        sets = ["updated_at = NOW()"]
        params: list = [case_id]
        idx = 2

        for field in ("case_number", "case_type", "jurisdiction", "court_name",
                       "filed_date", "closed_date", "status", "data_classification", "notes"):
            if field in data:
                sets.append(f"{field} = ${idx}")
                params.append(data[field])
                idx += 1

        for uuid_field in ("domain_id", "category_id"):
            if uuid_field in data:
                sets.append(f"{uuid_field} = ${idx}")
                params.append(data[uuid_field])
                idx += 1

        if "custom_fields" in data:
            sets.append(f"custom_fields = ${idx}::jsonb")
            val = data["custom_fields"]
            params.append(json.loads(val) if isinstance(val, str) else val)
            idx += 1

        row = await fetchrow(f"""
            UPDATE cases SET {', '.join(sets)}
            WHERE id = $1
            RETURNING *
        """, *params)

        if row:
            logger.info(f"Updated case: {case_id}")
        return self._serialize_case(row) if row else None

    # --- Charges ---

    async def list_charges(self, case_id: UUID) -> List[dict]:
        from backend.database import fetch

        rows = await fetch("""
            SELECT * FROM charges
            WHERE case_id = $1
            ORDER BY charge_number
        """, case_id)
        return [self._serialize_charge(r) for r in rows]

    async def get_charge(self, charge_id: UUID) -> Optional[dict]:
        from backend.database import fetchrow

        row = await fetchrow("SELECT * FROM charges WHERE id = $1", charge_id)
        return self._serialize_charge(row) if row else None

    async def create_charge(self, case_id: UUID, data: Dict[str, Any]) -> dict:
        from backend.database import fetchrow

        row = await fetchrow("""
            INSERT INTO charges (
                case_id, charge_number, charge_code, charge_description,
                charge_level, charge_class, severity, status,
                is_violent_crime, notes
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING *
        """,
            case_id,
            data["charge_number"],
            data.get("charge_code"),
            data["charge_description"],
            data.get("charge_level", "misdemeanor"),
            data.get("charge_class"),
            data.get("severity"),
            data.get("status", "filed"),
            data.get("is_violent_crime", False),
            data.get("notes"),
        )

        # Record initial filing in charge history
        await self._record_charge_event(
            row["id"], case_id, "filed",
            actor_type=data.get("filed_by_type"),
            actor_name=data.get("filed_by_name"),
            actor_id=data.get("filed_by_id"),
        )

        logger.info(f"Created charge #{data['charge_number']} for case {case_id}")
        return self._serialize_charge(row)

    async def update_charge(self, charge_id: UUID, data: Dict[str, Any]) -> Optional[dict]:
        from backend.database import fetchrow

        sets = ["updated_at = NOW()"]
        params: list = [charge_id]
        idx = 2

        for field in ("charge_code", "charge_description", "charge_level",
                       "charge_class", "severity", "status", "is_violent_crime",
                       "jail_days", "probation_days", "fine_amount",
                       "restitution_amount", "community_service_hours", "notes"):
            if field in data:
                sets.append(f"{field} = ${idx}")
                params.append(data[field])
                idx += 1

        row = await fetchrow(f"""
            UPDATE charges SET {', '.join(sets)}
            WHERE id = $1
            RETURNING *
        """, *params)

        if row:
            logger.info(f"Updated charge: {charge_id}")
        return self._serialize_charge(row) if row else None

    # --- Charge History ---

    async def list_charge_history(self, case_id: UUID, charge_id: Optional[UUID] = None) -> List[dict]:
        from backend.database import fetch

        if charge_id:
            rows = await fetch("""
                SELECT ch.*, a.canonical_name as actor_canonical_name
                FROM charge_history ch
                LEFT JOIN actors a ON ch.actor_id = a.id
                WHERE ch.case_id = $1 AND ch.charge_id = $2
                ORDER BY ch.event_date DESC, ch.created_at DESC
            """, case_id, charge_id)
        else:
            rows = await fetch("""
                SELECT ch.*, a.canonical_name as actor_canonical_name,
                       c.charge_number, c.charge_description
                FROM charge_history ch
                LEFT JOIN actors a ON ch.actor_id = a.id
                LEFT JOIN charges c ON ch.charge_id = c.id
                WHERE ch.case_id = $1
                ORDER BY ch.event_date DESC, ch.created_at DESC
            """, case_id)
        return [self._serialize_charge_history(r) for r in rows]

    async def _record_charge_event(
        self, charge_id: UUID, case_id: UUID, event_type: str,
        actor_type: Optional[str] = None, actor_name: Optional[str] = None,
        actor_id: Optional[UUID] = None, previous_charge_code: Optional[str] = None,
        new_charge_code: Optional[str] = None, previous_level: Optional[str] = None,
        new_level: Optional[str] = None, reason: Optional[str] = None,
        event_date=None,
    ) -> dict:
        from backend.database import fetchrow

        row = await fetchrow("""
            INSERT INTO charge_history (
                charge_id, case_id, event_type, actor_type, actor_name, actor_id,
                previous_charge_code, new_charge_code, previous_level, new_level,
                reason, event_date
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, COALESCE($12, CURRENT_DATE))
            RETURNING *
        """,
            charge_id, case_id, event_type,
            actor_type, actor_name, actor_id,
            previous_charge_code, new_charge_code,
            previous_level, new_level,
            reason, event_date,
        )
        return self._serialize_charge_history(row)

    async def record_charge_event(self, data: Dict[str, Any]) -> dict:
        """Public method to record a charge history event."""
        return await self._record_charge_event(
            charge_id=data["charge_id"],
            case_id=data["case_id"],
            event_type=data["event_type"],
            actor_type=data.get("actor_type"),
            actor_name=data.get("actor_name"),
            actor_id=data.get("actor_id"),
            previous_charge_code=data.get("previous_charge_code"),
            new_charge_code=data.get("new_charge_code"),
            previous_level=data.get("previous_level"),
            new_level=data.get("new_level"),
            reason=data.get("reason"),
            event_date=data.get("event_date"),
        )

    # --- Prosecutorial Actions ---

    async def list_prosecutorial_actions(self, case_id: UUID) -> List[dict]:
        from backend.database import fetch

        rows = await fetch("""
            SELECT pa.*, a.canonical_name as prosecutor_canonical_name
            FROM prosecutorial_actions pa
            LEFT JOIN actors a ON pa.prosecutor_id = a.id
            WHERE pa.case_id = $1
            ORDER BY pa.action_date DESC, pa.created_at DESC
        """, case_id)
        return [self._serialize_pros_action(r) for r in rows]

    async def create_prosecutorial_action(self, data: Dict[str, Any]) -> dict:
        from backend.database import fetchrow

        row = await fetchrow("""
            INSERT INTO prosecutorial_actions (
                case_id, prosecutor_id, prosecutor_name,
                action_type, action_date, description,
                reasoning, legal_basis, justification,
                supervisor_reviewed, supervisor_name
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING *
        """,
            data["case_id"],
            data.get("prosecutor_id"),
            data.get("prosecutor_name"),
            data["action_type"],
            data.get("action_date"),
            data.get("description"),
            data.get("reasoning"),
            data.get("legal_basis"),
            data.get("justification"),
            data.get("supervisor_reviewed", False),
            data.get("supervisor_name"),
        )
        logger.info(f"Created prosecutorial action: {data['action_type']} for case {data['case_id']}")
        return self._serialize_pros_action(row)

    # --- Bail Decisions ---

    async def list_bail_decisions(self, case_id: UUID) -> List[dict]:
        from backend.database import fetch

        rows = await fetch("""
            SELECT bd.*, a.canonical_name as judge_canonical_name
            FROM bail_decisions bd
            LEFT JOIN actors a ON bd.judge_id = a.id
            WHERE bd.case_id = $1
            ORDER BY bd.decision_date DESC, bd.created_at DESC
        """, case_id)
        return [self._serialize_bail(r) for r in rows]

    async def create_bail_decision(self, data: Dict[str, Any]) -> dict:
        from backend.database import fetchrow

        row = await fetchrow("""
            INSERT INTO bail_decisions (
                case_id, judge_id, judge_name,
                decision_type, decision_date,
                bail_amount, bail_type, conditions,
                flight_risk_assessed, danger_to_public_assessed,
                prior_record_considered, community_ties_considered,
                risk_factors_notes,
                prosecution_position, prosecution_requested_amount,
                defense_position, defense_requested_amount,
                decision_rationale, bail_status,
                defendant_released, release_date
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21)
            RETURNING *
        """,
            data["case_id"],
            data.get("judge_id"),
            data.get("judge_name"),
            data["decision_type"],
            data.get("decision_date"),
            data.get("bail_amount"),
            data.get("bail_type"),
            data.get("conditions"),
            data.get("flight_risk_assessed"),
            data.get("danger_to_public_assessed"),
            data.get("prior_record_considered", False),
            data.get("community_ties_considered", False),
            data.get("risk_factors_notes"),
            data.get("prosecution_position"),
            data.get("prosecution_requested_amount"),
            data.get("defense_position"),
            data.get("defense_requested_amount"),
            data.get("decision_rationale"),
            data.get("bail_status", "set"),
            data.get("defendant_released"),
            data.get("release_date"),
        )
        logger.info(f"Created bail decision: {data['decision_type']} for case {data['case_id']}")
        return self._serialize_bail(row)

    # --- Dispositions ---

    async def list_dispositions(self, case_id: UUID) -> List[dict]:
        from backend.database import fetch

        rows = await fetch("""
            SELECT d.*, a.canonical_name as judge_canonical_name,
                   c.charge_number, c.charge_description
            FROM dispositions d
            LEFT JOIN actors a ON d.judge_id = a.id
            LEFT JOIN charges c ON d.charge_id = c.id
            WHERE d.case_id = $1
            ORDER BY d.disposition_date DESC, d.created_at DESC
        """, case_id)
        return [self._serialize_disposition(r) for r in rows]

    async def create_disposition(self, data: Dict[str, Any]) -> dict:
        from backend.database import fetchrow

        row = await fetchrow("""
            INSERT INTO dispositions (
                case_id, charge_id, judge_id, judge_name,
                disposition_type, disposition_date,
                total_jail_days, jail_days_suspended, jail_days_served,
                incarceration_start_date, projected_release_date,
                actual_release_date, incarceration_facility,
                probation_days, probation_start_date, probation_end_date,
                probation_conditions,
                fine_amount, restitution_amount, court_costs,
                community_service_hours,
                ordered_programs, substance_abuse_treatment_ordered,
                mental_health_treatment_ordered,
                compliance_status, notes
            )
            VALUES (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10, $11, $12, $13,
                $14, $15, $16, $17::jsonb,
                $18, $19, $20, $21,
                $22::jsonb, $23, $24, $25, $26
            )
            RETURNING *
        """,
            data["case_id"],
            data.get("charge_id"),
            data.get("judge_id"),
            data.get("judge_name"),
            data["disposition_type"],
            data.get("disposition_date"),
            data.get("total_jail_days"),
            data.get("jail_days_suspended"),
            data.get("jail_days_served"),
            data.get("incarceration_start_date"),
            data.get("projected_release_date"),
            data.get("actual_release_date"),
            data.get("incarceration_facility"),
            data.get("probation_days"),
            data.get("probation_start_date"),
            data.get("probation_end_date"),
            data.get("probation_conditions"),
            data.get("fine_amount"),
            data.get("restitution_amount"),
            data.get("court_costs"),
            data.get("community_service_hours"),
            data.get("ordered_programs"),
            data.get("substance_abuse_treatment_ordered", False),
            data.get("mental_health_treatment_ordered", False),
            data.get("compliance_status", "pending"),
            data.get("notes"),
        )
        logger.info(f"Created disposition: {data['disposition_type']} for case {data['case_id']}")
        return self._serialize_disposition(row)

    # --- Case Linking ---

    async def list_case_incidents(self, case_id: UUID) -> List[dict]:
        from backend.database import fetch

        rows = await fetch("""
            SELECT ci.*, i.title, i.date, i.state
            FROM case_incidents ci
            JOIN incidents i ON ci.incident_id = i.id
            WHERE ci.case_id = $1
            ORDER BY ci.sequence_order NULLS LAST, ci.created_at
        """, case_id)
        return [self._serialize_link(r) for r in rows]

    async def link_incident(self, data: Dict[str, Any]) -> dict:
        from backend.database import fetchrow

        row = await fetchrow("""
            INSERT INTO case_incidents (case_id, incident_id, incident_role, sequence_order, notes)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (case_id, incident_id, incident_role) DO UPDATE SET
                sequence_order = EXCLUDED.sequence_order,
                notes = EXCLUDED.notes
            RETURNING *
        """,
            data["case_id"], data["incident_id"],
            data.get("incident_role", "related"),
            data.get("sequence_order"),
            data.get("notes"),
        )
        return self._serialize_link(row)

    async def list_case_actors(self, case_id: UUID) -> List[dict]:
        from backend.database import fetch

        rows = await fetch("""
            SELECT ca.*, a.canonical_name, a.actor_type,
                   art.name as role_name, art.slug as role_slug
            FROM case_actors ca
            JOIN actors a ON ca.actor_id = a.id
            LEFT JOIN actor_role_types art ON ca.role_type_id = art.id
            WHERE ca.case_id = $1
            ORDER BY ca.is_primary DESC, ca.created_at
        """, case_id)
        return [self._serialize_link(r) for r in rows]

    async def link_actor(self, data: Dict[str, Any]) -> dict:
        from backend.database import fetchrow

        row = await fetchrow("""
            INSERT INTO case_actors (
                case_id, actor_id, role_type_id, role_description,
                is_primary, notes, start_date, end_date
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (case_id, actor_id, role_type_id) DO UPDATE SET
                role_description = EXCLUDED.role_description,
                is_primary = EXCLUDED.is_primary,
                notes = EXCLUDED.notes,
                start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date
            RETURNING *
        """,
            data["case_id"], data["actor_id"],
            data.get("role_type_id"),
            data.get("role_description"),
            data.get("is_primary", False),
            data.get("notes"),
            data.get("start_date"),
            data.get("end_date"),
        )
        return self._serialize_link(row)

    # --- Prosecutor Stats ---

    async def get_prosecutor_stats(self, prosecutor_id: Optional[UUID] = None) -> List[dict]:
        from backend.database import fetch

        if prosecutor_id:
            rows = await fetch(
                "SELECT * FROM prosecutor_stats WHERE prosecutor_id = $1",
                prosecutor_id,
            )
        else:
            rows = await fetch(
                "SELECT * FROM prosecutor_stats ORDER BY total_cases DESC"
            )
        return [self._serialize_stats(r) for r in rows]

    async def refresh_prosecutor_stats(self) -> None:
        from backend.database import execute

        await execute("REFRESH MATERIALIZED VIEW CONCURRENTLY prosecutor_stats")
        logger.info("Refreshed prosecutor_stats materialized view")

    # --- Serialization ---

    def _serialize_case(self, row) -> Optional[dict]:
        if row is None:
            return None
        d = dict(row)
        for uid in ("id", "domain_id", "category_id"):
            if d.get(uid):
                d[uid] = str(d[uid])
        for ts in ("created_at", "updated_at"):
            if d.get(ts):
                d[ts] = d[ts].isoformat()
        for dt in ("filed_date", "closed_date"):
            if d.get(dt):
                d[dt] = d[dt].isoformat()
        return d

    def _serialize_charge(self, row) -> Optional[dict]:
        if row is None:
            return None
        d = dict(row)
        for uid in ("id", "case_id"):
            if d.get(uid):
                d[uid] = str(d[uid])
        for ts in ("created_at", "updated_at"):
            if d.get(ts):
                d[ts] = d[ts].isoformat()
        for dec in ("fine_amount", "restitution_amount"):
            if d.get(dec) is not None:
                d[dec] = float(d[dec])
        return d

    def _serialize_charge_history(self, row) -> Optional[dict]:
        if row is None:
            return None
        d = dict(row)
        for uid in ("id", "charge_id", "case_id", "actor_id"):
            if d.get(uid):
                d[uid] = str(d[uid])
        for ts in ("created_at",):
            if d.get(ts):
                d[ts] = d[ts].isoformat()
        if d.get("event_date"):
            d["event_date"] = d["event_date"].isoformat()
        return d

    def _serialize_pros_action(self, row) -> Optional[dict]:
        if row is None:
            return None
        d = dict(row)
        for uid in ("id", "case_id", "prosecutor_id"):
            if d.get(uid):
                d[uid] = str(d[uid])
        for ts in ("created_at", "updated_at"):
            if d.get(ts):
                d[ts] = d[ts].isoformat()
        if d.get("action_date"):
            d["action_date"] = d["action_date"].isoformat()
        return d

    def _serialize_bail(self, row) -> Optional[dict]:
        if row is None:
            return None
        d = dict(row)
        for uid in ("id", "case_id", "judge_id"):
            if d.get(uid):
                d[uid] = str(d[uid])
        for ts in ("created_at", "updated_at"):
            if d.get(ts):
                d[ts] = d[ts].isoformat()
        for dt in ("decision_date", "release_date"):
            if d.get(dt):
                d[dt] = d[dt].isoformat()
        for dec in ("bail_amount", "prosecution_requested_amount", "defense_requested_amount"):
            if d.get(dec) is not None:
                d[dec] = float(d[dec])
        return d

    def _serialize_disposition(self, row) -> Optional[dict]:
        if row is None:
            return None
        d = dict(row)
        for uid in ("id", "case_id", "charge_id", "judge_id"):
            if d.get(uid):
                d[uid] = str(d[uid])
        for ts in ("created_at", "updated_at"):
            if d.get(ts):
                d[ts] = d[ts].isoformat()
        for dt in ("disposition_date", "incarceration_start_date",
                    "projected_release_date", "actual_release_date",
                    "probation_start_date", "probation_end_date"):
            if d.get(dt):
                d[dt] = d[dt].isoformat()
        for dec in ("fine_amount", "fine_amount_paid", "restitution_amount",
                     "restitution_amount_paid", "court_costs"):
            if d.get(dec) is not None:
                d[dec] = float(d[dec])
        return d

    def _serialize_stats(self, row) -> Optional[dict]:
        if row is None:
            return None
        d = dict(row)
        if d.get("prosecutor_id"):
            d["prosecutor_id"] = str(d["prosecutor_id"])
        if d.get("refreshed_at"):
            d["refreshed_at"] = d["refreshed_at"].isoformat()
        for dec in ("conviction_rate", "avg_bail_requested", "avg_sentence_days",
                     "data_completeness_pct"):
            if d.get(dec) is not None:
                d[dec] = float(d[dec])
        return d

    def _serialize_link(self, row) -> Optional[dict]:
        if row is None:
            return None
        d = dict(row)
        for key, val in d.items():
            if isinstance(val, UUID):
                d[key] = str(val)
            elif hasattr(val, 'isoformat'):
                d[key] = val.isoformat()
        return d


# Singleton
_cj_service: Optional[CriminalJusticeService] = None


def get_criminal_justice_service() -> CriminalJusticeService:
    """Get the singleton CriminalJusticeService instance."""
    global _cj_service
    if _cj_service is None:
        _cj_service = CriminalJusticeService()
    return _cj_service
