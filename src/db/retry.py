"""Small retry wrapper for transient database failures (Supabase pooler
blips, brief network drops, a connection killed server-side).

Only retries connection-level errors — never a query that failed on its own
merits (constraint violation, bad SQL), which would just fail again. Callers
that are themselves retried by an upstream (the MANAVA Gateway re-delivers a
failed webhook) can keep `attempts` low and let the upstream handle the rest.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

import asyncpg

logger = logging.getLogger(__name__)

T = TypeVar("T")

_TRANSIENT: tuple[type[BaseException], ...] = (
    asyncpg.PostgresConnectionError,
    asyncpg.InterfaceError,
    ConnectionError,
    OSError,
    asyncio.TimeoutError,
)


async def with_db_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
) -> T:
    """Run `operation()` (usually a lambda that acquires a pool connection and
    does its work), retrying with exponential backoff on transient connection
    errors. Re-raises the last error if every attempt fails."""
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except _TRANSIENT as exc:
            if attempt == attempts:
                logger.error("DB operation failed after %s attempt(s): %s", attempts, exc)
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning("Transient DB error (attempt %s/%s), retrying in %.1fs: %s", attempt, attempts, delay, exc)
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")
