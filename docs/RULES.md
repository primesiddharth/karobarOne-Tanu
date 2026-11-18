# RULES.md — Binding engineering rules

Derived from: BTDD, State Machine & Business Rules, API/Event Contract, Repository Foundation, Infrastructure, Security Threat Model,
Test & Acceptance, External Integration, Backlog. These rules are what the agent enforces on itself.

---
## 1. Precedence and known document conflicts

Hierarchy: **BRD > State Machine > DB Schema spec > API/Event Contract > BTDD > Foundation / Infra / Security / Test / Integration.**
The BRD and the PostgreSQL Schema spec are referenced everywhere but may not be in `docs/specs/`. If missing, say so in `OPEN_QUESTIONS.md` (OQ-001) and work from the rest.

| # | Conflict | Ruling |
|---|---|---|
| C1 | Event names differ: BTDD says `guardian.consent-accepted`, `subscription.free-converted`, `domain.custom-purchased`, `domain.ready`, `tenant.created`, `customer.created`, `approval.version-approved`… | **Use the API/Event Contract names** (`guardian.consent.accepted.v1`, `subscription.converted-to-free.v1`, `domain.purchased.v1`, `content.approved.v1`…). Every event type ends in `.vN`. |
| C2 | Health paths: BTDD/earlier notes `/healthz`; Foundation `/health/live`, `/health/ready` | **`/health/live` and `/health/ready`.** Render health check → `/health/ready`. |
| C3 | Folder names `services/<x>-service` (BTDD) vs `services/<x>` (Foundation) | **`services/<x>`**: `iam tenant subscription approval catalog domain customer inventory gateway`. |
| C4 | Table names differ between BTDD §9 and State Machine Appendix A (e.g. `guardians` vs `guardian_profiles`, `reservations` vs `stock_reservations`) | Use the **DB Schema spec** if present. Otherwise use **State Machine Appendix A** names; for tables only BTDD lists, use BTDD names. Log in OQ. |
| C5 | Guardian endpoint: BTDD `POST /tenants/{id}/guardian`; Contract `POST /tenants/{tenant_id}/guardians` | Contract. |
| C6 | Customer claim: BTDD `POST /customers/{id}/claim`; Contract `…/claim/challenge` + `…/claim/verify` | Contract. |
| C7 | Content submit: BTDD has CAT publish `catalog.version-submitted` and APR consume it; Contract has `content.submitted.v1` on `approval.lifecycle` produced by APR | Contract. **CAT-006 calls APR-001 synchronously (internal call); APR emits `content.submitted.v1`.** |
| C8 | `SOURCE_GAPS.json`: 16 event types appear in endpoint "emits" but not in the Event Registry | **Do not publish them.** Endpoints still work; skip the emit and keep a `# TODO(OQ-xxx)` line. List: `identity.otp.challenge-created`, `identity.session.refreshed`, `gstin.verification-requested`, `store.staff-revoked`, `catalog.page-version-created`, `catalog.media-upload-intent-created`, `domain.dns-verification-requested`, `domain.route.activated`, `subscription.upgrade-discount-decided`, plus later-service ones (cart.*, return.*, ai.*, notification.template-created). |
| C9 | Directory layout: Foundation prescribes `api/application/domain/infrastructure` DDD folders | **Use the lean layout in §3** (human instruction: simple code). Keep the one rule that matters: `domain.py` never imports FastAPI/SQLAlchemy/httpx. |
| C10 | Foundation: AC tests in root `/tests/acceptance` | During the first 8, single-service ACs live in `services/<x>/tests/acceptance/`; cross-service flows in `microservice/tests/e2e/`. `tools/check_ac_coverage.py` verifies every AC assigned to a service has a `test_ac_NNN_*` test. |
| C11 | Earlier plan put SUB 3rd | **Use backlog order** (Free Presence slice first): IAM → TEN → APR → CAT → DOM(free) → CUS → SUB → DOM(paid) → INV. |
| C12 | Kafka is the specified bus but is not available on Render/Neon | Interim **HTTP outbox relay** (§7.4) behind a tiny seam so Kafka can replace it without touching business code. Needs human approval (OQ-002). |

---
## 2. Stack

