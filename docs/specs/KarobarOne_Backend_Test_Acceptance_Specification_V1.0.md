**KAROBARONE**

**Backend Test & Acceptance
Specification**

Implementation-grade QA baseline for API, database, event, workflow, concurrency, security and BRD acceptance verification

**Specification Version 1.0  |  14 September 2026**

Derived from: BRD V2.1 | Backend Technical Design V1.0 | PostgreSQL Schema V1.0 | State Machine & Business Rules V1.0 | REST API & Kafka Event Contract V1.0 | Repository & Engineering Foundation V1.0

# Document Control

| Field | Value |
| --- | --- |
| Document Version | 1.0 - Initial Backend Test & Acceptance Baseline |
| Status | Implementation / QA Specification |
| Effective Date | 14 September 2026 |
| Product | KarobarOne |
| Business Authority | KarobarOne BRD V2.1 - Final Consolidated |
| Technical Inputs | Backend Technical Design V1.0; PostgreSQL Schema Specification V1.0; State Machine & Business Rules V1.0; REST API & Kafka Event Contract V1.0; Repository & Engineering Foundation V1.0 |
| Primary Users | QA Engineering, Backend Engineering, Architecture, Product, Security, DevOps/SRE, Database and Release Management |
| Purpose | Define how KarobarOne backend correctness is verified and how AC-001..AC-090 become release-blocking executable acceptance tests. |

Authority - The BRD remains authoritative for business acceptance. The State Machine specification defines allowed transitions and the API/Event specification defines network contracts. This document defines verification; it must not silently change product behavior.

Release-blocking rule - AC-001 through AC-090 form the mandatory backend acceptance baseline. A release that changes an affected domain must not be promoted if its relevant acceptance tests fail; the full mandatory suite must pass for release certification.

# Document Contents

- 1. Purpose, Scope and Normative Hierarchy
- 2. Quality Strategy and Risk Model
- 3. Test Layers and Ownership
- 4. Test Environments and Dependency Strategy
- 5. Test Data, Fixtures and Clocks
- 6. Test Case Structure and Naming
- 7. API and Authorization Testing
- 8. Database, RLS and Migration Testing
- 9. Kafka, Outbox, Inbox and Consumer Testing
- 10. Webhook and External Integration Testing
- 11. Scheduler, Time and Lifecycle Testing
- 12. Concurrency and Race-Condition Testing
- 13. Financial and Ledger Testing
- 14. Security and Privacy Testing
- 15. Observability and Operational Testing
- 16. Performance and Resilience Testing
- 17. Contract Testing - OpenAPI / AsyncAPI / JSON Schema
- 18. CI/CD Test Execution and Release Gates
- 19. Defect Severity, Triage and Exit Criteria
- 20. Cross-Cutting Mandatory Engineering Test Registry
- 21. Acceptance Test Specification - AC-001..AC-090
- 22. Milestone Test Packs
- 23. Evidence, Reporting and Auditability
- 24. Definition of Done for Backend Testing
- Appendix A - Acceptance Coverage Matrix
- Appendix B - Test Repository Layout
- Appendix C - Recommended Pytest Markers and Commands
- Appendix D - Release Certification Checklist

# 1. Purpose, Scope and Normative Hierarchy

This specification converts KarobarOne business acceptance criteria and engineering invariants into a testable backend verification plan. It defines the minimum test layers, deterministic fixtures, concurrency scenarios, provider/webhook simulations, release gates and evidence required before a backend capability is considered complete.

## 1.1 In Scope

- All 16 logical backend services and their owned PostgreSQL schemas.
- All state-changing REST commands and high-value queries defined by the API contract.
- Kafka event production/consumption, transactional outbox, inbox deduplication, retry and DLQ behavior.
- PostgreSQL constraints, RLS, SQLAlchemy repositories, Alembic migrations and transaction boundaries.
- Subscription, order, booking, payment, refund, fulfilment, commission, GST, approval, domain and risk state machines.
- Razorpay/Shiprocket-style provider webhook verification, replay and reconciliation behavior using sandbox/fake adapters.
- Security, authorization, IDOR, sensitive-data handling, auditability, observability and resilience.
- All AC-001 through AC-090 as executable acceptance tests.

## 1.2 Normative Hierarchy

| Priority | Artifact | Testing authority |
| --- | --- | --- |
| 1 | KarobarOne BRD V2.1 | Business requirements and AC-001..AC-090. |
| 2 | State Machine & Business Rules V1.0 | Allowed states/transitions, guards, side effects and timer behavior. |
| 3 | PostgreSQL Schema Specification V1.0 | Persistence constraints, RLS, concurrency and retention rules. |
| 4 | REST API & Kafka Event Contract V1.0 | HTTP/event surface, schemas, idempotency and compatibility rules. |
| 5 | Repository & Engineering Foundation V1.0 | Test locations, CI gates, runtime/tooling standards. |
| 6 | This specification | Verification procedures, release gates and acceptance test design. |
| 7 | Test code and fixtures | Must conform to all higher-authority artifacts. |

# 2. Quality Strategy and Risk Model

KarobarOne is not primarily a CRUD system. Its highest backend risks are incorrect commercial calculations, illegal lifecycle transitions, tenant-isolation failures, duplicate event/webhook side effects, scheduler boundary errors and concurrency races. Testing therefore follows a risk-based layered strategy rather than relying on endpoint happy paths.

| Risk class | Examples | Required verification |
| --- | --- | --- |
| Critical financial | Subscription advance, commission, refunds, platform invoices | Policy unit tests + immutable snapshot/ledger DB tests + event/workflow acceptance tests. |
| Critical isolation | Tenant/store authorization, RLS, IDOR | API authorization + direct DB RLS tests + cross-tenant negative cases. |
| Critical concurrency | Final SKU, slot capacity, duplicate webhook, invoice scheduler | Real PostgreSQL concurrency/integration tests; no mocked-only proof. |
| Critical lifecycle | P3 cancellation, Day-8/23 transitions, content approval, booking states | State-machine unit/property tests + deterministic clock/scheduler tests. |
| Contract compatibility | OpenAPI/event schemas, stable errors | Schema validation and compatibility diff in CI. |
| Integration reliability | Razorpay/Shiprocket callbacks, missed events | Signed/fake webhook tests, replay/out-of-order tests, reconciliation tests. |
| Operational | Outbox backlog, DLQ, migration, observability | Failure injection, recovery tests, metrics/log/trace assertions. |

# 3. Test Layers and Ownership

| Layer | Primary location | Purpose | Default owner |
| --- | --- | --- | --- |
| Unit / policy | services/<svc>/tests/unit | Pure calculations, validators, policy functions, state guards, money/date rules. | Service engineering + QA |
| Repository / DB | services/<svc>/tests/integration | SQLAlchemy mappings, constraints, RLS, transactions, locks and concurrent updates. | Service engineering + DB/QA |
| API integration | services/<svc>/tests/integration | FastAPI request/response, authz, idempotency and real ephemeral dependencies. | Service engineering + QA |
| Contract | services/<svc>/tests/contract + /contracts | OpenAPI, AsyncAPI, JSON Schema and examples compatibility. | Architecture + QA |
| Consumer/event | service integration tests | Duplicate delivery, replay, retry, DLQ and business-key idempotency. | Service engineering + QA |
| Workflow/E2E | /tests/e2e | Cross-service orchestration including failure/retry/reconciliation. | QA + owning services |
| Acceptance | /tests/acceptance | Stable AC-001..AC-090 business baseline. | QA/Product + owning services |
| Security | service/repository CI | Authorization isolation, IDOR, webhook validation, rate limits, leakage. | Security + QA |
| Performance | /tooling/load-tests | Inventory/booking contention, webhook bursts, checkout/admin paths. | SRE/Performance + QA |

# 4. Test Environments and Dependency Strategy

| Environment | Data | Dependencies | Use |
| --- | --- | --- | --- |
| local | Synthetic/resettable | Containerized PostgreSQL, Kafka, Redis, S3-compatible store, mail capture, fake SMS/provider adapters | Developer and fast integration testing. |
| CI ephemeral | Synthetic per job | Ephemeral PostgreSQL/Kafka/Redis; deterministic fake/sandbox adapters | Unit, migration, integration, contract, impacted acceptance. |
| dev | Synthetic/shared | Shared service deployments and test integrations | Cross-service exploratory and workflow validation. |
| staging | Synthetic/masked only | Production-like topology; provider sandboxes where safe | Release candidate, security, load, reconciliation and full acceptance. |
| prod | Real customer data | Production dependencies | Smoke/health/reconciliation only; no destructive acceptance data creation unless explicitly designed and isolated. |

Provider tests must use adapter-controlled fakes or official sandbox/test modes where possible. Tests must not depend on unstable live third-party behavior for deterministic CI acceptance.

# 5. Test Data, Fixtures and Clocks

