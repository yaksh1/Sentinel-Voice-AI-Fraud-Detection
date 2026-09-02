"""Neon connection pool for core-api.

One pool for the process, opened on startup and closed on shutdown. Every write
in the product except `fraud_alerts` goes through this service
(ARCHITECTURE §7), so this is the only place a connection is made.
"""

import os

import asyncpg

_pool: asyncpg.Pool | None = None


async def connect() -> None:
    """Open the pool. Called once, from the app lifespan."""
    global _pool
    # DATABASE_URL is Neon's *pooled* endpoint, which is PgBouncer in
    # transaction mode: a connection is handed back between statements, so
    # there is no session for a named prepared statement to live in. asyncpg
    # prepares by default, so the cache has to be off or the second query on a
    # recycled connection fails with "prepared statement does not exist".
    # Migrations use DATABASE_URL_UNPOOLED for the same reason, in reverse.
    _pool = await asyncpg.create_pool(
        os.environ["DATABASE_URL"],
        statement_cache_size=0,
        min_size=1,
        max_size=5,
    )


async def close() -> None:
    """Close the pool. Called once, from the app lifespan."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    """The open pool, or an error naming the actual problem."""
    if _pool is None:
        raise RuntimeError("database pool is not open; core-api lifespan did not run")
    return _pool