**Allowed from day one:** Python 3.12; FastAPI; uvicorn; pydantic v2; pydantic-settings; SQLAlchemy 2 (async) + asyncpg; Alembic;
PyJWT[crypto]; argon2-cffi; cryptography; httpx; tenacity (retry for idempotent calls only); structlog; pyyaml; pytest; pytest-asyncio;
testcontainers (Postgres); ruff; mypy; uv (lockfile).
**Add only when the service that needs it is being built** (one-line justification + human approval): `redis` (gateway rate limit), `boto3` (CAT media), `opentelemetry-*` and `prometheus-client` (Phase 12), `bcrypt` (IAM only, only if the monolith has bcrypt hashes → verify-then-rehash to Argon2id).
**Forbidden:** streamlit, pandas, numpy, altair, pydeck, langchain*, langgraph, openai, google-genai, google-api/auth, dropbox, tavily, tiktoken, huggingface, passlib, python-jose, psycopg2, aiosqlite/sqlite (tests use real Postgres), razorpay (PAY), reportlab (FIN), any ORM except SQLAlchemy.
Each service has its own `pyproject.toml` + `uv.lock`. No root requirements file.

---
## 3. Layout

```
microservice/
  docs/  (specs/, RULES.md, SERVICES.md, ROADMAP.md, PROMPTS.md, DEPLOY.md, OPEN_QUESTIONS.md, STUBS.md, adr/)
  libs/platform_contracts/   # events.py (envelope), errors.py (envelope + registered codes), tokens.py (JWT verify, Principal), logging.py (redaction), relay.py (event dispatch), worker.py (outbox polling runner), metrics.py
  contracts/openapi/ contracts/events/schemas/ contracts/events/subscriptions.yaml
  services/<name>/
    app/main.py        # create app, include routers, /health/live, /health/ready, error handler, request-id middleware
    app/config.py      # pydantic-settings
    app/db.py          # engine, session, set_rls_context
    app/models.py      # SQLAlchemy tables
    app/schemas.py     # pydantic request/response (extra="forbid" on writes)
    app/domain.py      # PURE rules: transition tables, calculations, guards (no FastAPI/SQLAlchemy/httpx imports)
    app/commands.py    # one function per named command; each = one transaction
    app/routes.py      # thin: parse → authorize → call command → return
    app/events.py      # add_event(), inbox handling, handlers for consumed events
    app/clients.py     # httpx calls to other services + STUBS (each marked)
    app/worker.py      # `python -m app.worker`: outbox relay + this service's scheduled jobs
    alembic/  alembic.ini  tests/{unit,integration,acceptance}  Dockerfile  pyproject.toml  README.md
  deploy/compose/  deploy/k8s/  render.yaml  tools/  tests/e2e/
```
Split `routes.py`/`commands.py` into 2–4 files per concern only when a file passes ~300 lines. No other folders.

---
## 4. Code style (examples)

Good — a command is one readable function:
```python
async def cancel_subscription(s: AsyncSession, who: Principal, sub_id: UUID, expected_version: int, now: datetime):
    sub = await get_subscription(s, sub_id, who)          # scoped query, 404 if not in scope
    check_version(sub, expected_version)                  # STALE_VERSION
    domain.assert_can_cancel(sub, now)                    # BR-182: strictly before Period 3 → else CANCELLATION_WINDOW_CLOSED
    sub.cancel_notice_at = now
    sub.version += 1
    add_history(s, sub, "cancel", who)
    add_event(s, "subscription.cancellation-notice-recorded.v1", sub, {"subscription_id": str(sub.id), "notice_recorded_at": now.isoformat()})
    return sub
```
Bad — do not write: `BaseRepository[T]`, `AbstractUnitOfWork`, `CommandHandlerFactory`, `@register_command`, `ServiceLocator`, 5-layer folders, `try: ... except Exception: pass`, helper used once, config flags for things nobody asked for.

Transition tables are plain dicts in `domain.py`:
```python
ALLOWED = {"PENDING": {"APPROVED", "REJECTED", "EMERGENCY_TAKEDOWN"}, "REJECTED": {"DRAFT"}, ...}
def assert_transition(current, target):
    if target not in ALLOWED.get(current, set()):
        raise ApiError("INVALID_STATE_TRANSITION", {"current_state": current, "requested": target})
```

---
## 5. Database rules