- All automated fixtures use synthetic PAN/GSTIN/government-ID-like values; never use real personal or production credentials.
- Factories create explicit tenant_id/store_id ownership and avoid hidden global defaults.
- Commercial fixtures snapshot plan version, price, tax, discount, shipping and commission inputs used by the scenario.
- Time-bound tests use an injected clock abstraction; sleeping in tests is prohibited for 30-day periods, 15-day dues, 10-minute reservations and OTP/download expiry.
- Provider callbacks are represented by canonical signed fixtures with valid, invalid, duplicate, replayed and out-of-order variants.
- Kafka fixtures include event_id, aggregate version/effective timestamp, correlation_id and causation_id.
- Database fixtures expose helpers to set RLS transaction context for tenant/store/actor and to verify cross-scope denial.

# 6. Test Case Structure and Naming

Acceptance tests use stable names such as test_ac_041_billing_period_exactly_30_days. Engineering invariant tests use domain prefixes such as FND-TST, SEC-TST, EVT-TST, DB-TST or CON-TST. Test IDs remain stable even when implementation changes.

| Field | Required content |
| --- | --- |
| Test ID | Stable AC-* or engineering ID. |
| Requirement source | BR/AC/state/API/event reference where applicable. |
| Owner | Primary service(s) and QA owner. |
| Preconditions | Persisted state, entitlements, provider context, clock and fixtures. |
| Action | Single command/event/scheduler/reconciliation action or explicit concurrent actions. |
| Expected | HTTP/state/DB/event/audit result; negative side effects also stated. |
| Automation layer | Unit / DB / API / event / workflow / acceptance / security / performance. |
| Evidence | Assertions, audit/event IDs, DB snapshots and CI result link. |

# 7. API and Authorization Testing

- Every endpoint validates actor class, JWT/service identity, tenant/store assignment and resource ownership.
- High-value commands re-check mutable entitlement/lifecycle/restriction state; token role claims alone are insufficient.
- Every retry-sensitive POST verifies Idempotency-Key semantics, including same-key/same-payload and same-key/different-payload cases.
- Every conflict-prone write verifies expected_version/If-Match and STALE_VERSION behavior.
- Every state-changing command verifies invalid-from-state rejection using the stable error taxonomy.
- Public endpoints are checked for data-minimization and inability to access draft/internal/sensitive fields.
- Error responses must use the standard error envelope and must not expose raw SQL/provider exceptions.

# 8. Database, RLS and Migration Testing

- Unique/check constraints are tested both through service APIs and direct repository-level invalid writes.
- RLS tests intentionally omit application tenant predicates to prove the database still blocks cross-tenant access.
- Financial/commercial/audit tables are tested for append-only/compensating behavior where the schema requires it.
- Inventory/capacity/subscription scheduler paths use real transaction locking/atomic conditional updates in tests.
- Every migration is tested from an empty database and from the previous supported revision with representative data.
- Cross-service hard FK creation is prohibited by schema review/automated metadata checks unless formally approved.
- Fresh migration and upgrade tests verify service schema ownership/roles and required indexes where contractually material.

# 9. Kafka, Outbox, Inbox and Consumer Testing

- Business mutation + state/audit + outbox row must be one local transaction.
- Kafka publish retries reuse the same event_id and never duplicate aggregate mutation.
- Every consumer verifies duplicate event delivery, retry after transient failure, stale/out-of-order event handling and poison-message DLQ path.
- processed_events/inbox dedupe is committed in the same transaction as consumer side effects.
- Financial effects use unique business keys in addition to transport event dedupe.
- Consumers tolerate additive unknown fields for compatible .v1 schemas and ignore unsupported event types safely.
- Kafka is never used as the authoritative timer; scheduler-driven facts are tested separately.

# 10. Webhook and External Integration Testing

| Scenario | Expected verification |
| --- | --- |
| Valid signed callback | Durably accepted, raw callback/evidence stored, normalized once, downstream event emitted after commit. |
| Invalid signature/auth | 4xx/rejection; security/audit signal; no business transition. |
| Duplicate provider event | 2xx-safe replay response where appropriate; no duplicate payment/refund/shipment/commission side effect. |
| Out-of-order callback | No state regression; event parked/ignored/audited according to adapter policy. |
| Unknown provider event | Retained for investigation; no unsafe business mutation. |
| Provider outage/missed webhook | Reconciliation discovers authoritative state and repairs through idempotent approved path. |
| Provider disconnect | Online payment path is disabled as specified; unrelated eligible workflows such as approved COD may remain available. |

# 11. Scheduler, Time and Lifecycle Testing

All date/time behavior must be tested with an injected clock and explicit boundary values. The suite must include just-before, exact-boundary and just-after cases for every material lifecycle transition.

| Clocked rule | Mandatory boundary tests |
| --- | --- |
| Inventory reservation | Before TTL, at TTL, after TTL; duplicate expiry workers. |
| Booking payment deadline | Before deadline, exact deadline, after deadline; capacity release race. |
| Subscription | 30-day period calculation; P3 cancellation boundary; Day 1/7/8/22/23 delinquency; scheduled downgrade. |
| Commission invoice | Weekly cutoff idempotency; due date +15 calendar days; overdue restriction reevaluation. |
| Minor Tenant | Day before 18th birthday, exact adult threshold, repeated scheduler execution. |
| OTP/download links | Before/at/after expiry and maximum-use/download-count boundary. |

# 12. Concurrency and Race-Condition Testing

- Two buyers race for final tracked SKU: exactly one reservation succeeds.
- Two customers race for final appointment capacity: capacity is never exceeded.
- Duplicate Razorpay/Shiprocket callbacks cannot cause duplicate state transitions or financial effects.
- Two refund/reschedule commands on the same aggregate cannot both commit from the same version/state.
- Two scheduler replicas cannot create the same subscription transition/charge or reservation expiry twice.
- Two commission invoice workers cannot invoice the same commission record twice.
- Concurrency tests run against real PostgreSQL transactions; mocked repositories are insufficient evidence.

# 13. Financial and Ledger Testing

- All money calculations use Decimal/NUMERIC/minor-unit convention; binary floating point is prohibited.
- Historical calculations use stored plan/rate/tax/discount/snapshot inputs, not current configuration.
- Subscription advance movements balance and are never double-applied.
- Period 3/4 continuation charges and advance credits reconcile to the approved commercial model.
- Reactivation and upgrade calculations are tested as formulas plus persisted quote/ledger outcomes.
- Commission excludes GST/shipping and uses the snapshotted rate/base from the originating transaction.
- Refund/cancellation/reschedule corrections create compensating credit/reversal records; historical amounts are not destructively overwritten.
- Ledger reconstruction must reproduce authoritative balances used by reporting/reconciliation.

# 14. Security and Privacy Testing

| Control | Mandatory tests |
| --- | --- |
| Tenant/store isolation | Cross-tenant API IDOR + direct RLS read/write denial. |
| Roles | Platform, store owner/staff, customer, guardian and service principal scope separation. |
| Guardian | Guardian consent role does not automatically grant operational store-management permission. |
| Secrets/PII | PAN/GSTIN/government ID/OTP/provider secrets absent from ordinary logs, traces and unsafe errors. |
| OTP | Expiry, attempt limit, rate limit, replay/single-use where applicable. |
| Webhook security | Signature/auth validation and replay protection. |
| Admin paths | Explicit elevated role required; no tenant_id=NULL shortcut. |
| Uploads/downloads | Private object storage; signed URL expiration and non-guessable access; no permanent digital-product URL. |

# 15. Observability and Operational Testing

- HTTP -> outbox -> Kafka -> consumer trace retains request_id/correlation_id and trace context.
- Health endpoints distinguish liveness from readiness; metrics endpoint is not publicly exposed.
- Outbox backlog, Kafka consumer lag, DLQ, scheduler delay and provider reconciliation metrics can be observed in staging.
- Operational log failure cannot substitute for required append-only audit/history row; tests assert authoritative evidence exists.
- Alerting smoke tests cover critical backlog/reconciliation conditions before production readiness.

# 16. Performance and Resilience Testing

Performance testing is risk-targeted. Numerical SLO/load thresholds are established from staging measurements and production capacity planning; this specification does not invent business throughput requirements absent from the source documents.

| Workload | Test focus |
| --- | --- |
| Checkout burst | Inventory lock contention, payment-intent fan-out, API latency/error under concurrency. |
| Booking hot slot | Capacity contention and lock duration. |
| Webhook burst | Deduplication throughput, raw-event persistence and downstream lag. |
| Kafka backlog | Consumer catch-up, retry/DLQ behavior and no duplicate effects. |
| Scheduler backlog | Catch-up safety after downtime; idempotent due-job claims. |
| Admin/reporting | Tenant/store/date indexes prevent unbounded transactional-table scans. |
| Database fail/restart | Connection recovery, no committed-state loss, outbox/consumer resume. |

