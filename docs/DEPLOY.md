# DEPLOY.md — Docker → compose → Neon → Render (→ Kubernetes)

**What runs where**
| Where | What | Tool |
|---|---|---|
| Laptop (daily) | Docker containers + Postgres | docker compose |
| Laptop (occasional) | same images on K8s | kind / minikube |
| Staging / prod | same images | **Render** (Docker). Render does **not** run Kubernetes |
| Database | Postgres | **Neon** (local uses Postgres in compose) |

The thing that moves between environments is the **image**, never the K8s files. Render settings below change over time: verify against current Render and Neon docs before relying on them.

## 1. Environments & variables
`local` (compose) · `staging` (Render + Neon branch `staging`) · `prod` (Render + Neon `main`). Never share secrets across them.
| Variable | Used by | Notes |
|---|---|---|
| `SERVICE_NAME`, `ENVIRONMENT`, `LOG_LEVEL` | all | `ENVIRONMENT=prod` disables dev stubs and `/docs` |
| `DATABASE_URL` | api, worker | Neon **pooled** host (`-pooler`), role `<schema>_svc` |
| `MIGRATION_DATABASE_URL` | alembic only | Neon **direct** host, role `<schema>_migrator` |
| `MY_SERVICE_KEY`, `SERVICE_KEY_HASHES` | all | outgoing key / accepted caller key hashes (SECURITY_LAYER §2) |
| `JWT_PUBLIC_KEY`, `JWT_ISSUER`, `JWT_AUDIENCE` | all | verify user JWT |
| `JWT_PRIVATE_KEY` | iam only | signing |
| `PAN_ENC_KEY`, `PAN_FP_KEY` | tenant | encrypt / keyed fingerprint |
| `<SERVICE>_URL` | callers + relay | internal URL of other services |
| `GATEWAY_API_KEYS`, `UPSTREAM_*` | gateway | key hashes; upstream URLs |
| `RUN_WORKER_IN_API` | api | dev/early staging only (OQ-021) |
`.env` files are git-ignored; commit only `.env.example` with fake values.

## 2. Docker image standard (each service)
- Build context = `microservice/` (so `libs/platform_contracts` is copyable). `docker build -f services/<x>/Dockerfile .`
- Multi-stage `python:3.12-slim` (pin digest in CI); install from the lockfile (`uv`), no dev deps; copy only `libs/platform_contracts` + the service.
- Non-root user; no secrets in layers; `HEALTHCHECK` on `/health/live`.
- One image, two commands: api `uvicorn app.main:app --host 0.0.0.0 --port $PORT`; worker `python -m app.worker`.
- **Migrations never run at container start.** Render pre-deploy / K8s Job runs `alembic upgrade head`.
- Tag `registry/karobarone/<service>:<git-sha>`; promote the same digest staging → prod.
Acceptance: image builds; runs as non-root (`id -u` ≠ 0); `/health/ready` OK against compose Postgres; trivy clean for policy severity.

## 3. Local compose
`deploy/compose/docker-compose.yml`: `postgres:16` (mount `tools/db/bootstrap.sql`), `minio` + `minio-init` (S3 object storage on port 9000, console on 9001; auto-creates private bucket `karobarone-media`), `mailpit` (when IAM OTP), `gateway`, the monolith (until cut over), 8 services, workers. Healthchecks + `depends_on: condition: service_healthy`.
MinIO standalone setup script: `python tools/storage/setup_minio.py` ensures bucket readiness and private ACLs.
Commands: `make up`, `make down`, `make migrate SERVICE=tenant`, `make test SERVICE=tenant`, `make e2e`, `make build-all`.

