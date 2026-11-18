# KarobarOne

Production-grade, multi-tenant e-commerce backend built with **8 autonomous microservices** and **1 API Gateway**.

---

## Architecture & Services

KarobarOne enforces strict bounded contexts: each service owns its private PostgreSQL schema, communicates asynchronously via the **Transactional Outbox** pattern, and protects tenant data with **Row-Level Security (RLS)**.

| Service | Port | Schema | Swagger Docs | Description |
| :--- | :---: | :---: | :---: | :--- |
| **Gateway** | `8000` | — | — | Public reverse proxy, JWT verification, service routing & rate limiting |
| **IAM** | `8001` | `iam` | [`/docs`](http://localhost:8001/docs) | Authentication, OTP verification, Ed25519/RSA JWT signing, RBAC |
| **Tenant** | `8002` | `tenant` | [`/docs`](http://localhost:8002/docs) | Merchant onboarding, store lifecycle, encrypted PAN/GSTIN, RLS |
| **Approval** | `8003` | `approval` | [`/docs`](http://localhost:8003/docs) | Content moderation, human-in-the-loop review, takedown workflows |
| **Catalog** | `8004` | `catalog` | [`/docs`](http://localhost:8004/docs) | Products, variants, categories, price history, private S3 uploads |
| **Domain** | `8005` | `domain` | [`/docs`](http://localhost:8005/docs) | `*.karobar.one` subdomains, custom domains, DNS verification |
| **Customer** | `8006` | `customer` | [`/docs`](http://localhost:8006/docs) | Buyer accounts, guest profiles, phone verification, profile claims |
| **Subscription** | `8007` | `subscription` | [`/docs`](http://localhost:8007/docs) | Billing plans, 30-day billing cycles, grace periods, auto-downgrade |
| **Inventory** | `8008` | `inventory` | [`/docs`](http://localhost:8008/docs) | Real-time stock levels, SKU reservation TTL locks, optimistic locking |

---

## Prerequisites

- **Docker Desktop** (running)
- **Python 3.12** (used for initial key generation & local dev tooling)

---

## Quickstart & Run Guide

### 1. First Run (New Machine)

```powershell
# 1. Config + JWT keys
copy .env.example .env
pip install cryptography
python tools/gen_keys.py --write-env

# 2. Start database + storage (first start creates schemas, roles and the MinIO bucket)
docker compose -f deploy/compose/docker-compose.yml up -d postgres minio minio-init

# 3. Create tables (runs Alembic inside each service image)
foreach ($s in "iam","tenant","approval","catalog","domain","customer","subscription","inventory") {
  docker compose -f deploy/compose/docker-compose.yml run --rm --no-deps "$s-api" alembic upgrade head
}

# 4. Start everything
docker compose -f deploy/compose/docker-compose.yml up -d --build

# 5. Check
curl http://localhost:8000/health/ready
docker compose -f deploy/compose/docker-compose.yml ps
```

> **Bash / macOS / Linux alternative for Step 1 & 3:**
> ```bash
> cp .env.example .env && pip install cryptography && python tools/gen_keys.py --write-env
> for s in iam tenant approval catalog domain customer subscription inventory; do
>   docker compose -f deploy/compose/docker-compose.yml run --rm --no-deps "${s}-api" alembic upgrade head
> done
> ```

---

### 2. Every Day

```powershell
docker compose -f deploy/compose/docker-compose.yml up -d    # start
docker compose -f deploy/compose/docker-compose.yml down     # stop (data is kept)
```

> After pulling code with new migrations, repeat **Step 3** above.

---

### 3. Reset Everything (Deletes All Data)

```powershell
docker compose -f deploy/compose/docker-compose.yml down -v
```

> Then repeat **First run**.

---

## Useful URLs

| Service / Tool | URL | Notes |
| :--- | :--- | :--- |
| **Gateway** | [http://localhost:8000](http://localhost:8000) | Health ready: [`/health/ready`](http://localhost:8000/health/ready) |
| **IAM Swagger** | [http://localhost:8001/docs](http://localhost:8001/docs) | Authentication & RBAC |
| **Tenant Swagger** | [http://localhost:8002/docs](http://localhost:8002/docs) | Merchant onboarding & store lifecycle |
| **Approval Swagger** | [http://localhost:8003/docs](http://localhost:8003/docs) | Content moderation & review |
| **Catalog Swagger** | [http://localhost:8004/docs](http://localhost:8004/docs) | Products, variants & S3 media |
| **Domain Swagger** | [http://localhost:8005/docs](http://localhost:8005/docs) | Subdomains & DNS verification |
| **Customer Swagger** | [http://localhost:8006/docs](http://localhost:8006/docs) | Buyer accounts & guest identity |
| **Subscription Swagger** | [http://localhost:8007/docs](http://localhost:8007/docs) | Billing plans & grace periods |
| **Inventory Swagger** | [http://localhost:8008/docs](http://localhost:8008/docs) | Stock tracking & SKU locks |
| **MinIO Console** | [http://localhost:9001](http://localhost:9001) | Object storage (`minioadmin` / `minioadminpassword`) |
| **Mail Inbox (Dev)** | [http://localhost:8025](http://localhost:8025) | Local Mailpit inbox (SMTP on port `1025`) |
| **Postgres** | `localhost:5433` | Database: `karobarone_dev` (`postgres` / `dev_postgres_password`) |

---

## Logs and Tests

```powershell
# Follow logs from a specific service container
docker compose -f deploy/compose/docker-compose.yml logs -f tenant-api

# Run automated tests (needs Python deps installed + Docker running)
make test

# Verify acceptance criteria test coverage
make check-ac

# Code style and type checking
make lint
```

---

## Repository Structure

```
.
├── contracts/             # OpenAPI 3.1 & AsyncAPI 2.6 specifications & event schemas
├── deploy/
│   ├── compose/           # Local Docker Compose setup (Postgres, MinIO, Mailpit, 8 APIs + workers)
│   └── k8s/               # Kubernetes manifests
├── docs/                  # Architecture specs, engineering rules, and service cards
├── libs/
│   └── platform_contracts/# Shared core foundation (events, errors, tokens, logging, relay)
├── services/              # 8 autonomous business microservices + API Gateway
│   ├── approval/
│   ├── catalog/
│   ├── customer/
│   ├── domain/
│   ├── gateway/
│   ├── iam/
│   ├── inventory/
│   ├── subscription/
│   └── tenant/
├── tests/                 # End-to-end and cross-service integration test suites
└── tools/                 # Automation scripts (gen_keys.py, check_ac_coverage.py, DB bootstrap)
```

---

## Core Engineering Principles

1. **One Service = One Schema = One DB Role**: Direct cross-schema joins and queries are physically blocked at the database engine level.
2. **Transactional Outbox**: Mutations and event emissions commit atomically in the same database transaction.
3. **Row-Level Security (RLS)**: PostgreSQL enforces tenant isolation (`app.tenant_id`) even if application code misses a `WHERE` clause.
4. **Money in Paise**: Stored as integer paise (`bigint`) and represented as decimal strings (`"100.00"`). Never floating point.
5. **Contract-First**: OpenAPI 3.1 and AsyncAPI 2.6 contracts constrain all code implementations.

For full architectural documentation, refer to the [`docs/`](docs/) directory.
