"""
Database connection pool and utilities for PostgreSQL.
"""

import os
import json
import logging
from typing import AsyncGenerator, Optional
from contextlib import asynccontextmanager

import asyncpg
from asyncpg import Pool, Connection

logger = logging.getLogger(__name__)


async def _init_connection(conn: Connection):
    """Initialize connection with JSON codec."""
    await conn.set_type_codec(
        'jsonb',
        encoder=json.dumps,
        decoder=json.loads,
        schema='pg_catalog'
    )
    await conn.set_type_codec(
        'json',
        encoder=json.dumps,
        decoder=json.loads,
        schema='pg_catalog'
    )

# Database URL from environment
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://sentinel:devpassword@localhost:5433/sentinel"
)

# Global connection pool
_pool: Optional[Pool] = None


async def get_pool() -> Pool:
    """Get or create the connection pool."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=2,
            max_size=10,
            command_timeout=60,
            init=_init_connection,  # Register JSON codecs on each connection
        )
        logger.info("Database connection pool created")
    return _pool


async def close_pool():
    """Close the connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database connection pool closed")


@asynccontextmanager
async def get_connection() -> AsyncGenerator[Connection, None]:
    """Get a connection from the pool."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def get_transaction() -> AsyncGenerator[Connection, None]:
    """Get a connection with an active transaction."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn


async def execute(query: str, *args, timeout: float = None) -> str:
    """Execute a query and return status."""
    async with get_connection() as conn:
        return await conn.execute(query, *args, timeout=timeout)


async def fetch(query: str, *args, timeout: float = None) -> list:
    """Fetch multiple rows."""
    async with get_connection() as conn:
        return await conn.fetch(query, *args, timeout=timeout)


async def fetchrow(query: str, *args, timeout: float = None):
    """Fetch a single row."""
    async with get_connection() as conn:
        return await conn.fetchrow(query, *args, timeout=timeout)


async def fetchval(query: str, *args, timeout: float = None):
    """Fetch a single value."""
    async with get_connection() as conn:
        return await conn.fetchval(query, *args, timeout=timeout)


async def executemany(query: str, args: list, timeout: float = None):
    """Execute a query with multiple argument sets."""
    async with get_connection() as conn:
        return await conn.executemany(query, args, timeout=timeout)


# Health check
async def check_connection() -> bool:
    """Check if database connection is healthy."""
    try:
        result = await fetchval("SELECT 1")
        return result == 1
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False


# Migration runner
async def run_migration(migration_sql: str):
    """Run a migration SQL script."""
    async with get_transaction() as conn:
        await conn.execute(migration_sql)
        logger.info("Migration executed successfully")


# Utility for building parameterized queries
def build_where_clause(filters: dict, start_param: int = 1) -> tuple[str, list]:
    """
    Build a WHERE clause from a dict of filters.
    Returns (where_sql, params).
    """
    conditions = []
    params = []
    param_num = start_param

    for key, value in filters.items():
        if value is None:
            continue

        if isinstance(value, list):
            if not value:
                continue
            placeholders = ', '.join(f'${param_num + i}' for i in range(len(value)))
            conditions.append(f"{key} IN ({placeholders})")
            params.extend(value)
            param_num += len(value)
        else:
            conditions.append(f"{key} = ${param_num}")
            params.append(value)
            param_num += 1

    where_sql = ' AND '.join(conditions) if conditions else '1=1'
    return where_sql, params