- One cluster (Neon), one schema per service, one **runtime role** (`<schema>_svc`: DML on own schema only) and one **migration role** (`<schema>_migrator`: DDL on own schema). Runtime role can never `ALTER`.
- `tools/db/bootstrap.sql` creates schemas, roles, revokes cross-schema access. Alembic version table lives **inside** the service's schema.
- No FK across schemas. Foreign service IDs are `uuid` columns validated at command time.
- IDs: `uuid` default `gen_random_uuid()` (uuid4). Every tenant-owned table has `tenant_id`; every store-owned table has `store_id`; both indexed.
- **Money**: integer paise (`bigint`) + `currency_code text default 'INR'`. Compute with `Decimal`. API shows `"1000.00"` strings. Store unrounded inputs + rounding policy name + final amount for every calculation (BTDD §13.2). Rounding/GST treatment = OQ until tax review.
- **Time**: `timestamptz` UTC. Inject a `now` / clock parameter into commands and workers so tests never sleep.
- **Version column** (`version int`) on aggregates with conflict-prone commands; `expected_version` mismatch → `STALE_VERSION`.
- **History**: every state change writes a history row (old_state, new_state, command, actor/source, at, correlation_id, reason). History/audit/ledger tables are insert-only; the runtime role has no UPDATE/DELETE on them.
- **RLS** (defense in depth) on sensitive tenant/store tables: `ENABLE` + `FORCE ROW LEVEL SECURITY`, policy `USING`/`WITH CHECK` on `current_setting('app.tenant_id', true)::uuid` (and `app.store_id`). Set with `SET LOCAL` inside the transaction from the **authenticated** principal only. Test with the tenant predicate deliberately omitted (FND-TST-008/009). Platform staff use an explicit admin path, never `tenant_id IS NULL`.
- **Standard per-service tables** (add only what the service needs): `outbox_events`, `processed_events` (inbox), `idempotency_keys`, `scheduled_jobs` (only TEN, SUB, INV, DOM).
- **Sensitive IDs** (PAN, GSTIN, guardian ID): encrypted value (AES-GCM / Fernet via `cryptography`, key from env) + **keyed fingerprint** (HMAC-SHA256 with a *separate* key; plain hashes of PAN are brute-forceable) + masked display. Unique constraint on the fingerprint.
- **Migrations**: Alembic per service, expand → backfill → switch → contract. Test fresh DB and previous-revision upgrade (FND-TST-023/024).
- **Neon specifics**: app uses the **pooled** URL (`-pooler`, PgBouncer transaction mode): set `statement_cache_size=0`; `SET LOCAL` and `FOR UPDATE SKIP LOCKED` inside a transaction are fine; never use session-level advisory locks or `LISTEN/NOTIFY`. Alembic uses the **direct** URL (`MIGRATION_DATABASE_URL`). asyncpg wants `ssl=require` (not `sslmode=`) — normalize in `config.py`. Use `pool_pre_ping=True` (autosuspend). Verify the exact SQLAlchemy/asyncpg prepared-statement settings against current docs when wiring.
- **Legacy ids**: a nullable `legacy_id` column on migrated tables is allowed (ADR required) and dropped after cutover.

---
## 6. API rules

- Base `/api/v1`. JSON UTF-8. Paths, methods, actors and operationIds **exactly** as the contract registry (IDs like `TEN-001`).
- State transitions are `POST` action endpoints. `PATCH` exists only for `CAT-004` (operational fields) and `CUS-005` (profile fields) and must not accept a status.
- Idempotent commands read `Idempotency-Key`; store `(scope, key, request_hash, response)`; same key + same hash → replay stored response; same key + different hash → `409 IDEMPOTENCY_CONFLICT`.
- `X-Request-Id` accepted (valid UUID) or generated, returned on every response; `correlation_id` = request id unless provided; propagated in outgoing calls and events.
- Errors: `{"error":{"code","message","details","request_id"}}`. Status mapping per contract §3.2. Codes only from the registry (Contract Appendix C). Need a new code → OQ.
- Writes use pydantic models with `extra="forbid"`. Responses never include PAN/GSTIN/guardian ID in full (mask: `ABCDE*****`).
- Out-of-scope resource ids return `404` (UUID possession is not authority).
- Pagination: opaque cursor, `limit` default 50, max 200, allow-listed sort fields.
- Public endpoints (storefront snapshot) return approved/LIVE data only.
- OpenAPI: FastAPI output must match `contracts/openapi/services/<x>.yaml`. **Code conforms to contracts; never edit a contract to fit code.** Operations marked `registry-only` have no field schema in the spec: design the fields minimally from the service card, log the choice in OQ, and flag for review.