# 17. Contract Testing - OpenAPI / AsyncAPI / JSON Schema

| Gate | Release rule |
| --- | --- |
| Generated OpenAPI | Must match committed contract or include an approved compatible contract update. |
| Breaking API diff | Blocked on v1 unless formally versioned/incompatible path is introduced. |
| Event .v1 compatibility | Additive optional fields allowed; breaking meaning/required-field changes blocked and require .v2. |
| Examples | Every committed API/event example validates against Pydantic/OpenAPI/JSON Schema. |
| Stable errors | Known business rejections return registered machine-readable error codes. |
| Registry-only source gaps | No undocumented event is silently treated as authoritative; source-contract discrepancy must be resolved or explicitly approved. |

# 18. CI/CD Test Execution and Release Gates

| Pipeline stage | Mandatory tests | Failure effect |
| --- | --- | --- |
| Static quality | Format/lint/type/import-boundary | PR blocked. |
| Unit | Affected service unit/policy/state guards | PR blocked. |
| Contracts | OpenAPI diff, AsyncAPI/JSON Schema validation/compatibility | Breaking/uncommitted change blocked. |
| Migrations | Fresh DB + previous revision upgrade | PR blocked. |
| Integration | PostgreSQL/Kafka/Redis, RLS, repositories, outbox/inbox | PR blocked. |
| Impacted acceptance | Relevant AC-* selected from changed domain | PR/release blocked as configured. |
| Security | Secret/dependency/SAST/container scans + auth tests | Severity-policy gate. |
| Staging workflow | Cross-service E2E, webhooks, scheduler/reconciliation | Promotion blocked. |
| Release certification | Full AC-001..AC-090 + required engineering invariant suite | Production promotion blocked on failure. |

# 19. Defect Severity, Triage and Exit Criteria

| Severity | Examples | Release policy |
| --- | --- | --- |
| S0 / Critical | Cross-tenant data access, incorrect customer-fund ownership, duplicate financial charge/commission, corrupted ledger | Immediate release block; incident/security escalation. |
| S1 / High | AC failure, illegal state transition, payment/webhook acceptance flaw, inventory oversell, subscription misbilling | Release block until fixed and regression added. |
| S2 / Medium | Non-critical API contract mismatch, recoverable workflow defect, incomplete audit/notification behavior | Must be resolved or explicitly risk-accepted before release. |
| S3 / Low | Diagnostic/operational polish not affecting correctness/security | May defer with tracked backlog and owner. |

Exit criteria for a backend milestone: relevant state-machine positive/negative tests pass; DB/RLS/migration tests pass; API/event contracts pass; no unresolved S0/S1; impacted AC tests pass; required security checks pass; operational evidence/alerts exist for critical asynchronous workflows.

# 20. Cross-Cutting Mandatory Engineering Test Registry

| ID | Scenario | Layer | Precondition / Action | Expected result |
| --- | --- | --- | --- | --- |
| FND-TST-001 | Idempotency - repeat same request | API/DB | Retry-sensitive command with an Idempotency-Key has completed. \| Repeat identical request with same key. | Same logical response/resource is returned; no duplicate mutation/event. |
| FND-TST-002 | Idempotency - key conflict | API/DB | A key has been stored with request hash H1. \| Reuse the key with materially different payload H2. | 409 IDEMPOTENCY_CONFLICT; original result remains authoritative. |
| FND-TST-003 | Outbox atomicity | DB/Event | Business mutation produces a transactionally significant event. \| Force failure before commit and after commit-before-publish. | No event exists for rolled-back mutation; committed mutation has durable outbox row and later publishes. |
| FND-TST-004 | Duplicate Kafka delivery | Consumer/Event | Consumer has processed event E once. \| Deliver E again with same event_id. | processed_events/inbox suppresses duplicate side effect; acknowledgement is safe. |
| FND-TST-005 | Financial business-key dedupe | Finance/Event | Financial effect for source/business key already exists. \| Replay equivalent event with new transport attempt. | Unique business key prevents duplicate receivable/credit/charge even beyond event_id dedupe. |
| FND-TST-006 | Kafka outage recovery | Event/Resilience | Kafka is unavailable after DB commit. \| Commit business mutation and restore Kafka later. | Outbox backlog persists and publishes after recovery without duplicating business mutation. |
| FND-TST-007 | DLQ poison event | Consumer/Event | Event repeatedly fails with non-transient validation/processing error. \| Exhaust bounded retry policy. | Event moves to domain DLQ with original metadata; alert/operational evidence is emitted. |
| FND-TST-008 | RLS cross-tenant read isolation | DB/Security | Tenant A and Tenant B data exist. \| Run repository query under Tenant A context with missing tenant predicate. | PostgreSQL RLS still prevents reading Tenant B rows. |
| FND-TST-009 | RLS cross-tenant write isolation | DB/Security | Tenant A session context active. \| Attempt write/update targeting Tenant B row. | Database denies or affects zero rows; no cross-tenant mutation occurs. |
| FND-TST-010 | IDOR/resource scope | API/Security | Authenticated user assigned only to Store A. \| Request Store B resource by UUID. | Access is denied/not found according to API policy; UUID possession confers no authority. |
| FND-TST-011 | Role + entitlement + restriction authorization | API/Security | Actor has correct role but entitlement/restriction blocks command. \| Attempt commercial command. | Authorization fails closed; role alone cannot bypass lifecycle/entitlement/restriction. |
| FND-TST-012 | Generic status mutation prohibited | API/State | Controlled aggregate exists. \| Attempt arbitrary PATCH/status assignment or stale client state rewind. | No generic public status mutation exists; invalid transition returns stable error. |
| FND-TST-013 | Optimistic concurrency | API/DB | Aggregate version is V+1 while client holds V. \| Submit mutation with expected_version=V. | 409 STALE_VERSION; no stale mutation/event is committed. |
| FND-TST-014 | Inventory final-unit race | Concurrency | One tracked unit remains. \| Two independent checkouts reserve concurrently. | Exactly one reservation succeeds; stock never becomes negative. |
| FND-TST-015 | Booking final-capacity race | Concurrency | One unit of slot capacity remains. \| Two booking requests reserve concurrently. | Exactly one succeeds; capacity is never exceeded. |
| FND-TST-016 | Duplicate payment webhook | Webhook/Event | A valid provider payment success event exists. \| Send same verified callback twice. | Only one payment transition, order/booking side effect and commission effect occur. |
| FND-TST-017 | Invalid webhook signature | Webhook/Security | Provider callback endpoint reachable. \| Send callback with invalid signature/auth proof. | 4xx/rejection; raw/security evidence handled per policy; no business-state mutation. |
| FND-TST-018 | Webhook replay/out-of-order | Webhook/State | Later authoritative state already processed. \| Replay older or out-of-order provider event. | Consumer does not regress aggregate; event is ignored/parked/audited as designed. |
| FND-TST-019 | Browser redirect is non-authoritative | Payment/Invariant | Payment intent is PENDING. \| Call browser-success/return path without provider confirmation. | Payment remains unconfirmed; paid state/commission cannot be triggered. |
| FND-TST-020 | Scheduler duplicate claim | Scheduler/DB | Two scheduler replicas scan same due lifecycle job. \| Run concurrently. | SKIP LOCKED/idempotency business key produces one transition/charge. |
| FND-TST-021 | Commission invoice duplicate generation | Scheduler/Finance | Eligible receivables exist for weekly invoice cutoff. \| Run two invoice workers concurrently. | Each commission line is invoiced at most once; one authoritative invoice result. |
| FND-TST-022 | Time-bound boundary precision | Clock/Policy | Injected deterministic clock available. \| Test just-before/at/just-after P3 start, Day 7/8/22/23, 10-minute TTL, 15-day due. | Transitions occur exactly at documented boundaries with no off-by-one/calendar-month errors. |
| FND-TST-023 | Migration fresh database | DB/Migration | Empty supported PostgreSQL instance. \| Apply all service Alembic migrations in canonical order. | Schema reaches head successfully with ownership/constraints/RLS as expected. |
| FND-TST-024 | Migration upgrade path | DB/Migration | Database at previous supported revision with representative data. \| Upgrade to new head. | Upgrade succeeds without destructive loss; app compatibility/rollback assumptions hold. |
| FND-TST-025 | OpenAPI drift gate | Contract | Committed OpenAPI contract exists. \| Generate OpenAPI from FastAPI implementation. | Unapproved breaking/uncommitted diff fails CI. |
| FND-TST-026 | Event schema compatibility | Contract/Event | Existing .v1 JSON schema is committed. \| Producer change modifies payload. | Backward-compatible additive change passes; breaking .v1 change fails and requires .v2. |
| FND-TST-027 | Contract examples validate | Contract | Committed request/response/event examples exist. \| Validate examples against Pydantic/OpenAPI/JSON schemas. | All examples pass; malformed examples fail CI. |
| FND-TST-028 | Sensitive log redaction | Security/Observability | Requests contain PAN/GSTIN/OTP/provider-secret-like synthetic values. \| Exercise success/error/logging paths. | Logs/traces do not expose prohibited plaintext sensitive values. |
| FND-TST-029 | Correlation propagation | Observability | HTTP command causes DB mutation, outbox event and consumer work. \| Trace one request end to end. | request_id/correlation_id and trace context propagate across HTTP -> Kafka -> worker. |
| FND-TST-030 | Dependency failure fail-closed | Resilience/Security | Critical entitlement/restriction dependency is unavailable and safe cached decision is not available. \| Attempt new commerce command. | New commerce is denied/503 as defined; existing obligations remain manageable via permitted paths. |
| FND-TST-031 | Provider reconciliation repair | Integration/Resilience | A webhook is missed but provider API reflects authoritative completed state. \| Run reconciliation job. | System repairs state idempotently through approved command/event path without rewriting history. |
| FND-TST-032 | Notification failure isolation | Workflow/Resilience | Commercial transaction commits successfully. \| Make email/SMS provider fail. | Business transaction stays committed; notification retries/fails independently. |
| FND-TST-033 | Service import boundary | Static/Architecture | Monorepo source tree exists. \| Run import-boundary/lint rule. | No service imports another service domain/infrastructure package. |
| FND-TST-034 | Money type safety | Unit/Static | Commercial calculations execute. \| Exercise money/tax/commission/subscription calculations. | Decimal/NUMERIC/minor-unit convention is used; binary floating point is absent from financial values. |
| FND-TST-035 | Audit evidence completeness | Audit/DB | Execute material state transition/admin/financial action. \| Inspect authoritative audit/history rows. | Actor/source, old/new state or material values, timestamp, correlation ID and required reason/evidence are present. |

