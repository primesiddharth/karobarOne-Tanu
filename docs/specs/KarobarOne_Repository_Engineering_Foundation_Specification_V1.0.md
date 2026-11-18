**KAROBARONE**

**Repository & Engineering Foundation Specification**

Implementation baseline for backend repository, service scaffolding, local development, CI/CD, observability, security and deployment foundation

**Specification Version 1.0  •  14 September 2026**

Derived from: BRD V2.1 • Backend Technical Design V1.0 • PostgreSQL Schema Specification V1.0 • State Machine & Business Rules V1.0 • REST API & Kafka Event Contract V1.0

# Document Control

| Field | Value |
| --- | --- |
| Document Version | 1.0 — Initial Repository & Engineering Foundation Baseline |
| Status | Implementation Specification |
| Effective Date | 14 September 2026 |
| Product | KarobarOne |
| Business Authority | KarobarOne BRD V2.1 — Final Consolidated |
| Technical Inputs | Backend Technical Design V1.0; PostgreSQL Schema Specification V1.0; State Machine & Business Rules V1.0; REST API & Kafka Event Contract V1.0 |
| Target Runtime | Python 3.12+ / FastAPI / PostgreSQL / Kafka / Redis / Docker / Kubernetes |
| Primary Users | Backend Engineering, DevOps/SRE, QA, Security, Database, Architecture and Technical Leads |
| Purpose | Define the codebase, service template, tooling, local runtime, CI/CD and operational foundation that every KarobarOne backend service must follow. |

**Authority — **The BRD remains authoritative for business behavior. State-machine, database and API/event specifications define implementation contracts. This document governs repository/runtime engineering conventions and must not introduce new commercial or legal rules.

**Foundation rule — **No developer should create a service-specific project structure, logging format, migration pattern, event envelope, error model or CI process independently. Those concerns are standardized here so domain teams focus on business logic.

# Document Contents

1. Purpose, Scope and Normative Hierarchy

2. Foundation Design Principles

3. Repository Strategy and Ownership

4. Canonical Monorepo Layout

5. Standard FastAPI Service Template

6. Python Packaging and Dependency Management

7. Shared Libraries and Anti-Coupling Rules

8. API and Event Contract Artifacts

9. Configuration and Environment Management

10. Database, SQLAlchemy and Alembic Foundation

11. Kafka, Outbox, Inbox and Consumer Foundation

12. Scheduler and Worker Foundation

13. Authentication, Authorization and Security Foundation

14. Error Handling and Idempotency

15. Logging, Metrics, Tracing and Audit

16. Local Development Environment

17. Docker Image Standard

18. Kubernetes Deployment Standard

19. CI/CD Pipeline and Quality Gates

20. Testing Foundation

21. Code Quality and Engineering Standards

22. Secrets, Supply Chain and Security Scanning

23. Branching, Pull Requests, Releases and Versioning

24. Operational Readiness and Runbooks

25. M0 Engineering Foundation Delivery Plan

26. Service Onboarding Checklist and Definition of Done

27. Decisions and Extension Points

Appendix A — Full Repository Tree

Appendix B — Standard Service pyproject.toml

Appendix C — Standard Dockerfile

Appendix D — FastAPI Bootstrap Skeleton

Appendix E — Environment Variable Catalog

Appendix F — CI Pipeline Reference

Appendix G — Engineering Foundation Checklist

# 1. Purpose, Scope and Normative Hierarchy

## 1.1 Purpose

This specification turns the approved technical architecture and network contracts into a reproducible engineering foundation. Its goal is that a new backend engineer can clone the repository, start the platform locally, create or modify a service using the same conventions as every other service, run migrations and tests, publish/consume events safely, and open a pull request that is validated by automated gates.

## 1.2 In Scope

- Monorepo structure and ownership boundaries for all 16 logical services.
- Standard FastAPI service/module layout and dependency direction.
- Python packaging, lockfile and reproducible dependency policy.
- OpenAPI, AsyncAPI and event-schema storage/compatibility workflow.
- PostgreSQL schema/migration conventions, transaction boundaries and RLS context.
- Kafka producer/consumer, outbox/inbox, idempotency, retry and DLQ implementation foundation.
- Durable scheduler/worker baseline for time-based business rules.
- Authentication/authorization integration, common error envelope and request context.
- Logging, metrics, tracing, health checks and audit propagation.
- Local Docker-based developer environment, Docker image and Kubernetes deployment standards.
- CI/CD stages, contract gates, tests, security scanning, migration checks and image publishing.
- Branching, review, release, secrets, runbooks and Definition of Done.

## 1.3 Out of Scope

- Redefining BRD business rules, state transitions, pricing, commission or entitlement behavior.
- Frontend/Next.js repository conventions except the interface boundary with committed OpenAPI contracts.
- Final production cloud vendor, Kafka hosting model, DNS/registrar, email/SMS or verification-provider selection.
- Implementation of the first business vertical slice itself; this document creates the foundation on which those features are built.

## 1.4 Normative Hierarchy

| Priority | Artifact | Authority |
| --- | --- | --- |
| 1 | KarobarOne BRD V2.1 | Business/commercial/legal scope and acceptance criteria. |
| 2 | State Machine & Business Rules V1.0 | Deterministic lifecycle rules and transition guards. |
| 3 | PostgreSQL Schema Specification V1.0 | Persistence structures and database invariants. |
| 4 | REST API & Kafka Event Contract V1.0 | Synchronous/asynchronous interface contracts. |
| 5 | Backend Technical Design V1.0 | Service ownership and architecture patterns. |
| 6 | This Repository & Engineering Foundation | Codebase, tooling, deployment and quality conventions. |
| 7 | Generated code/configuration | Must conform to all higher-authority artifacts. |

# 2. Foundation Design Principles