---
## 7. Events

1. **Envelope** (`libs/platform_contracts/events.py`): `event_id, event_type, event_version, aggregate_type, aggregate_id, tenant_id, store_id, occurred_at, correlation_id, causation_id, producer, payload`.
2. `add_event(session, event_type, aggregate, payload)` inserts into `outbox_events` in the **same transaction** as the state change. It also stores the topic (from the contract registry).
3. Payloads = the minimum fields from Contract §12 / `contracts/events/schemas/*.schema.json`. No PAN/GSTIN/OTP/secret/unneeded PII.
4. **Interim transport (HTTP relay)** — until a Kafka-compatible service is chosen:
   - `app/worker.py` loop: `SELECT … FROM outbox_events WHERE published_at IS NULL AND next_attempt_at <= now() ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT n`.
   - For each event, look up subscribers in `contracts/events/subscriptions.yaml` and `POST {SUBSCRIBER_URL}/internal/events` with the service API key. All subscribers 2xx → set `published_at`. Failure → `attempts+1`, exponential `next_attempt_at`; after N attempts mark `dead` (DLQ) and log.
   - Subscriber `POST /internal/events` (service key only): in one transaction insert `(consumer, event_id)` into `processed_events` (unique) then run the handler; duplicate → 200 and do nothing; unknown `event_type` → 200 and ignore.
   - Business code only calls `add_event`; swapping to Kafka later changes only `worker.py` and `/internal/events`.
5. Consumers are idempotent (inbox) **and** financial effects use unique business keys (none in first 8).
6. Handlers ignore unknown extra payload fields; they never regress state on stale/out-of-order events (compare version/effective time).
7. Kafka/transport is **never a timer**. Time rules use `scheduled_jobs` (below).
8. Schemas live in `contracts/events/schemas/<event_type>.schema.json`; a producer test validates every emitted payload against its schema.

---
## 8. AuthN / AuthZ / security

- **JWT** issued by IAM only. Claims: `sub, session_id, roles, tenant_ids, store_ids, iat, exp` (+ `iss`, `aud`, `kid`). Asymmetric signing (IAM holds the private key; others verify with the public key from env) — OQ-003 to confirm. Access TTL short and config-driven; values are placeholders pending security review.
- Passwords Argon2id. Refresh tokens: random, stored **hashed**, rotated on use; reuse of a rotated token revokes the session. OTP: stored hashed with TTL, attempt cap, rate limit, single-use. Login/OTP responses do not reveal whether an account exists.
- **authorize(command)** = authenticated ∧ role allows ∧ principal assigned to tenant/store ∧ resource in scope ∧ entitlement allows ∧ lifecycle allows ∧ no blocking restriction. JWT roles are hints; high-value commands re-check current assignment (SDD-004). Restrictions (CMP) don't exist yet → stub returning "no restriction" (STUBS.md).
- Roles: `PUBLIC, CUSTOMER, STORE_OWNER, STORE_STAFF, GUARDIAN, PLATFORM_STAFF, GST_STAFF, PLATFORM_OWNER, SERVICE`. GUARDIAN never implies store management. Admin ≠ `tenant_id IS NULL`. Production platform-admin requires MFA (SDD-001) — design the hook now.
- **Service-to-service auth on Render** (no workload identity): per-service API key in `X-API-Key`, receiver validates against env hashes and a per-route caller allowlist (docs/SECURITY_LAYER.md). Needs approval (OQ-004/026).
- **API key / service-token layers: see `docs/SECURITY_LAYER.md` (gateway `X-API-Key`, internal service API keys). A key never grants tenant scope.**
- Never trust `X-Tenant-Id`/`X-Store-Id`. The gateway does **not** convert JWTs to trusted headers; each service verifies the JWT itself.
- Logs: structlog JSON with `service, env, request_id, correlation_id, tenant_id/store_id (UUIDs only), error_code`. A test (FND-TST-028) feeds PAN/GSTIN/OTP-like values and asserts they never appear in logs.
- CORS: only approved origins. Interactive docs (`/docs`) disabled in prod for internal services.