# 21. Acceptance Test Specification - AC-001..AC-090

The following tests are the release-blocking business acceptance baseline. Each acceptance criterion should be implemented as one stable top-level test ID with helper-level subcases for positive, negative, boundary and concurrency variants where required. Expected results below describe backend-observable behavior and do not replace detailed BR/state-machine rules.

## Tenant / Store

| AC | Acceptance criterion | Primary services | Automation layer | Given / When | Then / Expected |
| --- | --- | --- | --- | --- | --- |
| AC-001 | One PAN cannot create a second tenant account | TEN, IAM | API + DB + Acceptance | Existing active tenant with verified PAN fingerprint P exists. \| Attempt to register another tenant using the same verified PAN P. | Request is rejected with TENANT_PAN_ALREADY_REGISTERED; no second tenant row is created. |
| AC-002 | One PAN cannot create a second lifetime Free Store after entitlement is consumed | TEN, IAM | API + DB + Acceptance | Tenant has already consumed its lifetime Free Store entitlement. \| Attempt to create another Free Store entitlement/store for the same PAN tenant. | Request is rejected with FREE_STORE_ENTITLEMENT_CONSUMED; entitlement consumption remains single-use. |

## Store / Entitlement / Catalog

| AC | Acceptance criterion | Primary services | Automation layer | Given / When | Then / Expected |
| --- | --- | --- | --- | --- | --- |
| AC-003 | Free Store cannot create carts, orders, bookings or checkout transactions | TEN, SUB, CAT, DOM | API + DB + Acceptance | Store is in FREE_PRESENCE. \| Attempt cart creation, product checkout, commercial order creation and service booking. | All new commerce commands are denied; portfolio/public-read capabilities remain available. |
| AC-004 | Free Store cannot showcase more than 6 products/services combined | TEN, SUB, CAT, DOM | API + DB + Acceptance | Free Store already has 6 showcased catalog items. \| Attempt to make a seventh product/service showcase item active/public. | Command is rejected; combined showcase count remains at 6. |
| AC-005 | Each Free showcase item supports max 1 image and no video | TEN, SUB, CAT, DOM | API + DB + Acceptance | Free Store catalog item exists. \| Attempt to attach a second image or any item video. | Second image/video is rejected by entitlement/media validation. |
| AC-006 | Paid catalog is not blocked by the Free six-item limit | TEN, SUB, CAT, DOM | API + DB + Acceptance | Paid store has valid active paid entitlement and more than 6 items. \| Create or activate a seventh and subsequent paid catalog item. | Paid catalog operation succeeds subject to paid-plan media/other rules; Free six-item ceiling is not applied. |
| AC-007 | Paid store may contain products and services | TEN, SUB, CAT, DOM | API + DB + Acceptance | Paid store is active. \| Create at least one product and one service in the same store catalog. | Both item classes coexist in the same paid store; checkout separation rules still apply. |
| AC-008 | Paid commerce cannot activate until GSTIN is verified against tenant PAN | TEN, SUB, CAT, DOM | API + DB + Acceptance | Store attempts paid activation with unverified or mismatched GSTIN. \| Call paid activation/activation-quote path. | Activation is blocked until GSTIN is verified as belonging to tenant PAN. |
| AC-009 | Same GSTIN cannot activate two paid stores | TEN, SUB, CAT, DOM | API + DB + Acceptance | GSTIN G is already bound to an active paid store. \| Attempt paid activation of another store using G. | Request is rejected with GSTIN_ALREADY_USED; existing binding remains unchanged. |
| AC-010 | Different GSTIN-based stores under same PAN may use different paid plans | TEN, SUB, CAT, DOM | API + DB + Acceptance | Tenant has two verified GSTINs G1/G2 bound to separate stores. \| Activate different paid plans on each store. | Each store may hold its own paid plan independently. |
| AC-011 | No turnover-based mandatory upgrade exists | TEN, SUB, CAT, DOM | API + DB + Acceptance | Paid store has high transaction/turnover values. \| Run entitlement/subscription evaluation across billing periods. | No forced upgrade is created solely due to turnover. |
| AC-012 | Commerce item media allows max 5 images and no video | TEN, SUB, CAT, DOM | API + DB + Acceptance | Commerce-plan item exists. \| Upload 5 images, then attempt a 6th image and a video. | First 5 images are allowed; 6th image and video are rejected. |
| AC-013 | Growth item media allows max 10 images + 1 video | TEN, SUB, CAT, DOM | API + DB + Acceptance | Growth-plan item exists. \| Upload 10 images + 1 video, then exceed either limit. | 10 images and 1 video are allowed; excess media is rejected. |
| AC-014 | Scale AI has no commercial media-count ceiling, subject to technical limits | TEN, SUB, CAT, DOM | API + DB + Acceptance | Scale AI item exists. \| Add media beyond Commerce/Growth commercial count ceilings while staying within technical/fair-use controls. | No plan-level commercial media-count ceiling blocks the item; only technical/fair-use limits may apply. |

## Checkout / Inventory / Fulfilment

| AC | Acceptance criterion | Primary services | Automation layer | Given / When | Then / Expected |
| --- | --- | --- | --- | --- | --- |
| AC-015 | Product/service checkout cannot be combined | COM, INV, FUL, BKG, PAY | Workflow + Concurrency + Acceptance | Cart/checkout context contains or attempts to mix product and service lines. \| Submit checkout. | Request is rejected with MIXED_CHECKOUT_NOT_ALLOWED; no mixed commercial transaction is created. |
| AC-016 | Physical and digital products may share Product Checkout | COM, INV, FUL, BKG, PAY | Workflow + Concurrency + Acceptance | One-store product cart contains a physical product and a digital product. \| Submit Product Checkout. | Checkout/order is allowed if all other guards pass. |
| AC-017 | Appointment and non-appointment services use separate transactions | COM, INV, FUL, BKG, PAY | Workflow + Concurrency + Acceptance | Store offers appointment and non-appointment services. \| Attempt to place both service types into one service transaction. | System keeps them as separate service transactions; combined transaction is rejected/not offered. |
| AC-018 | Cross-store cart/checkout is impossible | COM, INV, FUL, BKG, PAY | Workflow + Concurrency + Acceptance | Cart already belongs to store S1. \| Attempt to add item from S2 or checkout across stores. | Cross-store operation is rejected with CROSS_STORE_CHECKOUT_NOT_ALLOWED. |
| AC-019 | Self-shipping/local pickup unavailable | COM, INV, FUL, BKG, PAY | Workflow + Concurrency + Acceptance | Physical order requires fulfilment. \| Attempt SELF_SHIP or LOCAL_PICKUP fulfilment mode. | Modes are unavailable/rejected; no unsupported shipment workflow is created. |
| AC-020 | COD requires approved logistics | COM, INV, FUL, BKG, PAY | Workflow + Concurrency + Acceptance | COD is requested. \| Submit checkout without approved integrated logistics COD capability. | COD is rejected; COD is allowed only when approved logistics is available. |

## Commission / Finance