| ID | Principle | Engineering consequence |
| --- | --- | --- |
| FND-001 | Business boundaries survive deployment consolidation | Logical services may share a monorepo and, during early phases, a deployable process, but service modules, schemas, migrations, contracts and ownership remain separate. |
| FND-002 | Service owns its writes | Only the owning service writes its PostgreSQL schema. Shared repository access does not permit shared data ownership. |
| FND-003 | Contracts before coupling | Cross-service calls use committed HTTP/event contracts. Importing another service’s domain models/repositories is prohibited. |
| FND-004 | Local ACID + outbox | No distributed DB transaction. A service commits state, audit/history and outbox atomically, then publishes asynchronously. |
| FND-005 | PostgreSQL is authoritative | Redis, Kafka and analytics projections may accelerate or distribute state but never become the financial/business source of truth. |
| FND-006 | Fail closed for commerce | Where entitlement/restriction cannot be verified safely, creation of new commerce is denied while existing obligations remain accessible as required. |
| FND-007 | Reproducible builds | Dependency lock, container build, migrations and contract artifacts are deterministic and CI-verifiable. |
| FND-008 | Observability is mandatory | Every service emits structured logs, metrics and traces and propagates request/correlation/event IDs. |
| FND-009 | Security by default | Secrets are externalized, sensitive identifiers never enter ordinary logs, tenant/store scope is explicit, and runtime containers are least-privilege. |
| FND-010 | Test the acceptance baseline | AC-001..AC-090 must remain mapped to automated acceptance tests; foundation tooling must make those tests easy to run in CI. |

# 3. Repository Strategy and Ownership

## 3.1 Monorepo Decision

V1 uses a backend monorepo. This reduces dependency/version drift, simplifies contract checks and allows one CI pipeline to validate changes that affect multiple services. The monorepo is an organizational boundary only; it must not become a shared-domain-code monolith.

| Concern | Rule |
| --- | --- |
| Repository | One canonical karobarone-backend repository. |
| Service ownership | CODEOWNERS assigns technical owners per service directory and contract area. |
| Schema ownership | One service-owned PostgreSQL schema and Alembic history per logical service. |
| Deployability | Every service directory can build an independent image even if selected services are co-deployed during early milestones. |
| Cross-service imports | Forbidden except platform-contracts/common infrastructure helpers explicitly listed in Section 7. |
| Contracts | Stored centrally under /contracts and validated against service-generated artifacts. |
| Infrastructure | Deployment manifests and environment overlays are stored under /deploy; application services do not embed cluster-specific configuration. |

## 3.2 Service Codes and Directories

| Directory | Logical service | DB schema |
| --- | --- | --- |
| iam | Identity & Access | iam |
| tenant | Tenant & Store | tenant |
| subscription | Subscription & Entitlement | subscription |
| domain | Domain & Publication | domain |
| catalog | Catalog & CMS | catalog |
| approval | Approval & Governance | approval |
| customer | Customer | customer |
| inventory | Inventory | inventory |
| commerce | Commerce | commerce |
| booking | Booking | booking |
| payment | Payment Integration | payment |
| fulfilment | Fulfilment | fulfilment |
| finance | Commission & Finance | finance |
| compliance | Compliance/GST/Risk | compliance |
| notification | Notification | notification |
| analytics | Analytics & AI | analytics |

# 4. Canonical Monorepo Layout

karobarone-backend/
├── services/
│   ├── iam/
│   ├── tenant/
│   ├── subscription/
│   ├── domain/
│   ├── catalog/
│   ├── approval/
│   ├── customer/
│   ├── inventory/
│   ├── commerce/
│   ├── booking/
│   ├── payment/
│   ├── fulfilment/
│   ├── finance/
│   ├── compliance/
│   ├── notification/
│   └── analytics/
├── libs/
│   ├── platform-contracts/
│   ├── platform-observability/
│   ├── platform-testing/
│   └── platform-db-testkit/
├── contracts/
│   ├── openapi/
│   ├── events/
│   │   ├── asyncapi-v1.yaml
│   │   └── schemas/
│   └── examples/
├── deploy/
│   ├── local/
│   ├── kubernetes/
│   │   ├── base/
│   │   └── overlays/{dev,staging,prod}/
│   └── monitoring/
├── tooling/
│   ├── scripts/
│   ├── contract-checks/
│   ├── migration-checks/
│   └── load-tests/
├── tests/
│   ├── acceptance/
│   ├── e2e/
│   └── contract-fixtures/
├── docs/
│   ├── adr/
│   ├── runbooks/
│   ├── diagrams/
│   └── onboarding/
├── .github/workflows/
├── .pre-commit-config.yaml
├── CODEOWNERS
├── pyproject.toml
├── uv.lock
├── Makefile
├── README.md
└── SECURITY.md

## 4.1 Root-Level Responsibilities

| Path | Responsibility |
| --- | --- |
| /services | Deployable/domain-owned application code and migrations. |
| /libs | Small infrastructure libraries only; no shared domain entities. |
| /contracts | Committed API/event contracts and examples. |
| /deploy | Docker Compose/local dependencies and Kubernetes manifests/overlays. |
| /tooling | Repository-wide developer and CI automation. |
| /tests/acceptance | Cross-service BRD acceptance tests with stable AC IDs. |
| /docs/adr | Architecture Decision Records for technical decisions. |
| /docs/runbooks | Operational recovery/reconciliation/deployment procedures. |

# 5. Standard FastAPI Service Template

