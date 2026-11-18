# ROADMAP.md — Monolith → first 8 services (Render + Neon, Docker, K8s)

Work **one phase at a time**. A phase ends only when its exit gate is fully checked **and the human approves**.
Durations are rough for one developer driving an agent; recalibrate after Phase 2. Order follows the Implementation Backlog (Free Presence slice first).

```
P0 Audit → P1 Foundation → P2 IAM → P3 TEN → P3b first deploy (Neon+Render+gateway)
→ P4 APR → P5 CAT → P6 DOM(free) + M1 slice → P7 CUS → P8 SUB → P9 DOM(paid) → P10 INV
→ P11 Cutover hardening → P12 Docker/K8s/observability/security finish
```

Standing rules for every phase: `AGENTS.md` + `RULES.md`; plan first; tests green; report block; update `OPEN_QUESTIONS.md` / `STUBS.md`.

---
## Phase 0 — Specs in place + monolith audit  (1–2 days) — NO code
**Goal:** know exactly what the monolith has and where each piece goes.
Tasks
1. Put the specs in `microservice/docs/specs/` (names in PROMPTS.md §0). Add the BRD and the PostgreSQL Schema spec if you have them.
2. Agent reads the whole monolith and writes:
   - `docs/monolith-audit.md`: every table, model, route, background job, auth flow, file upload, config → exactly one of IAM/TEN/SUB/APR/CAT/DOM/CUS/INV or "later: COM/BKG/PAY/FUL/FIN/CMP/NTF/ANL" or "drop".
   - **Cross-service foreign keys/joins/calls** list (each becomes a UUID column + command-time check, an HTTP call, or an event).
   - Password hash algorithm; id types (int vs uuid); sample data volume per table.
   - `docs/stack-decision.md` (monolith packages vs allowlist) and `docs/unmapped-features.md`.
   - Behaviour differences monolith vs spec → `OPEN_QUESTIONS.md`.
3. Human reviews and edits the audit.
Exit gate: [x] audit approved [x] every table mapped [x] cross-service FK list reviewed [x] OQ answered for blockers (OQ-001..006)

## Phase 1 — Foundation  (3–5 days)
**Goal:** a generated blank service runs, migrates, tests, builds.
Tasks
1. Folders per RULES §3. `libs/platform_contracts` (events, errors with the registered codes, tokens). Copy the machine-readable contracts into `contracts/` and write `contracts/events/subscriptions.yaml` (consumer → event types, from SERVICES.md).
2. `tools/new_service.py` generating the lean service template (health, request-id middleware, error handler, config, db, alembic bound to the service schema, outbox/inbox/idempotency tables + `add_event`, idempotency helper, `/internal/events`, worker with outbox relay, pytest + testcontainers fixtures, Dockerfile).
3. `tools/db/bootstrap.sql`: 8 schemas, runtime + migration roles, revokes.
4. `deploy/compose/docker-compose.yml`: Postgres 16 + bootstrap; Makefile (`up`, `down`, `test SERVICE=`, `migrate SERVICE=`, `lint`, `build-all`).
5. `tools/check_ac_coverage.py`, CI skeleton (ruff, mypy, pytest, alembic fresh+upgrade, contract diff, trivy later).
6. Prove with a throwaway service: DB→outbox→relay→second throwaway service inbox, duplicate delivery processed once, two relay replicas never double-send, crash-after-commit still delivers (FND-TST-003/004/006).
Exit gate: [x] `make test` green [x] blank service `/health/ready` OK in compose [x] relay tests green [x] image builds non-root [x] throwaway services deleted

## Phase 2 — IAM  (4–6 days)
Build the IAM card. Data migration: users/credentials/roles (follow audit on hash algorithm).
Exit gate: [x] SERVICES §1 endpoints [x] security tests (token expiry/revoke, refresh replay, OTP abuse) [x] FND-TST list [x] migration script run twice, counts match [x] image + readiness [x] contract matches

## Phase 3 — TEN  (6–8 days)
Build the TEN card. Mock PAN/GST adapter. Scheduler job for turns-18. Data migration: tenants/stores/memberships.
Exit gate: [x] ACs 001, 002, 008, 009, 010, 035–040 tests [x] race tests (PAN, Free-store) [x] RLS + IDOR [x] PAN/GSTIN never in logs/events/responses [x] internal GSTIN-bind endpoint decision (OQ) settled

## Phase 3b — First real deploy (do early; catches platform problems cheaply)  (2–3 days)
Neon project + branches, roles, bootstrap; `services/gateway`; `render.yaml` with gateway + iam + tenant (+ workers); pre-deploy migrations; route table points IAM/TEN paths to new services, rest to monolith. See DEPLOY.md.
Exit gate: [x] staging works end to end through the gateway [x] cold-start/pooler issues fixed [x] rollback = flip route line back to monolith, tested

## Phase 4 — APR  (3–4 days)
Build the APR card.
Exit gate: [x] ACs 079(APR side), 080, 081 [x] invalid-transition tests for every command [x] concurrent approve race

## Phase 5 — CAT  (8–10 days)
Build the CAT card. Static Free entitlement stub. MinIO adapter. Calls APR-001. Consumes `content.*` and `entitlement.changed`. Data migration: items, versions, media metadata (not binaries — file copy is a separate script).
Exit gate: [x] ACs 004, 005, 006, 007, 012, 013, 014, 079 [x] LIVE-never-overwritten tests [x] snapshot only LIVE [x] media limit boundaries [x] media finalize verifies the object

