#!/usr/bin/env python3
"""
Import crime-tracker data into the unified incident tracker.

Imports:
- cases -> incidents (category='crime')
- offenders -> persons
- crime_types -> incident_types
- extraction_prompts -> can be used directly
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from uuid import uuid4

import asyncpg

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database URLs
SOURCE_DB = os.getenv(
    "SOURCE_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5435/crime_tracker"
)
TARGET_DB = os.getenv(
    "TARGET_DATABASE_URL",
    "postgresql://sentinel:devpassword@localhost:5433/sentinel"
)

# Mapping from crime-tracker crime types to our incident types
CRIME_TYPE_MAPPING = {
    'Homicide': 'homicide',
    'Murder': 'homicide',
    'Manslaughter': 'homicide',
    'Vehicular Homicide': 'dui_fatality',
    'Assault': 'assault',
    'Aggravated Assault': 'assault',
    'Domestic Violence': 'assault',
    'Rape': 'sexual_assault',
    'Sexual Assault': 'sexual_assault',
    'Child Abuse': 'sexual_assault',
    'Kidnapping': 'kidnapping',
    'Human Trafficking': 'human_trafficking',
    'Robbery': 'robbery',
    'Armed Robbery': 'robbery',
    'Home Invasion': 'robbery',
    'Burglary': 'robbery',
    'Theft': 'robbery',
    'Identity Theft': 'robbery',
    'Drug Distribution': 'drug_trafficking',
    'Drug Trafficking': 'drug_trafficking',
    'Fentanyl Distribution': 'drug_trafficking',
    'DUI': 'dui_fatality',
    'DUI with Injury': 'dui_fatality',
    'Illegal Reentry': 'gang_activity',  # Map to gang_activity as closest match
    'Other': 'assault',  # Default
}


async def get_or_create_incident_type(conn: asyncpg.Connection, name: str) -> str:
    """Get or create an incident type, return its ID."""
    # Check if exists
    row = await conn.fetchrow(
        "SELECT id FROM incident_types WHERE name = $1",
        name
    )
    if row:
        return row['id']

    # Create new
    new_id = uuid4()
    await conn.execute(
        """
        INSERT INTO incident_types (id, name, category, severity_weight)
        VALUES ($1, $2, 'crime', 3.5)
        """,
        new_id, name
    )
    logger.info(f"Created incident type: {name}")
    return new_id


async def import_offenders(source_conn: asyncpg.Connection, target_conn: asyncpg.Connection) -> dict:
    """Import offenders as persons, return mapping of old_id -> new_id."""
    logger.info("Importing offenders...")

    offenders = await source_conn.fetch("""
        SELECT id, nationality, country_of_origin, age_at_offense, gender,
               immigration_status, entry_method, prior_deportations,
               prior_arrests, prior_convictions, gang_affiliation,
               cartel_connection, was_released_sanctuary, was_released_bail,
               ice_detainer_ignored, created_at
        FROM offenders
    """)

    id_mapping = {}
    imported = 0

    for off in offenders:
        new_id = uuid4()
        id_mapping[str(off['id'])] = new_id

        # Check for gang affiliation
        gang_affiliated = bool(off['gang_affiliation'] or off['cartel_connection'])
        gang_name = off['gang_affiliation'] or off['cartel_connection']

        try:
            await target_conn.execute(
                """
                INSERT INTO persons (
                    id, nationality, age, gender,
                    immigration_status, prior_deportations,
                    prior_convictions, gang_affiliated, gang_name,
                    external_ids, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW())
                """,
                new_id,
                off['nationality'] or off['country_of_origin'],
                off['age_at_offense'],
                off['gender'],
                off['immigration_status'],
                off['prior_deportations'] or 0,
                off['prior_convictions'] or 0,
                gang_affiliated,
                gang_name,
                json.dumps({
                    'crime_tracker_id': str(off['id']),
                    'prior_arrests': off['prior_arrests'],
                    'entry_method': off['entry_method'],
                    'was_released_sanctuary': off['was_released_sanctuary'],
                    'was_released_bail': off['was_released_bail'],
                    'ice_detainer_ignored': off['ice_detainer_ignored'],
                }),
                off['created_at'] or datetime.now(),
            )
            imported += 1
        except Exception as e:
            logger.error(f"Error importing offender {off['id']}: {e}")

    logger.info(f"Imported {imported} offenders as persons")
    return id_mapping


async def import_cases(
    source_conn: asyncpg.Connection,
    target_conn: asyncpg.Connection,
    offender_mapping: dict
) -> int:
    """Import cases as crime incidents."""
    logger.info("Importing cases...")

    # Get cases with crime type info
    cases = await source_conn.fetch("""
        SELECT c.*, ct.name as crime_type_name, ct.severity_weight,
               l.name as location_name, l.state_code
        FROM cases c
        LEFT JOIN crime_types ct ON c.crime_type_id = ct.id
        LEFT JOIN locations l ON c.location_id = l.id
        WHERE c.status = 'approved'
    """)

    imported = 0
    for case in cases:
        incident_id = uuid4()

        # Map crime type
        crime_type = case['crime_type_name'] or 'Other'
        mapped_type = CRIME_TYPE_MAPPING.get(crime_type, 'assault')
        incident_type_id = await get_or_create_incident_type(target_conn, mapped_type)

        # Get offender person ID
        offender_id = offender_mapping.get(str(case['offender_id'])) if case['offender_id'] else None

        # Determine state
        state = case['state'] or case['state_code'] or 'Unknown'

        # Determine outcome
        outcome_category = None
        if case['involves_fatality'] or case['victim_fatalities']:
            outcome_category = 'death'
        elif case['victim_count'] and case['victim_count'] > 0:
            outcome_category = 'serious_injury'

        # Get offender details for denormalized fields
        offender_details = None
        if offender_id:
            offender_details = await target_conn.fetchrow(
                "SELECT immigration_status, prior_deportations, gang_affiliated FROM persons WHERE id = $1",
                offender_id
            )

        try:
            await target_conn.execute(
                """
                INSERT INTO incidents (
                    id, legacy_id, category, date, date_precision, incident_type_id,
                    state, city, title, description,
                    affected_count, incident_scale, outcome_category,
                    source_tier, verified, curation_status,
                    offender_immigration_status, prior_deportations, gang_affiliated,
                    created_at, updated_at
                ) VALUES (
                    $1, $2, 'crime', $3, 'day', $4,
                    $5, $6, $7, $8,
                    $9, $10, $11,
                    '2', $12, 'approved',
                    $13, $14, $15,
                    $16, NOW()
                )
                """,
                incident_id,
                f"CT-{str(case['id'])[:8]}",  # Legacy ID
                case['incident_date'],
                incident_type_id,
                state,
                case['city'],
                case['headline'],
                case['description'],
                case['victim_count'] or 1,
                'single' if (case['victim_count'] or 1) == 1 else 'small',
                outcome_category,
                case['is_verified'] or False,
                offender_details['immigration_status'] if offender_details else None,
                offender_details['prior_deportations'] if offender_details else 0,
                offender_details['gang_affiliated'] if offender_details else False,
                case['created_at'] or datetime.now(),
            )

            # Link offender to incident
            if offender_id:
                await target_conn.execute(
                    """
                    INSERT INTO incident_persons (id, incident_id, person_id, role)
                    VALUES ($1, $2, $3, 'offender')
                    """,
                    uuid4(), incident_id, offender_id
                )

            imported += 1

        except Exception as e:
            logger.error(f"Error importing case {case['id']}: {e}")

    logger.info(f"Imported {imported} cases as crime incidents")
    return imported


async def import_extraction_prompts(source_conn: asyncpg.Connection, target_conn: asyncpg.Connection) -> int:
    """Import extraction prompts."""
    logger.info("Importing extraction prompts...")

    # Check if we have an extraction_prompts table
    table_exists = await target_conn.fetchval("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'extraction_prompts'
        )
    """)

    if not table_exists:
        logger.info("Creating extraction_prompts table...")
        await target_conn.execute("""
            CREATE TABLE IF NOT EXISTS extraction_prompts (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                name VARCHAR(100) NOT NULL,
                document_type VARCHAR(50) NOT NULL,
                system_prompt TEXT,
                extraction_prompt TEXT NOT NULL,
                output_schema JSONB,
                model VARCHAR(100) DEFAULT 'claude-sonnet-4-20250514',
                max_tokens INTEGER DEFAULT 2000,
                temperature DECIMAL(3,2) DEFAULT 0.0,
                is_active BOOLEAN DEFAULT TRUE,
                is_default BOOLEAN DEFAULT FALSE,
                total_uses INTEGER DEFAULT 0,
                avg_confidence DECIMAL(3,2) DEFAULT 0,
                success_rate DECIMAL(3,2) DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)

    prompts = await source_conn.fetch("""
        SELECT name, document_type, system_prompt, extraction_prompt,
               output_schema, model, max_tokens, temperature,
               is_active, is_default, total_uses, avg_confidence, success_rate
        FROM extraction_prompts
    """)

    imported = 0
    for prompt in prompts:
        try:
            await target_conn.execute(
                """
                INSERT INTO extraction_prompts (
                    name, document_type, system_prompt, extraction_prompt,
                    output_schema, model, max_tokens, temperature,
                    is_active, is_default, total_uses, avg_confidence, success_rate
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                ON CONFLICT DO NOTHING
                """,
                prompt['name'],
                prompt['document_type'],
                prompt['system_prompt'],
                prompt['extraction_prompt'],
                prompt['output_schema'],
                prompt['model'] or 'claude-sonnet-4-20250514',
                prompt['max_tokens'] or 2000,
                prompt['temperature'] or 0.0,
                prompt['is_active'],
                prompt['is_default'],
                prompt['total_uses'] or 0,
                prompt['avg_confidence'] or 0,
                prompt['success_rate'] or 0,
            )
            imported += 1
        except Exception as e:
            logger.error(f"Error importing prompt {prompt['name']}: {e}")

    logger.info(f"Imported {imported} extraction prompts")
    return imported


async def import_ingested_articles(source_conn: asyncpg.Connection, target_conn: asyncpg.Connection) -> int:
    """Import ingested articles for curation queue."""
    logger.info("Importing ingested articles...")

    articles = await source_conn.fetch("""
        SELECT id, feed_id, title, content, url, published_at, author,
               relevance_score, extracted_entities, processing_status,
               processed_at, is_relevant, curation_notes,
               extraction_confidence, confidence_details, created_at
        FROM ingested_articles
    """)

    imported = 0
    skipped = 0

    for article in articles:
        # Map processing_status to our curation_status
        status_mapping = {
            'pending': 'pending',
            'processing': 'in_review',
            'processed': 'pending',  # Still needs human review
            'approved': 'approved',
            'rejected': 'rejected',
            'converted': 'approved',
        }
        status = status_mapping.get(article['processing_status'], 'pending')

        try:
            # Check if already exists by URL
            exists = await target_conn.fetchval(
                "SELECT 1 FROM ingested_articles WHERE source_url = $1",
                article['url']
            )
            if exists:
                skipped += 1
                continue

            await target_conn.execute(
                """
                INSERT INTO ingested_articles (
                    id, source_url, title, content, published_date,
                    relevance_score, extracted_data, extraction_confidence,
                    status, fetched_at, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                article['id'],
                article['url'],
                article['title'],
                article['content'],
                article['published_at'].date() if article['published_at'] else None,
                article['relevance_score'],
                article['extracted_entities'],  # JSONB
                article['extraction_confidence'],
                status,
                article['created_at'] or datetime.now(),
                article['created_at'] or datetime.now(),
            )
            imported += 1
        except Exception as e:
            logger.error(f"Error importing article {article['id']}: {e}")

    logger.info(f"Imported {imported} ingested articles (skipped {skipped} duplicates)")
    return imported


async def main():
    """Main import function."""
    logger.info("Starting crime-tracker data import")
    logger.info(f"Source: {SOURCE_DB.split('@')[1] if '@' in SOURCE_DB else SOURCE_DB}")
    logger.info(f"Target: {TARGET_DB.split('@')[1] if '@' in TARGET_DB else TARGET_DB}")

    source_conn = await asyncpg.connect(SOURCE_DB)
    target_conn = await asyncpg.connect(TARGET_DB)

    try:
        # Import in order (offenders first, then cases that reference them)
        offender_mapping = await import_offenders(source_conn, target_conn)
        cases_imported = await import_cases(source_conn, target_conn, offender_mapping)
        prompts_imported = await import_extraction_prompts(source_conn, target_conn)
        articles_imported = await import_ingested_articles(source_conn, target_conn)

        # Final counts
        incident_count = await target_conn.fetchval(
            "SELECT COUNT(*) FROM incidents WHERE category = 'crime'"
        )
        person_count = await target_conn.fetchval("SELECT COUNT(*) FROM persons")
        article_count = await target_conn.fetchval("SELECT COUNT(*) FROM ingested_articles")

        logger.info("=" * 50)
        logger.info("Import complete!")
        logger.info(f"  Crime incidents in database: {incident_count}")
        logger.info(f"  Persons in database: {person_count}")
        logger.info(f"  Extraction prompts imported: {prompts_imported}")
        logger.info(f"  Ingested articles in database: {article_count}")

    finally:
        await source_conn.close()
        await target_conn.close()


if __name__ == "__main__":
    asyncio.run(main())