services/commerce/
├── src/karobarone_commerce/
│   ├── api/
│   │   ├── dependencies.py
│   │   ├── errors.py
│   │   └── v1/
│   │       ├── router.py
│   │       └── orders.py
│   ├── application/
│   │   ├── commands/
│   │   ├── queries/
│   │   ├── handlers/
│   │   └── dto/
│   ├── domain/
│   │   ├── entities/
│   │   ├── value_objects/
│   │   ├── enums/
│   │   ├── policies/
│   │   ├── events/
│   │   ├── repositories.py
│   │   └── exceptions.py
│   ├── infrastructure/
│   │   ├── db/
│   │   │   ├── models/
│   │   │   ├── repositories/
│   │   │   ├── session.py
│   │   │   └── rls.py
│   │   ├── kafka/
│   │   │   ├── producer.py
│   │   │   ├── consumers.py
│   │   │   └── outbox.py
│   │   ├── http/
│   │   └── providers/
│   ├── workers/
│   ├── bootstrap.py
│   ├── settings.py
│   └── main.py
├── alembic/
│   ├── versions/
│   └── env.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   └── fixtures/
├── Dockerfile
├── pyproject.toml
├── alembic.ini
└── README.md

## 5.1 Dependency Direction

API / Workers
      ↓
Application (commands, queries, handlers)
      ↓
Domain (entities, policies, repository interfaces)
      ↑
Infrastructure (DB/Kafka/HTTP implementations)

Rule: domain never imports FastAPI, SQLAlchemy, Kafka client or provider SDK.

| Layer | May depend on | Must not depend on |
| --- | --- | --- |
| domain | Python stdlib; tiny value-object helpers | FastAPI, SQLAlchemy, Kafka, Redis, external provider SDKs, another service |
| application | domain; DTO/contracts | Concrete DB/Kafka/provider implementations |
| api | application; auth/context helpers | Direct SQLAlchemy repositories of another service |
| infrastructure | domain interfaces; platform infrastructure libraries | Another service’s domain package |
| workers | application + infrastructure adapters | Frontend/user-specific assumptions |

# 6. Python Packaging and Dependency Management

**Design Decision — **Use pyproject.toml-based packaging with a repository lockfile. The default foundation uses uv workspaces/locking because it is fast and reproducible; the architectural requirement is the lockfile and reproducible build, not the specific resolver.

| Category | Baseline |
| --- | --- |
| Python | 3.12+; exact minor version pinned in CI/container image for a release line. |
| Web/API | FastAPI + Pydantic v2. |
| Settings | pydantic-settings or equivalent typed environment configuration. |
| ORM | SQLAlchemy 2.x. |
| Migrations | Alembic per service-owned schema. |
| PostgreSQL driver | Async-capable supported driver behind SQLAlchemy; migration path may use synchronous driver if operationally simpler. |
| HTTP client | HTTPX or equivalent with explicit timeout/retry policy. |
| Tests | pytest; Testcontainers or equivalent for integration dependencies. |
| Lint/format | Ruff as default formatter/linter. |
| Type checking | mypy or equivalent strict type checker, enabled incrementally but mandatory on new modules. |
| Security | Dependency vulnerability scan and image scan in CI; versions pinned through lockfile. |

## 6.1 Dependency Rules

- Root lockfile is updated only through a controlled dependency-update PR.
- Runtime dependencies belong to the owning service or approved platform library; avoid adding a package at repository root when only one service needs it.
- Provider SDKs are isolated behind adapter interfaces so vendor changes do not leak into domain/application code.
- No editable install of another service package as a substitute for an API/event call.
- Build fails when dependency resolution differs from the committed lockfile.
- Major framework upgrades require an ADR and contract/integration regression run.

# 7. Shared Libraries and Anti-Coupling Rules

| Library | Allowed content | Explicitly prohibited |
| --- | --- | --- |
| platform-contracts | Event envelope; common error envelope; request/correlation ID types; pagination primitives; shared JSON-schema helpers. | Order/Product/Subscription/Booking entities, business policies, service repositories. |
| platform-observability | Logging bootstrap, trace/metric initialization, safe context propagation. | Business analytics definitions or service-specific alert rules. |
| platform-testing | Common fixtures, container helpers, event/assertion utilities. | Production domain logic. |
| platform-db-testkit | Test DB bootstrap, schema isolation helpers, RLS test context. | Shared production repositories or cross-schema write helpers. |

**Anti-pattern — **A “common-models” package containing Tenant, Product, Order, Booking or Subscription ORM/Pydantic classes is prohibited. It creates a distributed monolith and allows services to bypass their contracts.

# 8. API and Event Contract Artifacts

contracts/
├── openapi/
│   ├── iam-v1.yaml
│   ├── tenant-v1.yaml
│   ├── subscription-v1.yaml
│   └── ...
├── events/
│   ├── asyncapi-v1.yaml
│   └── schemas/
│       ├── payment.confirmed.v1.json
│       ├── subscription.activated.v1.json
│       └── ...
└── examples/
    ├── api/
    └── events/

| Rule | Implementation |
| --- | --- |
| OpenAPI generation | Each FastAPI service generates OpenAPI; CI compares it to the committed service contract. |
| Operation IDs | Stable operationId corresponding to contract ID/stable command name. |
| Write schemas | Unknown write fields rejected by default for commercial/financial commands. |
| Event schemas | Required event envelope + required event payload fields; additive optional fields allowed when compatible. |
| Breaking API change | Requires approved incompatible version path/contract (normally /api/v2). |
| Breaking event change | Create a .v2 event type/schema; do not mutate existing .v1 meaning. |
| Generated clients | May be produced from committed contracts but are not the business source of truth. |

# 9. Configuration and Environment Management

## 9.1 Configuration Classes

| Class | Examples | Storage |
| --- | --- | --- |
| Static application config | service name, API prefix, feature implementation switches | Source-controlled defaults / settings model. |
| Environment config | DB/Kafka/Redis endpoints, log level, public base URLs | Environment variables / ConfigMap. |
| Secret config | DB password, provider tokens, JWT signing material | Secret manager / Kubernetes Secret reference; never Git. |
| Business configuration | Plan limits, timeouts/rules explicitly configuration-driven | Versioned authoritative tables controlled by owning service; not plain environment variables. |
| Operational tuning | pool size, worker concurrency, batch size | Environment variables with documented defaults and bounds. |

