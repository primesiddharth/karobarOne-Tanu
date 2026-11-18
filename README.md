# KarobarOne Microservices

Welcome to the **KarobarOne Microservices** core directory. This folder contains the clean-room, production-grade re-implementation of the KarobarOne business behavior, migrating the legacy monolith into **8 autonomous microservices** + **1 API Gateway**.

---

## Table of Contents
1. [Mission & Core Principles](#1-mission--core-principles)
2. [Service Catalog & Bounded Contexts](#2-service-catalog--bounded-contexts)
3. [System Architecture](#3-system-architecture)
   - [3.1 Network Topology & Data Flow](#31-network-topology--data-flow)
   - [3.2 Transactional Outbox & Inbox Deduplication](#32-transactional-outbox--inbox-deduplication)
   - [3.3 Service-to-Service Security & Auth](#33-service-to-service-security--auth)
   - [3.4 Row-Level Security (RLS) Defense-in-Depth](#34-row-level-security-rls-defense-in-depth)
4. [Directory Structure](#4-directory-structure)
5. [Shared Foundation (`libs/platform_contracts`)](#5-shared-foundation-libsplatform_contracts)
6. [Contracts & Schema Registry (`contracts/`)](#6-contracts--schema-registry-contracts)
7. [Developer Quickstart](#7-developer-quickstart)
   - [7.1 Prerequisites](#71-prerequisites)
   - [7.2 Running Locally with Docker Compose](#72-running-locally-with-docker-compose)
   - [7.3 Running a Single Service (Fast Inner Loop)](#73-running-a-single-service-fast-inner-loop)
   - [7.4 Running Database Migrations](#74-running-database-migrations)
8. [Testing & Quality Verification](#8-testing--quality-verification)
   - [8.1 Test Commands](#81-test-commands)
   - [8.2 Acceptance Criteria (AC) Verification](#82-acceptance-criteria-ac-verification)
   - [8.3 OpenAPI Contract Drift Verification](#83-openapi-contract-drift-verification)
9. [Deployment & Cloud Infrastructure](#9-deployment--cloud-infrastructure)
   - [9.1 Render Blueprint Deployment](#91-render-blueprint-deployment)
   - [9.2 Neon Serverless PostgreSQL Database](#92-neon-serverless-postgresql-database)
   - [9.3 Cost Optimization (`RUN_WORKER_IN_API`)](#93-cost-optimization-run_worker_in_api)
   - [9.4 Kubernetes (Kind / Minikube)](#94-kubernetes-kind--minikube)
10. [Service Directory Layout Standard](#10-service-directory-layout-standard)
11. [Developer Tooling & Automation](#11-developer-tooling--automation)
12. [Binding Engineering Rules (Summary)](#12-binding-engineering-rules-summary)

---

## 1. Mission & Core Principles

The mission of this codebase is to deliver an enterprise-grade, highly reliable, and horizontally scalable backend adhering strictly to the KarobarOne engineering specifications.

- **Clean-Room Implementation**: Built from scratch against the specifications in `docs/specs/`. The legacy monolith code is read-only reference.
- **One Service = One Schema = One DB Role**: Every microservice owns its private PostgreSQL schema. Direct cross-schema joins and cross-service SQL queries are blocked at the database engine level.
- **Transactional Outbox Pattern**: State mutations and event emissions commit atomically in the same database transaction.
- **Contract-First Development**: OpenAPI 3.1 and AsyncAPI 2.6 contracts constrain the application code; drift detection fails the CI pipeline.
- **Strict Domain Boundaries**: Pure domain logic (`domain.py`) is decoupled from framework code (zero FastAPI, SQLAlchemy, or HTTP client imports).
- **Zero Ambiguity**: Document conflicts and business ambiguities are logged in `docs/OPEN_QUESTIONS.md` rather than guessed.

---

## 2. Service Catalog & Bounded Contexts

KarobarOne comprises 8 business microservices and 1 public API Gateway:

| Service | Port | Schema | Bounded Context & Responsibilities | Key Emitted Events |
|---|---|---|---|---|
| **`gateway`** | `8000` | — | Public reverse proxy, JWT verification, route dispatch, service API key injection, rate limiting. | — |
| **`iam`** | `8001` | `iam` | Authentication, Argon2id passwords, phone OTP challenges, Ed25519 JWT issue/refresh, RBAC sessions. | `identity.user-created.v1`, `identity.role-assigned.v1` |
| **`tenant`** | `8002` | `tenant` | Merchant registration, store lifecycle, minor protection, encrypted PAN/GSTIN, guardian consent. | `tenant.registration-started.v1`, `tenant.activated.v1`, `store.created.v1` |
| **`approval`** | `8003` | `approval` | Human-in-the-loop content moderation, automated policy checks, emergency takedown reviews. | `content.submitted.v1`, `content.approved.v1`, `content.rejected.v1` |
| **`catalog`** | `8004` | `catalog` | Storefront products, variants, categories, price history, private S3 media upload intents. | `catalog.item-created.v1`, `catalog.item-unpublished.v1`, `catalog.media-uploaded.v1` |
| **`domain`** | `8005` | `domain` | Free `*.karobar.one` subdomains, custom domains, DNS record verification, store public live routing. | `domain.subdomain-assigned.v1`, `domain.dns-verified.v1`, `domain.activated.v1`, `store.published.v1` |
| **`customer`** | `8006` | `customer` | Buyer accounts, phone-based guest identity, customer profile claims, consent history. | `customer.created.v1`, `customer.profile-claimed.v1` |
| **`subscription`**| `8007` | `subscription`| Merchant billing plans, 30-day billing periods, payment due timers, grace periods, auto-downgrade. | `subscription.period-started.v1`, `subscription.grace-entered.v1`, `subscription.converted-to-free.v1` |
| **`inventory`** | `8008` | `inventory` | Real-time stock levels, SKU reservation TTL locks, optimistic concurrency, restock tracking. | `inventory.stock-reserved.v1`, `inventory.stock-released.v1`, `inventory.restocked.v1` |

*(All other business domains like payments, fulfilment, and invoicing are currently out-of-scope and stubbed).*

---

## 3. System Architecture

### 3.1 Network Topology & Data Flow

```mermaid
flowchart TD
    Client["Client Applications (Mobile / Web)"] -->|HTTPS (Port 443)| Gateway["Gateway Service (:8000)"]

    subgraph Internal_Private_Network["Private Service Mesh / VPC (Render / K8s)"]
        Gateway -->|HTTP + HMAC Header| IAM["IAM Service (:8001)"]
        Gateway -->|HTTP + HMAC Header| TEN["Tenant Service (:8002)"]
        Gateway -->|HTTP + HMAC Header| APR["Approval Service (:8003)"]
        Gateway -->|HTTP + HMAC Header| CAT["Catalog Service (:8004)"]
        Gateway -->|HTTP + HMAC Header| DOM["Domain Service (:8005)"]
        Gateway -->|HTTP + HMAC Header| CUS["Customer Service (:8006)"]
        Gateway -->|HTTP + HMAC Header| SUB["Subscription Service (:8007)"]
        Gateway -->|HTTP + HMAC Header| INV["Inventory Service (:8008)"]

        CAT -.->|Sync HTTP: Check Policy| APR
        DOM -.->|Sync HTTP: Verify Subscription| SUB
    end

    subgraph Outbox_Relay_Pipeline["Asynchronous Event Pipeline"]
        TEN -->|Outbox Table| W_TEN["Worker: tenant"]
        CAT -->|Outbox Table| W_CAT["Worker: catalog"]
        W_TEN -->|HTTP Outbox Relay / Kafka| Gateway
    end

    subgraph Neon_PostgreSQL["Neon Serverless PostgreSQL (One Project)"]
        IAM -->|Schema: iam| DB_IAM[(iam_svc)]
        TEN -->|Schema: tenant| DB_TEN[(tenant_svc)]
        APR -->|Schema: approval| DB_APR[(approval_svc)]
        CAT -->|Schema: catalog| DB_CAT[(catalog_svc)]
        DOM -->|Schema: domain| DB_DOM[(domain_svc)]
        CUS -->|Schema: customer| DB_CUS[(customer_svc)]
        SUB -->|Schema: subscription| DB_SUB[(subscription_svc)]
        INV -->|Schema: inventory| DB_INV[(inventory_svc)]
    end
```

### 3.2 Transactional Outbox & Inbox Deduplication
To completely eliminate distributed transaction failures and dual-write data inconsistencies:
1. **Outbox**: When an aggregate state change occurs, a new row is written to the service's `outbox_events` table inside the **exact same PostgreSQL transaction**.
2. **Relay**: The service's background worker (`python -m app.worker`) polls unpublished rows with `FOR UPDATE SKIP LOCKED` and dispatches them.
3. **Inbox**: Consumers record incoming `event_id` into their private `processed_events` table inside the processing transaction, preventing duplicate executions.

### 3.3 Service-to-Service Security & Auth
Direct HTTP communication between microservices is secured through a two-layer mechanism (`docs/SECURITY_LAYER.md`):
- **User Authentication**: Client requests carry an `Authorization: Bearer <JWT>` header verified against the public key (`JWT_PUBLIC_KEY`). The Gateway extracts and injects the authenticated `Principal` identity.
- **Service-to-Service Authentication**: Internal calls carry an `X-Service-Key` header. Each receiving service validates the SHA256 hash of the caller key against its `SERVICE_KEY_HASHES` allowlist.

### 3.4 Row-Level Security (RLS) Defense-in-Depth
Every tenant-scoped table enables and forces PostgreSQL Row-Level Security:
```sql
ALTER TABLE stores ENABLE ROW LEVEL SECURITY;
ALTER TABLE stores FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_policy ON stores
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
```
Commands inject `SET LOCAL app.tenant_id = :tenant_id` inside each database transaction from the authenticated `Principal`. Even if application code misses a `WHERE` clause, cross-tenant data leaks are physically blocked by PostgreSQL.

---

## 4. Directory Structure

```
microservice/
├── docs/                         # Specification documents and binding rules
│   ├── specs/                    # 10 source-of-truth Markdown specifications
│   ├── RULES.md                  # Non-negotiable engineering rules
│   ├── SERVICES.md               # Service cards (endpoints, tables, events, ACs)
│   ├── ROADMAP.md                # 12-phase development roadmap and exit gates
│   ├── DEPLOY.md                 # Docker, Neon, Render, and Kubernetes specifications
│   ├── SECURITY_LAYER.md         # Inter-service authentication and key rotation
│   ├── OPEN_QUESTIONS.md         # Ambiguity log (OQ-001..OQ-041)
│   └── STUBS.md                  # Temporary stubs inventory and sunset schedule
├── libs/
│   └── platform_contracts/       # Reusable, zero-business-logic platform library
│       ├── events.py             # EventEnvelope dataclass & metadata
│       ├── errors.py             # ApiError model & registered error codes
│       ├── tokens.py             # JWT verification & Principal extraction
│       ├── logging.py            # Structured JSON logging & sensitive redaction
│       ├── relay.py              # Outbox polling, dispatch & retry engine
│       ├── worker.py             # Scheduled worker loop runner
│       └── metrics.py            # Internal Prometheus metrics
├── contracts/
│   ├── openapi/services/         # Committed OpenAPI YAML contracts
│   └── events/
│       ├── asyncapi-v1.yaml      # AsyncAPI 2.6 specification of all event topics
│       ├── schemas/              # JSON Schema definitions for every event type
│       └── subscriptions.yaml    # Service-to-topic consumer mappings
├── services/                     # 8 core microservices + Gateway
│   ├── gateway/                  # API Gateway reverse proxy
│   ├── iam/                      # Identity & Access Management
│   ├── tenant/                   # Tenant, Store & Guardian management
│   ├── approval/                 # Content moderation & review
│   ├── catalog/                  # Products, Variants & Categories
│   ├── domain/                   # Subdomains & Custom DNS
│   ├── customer/                 # Buyer identity & claims
│   ├── subscription/             # Merchant billing & subscription lifecycles
│   └── inventory/                # Stock levels & SKU reservation locks
├── deploy/
│   ├── compose/                  # Local development docker-compose.yml
│   └── k8s/                      # Kubernetes manifests (base & overlays)
├── tools/
│   ├── db/bootstrap.sql          # Neon schema and role bootstrap script
│   ├── skeleton_service/         # Scaffolding templates for new services
│   ├── new_service.py            # Service generator CLI
│   ├── export_openapi.py         # OpenAPI contract export & drift check tool
│   ├── check_ac_coverage.py      # AC test coverage verification gate
│   └── gen_keys.py               # Key generation utility for secrets
├── tooling/
│   └── load-tests/               # Concurrency and load performance test suite
├── tests/
│   └── e2e/                      # Multi-service integration and end-to-end flows
├── render.yaml                   # Production Render Blueprint manifest
└── Makefile                      # Automation Makefile
```

---

## 5. Shared Foundation (`libs/platform_contracts`)

All microservices import shared infrastructure primitives from `libs/platform_contracts`. This library contains **zero business logic**:
- **`events.py`**: Declares the standard `EventEnvelope` format (`event_id`, `event_type`, `aggregate_id`, `tenant_id`, `store_id`, `occurred_at`, `payload`, `headers`).
- **`errors.py`**: Defines standard `ApiError` and HTTP exception handlers returning the specification error format: `{"error": {"code": "...", "message": "...", "details": {...}}}`.
- **`tokens.py`**: Extracts and validates JWTs, building a typed `Principal` (`user_id`, `tenant_id`, `roles`, `scopes`).
- **`logging.py`**: Formats structured JSON log lines and automatically masks sensitive fields (PAN, GSTIN, passwords, tokens, guardian IDs).
- **`relay.py`**: Implements the polling loop that queries `outbox_events` and dispatches events via HTTP relay or message broker.

---

## 6. Contracts & Schema Registry (`contracts/`)

KarobarOne enforces a strict **contract-driven** workflow:
- **`contracts/openapi/services/<service>.yaml`**: Committed OpenAPI 3.1 definitions for each service. Code must strictly adhere to the contract.
- **`contracts/events/asyncapi-v1.yaml`**: Complete AsyncAPI 2.6 catalog defining all event topics, channels, and bindings.
- **`contracts/events/schemas/*.json`**: Individual JSON Schema files for every emitted event payload.
- **`contracts/events/subscriptions.yaml`**: Matrix mapping which microservices consume which event types.

---

## 7. Developer Quickstart

### 7.1 Prerequisites
- **Python 3.12**
- **Docker Engine & Docker Compose** (v2+)
- **uv** (`pip install uv`)
- **make**

### 7.2 Running Locally with Docker Compose
To boot the full local environment (PostgreSQL 16 with schemas pre-configured, MinIO, Mailpit, Gateway, and all microservices):

```bash
cd microservice

# Start the complete stack in background
make up

# View container status and health probes
docker compose -f deploy/compose/docker-compose.yml ps

# Follow logs from any service
docker compose -f deploy/compose/docker-compose.yml logs -f tenant

# Stop all containers
make down

# Wipe containers and persistent volumes
make reset
```

The Gateway is accessible at `http://localhost:8000`. Test readiness:
```bash
curl http://localhost:8000/health/ready
```

### 7.3 Running a Single Service (Fast Inner Loop)
When actively developing a single service (e.g. `tenant`):

```bash
cd microservice/services/tenant

# 1. Setup virtual environment
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 2. Install dependencies
uv pip install -e ../../libs/platform_contracts -r <(uv pip compile pyproject.toml)

# 3. Apply schema migrations
export MIGRATION_DATABASE_URL="postgresql+asyncpg://tenant_migrator:dev_migrator_password@localhost:5432/karobarone_dev"
alembic upgrade head

# 4. Start the API with hot reload
export DATABASE_URL="postgresql+asyncpg://tenant_svc:dev_svc_password@localhost:5432/karobarone_dev"
export SERVICE_NAME="tenant"
export ENVIRONMENT="local"
uvicorn app.main:app --port 8002 --reload

# 5. In a second terminal, start the background worker
python -m app.worker
```

### 7.4 Running Database Migrations
Migrations are managed per-service using Alembic:

```bash
# Run migrations for a specific service
make migrate SERVICE=catalog
# Equivalent: alembic -c services/catalog/alembic.ini upgrade head

# Create a new revision for a service
alembic -c services/catalog/alembic.ini revision --autogenerate -m "add_indexes"
```

---

## 8. Testing & Quality Verification

KarobarOne implements a rigorous multi-tier test suite. In accordance with `RULES.md §2`, tests run against **real PostgreSQL instances** (via Docker or `testcontainers`). SQLite is prohibited.

### 8.1 Test Commands

```bash
cd microservice

# Run all tests across the repository
make test

# Run tests for a specific microservice
make test SERVICE=iam

# Run code style, formatting, and type checks
make lint
# Runs: ruff check . && mypy libs/platform_contracts tools/
```

### 8.2 Acceptance Criteria (AC) Verification
Business requirements from **AC-001 through AC-090** are modeled as executable automated tests.

Verify that all assigned acceptance criteria are covered by passing tests:
```bash
python tools/check_ac_coverage.py
```

### 8.3 OpenAPI Contract Drift Verification
Contracts must constrain the implementation. Verify that the running FastAPI app matches the committed contract:

```bash
# Check for schema drift on a service
python tools/export_openapi.py customer

# Overwrite/sync contract following an approved spec change
python tools/export_openapi.py customer --overwrite
```

---

## 9. Deployment & Cloud Infrastructure

### 9.1 Render Blueprint Deployment
The repository includes [`render.yaml`](file:///D:/Programming/KarobarOne-Backend/microservice/render.yaml) declaring the full production architecture:
- `karobar-gateway`: Public web service routing incoming internet traffic.
- `karobar-<svc>`: Private services (`pserv`) unreachable from outside the Render private network.
- `<svc>-worker`: Background workers running `python -m app.worker`.
- Auto-migrations execute via `preDeployCommand: alembic upgrade head`.

### 9.2 Neon Serverless PostgreSQL Database
Database architecture uses one Neon project partitioned by schemas:
1. **Branches**: `dev` (feature testing), `staging` (pre-release), `main` (production).
2. **Roles & Security**:
   - `<svc>_svc`: Runtime application role with DML permissions only. Connects via Neon pooled connection string (`-pooler`).
   - `<svc>_migrator`: Migration role with DDL permissions. Connects via direct connection string.
3. **Provisioning**: Bootstrapped via `tools/db/bootstrap.sql`.

### 9.3 Cost Optimization (`RUN_WORKER_IN_API`)
In staging or resource-constrained environments, you can run workers directly within the FastAPI web process by setting:
```bash
RUN_WORKER_IN_API=true
```
This runs the outbox relay background thread within the API container, cutting required container instances in half while maintaining full schema isolation.

### 9.4 Kubernetes (Kind / Minikube)
Kubernetes manifests are located in `deploy/k8s/`:
```bash
# Spin up local Kind cluster, build images, and run smoke tests
./tools/k8s/kind-up.sh
```

---

## 10. Service Directory Layout Standard

Every service adheres to this lean, non-negotiable folder structure (`RULES.md §3`):

```
services/<name>/
├── Dockerfile                  # Multi-stage Python 3.12-slim build
├── alembic.ini                 # Schema migration configuration
├── pyproject.toml              # Locked dependencies for this service
├── app/
│   ├── __init__.py
│   ├── config.py               # pydantic-settings BaseSettings
│   ├── db.py                   # Async SQLAlchemy engine & RLS session hook
│   ├── models.py               # SQLAlchemy models (includes outbox & inbox)
│   ├── schemas.py              # Pydantic v2 DTOs (extra="forbid" on writes)
│   ├── domain.py               # PURE business logic & state transition tables
│   ├── commands.py             # Transactional named command handlers
│   ├── routes.py               # Thin FastAPI route handlers
│   ├── events.py               # Event dispatchers & inbox event handlers
│   ├── clients.py              # Upstream HTTP clients + test stubs
│   ├── main.py                 # FastAPI application, middleware, /health probes
│   └── worker.py               # Scheduled worker & outbox relay process
├── migrations/
│   ├── env.py                  # Alembic runner
│   ├── script.py.mako          # Migration template
│   └── versions/               # Sequential database migrations
└── tests/
    ├── __init__.py
    ├── conftest.py             # Test fixtures & testcontainers database
    ├── test_outbox_atomicity.py# Asserts outbox rollback on transaction failure
    ├── test_idempotency.py     # Asserts idempotent command re-execution
    ├── test_service_auth.py    # Asserts rejection of unauthorized calls
    ├── test_inbox_unknown_events.py # Asserts safe ignore of unknown events
    ├── test_rls_isolation.py   # Asserts RLS blocks cross-tenant access
    └── acceptance/
        └── test_ac_*.py        # Executable Acceptance Criteria tests
```

---

## 11. Developer Tooling & Automation

The `tools/` directory contains CLI automation tools:
- **`tools/db/bootstrap.sql`**: Complete SQL script to initialize schemas, roles, and RLS policies on Neon/Postgres.
- **`tools/new_service.py`**: Scaffolds a new, specification-compliant microservice from `tools/skeleton_service/`.
- **`tools/export_openapi.py`**: Exports and diffs OpenAPI schemas against committed contracts to enforce contract-first integrity.
- **`tools/check_ac_coverage.py`**: Scans the test suite to ensure 100% test coverage of all assigned Acceptance Criteria.
- **`tools/gen_keys.py`**: Generates cryptographic keys (Ed25519 JWT keypairs, Fernet encryption keys, HMAC-SHA256 service keys).

---

## 12. Binding Engineering Rules (Summary)

All developers and automated agents must adhere to the rules in `docs/RULES.md`:

1. **Isolation**: Never read from or write to another service's database schema. No cross-schema foreign keys.
2. **State Transitions**: Mutations occur only through named commands in `commands.py` with explicit transition guards in `domain.py`. Generic status `PATCH` endpoints are forbidden.
3. **Money**: Always stored as integer **paise** in PostgreSQL (`bigint`), calculated using `Decimal` in Python, and represented as a **decimal string** (`"100.00"`) in API contracts. Never use `float`.
4. **Time**: Stored as UTC `timestamptz`. Business commands accept an injected `now: datetime` clock parameter (sleeping in tests is forbidden).
5. **No Monolith Edits**: Files in the legacy monolith directory are strictly read-only.
6. **No Secret Leaks**: Never log, store, or emit PAN, GSTIN, guardian ID, passwords, OTPs, or API secrets in plaintext. Use Fernet encryption + HMAC blind indexing (`RULES.md §5`).
7. **Error Envelope**: All error responses must adhere strictly to the platform error format:
   ```json
   {
     "error": {
       "code": "REGISTERED_ERROR_CODE",
       "message": "Human readable explanation",
       "details": {}
     }
   }
   ```
8. **Resolve Ambiguity Early**: When specifications conflict or numbers are missing, record the entry in `docs/OPEN_QUESTIONS.md` rather than inventing behavior.