---
## 9. State machines
Every controlled aggregate has: a transition dict in `domain.py`, a command per transition, a history row, an outbox event, tests for each valid transition **and** at least one invalid-from-state. Invalid → `409 INVALID_STATE_TRANSITION`. A stale client cannot force a state (TX-10). Two concurrent commands cannot both advance the same state (row lock or version check).

## 10. Scheduler
`scheduled_jobs(id, job_type, aggregate_id, business_key unique, due_at, status, attempts, last_error)` in the service's schema. Worker claims with `FOR UPDATE SKIP LOCKED`; the transition itself is guarded by current state so a duplicate run is a no-op. Missed runs catch up deterministically from absolute timestamps (Day 8/23 derived from due date, not from "now minus x"). Index `(status, due_at)`. Multiple replicas must be safe (FND-TST-020).

## 11. Testing rules
- Real PostgreSQL via testcontainers. No SQLite, no mocked-repository proof for concurrency.
- Layers: unit (domain.py), integration (API + DB), acceptance (`test_ac_NNN_<slug>`), security (IDOR, RLS), concurrency, migration.
- **Every service**: FND-TST-001/002 idempotency, 003 outbox atomicity, 004 duplicate event, 008/009 RLS, 010 IDOR, 011 role+entitlement, 012 no generic status mutation, 013 STALE_VERSION, 023/024 migrations, 025–027 contract/schema, 028 log redaction, 029 correlation propagation, 033 import boundary (no service imports another), 034 money type, 035 audit completeness. (Apply those relevant to the service.)
- Time tests use injected `now`; boundaries just-before / at / just-after.
- `tools/check_ac_coverage.py` fails if an AC assigned in `SERVICES.md` has no matching test.
- Never weaken a test to pass. Never add `sleep` for time rules.

## 12. Observability
Phase 1: JSON logs, request/correlation ids, health endpoints. Phase 12: OpenTelemetry traces, Prometheus `/metrics` (internal only; route-template labels, never tenant/store/customer ids as labels), outbox lag + scheduler lateness metrics.

## 13. Stubs
Every stub: lives in `app/clients.py` (or `app/stubs.py`), has a `# STUB(<service>, OQ-xxx)` comment, is listed in `docs/STUBS.md` with "replaced when …". Allowed stubs now: PAN/GST verifier (mock adapter), registrar/DNS (mock), email/SMS sender (log + Mailpit locally), object storage (MinIO locally), restrictions (CMP → none), `finance.platform-payment-recorded` (dev-only endpoint in SUB), entitlements for CAT before SUB exists (static Free capabilities). Stub endpoints that mimic missing events must be disabled in production (`ENVIRONMENT=prod`).

## 14. Porting from the monolith
Clean-room: the monolith is a source of **business behaviour and data shape**, not code to copy. Behaviour differences → spec wins, log in OQ. Per service: `tools/db/migrate_<svc>.py` — idempotent, re-runnable, prints source vs target row counts, never deletes source, writes only the service's schema, maps legacy ids. Passwords: follow IAM card. Unmapped features → `docs/unmapped-features.md`, not ported.

## 15. Containers / deployment (pointers; details in DEPLOY.md)
One image per service, two commands (api: uvicorn; worker: `python -m app.worker`). Multi-stage, locked deps, non-root, no secrets in layers, `HEALTHCHECK`. Migrations are a separate pre-deploy step, never run at app start. Tag images with git SHA; promote the same digest.

## 16. Definition of Done (per service)
- [ ] Endpoints/events exactly as `SERVICES.md` card and contract; OpenAPI matches committed contract
- [ ] Every critical rule in the card has a test; assigned ACs have `test_ac_NNN_*`
- [ ] Transition tables + invalid-transition tests; outbox/inbox/idempotency in place
- [ ] Tenant isolation: IDOR + RLS tests green
- [ ] Alembic fresh + upgrade tests green; bootstrap roles work
- [ ] Logs redacted; error envelope only; no cross-schema access; no cross-service import
- [ ] Docker image builds, non-root, `/health/ready` passes against compose Postgres
- [ ] Data migration script runs twice with matching counts
- [ ] STUBS.md and OPEN_QUESTIONS.md updated; report block delivered