## 9.2 Environment Names

| Environment | Purpose | Data rule |
| --- | --- | --- |
| local | Developer laptop/CI ephemeral | Synthetic only; resettable. |
| dev | Shared integration | Synthetic/test integrations; no production PII. |
| staging | Release candidate validation | Production-like topology; masked/synthetic data only unless formally approved. |
| prod | Customer workload | Strict secrets, backups, audit, restricted access. |

# 10. Database, SQLAlchemy and Alembic Foundation

| Area | Foundation rule |
| --- | --- |
| Schema | One PostgreSQL schema per logical service; service runtime role writes only its own schema. |
| Session | Request/command opens explicit transaction scope. No hidden autocommit for business mutations. |
| RLS context | SET LOCAL app.tenant_id/app.store_id/app.actor_id inside the transaction where RLS is used. |
| Models | SQLAlchemy models are infrastructure concerns; domain entities need not equal ORM tables one-to-one. |
| Cross-service FK | No hard cross-schema foreign keys by default; validate UUIDs at command boundary or via projection/reconciliation. |
| Money | NUMERIC/integer minor-unit convention per DB spec; never binary float. |
| Migrations | Alembic history owned by service; migrations execute in deterministic service order in CI/deployment. |
| Zero/low downtime | Expand → backfill → switch → contract. Never drop data in the same release that first stops using it. |
| Immutable history | Financial/commercial/audit corrections use compensating rows, not destructive rewrite. |
| Migration lock | Production migration stage is single-writer and blocks concurrent app rollout requiring incompatible schema state. |

## 10.1 Migration Naming

# services/subscription/alembic/versions/
20260914_001_create_subscription_core.py
20260920_002_add_advance_allocation_reference.py

# revision message format
<scope>: <imperative change>
subscription: add period charge calculation snapshot

# 11. Kafka, Outbox, Inbox and Consumer Foundation

| Concern | Standard |
| --- | --- |
| Event envelope | event_id, event_type, event_version, aggregate_type/id, tenant_id, store_id, occurred_at, correlation_id, causation_id, producer, payload. |
| Delivery model | Assume at-least-once at application level. |
| Producer | Business transaction writes outbox row atomically; publisher sends to Kafka and records publication status. |
| Consumer | processed_events/inbox dedupe inserted in same transaction as consumer side effects. |
| Partition key | Aggregate/store key when ordering matters. Never depend on total topic ordering. |
| Retry | Transient processing failure retries with bounded exponential backoff. |
| DLQ | Poison/unrecoverable messages moved to domain DLQ with original headers/payload metadata and operational alert. |
| Schema | JSON schema versioned in /contracts/events/schemas; compatibility checked in CI. |
| Replay | Consumers must be replay-safe. Financial effects also use unique business keys, not event_id alone. |
| Observability | event_id, topic, partition, offset, consumer group, processing latency and correlation_id logged/traced safely. |

## 11.1 Outbox Publisher Process

BEGIN
  mutate aggregate
  append state/audit history
  INSERT outbox_events(...)
COMMIT

publisher loop:
  claim unpublished outbox rows
  publish Kafka message
  mark published_at / attempts
  retry safely until acknowledged

# 12. Scheduler and Worker Foundation

Kafka is not a timer. V1 uses durable PostgreSQL-backed scheduled jobs for time-based lifecycle behavior. A later move to Temporal is permitted without changing domain contracts.

| Job family | Examples | Execution rule |
| --- | --- | --- |
| Subscription | period charge, Day 1 grace, Day 8 expiry, Day 23 Free conversion, scheduled downgrade | Idempotency/business key per subscription+period+transition. |
| Inventory | expire 10-minute reservation | Claim active due reservations; atomic state guard prevents duplicate release. |
| Booking | payment deadline, capacity release | Lock booking/capacity reservation before transition. |
| Commission | weekly invoice, 15-day overdue evaluation | Only uninvoiced eligible commissions; unique invoice-line key prevents duplication. |
| Minor/Guardian | turns-18 reverification | Date-driven; record transition once. |
| Reconciliation | payments/shipments/stuck states | Does not rewrite authoritative history; opens/repairs through idempotent commands. |

SELECT id
FROM scheduled_jobs
WHERE status = 'READY' AND due_at <= now()
ORDER BY due_at
FOR UPDATE SKIP LOCKED
LIMIT :batch_size;

# 13. Authentication, Authorization and Security Foundation

| Control | Repository/runtime implementation |
| --- | --- |
| JWT/session | IAM service owns issuance/refresh/revocation. Services validate trusted token metadata and current authorization where required. |
| Authorization | RBAC + tenant/store assignment + resource ownership + entitlement + lifecycle state + risk restriction. |
| Service auth | Internal calls use workload/service identity; never trust X-Tenant-Id from the public internet without authenticated context. |
| Admin separation | Platform/admin routes are explicitly separated and require elevated role; admin is not represented by tenant_id=NULL shortcut. |
| Passwords/OTP | Strong password hashing; OTP hash only, TTL, attempt and rate limits. |
| Sensitive IDs | PAN/GSTIN/government IDs encrypted/fingerprinted per DB spec; never log plaintext. |
| Network | DB/Kafka/Redis are private; Kubernetes NetworkPolicy restricts access; public traffic terminates through WAF/ingress. |
| Container | Non-root, minimal image, least Linux capabilities; read-only filesystem where service permits. |
| Uploads | Private object storage; pre-signed upload/download; malware/content scanning where appropriate. |

# 14. Error Handling and Idempotency