| AC | Acceptance criterion | Primary services | Automation layer | Given / When | Then / Expected |
| --- | --- | --- | --- | --- | --- |
| AC-021 | COD commission becomes receivable on confirmed delivery | FIN, PAY, BKG, FUL | Policy + Event + DB + Acceptance | COD order is delivered via approved logistics. \| Process authoritative delivery event. | Commission transitions from pending trigger to RECEIVABLE exactly once. |
| AC-022 | Prepaid commission trigger uses confirmed/verified payment receipt | FIN, PAY, BKG, FUL | Policy + Event + DB + Acceptance | Prepaid order/booking is awaiting payment. \| Send browser redirect only, then send verified provider receipt/webhook. | Redirect alone does not trigger commission; verified payment confirmation does. |
| AC-023 | Pay-after-service commission becomes receivable on booking date | FIN, PAY, BKG, FUL | Policy + Event + DB + Acceptance | Pay-after-service booking exists with commission snapshot. \| Reach the booking date under configured pay-after-service mode. | Commission becomes RECEIVABLE automatically according to booking-date trigger. |
| AC-024 | Eligible customer cancellation may reverse pay-after-service commission | FIN, PAY, BKG, FUL | Policy + Event + DB + Acceptance | Pay-after-service commission exists for a booking. \| Process an eligible customer cancellation. | Commission is cancelled/non-payable or credited according to state, with append-only adjustment history. |
| AC-025 | Seller rejection of valid booking does not automatically remove commission | FIN, PAY, BKG, FUL | Policy + Event + DB + Acceptance | Valid booking is seller-rejected after applicable commission trigger context exists. \| Process seller rejection. | Commission is not automatically removed merely because seller rejected; any later correction follows dispute/credit rules. |
| AC-026 | NO_SHOW does not remove applicable commission | FIN, PAY, BKG, FUL | Policy + Event + DB + Acceptance | Applicable pay-after-service commission exists. \| Mark booking NO_SHOW. | Commission remains applicable; no automatic cancellation/credit occurs. |
| AC-027 | Rescheduling prevents double commission | FIN, PAY, BKG, FUL | Policy + Event + DB + Acceptance | Booking with commission context is rescheduled. \| Execute valid reschedule to a new occurrence. | Old commission context is reversed/neutralized and new context created so only one final commission is payable. |
| AC-028 | Commission calculation excludes GST and shipping | FIN, PAY, BKG, FUL | Policy + Event + DB + Acceptance | Transaction has taxable value, GST and shipping components. \| Calculate commission. | Commission base uses taxable product/service value after eligible discounts/refunds and excludes GST and shipping. |
| AC-029 | Weekly commission demand has 15-calendar-day payment window | FIN, PAY, BKG, FUL | Policy + Event + DB + Acceptance | Weekly commission invoice is generated. \| Inspect invoice date and due date. | Due date equals invoice date + 15 calendar days. |
| AC-030 | Commission disputes use pay-first/credit-later model | FIN, PAY, BKG, FUL | Policy + Event + DB + Acceptance | Commission invoice is disputed. \| Attempt ordinary dispute before payment, then after payment. | Pay-first rule is enforced; successful post-payment dispute creates later credit rather than rewriting paid history. |

## GST Compliance

| AC | Acceptance criterion | Primary services | Automation layer | Given / When | Then / Expected |
| --- | --- | --- | --- | --- | --- |
| AC-031 | Commerce includes NIL GSTR-1/GSTR-3B only | CMP, FIN | Workflow + Audit + Acceptance | Commerce-plan store requests included GST filing service. \| Create NIL GSTR-1/GSTR-3B case. | NIL GSTR-1/GSTR-3B is treated as included service; no broader included filing scope is inferred. |
| AC-032 | Commerce non-NIL GST work requires separate quotation | CMP, FIN | Workflow + Audit + Acceptance | Commerce-plan store has non-NIL GST return work. \| Open GST service case. | System requires separate quotation/chargeable workflow before work proceeds. |
| AC-033 | Growth/Scale GST filing is separately chargeable | CMP, FIN | Workflow + Audit + Acceptance | Growth or Scale AI store requests GST filing. \| Open GST service case. | GST filing is treated as separately chargeable, not included by plan entitlement. |
| AC-034 | GST filing requires recorded tenant approval | CMP, FIN | Workflow + Audit + Acceptance | GST draft/version exists. \| Attempt filing without tenant approval, then approve exact draft and retry. | Filing is blocked before approval; after recorded approval of exact immutable draft/version, filing may proceed. |

## Tenant / Guardian

| AC | Acceptance criterion | Primary services | Automation layer | Given / When | Then / Expected |
| --- | --- | --- | --- | --- | --- |
| AC-035 | Registrant below 18 cannot complete required onboarding without Guardian workflow | TEN, IAM, NTF | Workflow + Security + Acceptance | Registrant age is below 18. \| Attempt to complete mandatory onboarding without guardian verification/consent. | Onboarding completion is blocked with GUARDIAN_REQUIRED. |
| AC-036 | Minor Tenant uses own verified PAN | TEN, IAM, NTF | Workflow + Security + Acceptance | Minor onboarding case exists. \| Verify identity/PAN. | Tenant identity uses the minor registrant's own verified PAN, not guardian PAN. |
| AC-037 | Minor Paid Store GSTIN must belong to Minor Tenant PAN | TEN, IAM, NTF | Workflow + Security + Acceptance | Minor Tenant attempts paid activation. \| Submit GSTIN that does not belong to Minor Tenant PAN. | Activation is blocked with GSTIN_NOT_OWNED. |
| AC-038 | Guardian government ID and signed consent must be recorded | TEN, IAM, NTF | Workflow + Security + Acceptance | Guardian workflow is required. \| Complete guardian verification and consent. | Required government-ID reference/evidence and signed/electronic consent record are stored with version/timestamp evidence. |
| AC-039 | Guardian data collection is limited to required minimum | TEN, IAM, NTF | Workflow + Security + Acceptance | Guardian onboarding is performed. \| Inspect persisted guardian profile and request payload acceptance. | Only minimum required identity, relationship, mobile/email, government-ID evidence and consent fields are required/stored; unrelated fields are absent. |
| AC-040 | Minor reaching 18 triggers adult reverification | TEN, IAM, NTF | Workflow + Security + Acceptance | Active Minor Tenant reaches age 18. \| Run due scheduler/adult-reverification job. | Tenant moves to ADULT_REVERIFICATION_REQUIRED exactly once; guardian history is retained. |

## Subscription / Plan Change