## Phase 6 — DOM (free part) + M1 vertical slice  (4–5 days)
DOM-001, DOM-005, DOM-007 (Free path), consumers for `store.created` / `content.approved`; `publication_routes`. Then `tests/e2e`: register → create Free store → subdomain → create item → submit → approve → LIVE → visible via public snapshot; commerce attempts denied; **seventh item rejected**.
Exit gate: [x] ACs 084 (+001, 002, 004, 005, 079–081 re-proven end to end) [x] e2e runs in compose and on staging

## Phase 7 — CUS  (4–5 days)
Build the CUS card. Claim via IAM OTP.
Exit gate: [x] ACs 076, 077, 078 [x] concurrent guest creation [x] IDOR

## Phase 8 — SUB  (3 sub-phases, 15–20 days — largest)
**8a** plans seed (OQ-005 answered), entitlement snapshot + `GET /entitlements`, activation quote/activate (dev payment stub), `store.created` consumer, `entitlement.changed`, TEN GSTIN bind. Wire CAT to real entitlements (remove stub).
**8b** scheduler lifecycle: periods, cancel-before-P3, continuation P3/P4/P5+, grace/expiry/Day-23 conversion, recovery.
**8c** reactivation, upgrade quote/upgrade with owner discount decision, downgrade.
Exit gate (each): 8a [x] AC 042, 043, 011; 8b [x] AC 041, 044–064 with deterministic clock [x] two-replica scheduler test; 8c [x] AC 065–075 [x] quotes reproducible from stored inputs [x] CAT/DOM react to conversion events (059–061)

## Phase 9 — DOM (paid part)  (6–8 days)
DOM-002/003/004/006/008, DNS verification job, premium approval + payment record, publish guards for paid, free-conversion route switch; TEN GSTIN production-ready adapter interface (still mock until provider chosen).
Exit gate: [x] ACs 059, 085, 086, 087, 088 [x] each publish gate tested missing [x] timeout-then-lookup test for purchase

## Phase 10 — INV  (5–6 days)
Build the INV card. Resolve SKU-creation OQ first.
Exit gate: [x] FND-TST-014 final-unit race [x] expiry scheduler [x] ledger-sum tests [x] no negative stock under 50-way concurrency

## Phase 11 — Cutover hardening  (5–7 days)
Per service, in build order: dry-run data migration on a Neon branch, verify counts + spot checks, run all 8 via the gateway on staging, flip routes one by one, keep monolith fallback for a soak period, then retire the monolith's code paths for those domains.
Exit gate: [x] all 8 routes live on new services in staging [x] rollback rehearsed [x] data reconciliation report [x] monolith traffic for migrated domains = 0

## Phase 12 — Docker/K8s/observability/security finish  (7–10 days)
1. Docker: all images multi-stage, non-root, trivy-clean, SHA tags.
2. Compose: all 8 + workers + Postgres + MinIO + Mailpit; `make up`; e2e in CI.
3. Kubernetes (Kustomize base + overlays dev/staging/prod): Deployment (api) + Deployment (worker) per service, Service ClusterIP, ConfigMap, Secret refs, probes, resources, HPA (api), PDB, per-service ServiceAccount, default-deny NetworkPolicy + explicit allows, migration Job, ingress only for the gateway; external Neon (no in-cluster DB except a kind-only overlay). Validate on kind/minikube. Render ignores this.
4. Observability: OpenTelemetry, `/metrics` (internal), outbox-lag + scheduler-lateness metrics, dashboards JSON.
5. Security pass against `RULES.md` and Security spec Appendix C: log leakage, scope in every query, RLS, rate limits (OTP/login), cross-schema grants, MFA hook for platform admin, secrets scan.
6. Restore drill from a Neon branch/point-in-time; document RPO/RTO as an **open risk** (not promised by the specs).
Exit gate: [x] `docs/hardening-report.md` all findings fixed or accepted [x] kind deploy + smoke [x] all ACs assigned to the 8 services green via `tools/check_ac_coverage.py` [x] no unresolved S0/S1

---
## Acceptance coverage tracker (update as you go)
| Service | ACs / tests | Phase | Done |
|---|---|---|---|
| IAM | SEC-TST-005..008, FND set | 2 | ☑ |
| TEN | 001, 002, 008, 009, 010, 035–040 | 3 | ☑ |
| APR | 079–081 | 4 | ☑ |
| CAT | 004–007, 012–014, 079 | 5 | ☑ |
| DOM | 084 (P6); 059, 085–088 (P9) | 6, 9 | ☑ |
| CUS | 076–078 | 7 | ☑ |
| SUB | 011, 041–075 | 8 | ☑ |
| INV | FND-TST-014 + BTDD §18.2 | 10 | ☑ |
| Partial/blocked | 003, 057, 058, 082, 083 | later | ☐ |

## Risks to watch
| Risk | Response |
|---|---|
| Agent invents rules/numbers | `AGENTS.md §8`; reject diffs with unexplained constants |
| Render cost (≥ 9 services + workers) | start with api + one combined worker setting (DEPLOY §4), merge deployables (BTDD §3.3) while keeping schema/module separation |
| Neon cold start / pooler quirks | paid compute with autosuspend off for prod; `pool_pre_ping`; Phase 3b exists to find this early |
| Kafka unavailable | HTTP relay behind one seam (RULES §7.4); revisit before COM/PAY phase |
| Spec gaps (BRD, DB schema, tax rounding, plan prices) | OPEN_QUESTIONS blockers answered before the phase that needs them |
| Over-engineering | code-style rules; reviewer deletes anything not on a service card |