{
  "error": {
    "code": "INVALID_STATE_TRANSITION",
    "message": "Requested transition is not permitted.",
    "details": {},
    "request_id": "uuid"
  }
}

- Domain/application layers raise typed service errors; API layer maps them to stable HTTP/error codes.
- Do not expose raw SQL/provider exceptions to clients.
- Create/payment/refund/reschedule and other retry-sensitive commands require Idempotency-Key where defined by the API contract.
- Idempotency storage compares request hash. Reusing the same key with materially different input returns IDEMPOTENCY_CONFLICT.
- Optimistic-concurrency resources require expected_version/If-Match and return STALE_VERSION on conflict.
- Provider webhooks are idempotent through provider event ID/hash plus aggregate/business uniqueness.

# 15. Logging, Metrics, Tracing and Audit

## 15.1 Structured Logging

| Required field | Notes |
| --- | --- |
| timestamp | UTC ISO timestamp. |
| level | Structured severity. |
| service | Stable logical/deployable service name. |
| environment | local/dev/staging/prod. |
| request_id | HTTP request ID. |
| correlation_id | Propagated HTTP → events → workers. |
| trace_id/span_id | OpenTelemetry trace context. |
| principal_id | Only where safe/appropriate. |
| tenant_id/store_id | Safe UUID context; no PAN/GSTIN. |
| event_id | Kafka/event handlers. |
| error_code | Stable machine-readable error code. |
| message | Human diagnostic without secrets/PII. |

## 15.2 Metrics and Health

| Endpoint/metric | Rule |
| --- | --- |
| /health/live | Process is alive; no deep dependency checks. |
| /health/ready | Service can accept intended workload; DB required, other dependencies evaluated based on service criticality. |
| /metrics | Internal Prometheus scrape only; never public internet. |
| API metrics | request count/latency/error/429 by route template, not raw tenant path values. |
| Kafka metrics | consumer lag, processing latency, retries, DLQ, outbox backlog. |
| DB metrics | pool usage, lock waits, slow queries, transaction failures. |
| Business metrics | orders/bookings/payment confirmation/subscription conversions/overdue commissions from authoritative event-derived counters. |

## 15.3 Audit vs Operational Log

Operational logs are diagnostic and may be rotated aggressively. Audit records are business evidence and are append-only according to the owning schema. A log line is not a substitute for a required audit/state-history row.

# 16. Local Development Environment

| Dependency | Local baseline | Notes |
| --- | --- | --- |
| PostgreSQL | Container | Single cluster; all service schemas created by migrations. |
| Kafka | Container using KRaft-compatible configuration | Topic bootstrap script creates required topic families/DLQs. |
| Redis | Container | Cache/rate limit only. |
| S3-compatible storage | MinIO or equivalent local emulator | Private buckets; signed URL flows testable. |
| Email | Mailpit/MailHog equivalent | Captures outbound development email. |
| SMS | Fake provider adapter | No real SMS required for normal local run. |
| Provider adapters | Sandbox/fake Razorpay/Shiprocket/verification adapters | Deterministic contract fixtures preferred for automated tests. |
| Observability | Optional local Prometheus/Grafana/OTel collector profile | Core app still runs if optional UI stack disabled. |

## 16.1 Developer Commands

make bootstrap          # install/sync dependencies and local tooling
make infra-up           # postgres, kafka, redis, object store, mail
make migrate            # apply all service migrations in canonical order
make dev                # run selected APIs/workers with reload
make test               # unit + fast integration subset
make test-integration   # full container-backed service integration tests
make test-acceptance    # AC-* cross-service suite
make contracts          # generate + compare OpenAPI/event artifacts
make lint               # format/lint/type checks
make infra-down

# 17. Docker Image Standard

| Requirement | Standard |
| --- | --- |
| Build | Multi-stage build; dependency layer cached from lockfile. |
| Runtime user | Non-root UID/GID. |
| Image base | Minimal supported Python runtime; digest/pinned release in production build pipeline. |
| Install | Locked dependencies only; development dependencies excluded from runtime image. |
| Source | Copy service package plus approved platform libs; do not copy entire repo unless required. |
| Entrypoint | API or worker role explicit; migrations are separate deployment job, not automatic pod startup side effect. |
| Health | Kubernetes probes call service health endpoints. |
| Filesystem | Read-only root where feasible; /tmp or explicit writable mounts only. |
| Secrets | Never baked into image layers. |
| Tagging | Immutable image tag by git SHA; human release tag may point to same digest. |

# 18. Kubernetes Deployment Standard

| Resource | Baseline |
| --- | --- |
| Deployment | Stateless API/consumer/workers; rolling update; readiness/liveness probes. |
| Service | ClusterIP for internal services; ingress/gateway exposes only required public APIs. |
| ConfigMap | Non-secret environment configuration. |
| Secret | References external secret management where available. |
| ServiceAccount | Per service/workload identity. |
| NetworkPolicy | Restrict DB/Kafka/Redis/internal-service access. |
| HPA | API/consumer scaling based on CPU plus request/lag metrics as maturity increases. |
| PDB | For production critical API services where replica count justifies it. |
| Migration Job | Dedicated one-shot job gated before incompatible application rollout. |
| CloudNativePG | Preferred production PostgreSQL operator/control plane according to BTDD. |
| Ingress/WAF | Cloudflare/WAF → ingress/API gateway; internal services not directly exposed. |
| Observability | OTel collector/Prometheus/Grafana/log shipping deployed centrally. |

## 18.1 Resource and Scaling Policy

- Every production workload has CPU/memory requests and limits established from measured staging/load tests.
- API pods scale horizontally; consumers scale by Kafka partition/lag constraints.
- Workers/schedulers must be safe with multiple replicas; database claiming/idempotency prevents duplicate lifecycle effects.
- No application pod manages PostgreSQL/Kafka lifecycle.
- Production and development namespaces/clusters are separated; staging is strongly recommended.