| AC | Acceptance criterion | Primary services | Automation layer | Given / When | Then / Expected |
| --- | --- | --- | --- | --- | --- |
| AC-041 | Subscription Billing Period is exactly 30 calendar days | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Paid subscription starts at timestamp/date D. \| Calculate period end and next period start. | Each Billing Period is exactly 30 consecutive calendar days; calendar-month arithmetic is not used. |
| AC-042 | First paid activation collects Period 1 fee plus 100% Third-Period Advance | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | First paid activation quote for plan price S. \| Calculate/collect initial activation. | Collection contains Period 1 fee S plus Third-Period Advance S, plus applicable tax; setup fee is handled separately per AC-043. |
| AC-043 | First-ever setup of each individual store is complimentary | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Store has never previously completed paid activation. \| Create first paid activation quote. | Initial setup fee for that store is zero/complimentary. |
| AC-044 | Period 2 requires full applicable subscription payment | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Subscription reaches Period 2. \| Generate Period 2 required charge. | Full applicable plan price is due for Period 2. |
| AC-045 | Cancellation notice can be submitted any time before Period 3 starts | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Subscription is before Period 3 start. \| Submit cancellation notice at multiple timestamps before P3 boundary. | Notice is accepted before P3; boundary at/after P3 start is rejected per state rules. |
| AC-046 | Valid cancellation before Period 3 produces INR 0 additional Period-3 payment | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Valid cancellation notice exists before Period 3. \| Calculate Period 3 amount. | Additional Period 3 subscription payment is INR 0 because the Third-Period Advance funds it. |
| AC-047 | Valid cancellation allows full paid functionality during Period 3 | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Valid cancellation notice exists and subscription is in Period 3. \| Exercise paid features during Period 3. | Paid functionality remains available through Period 3, subject to unrelated restrictions. |
| AC-048 | Valid cancellation causes paid subscription to end after Period 3 | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Valid cancellation notice exists before P3. \| Reach end of Period 3. | Paid subscription ends/converts according to rules after P3; no Period 4 paid continuation begins. |
| AC-049 | No cancellation notice means subscription continuation | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | No cancellation notice exists. \| Reach Period 3 boundary. | Subscription follows continuation path rather than end-after-P3 path. |
| AC-050 | Continuing Period 3 charge equals 50% of applicable plan price | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Continuing subscription plan price is S. \| Generate Period 3 continuation charge. | Period 3 required subscription charge equals 0.5 * S (before applicable tax). |
| AC-051 | Continuing Period 4 charge equals 50% of applicable plan price | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Continuing subscription plan price is S. \| Generate Period 4 continuation charge. | Period 4 required subscription charge equals 0.5 * S (before applicable tax). |
| AC-052 | Advance credits across Period 3 and 4 total 100% of original advance | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Initial Third-Period Advance amount is A. \| Inspect economic credit/application across Periods 3 and 4. | Total advance credit/application across P3/P4 equals 100% of A, without double application. |
| AC-053 | Period 5 onward returns to full normal subscription | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Subscription continues beyond Period 4. \| Generate Period 5 and later charges. | Each normal period from Period 5 onward returns to full applicable plan price. |
| AC-054 | Missing required payment triggers 7-day PAYMENT_GRACE | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Required subscription charge becomes unpaid at due boundary. \| Advance simulated clock through Days 1-7. | Subscription is in PAYMENT_GRACE throughout Days 1-7 and required reminders/jobs are idempotent. |
| AC-055 | Days 8-22 become SUBSCRIPTION_EXPIRED | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Charge remains unpaid after grace. \| Advance simulated clock through Days 8-22. | Subscription state is SUBSCRIPTION_EXPIRED during Days 8-22. |
| AC-056 | Day 23 unpaid converts store to Free Presence | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Charge remains unpaid through Day 23. \| Run Day-23 lifecycle job. | Store converts to FREE_PRESENCE exactly once and paid entitlements are disabled. |
| AC-057 | During SUBSCRIPTION_EXPIRED, no new orders/bookings may be created | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Store is SUBSCRIPTION_EXPIRED. \| Attempt new product order and new booking creation. | Both commands are denied; stable entitlement/subscription error is returned. |
| AC-058 | Existing obligations remain manageable during delinquency | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Store is delinquent/expired with existing orders/bookings/refunds/dues. \| Operate existing obligation workflows. | Existing obligations remain manageable according to their normal rules while new commerce stays blocked. |
| AC-059 | Free conversion stops custom-domain serving | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Paid store converts to Free Presence. \| Evaluate active publication routes. | Custom-domain serving is stopped and Free subdomain route becomes/continues active. |
| AC-060 | Free conversion leaves no more than 6 showcase items | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Paid store with more than 6 catalog items converts to Free. \| Resolve Free showcase after conversion. | No more than 6 items remain publicly showcased; other data is retained. |
| AC-061 | Higher-plan data is retained but disabled after Free conversion | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Store with paid-only data/features converts to Free. \| Inspect stored data and entitlement behavior. | Higher-plan data remains retained but is disabled/hidden; it is not destructively deleted. |
| AC-062 | Third-Period Advance does not automatically settle Period 2 while Period 2 payment is still within its normal payment/grace lifecycle | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Period 2 payment is outstanding but still in normal/grace lifecycle and advance exists. \| Run billing allocation logic. | Third-Period Advance is not automatically consumed to settle Period 2. |
| AC-063 | Unused advance may be set off against outstanding subscription at Free conversion | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Store reaches Free conversion with eligible unused advance and outstanding subscription amount. \| Run conversion/accounting set-off policy. | Eligible unused advance may be set off with auditable ledger movements. |
| AC-064 | Such set-off does not automatically restore paid status | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Advance set-off occurs at Free conversion. \| Re-evaluate subscription entitlement after set-off. | Store remains Free; set-off alone does not restore paid subscription status. |
| AC-065 | Reactivation requires full new 30-day subscription fee | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Store is Free after non-payment conversion. \| Request reactivation to paid plan price S. | Quote/collection requires a full new 30-day subscription fee S. |
| AC-066 | Reactivation Setup Fee equals 50% of selected plan fee | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Reactivation is requested for plan price S. \| Calculate setup fee. | Reactivation Setup Fee equals 0.5 * S, plus applicable tax treatment. |
| AC-067 | Reactivation date starts a new 30-day Billing Period | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Reactivation payment is confirmed at time D. \| Activate subscription. | A new 30-day Billing Period starts from reactivation date/time D. |
| AC-068 | Complimentary Initial Setup cannot be reused for reactivation | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Store previously used complimentary initial setup. \| Reactivate after Free conversion. | Complimentary setup is not reused; reactivation setup fee rules apply. |
| AC-069 | Mid-period upgrade subscription difference is prorated by remaining days | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Upgrade from lower price L to higher price H with R days remaining. \| Calculate immediate upgrade quote. | Prorated subscription difference equals (H-L)*R/30 using stored calculation/rounding policy. |
| AC-070 | Upgrade before Period 3 recalculates Third-Period Advance | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Upgrade occurs before Period 3 and existing advance was based on lower plan. \| Calculate upgrade quote. | Required Third-Period Advance is recalculated against higher-plan requirements. |
| AC-071 | Advance Top-Up equals required advance minus existing eligible advance | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Required advance is A_req and eligible existing advance A_exist. \| Calculate upgrade top-up. | Advance Top-Up = max(0, A_req - A_exist). |
| AC-072 | Gross Upgrade Setup Fee equals 50% of plan-price difference | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Lower plan price L and higher plan price H. \| Calculate gross upgrade setup fee. | Gross Upgrade Setup Fee = 0.5 * (H-L). |
| AC-073 | Upgrade Setup Fee discount requires Platform Owner approval | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Upgrade includes requested setup-fee discount. \| Attempt to apply discount without Platform Owner decision, then with approval. | Discount cannot be applied without Platform Owner approval; approved amount may then reduce setup fee. |
| AC-074 | Setup discount approval is auditable | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Platform Owner decides upgrade setup discount. \| Persist decision and inspect audit trail. | Decision records approver, amount/reason, timestamp/correlation evidence and cannot be silently rewritten. |
| AC-075 | Upgrade setup discount does not automatically waive subscription-price difference | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | Upgrade setup discount is approved. \| Calculate total upgrade charges. | Only setup-fee component is reduced; prorated subscription-price difference remains payable unless a separate approved rule exists. |

## Customer Claim

| AC | Acceptance criterion | Primary services | Automation layer | Given / When | Then / Expected |
| --- | --- | --- | --- | --- | --- |
| AC-076 | Customer email/mobile are mandatory and unique within store | CUS, IAM, NTF | API + OTP + Security + Acceptance | Customer profile is created/updated in store S. \| Omit email/mobile or duplicate either within S; then use same values in another store. | Email/mobile are mandatory and unique within S, but may independently exist in another store. |
| AC-077 | Guest checkout creates UNCLAIMED customer | CUS, IAM, NTF | API + OTP + Security + Acceptance | Guest begins eligible checkout in store S with mandatory identity data. \| Resolve/create customer. | A store-scoped customer is created/resolved in UNCLAIMED state. |
| AC-078 | Email OTP is used to claim UNCLAIMED account | CUS, IAM, NTF | API + OTP + Security + Acceptance | UNCLAIMED customer initiates claim. \| Verify claim using Email OTP flow. | Valid non-expired Email OTP moves account to CLAIMED; invalid/expired OTP does not. |

## Content Approval

| AC | Acceptance criterion | Primary services | Automation layer | Given / When | Then / Expected |
| --- | --- | --- | --- | --- | --- |
| AC-079 | Controlled content cannot go LIVE without approval | APR, CAT, DOM, CMP | State-machine + API + Acceptance | Controlled public content version is DRAFT/PENDING. \| Attempt to expose it as LIVE without approval. | Operation is blocked; existing LIVE version remains unchanged until approved. |
| AC-080 | Rejected content records reason | APR, CAT, DOM, CMP | State-machine + API + Acceptance | Reviewer rejects PENDING controlled content. \| Submit rejection. | A non-empty reason/comment is persisted with decision evidence; version does not become LIVE. |
| AC-081 | Platform Staff can emergency-unpublish suspicious/prohibited content | APR, CAT, DOM, CMP | State-machine + API + Acceptance | Suspicious/prohibited content is LIVE or PENDING. \| Authorized Platform Staff executes emergency takedown. | Content is immediately removed from public serving and takedown audit/evidence is recorded. |

## Retention / Closure

| AC | Acceptance criterion | Primary services | Automation layer | Given / When | Then / Expected |
| --- | --- | --- | --- | --- | --- |
| AC-082 | Sellers cannot delete historical commercial transactions | TEN, COM, BKG, FIN, CMP | DB + Authorization + Acceptance | Historical order/booking/payment/invoice/commission record exists. \| Seller attempts delete/destructive overwrite. | Destructive deletion is denied; record/history remains available according to retention policy. |
| AC-083 | Store with commercial history is archived rather than destructively erased | TEN, COM, BKG, FIN, CMP | DB + Authorization + Acceptance | Store with commercial history is closed. \| Execute closure process. | Store is archived/closed while required commercial history is retained; hard delete is not performed. |

## Domain

