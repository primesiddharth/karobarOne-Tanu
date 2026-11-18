# ==============================================================================
# File: libs/platform_contracts/relay.py
# Purpose: Transactional outbox HTTP relay dispatcher (RULES.md §7.4)
# ==============================================================================
import os
import json
from pathlib import Path
from typing import Any
import httpx
import yaml
import structlog

logger = structlog.get_logger("platform_contracts.relay")

# Default service ports for local dev
DEFAULT_SERVICE_PORTS: dict[str, int] = {
    "iam": 8001,
    "tenant": 8002,
    "approval": 8003,
    "catalog": 8004,
    "domain": 8005,
    "customer": 8006,
    "subscription": 8007,
    "inventory": 8008,
}


def load_subscriptions_map() -> dict[str, list[str]]:
    """Loads subscriptions mapping from subscriptions.yaml or raises FileNotFoundError."""
    candidate_paths = [
        Path(__file__).resolve().parent.parent.parent / "contracts" / "events" / "subscriptions.yaml",
        Path("/app/contracts/events/subscriptions.yaml"),
        Path("contracts/events/subscriptions.yaml"),
    ]
    for p in candidate_paths:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict) and "subscriptions" in data:
                    return data["subscriptions"]

    raise FileNotFoundError(
        "subscriptions.yaml not found. The subscriptions file is required per RULES.md §7.4."
    )


_SUBSCRIPTIONS_CACHE: dict[str, list[str]] | None = None


def get_subscribers_for_event(event_type: str) -> list[str]:
    """Returns list of consumer service names subscribed to this event type."""
    global _SUBSCRIPTIONS_CACHE
    if _SUBSCRIPTIONS_CACHE is None:
        _SUBSCRIPTIONS_CACHE = load_subscriptions_map()

    subscribers = []
    for consumer, event_types in _SUBSCRIPTIONS_CACHE.items():
        if event_type in event_types:
            subscribers.append(consumer)
    return subscribers


def get_subscriber_base_url(consumer: str) -> str:
    """Resolves base URL for consumer service with env overrides falling back to local dev ports."""
    env_var = f"{consumer.upper()}_SERVICE_URL"
    if env_var in os.environ and os.environ[env_var]:
        return os.environ[env_var].rstrip("/")

    port = DEFAULT_SERVICE_PORTS.get(consumer, 8000)
    return f"http://localhost:{port}"


async def dispatch_event_to_subscribers(
    client: httpx.AsyncClient,
    event_data: dict[str, Any],
    service_key: str,
    timeout: float = 5.0,
) -> bool:
    """
    Dispatches an event dictionary from outbox to all registered subscribers.
    Returns True if delivery succeeded for all subscribers (or no subscribers exist),
    and False if any subscriber call failed or returned non-2xx.
    """
    event_type = event_data.get("event_type")
    if not event_type:
        return True

    subscribers = get_subscribers_for_event(event_type)
    if not subscribers:
        return True

    raw_payload = event_data.get("payload")
    if isinstance(raw_payload, dict):
        payload_dict = raw_payload
    elif isinstance(raw_payload, str) and raw_payload:
        try:
            payload_dict = json.loads(raw_payload)
        except Exception:
            payload_dict = {}
    else:
        payload_dict = {}

    payload_body = {
        "event_id": str(event_data.get("event_id", "")),
        "event_type": event_type,
        "payload": payload_dict,
        "correlation_id": str(event_data.get("correlation_id", "") or ""),
    }

    headers = {
        "X-Service-Key": service_key,
        "X-Correlation-Id": str(event_data.get("correlation_id", "") or ""),
        "Content-Type": "application/json",
    }

    all_delivered = True
    for sub in subscribers:
        base_url = get_subscriber_base_url(sub)
        url = f"{base_url}/internal/events"
        try:
            resp = await client.post(url, json=payload_body, headers=headers, timeout=timeout)
            if resp.is_success:
                logger.info(
                    "relay_event_delivered",
                    subscriber=sub,
                    event_type=event_type,
                    event_id=payload_body["event_id"],
                    status=resp.status_code,
                )
            else:
                logger.warning(
                    "relay_event_delivery_rejected",
                    subscriber=sub,
                    url=url,
                    event_type=event_type,
                    status=resp.status_code,
                    body=resp.text[:200],
                )
                all_delivered = False
        except Exception as exc:
            logger.warning(
                "relay_event_delivery_error",
                subscriber=sub,
                url=url,
                event_type=event_type,
                error=str(exc),
            )
            all_delivered = False

    return all_delivered
