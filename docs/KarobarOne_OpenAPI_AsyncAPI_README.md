# KarobarOne OpenAPI + AsyncAPI Machine-Readable Contracts V1.0

This package is the machine-readable implementation layer derived from **KarobarOne REST API & Kafka Event Contract Specification V1.0** and its higher-authority BRD/state-machine/database/architecture artifacts.

## Contents

- `openapi/karobarone-openapi-v1.yaml` — bundled OpenAPI 3.1 platform contract.
- `openapi/services/*.yaml` — 16 service-specific OpenAPI 3.1 contracts.
- `asyncapi/asyncapi-v1.yaml` — AsyncAPI 3.1.0 Kafka topic/message contract.
- `asyncapi/schemas/event-envelope.schema.json` — common immutable event envelope.
- `asyncapi/schemas/*.schema.json` — one JSON Schema per registered event type.
- `scripts/validate_contracts.py` — local structural/schema validation.
- `manifest.json` — package counts and SHA-256 inventory.

## Coverage

- REST operations: **129**
- Logical backend services: **16**
- Kafka topic families: **21**
- Registered event types: **141**
- Critical REST commands with field-level request/response schemas: **20**
- Events with explicit minimum payload contracts: **21**

## Contract status markers

The source specification intentionally defines exact fields only for the commercially/concurrency-sensitive commands and selected event payloads. This package does **not invent missing business fields**.

- `x-contract-status: critical-field-level` — request/response fields come from the detailed source contract.
- `x-contract-status: detailed-minimum-payload` — event payload required fields come from the source payload table.
- `x-contract-status: registry-only` — path/event name, actor/producer, idempotency, purpose and routing are authoritative, but exact field schema was not specified. These operations/events must be completed from the owning service's Pydantic/domain model and reviewed before production.

## Key enforcement rules

- Base API path is `/api/v1`.
- State changes use explicit command endpoints, never generic status mutation.
- Retry-sensitive commands require `Idempotency-Key`.
- `X-Request-Id` is accepted/generated; correlation IDs propagate across services/events.
- Provider webhooks are authenticated by provider-specific verification, raw-retained, deduplicated and replay-safe.
- Browser redirects never confirm payment.
- UPI is absent from KarobarOne checkout contracts.
- Events use an immutable versioned envelope, transactional outbox and idempotent consumer/inbox semantics.
- Kafka is not the authoritative timer for scheduled lifecycle rules.

## Version choices

- OpenAPI: **3.1.0**, matching the approved API contract baseline (`OpenAPI 3.1`).
- AsyncAPI: **3.1.0** as a technical/tooling choice. It does not change any KarobarOne business behavior. If a selected toolchain requires AsyncAPI 3.0.x, downgrade syntax only after compatibility validation.
- Event JSON Schemas: JSON Schema **2020-12**.

## Source registry gaps

`SOURCE_GAPS.json` records event names that appear in endpoint/detailed command `Emitted facts` but are absent from the authoritative Appendix B event registry. They are **not silently added** to AsyncAPI. Reconcile these through contract change control before producers publish them.

## Validation

Run:

```bash
python scripts/validate_contracts.py
```

The validator checks YAML parsing, duplicate/missing operation IDs, event schema syntax, AsyncAPI external schema references, event-type `const` alignment, and file existence. It is intentionally not a substitute for CI validation with your selected OpenAPI/AsyncAPI tooling.

## CI recommendation

The repository should fail CI when:

1. generated FastAPI OpenAPI differs incompatibly from the committed contract;
2. an existing `.v1` event schema is changed incompatibly;
3. an event registry entry has no JSON Schema;
4. duplicate `operationId` values appear;
5. a critical contract becomes less strict without approved change control.

## Source authority

Business behavior remains governed by KarobarOne BRD V2.1. State transition behavior is governed by the State Machine & Business Rules Specification V1.0. These machine-readable contracts implement those artifacts; they do not amend them.