| AC | Acceptance criterion | Primary services | Automation layer | Given / When | Then / Expected |
| --- | --- | --- | --- | --- | --- |
| AC-084 | Free subdomain is immutable | DOM, SUB, TEN | Workflow + Provider-adapter + Acceptance | Free Store already has assigned subdomain. \| Attempt to rename/change Free subdomain. | Mutation is rejected; original Free subdomain remains immutable. |
| AC-085 | Paid public launch requires custom domain | DOM, SUB, TEN | Workflow + Provider-adapter + Acceptance | Paid store has active subscription but no verified custom domain. \| Attempt paid public launch. | Publication is blocked with CUSTOM_DOMAIN_REQUIRED until custom domain/DNS readiness is satisfied. |
| AC-086 | Standard qualifying domain cost is included according to commercial policy | DOM, SUB, TEN | Workflow + Provider-adapter + Acceptance | Tenant selects standard qualifying domain under active paid service. \| Calculate/record domain charge treatment. | Standard qualifying domain cost is treated according to included commercial policy; no premium surcharge is created solely for standard classification. |
| AC-087 | Premium domain requires additional approval/payment | DOM, SUB, TEN | Workflow + Provider-adapter + Acceptance | Selected domain is classified premium/non-standard. \| Attempt purchase without extra approval/payment, then with both. | Purchase is blocked until explicit approval and required additional payment are satisfied. |
| AC-088 | Domain transfer after closure is not automatic | DOM, SUB, TEN | Workflow + Provider-adapter + Acceptance | Store is closed and tenant requests domain transfer. \| Submit transfer review request. | Transfer is not automatic; a case/manual review is opened and outcome remains separate from closure. |

## Payment / Platform Funds

| AC | Acceptance criterion | Primary services | Automation layer | Given / When | Then / Expected |
| --- | --- | --- | --- | --- | --- |
| AC-089 | UPI through KarobarOne checkout is unavailable | PAY, COM, BKG, FIN | API + Webhook + Invariant + Acceptance | Customer reaches KarobarOne checkout payment-method selection. \| Request/select UPI. | UPI is absent or rejected with UPI_NOT_SUPPORTED; provider intent does not include UPI. |
| AC-090 | Platform does not hold customer purchase funds | PAY, COM, BKG, FIN | API + Webhook + Invariant + Acceptance | Online order/booking payment is initiated. \| Inspect payment provider account context and platform ledger/settlement paths. | Customer purchase consideration is directed to tenant-owned provider context; KarobarOne does not represent itself as holder/splitter/settler of customer funds. |

# 22. Milestone Test Packs

| Milestone | Mandatory acceptance focus | Engineering focus |
| --- | --- | --- |
| M0 - Foundation | Foundation harness only; no business AC certification yet | FND-TST-001..035, migrations, contracts, RLS, outbox/inbox, observability. |
| M1 - Free Presence | AC-001..014, AC-035..040, AC-076..085 as applicable to Free flow | Registration, guardian, Free entitlement, CMS approval, immutable subdomain, customer claim. |
| M2 - Subscription Core | AC-041..075 | Clocked billing/advance/upgrade/reactivation, scheduler races, ledger snapshots. |
| M3 - Paid Domain/Publication | AC-008..010, AC-084..088 | GSTIN gate, domain workflow/DNS, publication guards. |
| M4 - Product Commerce | AC-015..018, AC-022, AC-028, AC-076..078, AC-089..090 | Inventory race, checkout, payment webhook, refund, customer identity. |
| M5 - Fulfilment | AC-019..021 | Shiprocket/COD delivery authority, digital entitlement security. |
| M6 - Booking | AC-017, AC-023..027 | Capacity race, payment sequences, reschedule/no-show/cancellation. |
| M7 - Commission/Finance | AC-021..030 | Commission trigger/credit/invoice/due/suspension and financial dedupe. |
| M8 - GST/Risk | AC-031..034 plus restriction-related obligations | GST draft approval, filing workflow, restriction preservation of existing obligations. |
| M9 - Analytics/AI | Plan entitlement related ACs; no new financial mutation acceptance | Quota/entitlement and governed content approval; analytics remains derived. |
| M10 - Hardening | Full AC-001..090 | Security, load, backup/restore, reconciliation, full regression. |

# 23. Evidence, Reporting and Auditability

- Every CI acceptance run exports machine-readable results (JUnit or equivalent) with stable test IDs.
- Failed AC tests record the authoritative state, request/event ID, correlation ID and relevant fixture identifiers without leaking sensitive values.
- Financial test evidence includes calculated inputs, configured policy/version and resulting ledger/commission/charge rows.
- Webhook tests retain synthetic raw callback fixture ID, signature result and dedupe outcome.
- Concurrency failures capture transaction/lock timeline and final authoritative database state.
- Release certification stores commit SHA, image digest(s), migration revisions, contract versions and full acceptance result.

# 24. Definition of Done for Backend Testing

**☐ **Relevant unit/policy/state transition tests exist, including invalid-from-state cases.

**☐ **Database constraints, RLS and transaction behavior are covered with real PostgreSQL tests.

**☐ **Retry-sensitive API paths have idempotency and stale-version tests.

**☐ **Published/consumed events have schema, duplicate/replay and retry/DLQ tests.

**☐ **Provider webhooks have signature, duplicate, out-of-order and reconciliation tests where applicable.

**☐ **All affected AC-* tests pass and trace to requirement/service ownership.

**☐ **OpenAPI/event contract compatibility gates pass.

**☐ **No unresolved S0/S1 defects; S2 exceptions are explicitly risk-accepted with owner/date.

**☐ **Logs/traces/audit evidence satisfy sensitive-data and correlation requirements.

**☐ **Migrations are fresh/upgrade tested and operational recovery path is documented.

**☐ **Critical asynchronous workloads have monitorable metrics/alerts and runbook coverage.

# Appendix A - Acceptance Coverage Matrix

