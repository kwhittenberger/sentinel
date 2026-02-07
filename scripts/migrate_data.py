#!/usr/bin/env python3
"""
Data migration script: JSON files -> PostgreSQL

Migrates existing ICE incident data from JSON files to the PostgreSQL database.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

import asyncpg

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database URL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://sentinel:sentinel@localhost:5433/sentinel"
)

# Data directories
DATA_DIR = PROJECT_ROOT / "data"
INCIDENTS_DIR = DATA_DIR / "incidents"
REFERENCE_DIR = DATA_DIR / "reference"

# Incident files to migrate
INCIDENT_FILES = [
    ("tier1_deaths_in_custody.json", "1"),
    ("tier2_shootings.json", "2"),
    ("tier2_less_lethal.json", "2"),
    ("tier3_incidents.json", "3"),
    ("tier4_incidents.json", "4"),
]

# Mapping from incident types to incident_type IDs (populated at runtime)
INCIDENT_TYPE_MAP = {}

# Valid values
VALID_VICTIM_CATEGORIES = {
    'detainee', 'enforcement_target', 'protester', 'journalist',
    'bystander', 'us_citizen_collateral', 'officer', 'multiple'
}

VALID_OUTCOME_CATEGORIES = {
    'death', 'serious_injury', 'minor_injury', 'no_injury', 'unknown'
}

VALID_INCIDENT_SCALES = {'single', 'small', 'medium', 'large', 'mass'}


def normalize_victim_category(value: str) -> Optional[str]:
    """Normalize victim category to valid enum value."""
    if not value:
        return None
    value = value.lower().strip()

    # Handle common variations
    mappings = {
        'us_citizen': 'us_citizen_collateral',
        'citizen': 'us_citizen_collateral',
        'legal_resident': 'bystander',
        'us citizen': 'us_citizen_collateral',
    }

    if value in mappings:
        return mappings[value]
    if value in VALID_VICTIM_CATEGORIES:
        return value
    return None


def normalize_outcome_category(value: str) -> Optional[str]:
    """Normalize outcome category."""
    if not value:
        return None
    value = value.lower().strip()
    if value in VALID_OUTCOME_CATEGORIES:
        return value
    # Map common variations
    if 'death' in value:
        return 'death'
    if 'serious' in value or 'major' in value:
        return 'serious_injury'
    if 'minor' in value:
        return 'minor_injury'
    return 'unknown'


def normalize_incident_scale(value: str) -> str:
    """Normalize incident scale."""
    if not value:
        return 'single'
    value = value.lower().strip()
    if value in VALID_INCIDENT_SCALES:
        return value
    return 'single'


async def load_incident_types(conn: asyncpg.Connection) -> dict:
    """Load incident types from database."""
    rows = await conn.fetch("SELECT id, name FROM incident_types")
    return {row['name']: row['id'] for row in rows}


async def get_or_create_incident_type(
    conn: asyncpg.Connection,
    name: str,
    category: str = 'enforcement'
) -> str:
    """Get or create an incident type, return its ID."""
    global INCIDENT_TYPE_MAP

    if name in INCIDENT_TYPE_MAP:
        return INCIDENT_TYPE_MAP[name]

    # Check if exists
    row = await conn.fetchrow(
        "SELECT id FROM incident_types WHERE name = $1",
        name
    )
    if row:
        INCIDENT_TYPE_MAP[name] = row['id']
        return row['id']

    # Create new
    new_id = uuid4()
    await conn.execute(
        """
        INSERT INTO incident_types (id, name, category, severity_weight)
        VALUES ($1, $2, $3, 2.5)
        """,
        new_id, name, category
    )
    INCIDENT_TYPE_MAP[name] = new_id
    logger.info(f"Created new incident type: {name}")
    return new_id


async def migrate_incident(conn: asyncpg.Connection, incident: dict, tier: str) -> bool:
    """Migrate a single incident to the database."""
    try:
        incident_id = uuid4()
        legacy_id = incident.get('id', '')

        # Check for existing
        existing = await conn.fetchrow(
            "SELECT id FROM incidents WHERE legacy_id = $1",
            legacy_id
        )
        if existing:
            logger.debug(f"Skipping duplicate: {legacy_id}")
            return False

        # Get incident type ID
        incident_type = incident.get('incident_type', 'unknown')
        incident_type_id = await get_or_create_incident_type(conn, incident_type, 'enforcement')

        # Parse date
        date_str = incident.get('date', '')
        incident_date = None
        if date_str:
            try:
                # Handle various date formats
                if len(date_str) == 10:
                    incident_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                elif len(date_str) == 7:
                    incident_date = datetime.strptime(date_str + '-01', '%Y-%m-%d').date()
                else:
                    incident_date = datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
            except ValueError:
                logger.warning(f"Invalid date format for {legacy_id}: {date_str}")
                incident_date = None

        if not incident_date:
            logger.warning(f"Skipping incident without valid date: {legacy_id}")
            return False

        # Normalize fields
        victim_category = normalize_victim_category(incident.get('victim_category'))
        outcome_category = normalize_outcome_category(incident.get('outcome_category'))
        incident_scale = normalize_incident_scale(incident.get('incident_scale'))

        # Insert incident
        await conn.execute(
            """
            INSERT INTO incidents (
                id, legacy_id, category, date, date_precision, incident_type_id,
                state, city, address, latitude, longitude,
                title, description, notes,
                affected_count, incident_scale, outcome, outcome_category, outcome_detail,
                victim_category, victim_name, victim_age, us_citizen, protest_related,
                source_tier, source_url, source_name, verified,
                state_sanctuary_status, local_sanctuary_status, detainer_policy,
                curation_status, created_at, updated_at
            ) VALUES (
                $1, $2, 'enforcement', $3, $4, $5,
                $6, $7, $8, $9, $10,
                $11, $12, $13,
                $14, $15, $16, $17, $18,
                $19, $20, $21, $22, $23,
                $24, $25, $26, $27,
                $28, $29, $30,
                'approved', NOW(), NOW()
            )
            """,
            incident_id,
            legacy_id,
            incident_date,
            incident.get('date_precision', 'day'),
            incident_type_id,
            incident.get('state', ''),
            incident.get('city'),
            incident.get('address'),
            incident.get('lat') or incident.get('latitude'),
            incident.get('lon') or incident.get('longitude'),
            incident.get('title'),
            incident.get('description'),
            incident.get('notes'),
            incident.get('affected_count', 1),
            incident_scale,
            incident.get('outcome'),
            outcome_category,
            incident.get('outcome_detail'),
            victim_category,
            incident.get('victim_name'),
            incident.get('victim_age'),
            incident.get('us_citizen'),
            incident.get('protest_related', False),
            tier,
            incident.get('source_url'),
            incident.get('source_name'),
            incident.get('verified', False),
            incident.get('state_sanctuary_status'),
            incident.get('local_sanctuary_status'),
            incident.get('detainer_policy'),
        )

        return True

    except Exception as e:
        logger.error(f"Error migrating incident {incident.get('id')}: {e}")
        return False


async def migrate_sanctuary_jurisdictions(conn: asyncpg.Connection):
    """Migrate sanctuary jurisdiction data."""
    sanctuary_file = REFERENCE_DIR / "sanctuary_jurisdictions.json"

    if not sanctuary_file.exists():
        logger.warning(f"Sanctuary file not found: {sanctuary_file}")
        return 0

    with open(sanctuary_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    migrated = 0

    # Migrate states - data.get('states') is a dict with state names as keys
    states_data = data.get('states', {})
    if isinstance(states_data, dict):
        for state_name, state_info in states_data.items():
            if state_name.startswith('_'):  # Skip metadata
                continue
            state_id = uuid4()
            try:
                await conn.execute(
                    """
                    INSERT INTO jurisdictions (
                        id, name, jurisdiction_type,
                        state_sanctuary_status, policy_source_url
                    ) VALUES ($1, $2, 'state', $3, $4)
                    ON CONFLICT DO NOTHING
                    """,
                    state_id,
                    state_name,
                    state_info.get('classification'),
                    state_info.get('source_url'),
                )
                migrated += 1
            except Exception as e:
                logger.error(f"Error migrating state {state_name}: {e}")

    # Migrate cities - data.get('cities') is a dict with city names as keys
    cities_data = data.get('cities', {})
    if isinstance(cities_data, dict):
        for city_name, city_info in cities_data.items():
            if city_name.startswith('_'):  # Skip metadata
                continue
            city_id = uuid4()
            try:
                await conn.execute(
                    """
                    INSERT INTO jurisdictions (
                        id, name, jurisdiction_type, state_code,
                        local_sanctuary_status, policy_source_url
                    ) VALUES ($1, $2, 'city', $3, $4, $5)
                    ON CONFLICT DO NOTHING
                    """,
                    city_id,
                    city_name,
                    city_info.get('state'),
                    city_info.get('classification'),
                    city_info.get('source_url'),
                )
                migrated += 1
            except Exception as e:
                logger.error(f"Error migrating city {city_name}: {e}")

    return migrated


async def main():
    """Main migration function."""
    logger.info("Starting data migration to PostgreSQL")
    logger.info(f"Database URL: {DATABASE_URL.replace(DATABASE_URL.split(':')[2].split('@')[0], '***')}")

    conn = await asyncpg.connect(DATABASE_URL)

    try:
        # Load existing incident types
        global INCIDENT_TYPE_MAP
        INCIDENT_TYPE_MAP = await load_incident_types(conn)
        logger.info(f"Loaded {len(INCIDENT_TYPE_MAP)} existing incident types")

        # Migrate incidents
        total_migrated = 0
        total_skipped = 0

        for filename, tier in INCIDENT_FILES:
            filepath = INCIDENTS_DIR / filename
            if not filepath.exists():
                logger.warning(f"File not found: {filepath}")
                continue

            with open(filepath, 'r', encoding='utf-8') as f:
                incidents = json.load(f)

            logger.info(f"Migrating {len(incidents)} incidents from {filename} (tier {tier})")

            migrated = 0
            for incident in incidents:
                async with conn.transaction():
                    if await migrate_incident(conn, incident, tier):
                        migrated += 1
                    else:
                        total_skipped += 1

            total_migrated += migrated
            logger.info(f"  -> Migrated {migrated} incidents from {filename}")

        # Migrate sanctuary jurisdictions
        logger.info("Migrating sanctuary jurisdiction data...")
        jurisdiction_count = await migrate_sanctuary_jurisdictions(conn)
        logger.info(f"  -> Migrated {jurisdiction_count} jurisdictions")

        # Final counts
        incident_count = await conn.fetchval("SELECT COUNT(*) FROM incidents")
        jurisdiction_count = await conn.fetchval("SELECT COUNT(*) FROM jurisdictions")

        logger.info("=" * 50)
        logger.info("Migration complete!")
        logger.info(f"  Total incidents migrated: {total_migrated}")
        logger.info(f"  Total incidents skipped: {total_skipped}")
        logger.info(f"  Total incidents in database: {incident_count}")
        logger.info(f"  Total jurisdictions in database: {jurisdiction_count}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