## 4. Neon + Render
### 4.1 Neon (one project)
1. Create project; branches `main` (prod), `staging`, `dev`. Test every migration on a branch first.
2. As the owner role run `tools/db/bootstrap.sql` on each branch: schemas, `<schema>_svc` (DML on own schema), `<schema>_migrator` (DDL on own schema), revoke cross-schema.
3. Build two URLs per service: pooled (`…-pooler…`) for `DATABASE_URL`, direct for `MIGRATION_DATABASE_URL`. asyncpg: `ssl=require`, not `sslmode`.
4. Prod compute: paid, autosuspend disabled (cold start adds latency). Pooler = transaction mode: no session advisory locks, no LISTEN/NOTIFY; `SET LOCAL` and `FOR UPDATE SKIP LOCKED` inside transactions are fine; `statement_cache_size=0`.
### 4.2 Render blueprint (sketch — agent completes it)
```yaml
services:
  - type: web                     # only public service
    name: gateway
    runtime: docker
    dockerfilePath: ./services/gateway/Dockerfile
    dockerContext: .
    healthCheckPath: /health/ready
    envVars:
      - {key: GATEWAY_API_KEYS, sync: false}
      - {key: UPSTREAM_TENANT, fromService: {type: pserv, name: tenant, property: hostport}}
      - {key: UPSTREAM_MONOLITH, sync: false}
  - type: pserv                   # private service: not reachable from the internet
    name: tenant
    runtime: docker
    dockerfilePath: ./services/tenant/Dockerfile
    dockerContext: .
    preDeployCommand: alembic upgrade head      # reads MIGRATION_DATABASE_URL
    envVars:
      - {key: DATABASE_URL, sync: false}
      - {key: MIGRATION_DATABASE_URL, sync: false}
      - {key: MY_SERVICE_KEY, sync: false}
      - {key: SERVICE_KEY_HASHES, sync: false}
  - type: worker
    name: tenant-worker
    runtime: docker
    dockerfilePath: ./services/tenant/Dockerfile
    dockerContext: .
    dockerCommand: python -m app.worker
    envVars: [ ...same secrets... ]
```
Notes: private services and workers need paid instances; free web services sleep. Auto-deploy only from `main` after CI. Secrets are `sync: false` (set in the dashboard). Keep render.yaml at the repo root, or point the Blueprint to its path.
### 4.3 Cost mode (BTDD §3.3 allows temporary co-deployment)
9 services + 8 workers is expensive. Options, cheapest first: (a) `RUN_WORKER_IN_API=true` on staging/early prod (one process per service; off once load grows); (b) deploy only the services you have built; (c) merge small services into one deployable keeping separate modules, schemas and contracts. Keep the code layout identical so splitting later needs no data rewrite.
### 4.4 Rollout & rollback
Gateway route table = per-prefix upstream. Cut over one service: set its upstream to the new service. **Rollback = flip the line back to the monolith.** Keep the monolith path until the soak period passes. DB rollbacks: roll forward; migrations are expand → backfill → switch → contract.
### 4.5 Scheduler safety on restarts
Render restarts workers freely. Jobs are claimed with `SKIP LOCKED`, transitions are state-guarded and keyed by `business_key`, so a restart or two replicas never double-charge or double-expire.

## 5. Kubernetes (Phase 12; local validation; not used by Render)
`deploy/k8s` Kustomize `base/` + `overlays/{dev,staging,prod}`. Per service: Deployment (api), Deployment (worker), Service (ClusterIP), ConfigMap, Secret refs, ServiceAccount (own, token automount off), probes (`/health/live`, `/health/ready`), requests/limits, HPA (api), PDB (when ≥2 replicas), `securityContext` (runAsNonRoot, no privilege escalation, drop ALL, read-only root fs + `/tmp` emptyDir). Namespace default-deny NetworkPolicy; allow gateway → services, services → Neon (egress 5432/TLS) + other needed services, DNS; ingress only for the gateway. Migration `Job` per service (own migrator secret). Database is external (Neon): a Secret for the URLs; an in-cluster Postgres overlay exists **only** for kind. Script `tools/k8s/kind-up.sh` builds, loads images into kind, applies the dev overlay, runs smoke. Document all commands in `docs/k8s.md`.

## 6. Observability (Phase 12)
JSON logs → platform logs; OTel traces with correlation id HTTP → relay → inbox; `/metrics` internal only with bounded labels (route template, status class, event type); alerts: outbox oldest-age, dead events, scheduler lateness, readiness failing, auth failure spikes.

## 7. Release checklist
- [ ] CI green (lint, types, unit, integration, migrations fresh+upgrade, contracts, scans, AC coverage)
- [ ] Same image digest staging → prod; migration ran as a pre-deploy step and recorded
- [ ] Smoke + e2e on staging; rollback line ready
- [ ] No secrets in repo/images; dev stubs off in prod; `/docs` off in prod
- [ ] OPEN_QUESTIONS blockers for this phase answered