| AC | Area | Primary services | Primary test layer | Stable automated naming |
| --- | --- | --- | --- | --- |
| AC-001 | Tenant / Store | TEN, IAM | API + DB + Acceptance | test_ac_001_... |
| AC-002 | Tenant / Store | TEN, IAM | API + DB + Acceptance | test_ac_002_... |
| AC-003 | Store / Entitlement / Catalog | TEN, SUB, CAT, DOM | API + DB + Acceptance | test_ac_003_... |
| AC-004 | Store / Entitlement / Catalog | TEN, SUB, CAT, DOM | API + DB + Acceptance | test_ac_004_... |
| AC-005 | Store / Entitlement / Catalog | TEN, SUB, CAT, DOM | API + DB + Acceptance | test_ac_005_... |
| AC-006 | Store / Entitlement / Catalog | TEN, SUB, CAT, DOM | API + DB + Acceptance | test_ac_006_... |
| AC-007 | Store / Entitlement / Catalog | TEN, SUB, CAT, DOM | API + DB + Acceptance | test_ac_007_... |
| AC-008 | Store / Entitlement / Catalog | TEN, SUB, CAT, DOM | API + DB + Acceptance | test_ac_008_... |
| AC-009 | Store / Entitlement / Catalog | TEN, SUB, CAT, DOM | API + DB + Acceptance | test_ac_009_... |
| AC-010 | Store / Entitlement / Catalog | TEN, SUB, CAT, DOM | API + DB + Acceptance | test_ac_010_... |
| AC-011 | Store / Entitlement / Catalog | TEN, SUB, CAT, DOM | API + DB + Acceptance | test_ac_011_... |
| AC-012 | Store / Entitlement / Catalog | TEN, SUB, CAT, DOM | API + DB + Acceptance | test_ac_012_... |
| AC-013 | Store / Entitlement / Catalog | TEN, SUB, CAT, DOM | API + DB + Acceptance | test_ac_013_... |
| AC-014 | Store / Entitlement / Catalog | TEN, SUB, CAT, DOM | API + DB + Acceptance | test_ac_014_... |
| AC-015 | Checkout / Inventory / Fulfilment | COM, INV, FUL, BKG, PAY | Workflow + Concurrency + Acceptance | test_ac_015_... |
| AC-016 | Checkout / Inventory / Fulfilment | COM, INV, FUL, BKG, PAY | Workflow + Concurrency + Acceptance | test_ac_016_... |
| AC-017 | Checkout / Inventory / Fulfilment | COM, INV, FUL, BKG, PAY | Workflow + Concurrency + Acceptance | test_ac_017_... |
| AC-018 | Checkout / Inventory / Fulfilment | COM, INV, FUL, BKG, PAY | Workflow + Concurrency + Acceptance | test_ac_018_... |
| AC-019 | Checkout / Inventory / Fulfilment | COM, INV, FUL, BKG, PAY | Workflow + Concurrency + Acceptance | test_ac_019_... |
| AC-020 | Checkout / Inventory / Fulfilment | COM, INV, FUL, BKG, PAY | Workflow + Concurrency + Acceptance | test_ac_020_... |
| AC-021 | Commission / Finance | FIN, PAY, BKG, FUL | Policy + Event + DB + Acceptance | test_ac_021_... |
| AC-022 | Commission / Finance | FIN, PAY, BKG, FUL | Policy + Event + DB + Acceptance | test_ac_022_... |
| AC-023 | Commission / Finance | FIN, PAY, BKG, FUL | Policy + Event + DB + Acceptance | test_ac_023_... |
| AC-024 | Commission / Finance | FIN, PAY, BKG, FUL | Policy + Event + DB + Acceptance | test_ac_024_... |
| AC-025 | Commission / Finance | FIN, PAY, BKG, FUL | Policy + Event + DB + Acceptance | test_ac_025_... |
| AC-026 | Commission / Finance | FIN, PAY, BKG, FUL | Policy + Event + DB + Acceptance | test_ac_026_... |
| AC-027 | Commission / Finance | FIN, PAY, BKG, FUL | Policy + Event + DB + Acceptance | test_ac_027_... |
| AC-028 | Commission / Finance | FIN, PAY, BKG, FUL | Policy + Event + DB + Acceptance | test_ac_028_... |
| AC-029 | Commission / Finance | FIN, PAY, BKG, FUL | Policy + Event + DB + Acceptance | test_ac_029_... |
| AC-030 | Commission / Finance | FIN, PAY, BKG, FUL | Policy + Event + DB + Acceptance | test_ac_030_... |
| AC-031 | GST Compliance | CMP, FIN | Workflow + Audit + Acceptance | test_ac_031_... |
| AC-032 | GST Compliance | CMP, FIN | Workflow + Audit + Acceptance | test_ac_032_... |
| AC-033 | GST Compliance | CMP, FIN | Workflow + Audit + Acceptance | test_ac_033_... |
| AC-034 | GST Compliance | CMP, FIN | Workflow + Audit + Acceptance | test_ac_034_... |
| AC-035 | Tenant / Guardian | TEN, IAM, NTF | Workflow + Security + Acceptance | test_ac_035_... |
| AC-036 | Tenant / Guardian | TEN, IAM, NTF | Workflow + Security + Acceptance | test_ac_036_... |
| AC-037 | Tenant / Guardian | TEN, IAM, NTF | Workflow + Security + Acceptance | test_ac_037_... |
| AC-038 | Tenant / Guardian | TEN, IAM, NTF | Workflow + Security + Acceptance | test_ac_038_... |
| AC-039 | Tenant / Guardian | TEN, IAM, NTF | Workflow + Security + Acceptance | test_ac_039_... |
| AC-040 | Tenant / Guardian | TEN, IAM, NTF | Workflow + Security + Acceptance | test_ac_040_... |
| AC-041 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_041_... |
| AC-042 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_042_... |
| AC-043 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_043_... |
| AC-044 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_044_... |
| AC-045 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_045_... |
| AC-046 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_046_... |
| AC-047 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_047_... |
| AC-048 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_048_... |
| AC-049 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_049_... |
| AC-050 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_050_... |
| AC-051 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_051_... |
| AC-052 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_052_... |
| AC-053 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_053_... |
| AC-054 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_054_... |
| AC-055 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_055_... |
| AC-056 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_056_... |
| AC-057 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_057_... |
| AC-058 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_058_... |
| AC-059 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_059_... |
| AC-060 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_060_... |
| AC-061 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_061_... |
| AC-062 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_062_... |
| AC-063 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_063_... |
| AC-064 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_064_... |
| AC-065 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_065_... |
| AC-066 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_066_... |
| AC-067 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_067_... |
| AC-068 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_068_... |
| AC-069 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_069_... |
| AC-070 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_070_... |
| AC-071 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_071_... |
| AC-072 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_072_... |
| AC-073 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_073_... |
| AC-074 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_074_... |
| AC-075 | Subscription / Plan Change | SUB, FIN, DOM, CAT, COM, BKG | Policy + Scheduler + Ledger + Acceptance | test_ac_075_... |
| AC-076 | Customer Claim | CUS, IAM, NTF | API + OTP + Security + Acceptance | test_ac_076_... |
| AC-077 | Customer Claim | CUS, IAM, NTF | API + OTP + Security + Acceptance | test_ac_077_... |
| AC-078 | Customer Claim | CUS, IAM, NTF | API + OTP + Security + Acceptance | test_ac_078_... |
| AC-079 | Content Approval | APR, CAT, DOM, CMP | State-machine + API + Acceptance | test_ac_079_... |
| AC-080 | Content Approval | APR, CAT, DOM, CMP | State-machine + API + Acceptance | test_ac_080_... |
| AC-081 | Content Approval | APR, CAT, DOM, CMP | State-machine + API + Acceptance | test_ac_081_... |
| AC-082 | Retention / Closure | TEN, COM, BKG, FIN, CMP | DB + Authorization + Acceptance | test_ac_082_... |
| AC-083 | Retention / Closure | TEN, COM, BKG, FIN, CMP | DB + Authorization + Acceptance | test_ac_083_... |
| AC-084 | Domain | DOM, SUB, TEN | Workflow + Provider-adapter + Acceptance | test_ac_084_... |
| AC-085 | Domain | DOM, SUB, TEN | Workflow + Provider-adapter + Acceptance | test_ac_085_... |
| AC-086 | Domain | DOM, SUB, TEN | Workflow + Provider-adapter + Acceptance | test_ac_086_... |
| AC-087 | Domain | DOM, SUB, TEN | Workflow + Provider-adapter + Acceptance | test_ac_087_... |
| AC-088 | Domain | DOM, SUB, TEN | Workflow + Provider-adapter + Acceptance | test_ac_088_... |
| AC-089 | Payment / Platform Funds | PAY, COM, BKG, FIN | API + Webhook + Invariant + Acceptance | test_ac_089_... |
| AC-090 | Payment / Platform Funds | PAY, COM, BKG, FIN | API + Webhook + Invariant + Acceptance | test_ac_090_... |

# Appendix B - Test Repository Layout

karobarone-backend/

services/<service>/tests/unit/

services/<service>/tests/integration/

services/<service>/tests/contract/

services/<service>/tests/fixtures/

tests/acceptance/test_ac_001_...py

tests/acceptance/test_ac_090_...py

tests/e2e/

tests/contract-fixtures/

libs/platform-testing/

libs/platform-db-testkit/

tooling/load-tests/

contracts/openapi/

contracts/events/asyncapi-v1.yaml

contracts/events/schemas/

# Appendix C - Recommended Pytest Markers and Commands

| Marker | Meaning |
| --- | --- |
| @pytest.mark.unit | Pure unit/policy test. |
| @pytest.mark.integration | Real PostgreSQL/Kafka/Redis or service integration. |
| @pytest.mark.contract | OpenAPI/AsyncAPI/JSON Schema compatibility. |
| @pytest.mark.acceptance | BRD AC-* test. |
| @pytest.mark.security | Authorization/privacy/security test. |
| @pytest.mark.concurrency | Race/locking/idempotency test. |
| @pytest.mark.webhook | Provider callback/replay test. |
| @pytest.mark.scheduler | Time-based lifecycle worker test. |
| @pytest.mark.financial | Money/ledger/subscription/commission test. |
| @pytest.mark.slow | Long-running workflow/load/reconciliation test. |

make test                 # unit + fast integration subset

make test-integration     # full container-backed service integration

make test-acceptance      # AC-001..AC-090 suite

pytest -m "contract"      # contract compatibility

pytest -m "concurrency"   # race-condition suite

pytest -m "security"      # authorization/privacy suite

pytest tests/acceptance/test_ac_041_*.py -q

# Appendix D - Release Certification Checklist

**☐ **All service/unit/integration test suites for changed components are green.

**☐ **All database migrations pass fresh and upgrade-path tests.

**☐ **OpenAPI generation/diff and AsyncAPI/JSON Schema compatibility gates are green.

**☐ **All required webhook/provider/reconciliation tests for changed integrations are green.

**☐ **All impacted AC tests are green; full AC-001..AC-090 suite is green for release certification.

**☐ **Concurrency suites for inventory, capacity, webhook dedupe, scheduler and commission invoice creation are green.

**☐ **RLS/IDOR/security regression suites are green.

**☐ **No unresolved S0/S1 defects; approved S2 exceptions documented.

**☐ **No sensitive production data is present in test artifacts/logs.

**☐ **Build commit SHA, image digests, migration heads and contract versions are recorded.

**☐ **Staging smoke/workflow checks and post-deploy reconciliation plan are approved.

Engineering Baseline Statement - This Backend Test & Acceptance Specification V1.0 is the QA implementation baseline for KarobarOne backend development. It does not create new business rules. Any material mismatch between a test expectation and an explicit BRD/state-machine rule must be resolved by correcting the test/specification or formal business change control, not by silently changing backend behavior.