# 19. CI/CD Pipeline and Quality Gates

| Stage | Mandatory checks | Failure effect |
| --- | --- | --- |
| 1. Change detection | Determine affected services/libs/contracts/migrations. | Stop invalid path/metadata. |
| 2. Static quality | Ruff format/lint; type checks; import-boundary checks. | PR blocked. |
| 3. Unit tests | Affected service unit/domain policy tests. | PR blocked. |
| 4. Contract gates | Generate OpenAPI; compare committed contract; validate JSON schemas/AsyncAPI compatibility. | Breaking/uncommitted contract blocked. |
| 5. Migration validation | Fresh DB upgrade + previous-revision upgrade path; schema ownership checks. | PR blocked. |
| 6. Integration tests | Ephemeral PostgreSQL/Kafka/Redis; outbox/inbox, RLS and repository behavior. | PR blocked. |
| 7. Acceptance subset | Relevant AC-* tests based on touched domain; full mandatory set on release. | Release/PR blocked as configured. |
| 8. Security | Dependency scan, secret scan, SAST and container image scan. | Severity-policy gate. |
| 9. Build | Immutable service image(s) tagged with commit SHA; SBOM/provenance where supported. | No deploy if build fails. |
| 10. Dev/staging deploy | Apply migrations under gate; deploy; run smoke/workflow tests. | Promotion blocked. |
| 11. Production promotion | Approved artifact digest; migration gate; health checks; rollback/roll-forward plan. | Deployment halted/rolled back where safe. |

## 19.1 Path-Based CI Optimization

The monorepo pipeline may skip unaffected service unit/image builds, but changes to platform-contracts, repository-wide tooling, API/event contracts, database infrastructure or deployment base manifests trigger the broader dependent matrix. Optimization must never skip compatibility checks for a touched shared contract.

# 20. Testing Foundation

| Test layer | Location | Purpose |
| --- | --- | --- |
| Unit | services/<svc>/tests/unit | Domain policies, calculations, validators, transition guards. |
| Repository/DB | services/<svc>/tests/integration | SQLAlchemy mappings, constraints, RLS, transactions, concurrent updates. |
| API integration | services/<svc>/tests/integration | FastAPI + real ephemeral dependencies. |
| Contract | services/<svc>/tests/contract + /contracts | OpenAPI/event compatibility and examples. |
| Consumer | service tests | Duplicate delivery, replay, retry, DLQ and business-key idempotency. |
| Workflow/E2E | /tests/e2e | Cross-service orchestration with failure/retry/reconciliation. |
| Acceptance | /tests/acceptance | Stable AC-001..AC-090 executable business baseline. |
| Security | service/repository CI | Authorization isolation, IDOR, webhook signature, rate limit, log/secret leakage. |
| Performance | /tooling/load-tests | Inventory/booking contention, webhook bursts, checkout and admin queries. |

## 20.1 Mandatory Foundation Tests

- Same Idempotency-Key + same payload returns the same result; same key + different payload returns IDEMPOTENCY_CONFLICT.
- Duplicate Kafka event produces one side effect.
- Outbox row survives Kafka outage and publishes later without duplicate business mutation.
- Tenant/store RLS prevents cross-scope read/write even if repository query omits the predicate.
- Two scheduler replicas cannot create the same lifecycle transition/charge twice.
- OpenAPI generated by code matches committed contract or the PR explicitly updates the approved contract.
- No service imports another service’s domain/infrastructure package.
- Logs redact prohibited secrets/PAN/GSTIN/OTP/provider credential data.

# 21. Code Quality and Engineering Standards

| Area | Rule |
| --- | --- |
| Formatting | Automated formatter; no style debates in review. |
| Linting | Repository default lint rules; suppressions require reason and narrow scope. |
| Typing | Public application/domain interfaces fully typed; new code should pass configured strict checks. |
| Async | Do not call blocking provider/DB/filesystem operations from async request path without appropriate offload/client. |
| Transactions | Application command handler owns transaction boundary; repositories do not silently commit. |
| Time | Use UTC timestamptz instants; injected clock abstraction for time-bound business tests. |
| Money | Use Decimal/defined money value object; never Python float for commercial calculations. |
| Identifiers | UUID type/value object; never infer authorization from a user-supplied UUID. |
| Errors | Stable domain/application error codes, not string matching. |
| Comments | Explain policy/why; avoid restating obvious code. |
| ADRs | Material technical decisions recorded under docs/adr. |

# 22. Secrets, Supply Chain and Security Scanning

- Git secret scanning is mandatory in CI; leaked credential response includes immediate revoke/rotate and history cleanup procedure.
- Runtime secrets are injected from an approved secret store; local developers use ignored .env files containing non-production credentials only.
- Python dependency vulnerability scanning runs on lockfile; critical/high findings follow defined remediation SLA/exception process.
- Container image scan runs before promotion; base images are regularly rebuilt even when application code is unchanged.
- SBOM/provenance generation is recommended for production images and becomes mandatory when organizational compliance requires it.
- Provider webhook secrets/signing keys are separately scoped per environment.
- No PAN/GSTIN/Guardian ID/payment-provider secret appears in test fixtures unless generated synthetic data.

# 23. Branching, Pull Requests, Releases and Versioning

| Concern | Policy |
| --- | --- |
| Branching | Trunk-based default with short-lived feature branches; protected main. |
| PR scope | Prefer one coherent domain/foundation change; schema + code + contract update may be in same PR when required for consistency. |
| Reviews | CODEOWNERS review for touched service/contracts/migrations; security/DB review for sensitive changes. |
| Commit/release trace | Container image uses immutable git SHA; deployment records digest and migration revision. |
| API version | Path-level incompatible versioning; additive compatible changes remain v1. |
| Event version | event_type/schema .v1/.v2 semantics; existing version meaning immutable. |
| DB version | Alembic revision per service; not semver. |
| Rollback | Prefer roll-forward for data migrations. Application rollback allowed only while DB remains backward-compatible. |
| Hotfix | Same CI/security/contract minimum gates; no direct production patch outside version control. |

