# ==============================================================================
# File: microservice/tools/tests/test_subscriptions.py
# Purpose: Validate subscriptions.yaml against canonical Appendix B Event Registry
# ==============================================================================
import os
import yaml
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SUBSCRIPTIONS_FILE = os.path.join(ROOT_DIR, "contracts", "events", "subscriptions.yaml")
SCHEMAS_DIR = os.path.join(ROOT_DIR, "contracts", "events", "schemas")
ASYNCAPI_FILE = os.path.join(ROOT_DIR, "contracts", "events", "asyncapi-v1.yaml")
CONTRACT_SPEC = os.path.join(ROOT_DIR, "docs", "specs", "KarobarOne_REST_API_Kafka_Event_Contract_Specification_V1.0.md")


def load_canonical_event_registry() -> set[str]:
    """Extracts all registered event_type names from Contract Appendix B."""
    if not os.path.exists(CONTRACT_SPEC):
        return set()
    with open(CONTRACT_SPEC, "r", encoding="utf-8") as f:
        text = f.read()
    idx_b = text.find("# Appendix B")
    idx_c = text.find("# Appendix C")
    lines = text[idx_b:idx_c].splitlines()
    registry = set()
    for line in lines:
        if line.strip().startswith("|") and not line.strip().startswith("| Topic") and not line.strip().startswith("| ---"):
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) >= 3:
                registry.add(parts[2])
    return registry


def test_subscriptions_file_and_asyncapi_exist():
    """Asserts that both subscriptions.yaml and asyncapi-v1.yaml are present."""
    assert os.path.exists(SUBSCRIPTIONS_FILE), "subscriptions.yaml must exist"
    assert os.path.exists(ASYNCAPI_FILE), "asyncapi-v1.yaml must exist"


def test_every_subscribed_event_matches_registry_and_schema():
    """Validates that subscribed events exist in Appendix B and have a .json schema."""
    with open(SUBSCRIPTIONS_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    subscriptions = data.get("subscriptions", {})
    assert len(subscriptions) > 0, "subscriptions.yaml must define at least one consumer"

    registry = load_canonical_event_registry()
    assert len(registry) > 0, "Appendix B Event Registry must be parsed from specification"

    all_subscribed_events = set()
    for consumer, events in subscriptions.items():
        assert isinstance(events, list), f"Consumer {consumer} must list subscribed event types"
        for ev in events:
            all_subscribed_events.add(ev)

    for ev in all_subscribed_events:
        # Check against Appendix B Event Registry
        assert ev in registry, f"Subscribed event '{ev}' is not in Contract Appendix B Event Registry"
        # Check against schemas/<event_type>.json per Contract §17.1
        schema_file = os.path.join(SCHEMAS_DIR, f"{ev}.json")
        assert os.path.exists(schema_file), f"Subscribed event '{ev}' lacks {schema_file}"
