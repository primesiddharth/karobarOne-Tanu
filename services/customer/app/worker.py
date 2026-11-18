# worker/relay.py
import asyncio
from libs.platform_contracts.worker import (
    claim_batch as _claim_batch,
    mark_sent as _mark_sent,
    mark_failed as _mark_failed,
    run_outbox_worker,
)
from app.db import async_session_factory
from app.config import settings

SCHEMA = "customer"


async def claim_batch(session, batch_size: int, lease_seconds: int):
    return await _claim_batch(session, batch_size, lease_seconds, schema=SCHEMA)


async def mark_sent(session, row_id):
    return await _mark_sent(session, row_id, schema=SCHEMA)


async def mark_failed(session, row_id, attempts: int):
    return await _mark_failed(session, row_id, attempts, schema=SCHEMA)


async def relay_loop(poll_interval: float = 1.0) -> None:
    await run_outbox_worker(
        schema=SCHEMA,
        session_factory=async_session_factory,
        service_key=settings.MY_SERVICE_KEY,
        batch_size=settings.OUTBOX_BATCH_SIZE,
        lease_seconds=settings.OUTBOX_LEASE_SECONDS,
        poll_interval=poll_interval,
    )


if __name__ == "__main__":
    asyncio.run(relay_loop())