# 24. Operational Readiness and Runbooks

| Runbook | Minimum content |
| --- | --- |
| Database migration failure | Detect, stop rollout, assess applied revisions, restore/roll-forward decision, owner/escalation. |
| Kafka consumer lag/DLQ | Identify group/topic/partition, inspect failing event, replay/skip policy, business reconciliation. |
| Outbox backlog | DB query, publisher health, safe replay, duplicate-risk verification. |
| Razorpay webhook outage | Provider status, raw callback/reconciliation, replay path, payment state correction command. |
| Shiprocket webhook outage | Polling/reconciliation path; COD/delivery commission impact. |
| Subscription scheduler delay | Due-job backlog, catch-up behavior, duplicate guard, customer-impact checks. |
| Commission invoice failure | Selection cutoff, duplicate line prevention, rerun idempotency. |
| Secret compromise | Revoke/rotate, redeploy, audit access, invalidate sessions where relevant. |
| Database restore | Backup selection, restore verification, migration position, application smoke tests. |
| Production rollback | Image rollback vs schema compatibility, contract compatibility, event-consumer behavior. |

# 25. M0 Engineering Foundation Delivery Plan

| Step | Deliverable |
| --- | --- |
| M0.1 Repository bootstrap | Create monorepo, CODEOWNERS, root tooling, dependency lock, documentation/ADR structure. |
| M0.2 Service template | Create one reference FastAPI service template with health, settings, context, errors, SQLAlchemy session and tests. |
| M0.3 Data foundation | Provision local PostgreSQL; create schema roles; Alembic-per-service template; RLS test helper. |
| M0.4 Event foundation | Kafka local stack; event envelope library; outbox publisher; inbox/processed-event consumer helper; DLQ convention. |
| M0.5 API/contract foundation | Commit initial OpenAPI/event directories; generation/diff scripts; error/idempotency middleware. |
| M0.6 Auth/observability | IAM skeleton/JWT validation hooks; structured logs; OTel; Prometheus metrics; correlation propagation. |
| M0.7 CI/security | Static checks, unit/integration test matrix, migration checks, contract compatibility, vulnerability/secret/image scans. |
| M0.8 Kubernetes baseline | Base manifests/overlays, probes, service accounts, NetworkPolicy examples, migration Job pattern. |
| M0.9 Acceptance harness | Create AC test naming/mapping structure and first foundation invariant tests. |
| M0 exit | New service can be generated from template; local stack runs; CI builds/scans/tests; one sample event flows DB→outbox→Kafka→consumer idempotently. |

# 26. Service Onboarding Checklist and Definition of Done

☐ Service directory follows canonical template and has a README describing ownership and dependencies.

☐ Service has its own PostgreSQL schema/role and Alembic history.

☐ No direct cross-service database write and no imported foreign service domain package.

☐ OpenAPI endpoints are generated and contract-tested; operation IDs stable.

☐ Published/consumed Kafka events use committed versioned schemas.

☐ Relevant state transitions are commands, not arbitrary status PATCH operations.

☐ Business mutations write audit/history/outbox atomically where required.

☐ Consumers are idempotent and have retry/DLQ behavior.

☐ Tenant/store authorization and RLS tests exist where applicable.

☐ Unit, DB/integration, contract and relevant AC tests pass.

☐ Structured logs/metrics/traces/health endpoints implemented without sensitive-data leakage.

☐ Docker image is non-root, locked-dependency and scan-clean within policy.

☐ Kubernetes manifests include probes, config/secret separation, service account and resource baseline.

☐ Migration is forward-tested and has recovery/roll-forward plan.

☐ Operational runbook/alerts exist for critical integration or scheduled workload.

☐ CI identifies and builds/tests the service independently.

# 27. Decisions and Extension Points

| Decision | V1 baseline | May change if… |
| --- | --- | --- |
| Dependency manager | uv + pyproject/lockfile | Team standard changes while retaining reproducibility. |
| Repository model | Backend monorepo | Scale/team structure justifies split; contracts/schema ownership preserved. |
| Scheduler | PostgreSQL durable jobs + worker replicas | Workflow complexity justifies Temporal. |
| Kafka client | Adapter behind internal producer/consumer interface | Supported client selection changes. |
| Kubernetes manifests | Kustomize-style base/overlays or equivalent | Helm/platform standard preferred; rendered resources preserve controls. |
| Observability | OpenTelemetry + Prometheus/Grafana + centralized logs | Managed equivalent selected. |
| CI platform | GitHub Actions default assumption | Organization uses GitLab/Jenkins/etc.; gates remain equivalent. |
| Secrets | External secret manager integration recommended | Cloud platform determines implementation. |
| Deployment granularity | Logical services independently buildable; temporary co-deploy permitted | Team/traffic justifies extraction; no data rewrite required. |

# Appendix A — Full Repository Tree

