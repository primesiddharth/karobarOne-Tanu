# ==============================================================================
# File: libs/platform_contracts/worker.py
# Purpose: Reusable transactional outbox worker engine (RULES.md §7.4 & §15)
# ==============================================================================
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any
import httpx
import structlog
from sqlalchemy import text
from .relay import dispatch_event_to_subscribers

logger = structlog.get_logger("platform_contracts.worker")


async def claim_batch(session: Any, batch_size: int, lease_seconds: int, schema: str) -> Any:
    """Claims a batch of outbox rows by leasing them in a fast transaction using FOR UPDATE SKIP LOCKED."""
    now = datetime.now(timezone.utc)
    lease_until = now + timedelta(seconds=lease_seconds)

    query = text(
        f"UPDATE {schema}.outbox_events "
        f"SET locked_until = :lease, attempts = attempts + 1 "
        f"WHERE id IN ("
        f"    SELECT id FROM {schema}.outbox_events "
        f"    WHERE published_at IS NULL "
        f"      AND dead = FALSE "
        f"      AND (next_attempt_at IS NULL OR next_attempt_at <= :now) "
        f"      AND (locked_until IS NULL OR locked_until < :now) "
        f"    ORDER BY created_at ASC "
        f"    FOR UPDATE SKIP LOCKED "
        f"    LIMIT :batch "
        f") "
        f"RETURNING id, event_id, event_type, payload, correlation_id, causation_id, attempts"
    )
    result = await session.execute(query, {"lease": lease_until, "now": now, "batch": batch_size})
    return result.mappings().all()


async def mark_sent(session: Any, row_id: Any, schema: str) -> None:
    """Marks an outbox row as delivered."""
    now = datetime.now(timezone.utc)
    await session.execute(
        text(f"UPDATE {schema}.outbox_events SET published_at = :now, locked_until = NULL WHERE id = :id"),
        {"now": now, "id": row_id}
    )


async def mark_failed(session: Any, row_id: Any, attempts: int, schema: str) -> None:
    """Applies exponential backoff or marks row dead after 5 attempts."""
    now = datetime.now(timezone.utc)
    if attempts >= 5:
        await session.execute(
            text(f"UPDATE {schema}.outbox_events SET dead = TRUE, locked_until = NULL WHERE id = :id"),
            {"id": row_id}
        )
    else:
        backoff_sec = 2 ** attempts
        next_at = now + timedelta(seconds=backoff_sec)
        await session.execute(
            text(f"UPDATE {schema}.outbox_events SET next_attempt_at = :next, locked_until = NULL WHERE id = :id"),
            {"next": next_at, "id": row_id}
        )


async def run_outbox_worker(
    schema: str,
    session_factory: Any,
    service_key: str,
    batch_size: int = 50,
    lease_seconds: int = 60,
    poll_interval: float = 1.0,
) -> None:
    """Continuous transactional outbox polling loop per RULES §7.4."""
    worker_log = structlog.get_logger(f"{schema}.worker")
    worker_log.info("outbox_relay_started", service=schema)
    while True:
        try:
            async with session_factory() as session:
                async with session.begin():
                    rows = await claim_batch(
                        session,
                        batch_size=batch_size,
                        lease_seconds=lease_seconds,
                        schema=schema,
                    )

            if rows:
                worker_log.info("outbox_batch_claimed", count=len(rows))
                async with httpx.AsyncClient(timeout=5.0) as http_client:
                    for row in rows:
                        delivered = await dispatch_event_to_subscribers(
                            client=http_client,
                            event_data=dict(row),
                            service_key=service_key,
                        )
                        async with session_factory() as session:
                            async with session.begin():
                                if delivered:
                                    await mark_sent(session, row["id"], schema=schema)
                                else:
                                    await mark_failed(session, row["id"], row["attempts"], schema=schema)

            await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            worker_log.info("outbox_relay_stopping")
            break
        except Exception as e:
            worker_log.error("outbox_relay_error", error=str(e))
            await asyncio.sleep(poll_interval)