karobarone-backend/
├── services/
│   └── <service>/
│       ├── src/karobarone_<service>/
│       │   ├── api/v1/
│       │   ├── application/{commands,queries,handlers,dto}/
│       │   ├── domain/{entities,value_objects,enums,policies,events}/
│       │   ├── infrastructure/{db,kafka,http,providers}/
│       │   ├── workers/
│       │   ├── bootstrap.py
│       │   ├── settings.py
│       │   └── main.py
│       ├── alembic/versions/
│       ├── tests/{unit,integration,contract,fixtures}/
│       ├── Dockerfile
│       ├── alembic.ini
│       ├── pyproject.toml
│       └── README.md
├── libs/
│   ├── platform-contracts/
│   ├── platform-observability/
│   ├── platform-testing/
│   └── platform-db-testkit/
├── contracts/
│   ├── openapi/*.yaml
│   ├── events/asyncapi-v1.yaml
│   ├── events/schemas/*.json
│   └── examples/
├── deploy/
│   ├── local/docker-compose.yml
│   ├── kubernetes/base/
│   ├── kubernetes/overlays/dev/
│   ├── kubernetes/overlays/staging/
│   ├── kubernetes/overlays/prod/
│   └── monitoring/
├── tooling/
│   ├── scripts/
│   ├── contract-checks/
│   ├── migration-checks/
│   └── load-tests/
├── tests/{acceptance,e2e,contract-fixtures}/
├── docs/{adr,runbooks,diagrams,onboarding}/
├── .github/workflows/
├── CODEOWNERS
├── pyproject.toml
├── uv.lock
├── Makefile
├── README.md
└── SECURITY.md

# Appendix B — Standard Service pyproject.toml

[project]
name = "karobarone-commerce"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi",
  "pydantic>=2",
  "pydantic-settings",
  "sqlalchemy>=2",
  "alembic",
  "httpx",
  "structlog",
  "opentelemetry-api",
]

[project.optional-dependencies]
dev = [
  "pytest",
  "pytest-asyncio",
  "ruff",
  "mypy",
  "testcontainers",
]

[tool.ruff]
line-length = 100

[tool.pytest.ini_options]
testpaths = ["tests"]

# Exact dependency resolution is controlled by the repository lockfile.
# Kafka/DB driver packages are selected through the foundation adapter decision.

# Appendix C — Standard Dockerfile

# Illustrative baseline; exact image digest is pinned by build tooling.
FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml uv.lock ./
# install locked production dependencies into /venv

FROM python:3.12-slim AS runtime
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=builder /venv /venv
COPY services/commerce/src ./src
ENV PATH="/venv/bin:$PATH"     PYTHONUNBUFFERED=1
USER 10001
CMD ["uvicorn", "karobarone_commerce.main:app", "--host", "0.0.0.0", "--port", "8080"]

# Migrations run as a separate deployment job, not implicitly in CMD.

# Appendix D — FastAPI Bootstrap Skeleton

from fastapi import FastAPI
from karobarone_commerce.api.v1.router import router
from karobarone_commerce.settings import Settings

def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="KarobarOne Commerce API", version="1.0")

    # install request/correlation context middleware
    # install structured logging / OpenTelemetry
    # install stable exception -> error-envelope mapping
    # register health/readiness and metrics endpoints
    app.include_router(router, prefix="/api/v1")
    return app

app = create_app()

# Appendix E — Environment Variable Catalog

| Variable family | Examples | Rule |
| --- | --- | --- |
| SERVICE_* | SERVICE_NAME, ENVIRONMENT, LOG_LEVEL | Non-secret. |
| DATABASE_* | DATABASE_DSN or host/name/user refs | Password/secret component via secret manager. |
| KAFKA_* | KAFKA_BOOTSTRAP_SERVERS, KAFKA_CLIENT_ID | Credentials secret; brokers non-secret config. |
| REDIS_* | REDIS_URL | Password secret if enabled. |
| OTEL_* | OTEL_SERVICE_NAME, OTEL_EXPORTER_OTLP_ENDPOINT | Non-secret except provider tokens. |
| AUTH_* | JWT_ISSUER, JWT_AUDIENCE, public key refs | Signing/private keys secret and IAM-owned. |
| PROVIDER_* | RAZORPAY/SHIPROCKET/etc adapter endpoints | Credentials/tokens always secret. |
| OBJECT_STORAGE_* | bucket/endpoint/region | Access keys secret. |
| WORKER_* | concurrency, batch size, poll interval | Operational tuning with bounded defaults. |

# Appendix F — CI Pipeline Reference

pull_request:
  detect_changes
  static_quality
  unit_tests
  contract_diff
  migration_validation
  integration_tests
  acceptance_impacted
  dependency_and_secret_scan
  build_test_images

main/release:
  all_above
  full_acceptance_suite
  container_scan + SBOM
  publish immutable images
  deploy_dev/staging
  smoke + workflow tests
  approval gate
  production migration job
  production rollout
  post-deploy health + reconciliation checks

# Appendix G — Engineering Foundation Checklist

☐ Root monorepo + service directories created for all 16 logical services.

☐ Root lockfile and reproducible install verified in CI.

☐ Standard FastAPI service template builds and runs.

☐ Local PostgreSQL/Kafka/Redis/object-store/email stack starts with one command.

☐ Alembic-per-service template and canonical migration order implemented.

☐ RLS context helper and cross-tenant test fixture implemented.

☐ Event envelope + transactional outbox + inbox dedupe reference implementation works.

☐ Retry/DLQ convention and operational replay procedure documented.

☐ Request/correlation/trace context propagates HTTP → Kafka → workers.

☐ Standard error envelope and idempotency middleware implemented.

☐ OpenAPI generation/diff and event-schema validation run in CI.

☐ Structured logging, Prometheus metrics and OTel traces available.

☐ Docker images build non-root and pass scan policy.

☐ Kubernetes base/overlay and migration Job pattern verified in dev/staging.

☐ Acceptance test harness supports AC-001..AC-090 stable IDs.

☐ CODEOWNERS, SECURITY.md, ADR and runbook conventions established.

**Engineering Baseline Statement**

This Repository & Engineering Foundation Specification V1.0 is the implementation baseline for establishing the KarobarOne backend codebase before feature development begins. A service is considered production-eligible only when it conforms to the repository, contract, migration, security, observability, testing and deployment standards defined here and to the higher-authority BRD and technical specifications.
