**KAROBARONE**

**Implementation Backlog & Sprint Plan**

Delivery roadmap converting the approved business, architecture, security, infrastructure and test specifications into executable engineering work

| Document Field | Value |
| --- | --- |
| Specification Version | 1.0 |
| Status | Engineering Delivery Planning Baseline |
| Effective Date | 14 September 2026 |
| Business Authority | KarobarOne BRD V2.1 - Final Consolidated |
| Planning Inputs | Backend Technical Design; PostgreSQL Schema; State Machine & Business Rules; REST/Kafka Contracts; OpenAPI/AsyncAPI; Repository/Foundation; Backend Test & Acceptance; Infrastructure/Kubernetes; Security Threat Model; External Integration |
| Planning cadence | 2-week sprint baseline (planning assumption; not a contractual delivery date) |
| Primary audience | Product Owner, Engineering Lead, Backend/Database Engineers, DevOps/SRE, QA, Security, Integration Engineering and Delivery Management |

| Authority — This document sequences implementation work; it does not change any approved business rule, state transition, API/event contract, database invariant, security control or acceptance criterion. Higher-authority specifications prevail on conflict. |
| --- |

# **1. Purpose, Scope and Planning Authority**

This specification converts the approved KarobarOne requirements and technical specifications into an actionable product-engineering backlog and sprint sequence. It is intended to be the shared delivery control document used for sprint planning, dependency management, implementation reviews, QA certification and production-readiness tracking.

## **1.1 In Scope**

- All 16 logical backend services and their PostgreSQL schemas.
- Engineering foundation, contracts, migrations, eventing, infrastructure, security and provider adapters.
- Business capabilities from Free Presence through paid commerce, bookings, commission/GST/risk, analytics and Scale AI.
- Cross-cutting QA, security, observability, performance, backup/restore, release certification and operations handoff.
- Stable backlog identifiers, priorities, story-point sizing, dependencies, sprint allocation and exit gates.

## **1.2 Out of Scope**

- Changing BRD pricing, commission, subscription, GST, domain, payment ownership or other commercial rules.
- Committing to a calendar launch date or fixed team velocity before measured sprint evidence exists.
- Frontend/Next.js implementation backlog except interface dependencies needed to unblock backend contract usage.
- Final cloud/provider procurement decisions that remain deliberately open in approved specifications.

| Planning rule — Sprint placement and story points are implementation planning estimates. If team size, provider onboarding, procurement or priorities change, backlog sequencing may move while dependency and acceptance gates remain intact. |
| --- |

# **2. Delivery Model and Planning Assumptions**

| Planning dimension | Baseline |
| --- | --- |
| Sprint cadence | 2 weeks. S0 is also planned as a full 2-week engineering-foundation sprint. |
| Baseline team | 1 cross-functional backend squad: Engineering Lead/Architect, 4-6 backend/database engineers, 1 QA automation engineer, shared DevOps/SRE and shared security/integration support. |
| Parallelization | Infrastructure/security/QA work runs continuously. A second backend squad can overlap independent epics after S3, especially Subscription/Domain vs Commerce/Customer and Booking vs Finance. |
| Estimation | Fibonacci-style story points: 3/5/8/13. Points express relative complexity/risk, not hours. |
| Priority | P0 = release-critical/core invariant; P1 = required V1 capability but can trail the immediate vertical slice; P2 = later-plan/optimization capability. |
| Release model | Trunk-based development, short-lived branches, protected main, immutable images by Git SHA, staged promotion, gated migrations and acceptance certification. |
| Source of truth | BRD and approved implementation specifications; this plan never overrides them. |

## **2.1 Suggested Team Streams**

| Stream | Typical ownership | Starts |
| --- | --- | --- |
| Platform / Foundation | Repository, CI/CD, contracts, shared testkit, observability, Kubernetes, DB/Kafka platform | S0 and continuous |
| Domain Squad A | IAM/Tenant/Subscription/Domain/Catalog/Approval | S1 |
| Domain Squad B (when available) | Customer/Inventory/Commerce/Payment/Fulfilment | S3/S4 |
| Domain Squad C (optional scale-up) | Booking/Finance/Compliance/Analytics/AI | S10+ |
| QA/Security | Acceptance automation, security matrix, performance/resilience, release certification | Every sprint |

# **3. Backlog Governance**

## **3.1 Definition of Ready**

- Business behavior is traceable to BRD/state-machine rule and relevant AC where applicable.
- API/event contract is defined or the story explicitly includes an approved contract update.
- Database ownership/table impact is known; migration implications are identified.
- Authorization/tenant-store scope and sensitive-data classification are known.
- Provider dependency is either available, sandboxed/faked, or explicitly adapter-first.
- Testable acceptance conditions and failure/negative paths are written.

## **3.2 Definition of Done**

- Code follows service/template boundaries and passes format/lint/type/import checks.
- Unit, DB/integration, contract and relevant AC tests pass; concurrency/replay tests included where risk requires.
- Any schema change has Alembic migration + fresh/upgrade migration tests.
- Any public/internal API or event change matches committed OpenAPI/AsyncAPI/JSON Schema.
- Tenant/store authorization and RLS/security tests pass where applicable.
- Business mutation includes required audit/history/outbox atomically; consumers are idempotent.
- Logs/metrics/traces/alerts are added without sensitive-data leakage.
- Operational runbook or reconciliation path exists for critical async/provider workflow.
- No unresolved S0/S1 defect attributable to the story.

# **4. Epic Registry**

| Epic | Name | Priority | Scope | Target milestone |
| --- | --- | --- | --- | --- |
| EP-00 | Engineering Foundation | P0 | Repository, service template, contracts, PostgreSQL/Kafka/Redis local stack, CI/CD, observability, Kubernetes baseline | M0 |
| EP-01 | Identity, Tenant, PAN & Guardian | P0 | IAM/session/OTP, tenant PAN uniqueness, Minor/Guardian workflow, GSTIN verification interfaces, roles and memberships | M1 |
| EP-02 | Free Presence, Catalog & Approval | P0 | Free Store, <=6 showcase items, media limits, CMS/catalog versioning, approval queue, public snapshot | M1 |
| EP-03 | Domains & Publication | P0 | Immutable free subdomain, custom-domain workflow, DNS verification, publication gates, host routing | M3 |
| EP-04 | Subscription & Entitlements | P0 | Plan versions, 30-day periods, Third-Period Advance, grace/expiry/free conversion, upgrade/downgrade/reactivation | M2 |
| EP-05 | Customer Identity & Claim | P0 | Store-scoped customer, guest UNCLAIMED, email/mobile uniqueness, OTP claim, addresses/privacy workflow | M1/M4 |
| EP-06 | Inventory & Cart/Checkout | P0 | SKU stock, reservations, contention control, cart composition rules, checkout isolation | M4 |
| EP-07 | Orders, Returns & Refunds | P0 | Order state machine, seller/customer actions, commercial snapshots, return/refund workflow | M4/M5 |
| EP-08 | Payments & Razorpay | P0 | Tenant payment connection, payment intents, verified webhooks, refunds, reconciliation; UPI excluded | M4 |
| EP-09 | Fulfilment & Shiprocket | P0 | Shipping quote, shipment, tracking, COD delivery, digital entitlements/downloads | M5 |
| EP-10 | Bookings & Capacity | P0 | Schedules, slots, capacity, approval, payment modes, reschedule/no-show/cancel, booking history | M6 |
| EP-11 | Commission & Platform Finance | P0 | Commission triggers, weekly invoices, 15-day due, disputes/credits, PAN-wide commerce suspension, ledger | M7 |
| EP-12 | GST, Compliance & Risk | P1 | GST service workflow, compliance documents, grievances, risk cases/restrictions/termination | M8 |
| EP-13 | Notifications | P1 | Email/SMS/OTP delivery jobs, templates, provider callbacks, transactional event coverage | Cross-cutting |
| EP-14 | Analytics & Scale AI | P2 | Operational/advanced analytics, usage ledger, AI drafts/recommendations, quota, approval boundary | M9 |
| EP-15 | Security, Reliability & Release Hardening | P0 | Threat controls, performance, DR/restore, operations/runbooks, release certification and production readiness | M10 |

# **5. Milestone and Dependency Strategy**

The implementation sequence deliberately proves the platform with the Free Presence vertical slice before introducing paid commerce. This minimizes the number of simultaneous unknowns while validating the architectural foundation, tenant isolation, content governance, publication, contracts, database ownership and acceptance harness early.

| Milestone | Primary capability | Depends on | Release evidence |
| --- | --- | --- | --- |
| M0 | Engineering foundation | None | Repository, CI, migrations, event path, local/K8s dev baseline |
| M1 | Free Presence | M0 | Tenant/PAN/Guardian + Free store + catalog + approval + subdomain + public snapshot |
| M2 | Subscription core | M1 | 30-day lifecycle, advance, cancellation, delinquency, reactivation/upgrade |
| M3 | Paid domain/publication | M2 | Verified GSTIN + domain purchase/DNS/publication gates |
| M4 | Product commerce | M1-M3 | Customer + inventory + cart/order + Razorpay prepaid path |
| M5 | Fulfilment | M4 | Shiprocket/COD + digital delivery + returns/refunds |
| M6 | Booking | M2/M4 shared foundations | Capacity + payment modes + lifecycle/reschedule/no-show |
| M7 | Commission/finance | M4-M6 | All trigger types + invoice/due/dispute/suspension |
| M8 | Compliance/GST/risk | M7 | GST workflow + licences + grievance + restrictions |
| M9 | Analytics/Scale AI | Core event streams | Entitled analytics + AI drafts/quotas/safety |
| M10 | Hardening/launch | M0-M9 | Security/performance/DR/operations + full release certification |

# **6. Detailed Implementation Backlog**

The following registry is the baseline engineering backlog. IDs are stable planning identifiers. Teams may split a row into smaller implementation tickets as long as traceability to the parent backlog ID is retained.

| ID | Epic | Backlog item | Pri | SP | Depends on | Sprint | Acceptance / output |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FND-001 | EP-00 | Bootstrap monorepo, CODEOWNERS, pyproject/uv lock and service directories | P0 | 5 | - | S0 | Repository installs reproducibly; all 16 service directories exist. |
| FND-002 | EP-00 | Create reference FastAPI service template and dependency boundaries | P0 | 8 | FND-001 | S0 | Health/ready, typed settings, error envelope, request/correlation context and tests. |
| FND-003 | EP-00 | Provision local PostgreSQL/Kafka/Redis/MinIO/Mail stack | P0 | 8 | FND-001 | S0 | One-command local infra; synthetic-only data. |
| FND-004 | EP-00 | Alembic-per-service schema/role template and migration runner | P0 | 8 | FND-003 | S0 | Fresh DB and upgrade path work in canonical order. |
| FND-005 | EP-00 | Transactional outbox, inbox/processed-events and DLQ foundation | P0 | 13 | FND-003 | S0 | Sample DB->outbox->Kafka->consumer flow is idempotent. |
| FND-006 | EP-00 | CI quality, contract, migration, test and security gates | P0 | 8 | FND-001 | S0 | PR blocked on lint/type/test/contract/migration/security failures. |
| FND-007 | EP-00 | Structured logs, OTel traces, Prometheus metrics and health conventions | P0 | 5 | FND-002 | S0 | Correlation propagates HTTP->Kafka->worker without PII leakage. |
| FND-008 | EP-00 | Kubernetes base manifests, ServiceAccounts, probes and default-deny policy examples | P0 | 8 | FND-002 | S0 | Dev overlay deploys sample service; no public DB/Kafka/Redis. |
| IAM-001 | EP-01 | Principal credentials, password hashing, login, refresh rotation and logout | P0 | 13 | FND-002,FND-004 | S1 | JWT/session lifecycle, revocation and security audit implemented. |
| IAM-002 | EP-01 | OTP challenge/verification with TTL, attempts and rate limiting | P0 | 8 | IAM-001,EP-13 base | S1 | OTP hash-only storage; replay/abuse tests pass. |
| TEN-001 | EP-01 | Tenant registration with verified PAN uniqueness | P0 | 13 | IAM-001,FND-004 | S1 | AC-001; one PAN cannot create second tenant. |
| TEN-002 | EP-01 | Minor age evaluation and Guardian workflow data model/API | P0 | 13 | TEN-001 | S1 | AC-035..040 guard structure; Guardian role separated. |
| TEN-003 | EP-01 | Store aggregate, membership and lifetime Free entitlement | P0 | 13 | TEN-001 | S1 | AC-002; one lifetime Free Store entitlement per PAN. |
| TEN-004 | EP-01 | GSTIN verification adapter contract and ownership records | P0 | 8 | TEN-001 | S1/S6 | Provider-neutral flow ready; activation later requires verified owned GSTIN. |
| SEC-001 | EP-15 | Tenant/store authorization middleware and RLS test context | P0 | 8 | IAM-001,TEN-003,FND-004 | S1 | Cross-tenant API and DB access denied. |
| CAT-001 | EP-02 | Catalog item model for product/service showcase and operational fields | P0 | 13 | TEN-003 | S2 | Free/Paid item types supported; plan guard hooks included. |
| CAT-002 | EP-02 | Content versioning for item/page/blog controlled fields | P0 | 8 | CAT-001 | S2 | Pending version cannot overwrite LIVE. |
| CAT-003 | EP-02 | Free Presence 6-item and media entitlement enforcement | P0 | 8 | CAT-001 | S2 | AC-003..005; max 6 combined, 1 image/item, no video. |
| APR-001 | EP-02 | Approval submission/queue/approve/reject state machine | P0 | 13 | CAT-002 | S2 | AC-079..080; LIVE only after approval; reject reason recorded. |
| APR-002 | EP-02 | Emergency takedown and governance audit | P0 | 5 | APR-001 | S2 | AC-081; authorized staff can emergency-unpublish with audit. |
| DOM-001 | EP-03 | Immutable Free subdomain assignment and uniqueness | P0 | 8 | TEN-003 | S2 | AC-084; immutable storename.karobarone.com mapping. |
| CAT-004 | EP-02 | Public approved storefront snapshot/read projection | P0 | 13 | APR-001,DOM-001 | S2 | Public API exposes approved/live content only. |
| NTF-001 | EP-13 | Notification job/template/delivery attempt foundation | P1 | 8 | FND-005 | S2 | Async notification is independent from domain commit. |
| CUS-001 | EP-05 | Store-scoped customer, email/mobile uniqueness and guest resolution | P0 | 13 | TEN-003 | S3 | AC-076..077; guest checkout creates/resolves UNCLAIMED. |
| CUS-002 | EP-05 | Customer email OTP claim workflow | P0 | 8 | CUS-001,IAM-002 | S3 | AC-078; UNCLAIMED -> CLAIMED only through verified OTP. |
| CUS-003 | EP-05 | Customer addresses and privacy request workflow | P1 | 5 | CUS-001 | S3 | Store-scoped access; deletable profile vs retained commercial history. |
| TEN-005 | EP-01 | Guardian consent completion and adult reverification scheduler | P0 | 8 | TEN-002,FND-005 | S3 | AC-035..040 end-to-end; turns-18 job is idempotent. |
| NTF-002 | EP-13 | OTP + Guardian/security notification provider adapter | P1 | 8 | NTF-001,IAM-002 | S3 | Fake adapter and callback/retry behavior available. |
| QA-001 | EP-15 | M1 Free Presence acceptance pack and isolation tests | P0 | 13 | S1-S3 features | S3 | AC-001..014, AC-035..040, AC-076..081, AC-084 foundation subset pass. |
| SUB-001 | EP-04 | Plan/plan-version/entitlement data and resolution engine | P0 | 13 | FND-004,TEN-003 | S4 | Presence/Commerce/Growth/Scale AI capabilities versioned. |
| SUB-002 | EP-04 | Initial paid activation quote, Third-Period Advance and charge snapshots | P0 | 13 | SUB-001,TEN-004 | S4 | AC-041..044 foundations; initial amount = P1 + 100% advance; first setup complimentary. |
| FIN-001 | EP-11 | Platform invoice/receipt and immutable finance ledger foundation | P0 | 13 | FND-004 | S4 | Subscription/setup/GST/domain/commission charges can be represented without mutable balance truth. |
| SUB-003 | EP-04 | Subscription activation and entitlement.changed projection/event | P0 | 8 | SUB-002,FIN-001 | S4 | Paid activation only after authoritative platform-fee payment evidence. |
| NTF-003 | EP-13 | Subscription due/activation/advance notification templates | P1 | 5 | NTF-001,SUB-003 | S4 | Required lifecycle notifications queued idempotently. |
| SUB-004 | EP-04 | Period scheduler and exact 30-day Billing Period lifecycle | P0 | 13 | SUB-003,FND-005 | S5 | AC-041,044,049..053 exact period rules. |
| SUB-005 | EP-04 | Initial cancellation before Period 3 and prepaid Period-3 behavior | P0 | 8 | SUB-004 | S5 | AC-045..048; P3 additional due = 0 after valid notice. |
| SUB-006 | EP-04 | Payment grace, Day-8 expiry and Day-23 Free conversion | P0 | 13 | SUB-004 | S5 | AC-054..064; new commerce blocked when expired; obligations manageable. |
| SUB-007 | EP-04 | Reactivation calculation and fresh billing period | P0 | 8 | SUB-006 | S5 | AC-065..068; full plan fee + 50% setup. |
| SUB-008 | EP-04 | Upgrade quote/proration/advance top-up/setup-fee discount approval | P0 | 13 | SUB-004,FIN-001 | S5 | AC-069..075; owner-approved discount auditable. |
| SUB-009 | EP-04 | Scheduled downgrade with data retention/feature hiding | P1 | 8 | SUB-004 | S5 | Lower-plan compatibility; higher-plan data retained/disabled. |
| QA-002 | EP-15 | Subscription deterministic clock and scheduler race suite | P0 | 8 | SUB-004..009 | S5 | Boundary tests at before/at/after P3 and Day 7/8/22/23; duplicate jobs impossible. |
| DOM-002 | EP-03 | Paid domain options, selection and purchase request workflow | P0 | 8 | SUB-003 | S6 | Domain request state/evidence and premium-domain approval hooks. |
| DOM-003 | EP-03 | DNS configuration/verification and custom-domain publication gate | P0 | 13 | DOM-002 | S6 | AC-085..087; paid public launch needs verified custom domain. |
| DOM-004 | EP-03 | Free-conversion routing and closure/transfer review | P0 | 8 | DOM-001,DOM-003,SUB-006 | S6 | AC-059,088; custom serving stops; transfer is review-only. |
| TEN-006 | EP-01 | Production-ready PAN/GST provider adapter + verification evidence | P0 | 13 | TEN-004,provider decision | S6 | AC-008..010; GSTIN belongs to tenant PAN and unique across paid stores. |
| SEC-002 | EP-15 | Privileged MFA/admin separation and sensitive identifier encryption/fingerprints | P0 | 8 | IAM-001,TEN-006 | S6 | Production admin MFA; PAN/GSTIN plaintext absent from logs/events. |
| QA-003 | EP-15 | Paid onboarding/domain acceptance pack | P0 | 8 | S4-S6 features | S6 | AC-006..014, AC-084..088 relevant cases pass. |
| INV-001 | EP-06 | SKU/stock balance/movement and inventory adjustment model | P0 | 13 | CAT-001 | S7 | Tracked stock never negative; digital inventory unlimited unless restricted. |
| INV-002 | EP-06 | Atomic reservation/consume/release/expiry workflow | P0 | 13 | INV-001,FND-005 | S7 | Final-unit race yields exactly one winner; default TTL 10 min configurable. |
| COM-001 | EP-06 | Store-scoped product cart and composition guards | P0 | 8 | CUS-001,CAT-001 | S7 | AC-015..018; cross-store/product-service mixing prohibited. |
| COM-002 | EP-07 | Checkout orchestration and immutable commercial snapshots | P0 | 13 | COM-001,INV-002 | S7 | Order placement reserves stock atomically; seller/tax/commission inputs snapshotted. |
| COM-003 | EP-07 | Order state machine and processing/cancel paths | P0 | 8 | COM-002 | S7 | Explicit transitions only; no generic status patch. |
| PAY-001 | EP-08 | Razorpay tenant provider connection abstraction | P0 | 8 | TEN-003,SEC-002 | S8 | Credentials server-side/secret-managed; disconnect blocks new online intents. |
| PAY-002 | EP-08 | Payment intent creation from immutable order/booking snapshot | P0 | 13 | PAY-001,COM-002 | S8 | UPI omitted/rejected; source amount/currency validated. |
| PAY-003 | EP-08 | Razorpay webhook raw verification, dedupe and normalized payment facts | P0 | 13 | PAY-001,FND-005 | S8 | Authoritative confirmation only; duplicate/out-of-order safe. |
| PAY-004 | EP-08 | Payment reconciliation worker for missed/ambiguous callbacks | P0 | 8 | PAY-003,FND-005 | S8 | Stuck PENDING repaired without browser-return trust or history rewrite. |
| COM-004 | EP-07 | Prepaid order paid/failed orchestration and inventory consume/release | P0 | 8 | PAY-003,INV-002 | S8 | One payment effect; inventory consistent under replay. |
| QA-004 | EP-15 | Checkout/payment concurrency, webhook replay and AC pack | P0 | 13 | S7-S8 features | S8 | AC-015..018, AC-022, AC-089..090 + mandatory payment tests pass. |
| FUL-001 | EP-09 | Shiprocket connection/quote/serviceability adapter | P0 | 8 | COM-004 | S9 | Self-shipping/local pickup not exposed; AC-019..020. |
| FUL-002 | EP-09 | Shipment create/cancel/tracking state normalization | P0 | 13 | FUL-001 | S9 | Shipment state monotonic; provider strings do not become order states directly. |
| FUL-003 | EP-09 | Shiprocket webhook verification/dedupe + COD delivery fact | P0 | 13 | FUL-002,FND-005 | S9 | AC-021; duplicate delivery cannot duplicate commission trigger. |
| FUL-004 | EP-09 | Shipment reconciliation for missed/out-of-order tracking | P0 | 8 | FUL-003 | S9 | Stale shipment repaired via idempotent command. |
| FUL-005 | EP-09 | Digital entitlement, signed link and download-count controls | P0 | 13 | COM-004,object storage | S9 | Private object; 24h initial link and max 3 downloads policy enforced server-side. |
| QA-005 | EP-15 | Fulfilment/COD/digital acceptance and resilience pack | P0 | 8 | FUL-001..005 | S9 | AC-019..021 and signed-link/replay tests pass. |
| COM-005 | EP-07 | Return request/decision workflow | P0 | 8 | COM-003,FUL-002 | S10 | Return eligibility/state history preserved. |
| COM-006 | EP-07 | Refund request/approval and provider-refund orchestration | P0 | 13 | COM-005,PAY-003 | S10 | Partial refund bounded by refundable amount; duplicate refund prevented. |
| PAY-005 | EP-08 | Refund execution + reconciliation | P0 | 8 | COM-006,PAY-004 | S10 | Ambiguous refund result reconciled before retry. |
| FIN-002 | EP-11 | Seller invoice snapshot/numbering and platform billing documents | P1 | 13 | COM-002,FIN-001 | S10 | Store-level sequence and historical seller/tax snapshot auditability. |
| RET-001 | EP-15 | Archive/soft-delete/retention enforcement for commercial history | P0 | 8 | COM-003,FIN-001 | S10 | AC-082..083; history cannot be destructively deleted. |
| BKG-001 | EP-10 | Service schedules/windows/blackouts/slot model | P0 | 13 | CAT-001 | S11 | Appointment/non-appointment models represented; timezone/effective dates explicit. |
| BKG-002 | EP-10 | Atomic capacity reservation and booking creation | P0 | 13 | BKG-001,CUS-001 | S11 | Final-capacity race yields one winner; commercial snapshot persisted. |
| BKG-003 | EP-10 | Approval/rejection/confirmation/payment-pending transitions | P0 | 8 | BKG-002 | S11 | Seller approval vs instant-confirm flows supported. |
| BKG-004 | EP-10 | Booking payment intent/deposit/full advance integrations | P0 | 8 | BKG-003,PAY-002 | S11 | Payment mode drives state without weakening provider authority. |
| BKG-005 | EP-10 | Reschedule with reserve-new-before-release-old semantics | P0 | 13 | BKG-002 | S12 | AC-027; old/new history retained; no double capacity/commission. |
| BKG-006 | EP-10 | Cancel, complete and no-show transitions/policies | P0 | 8 | BKG-003 | S12 | AC-024..026 business effects represented. |
| BKG-007 | EP-10 | Pay-after-service trigger and booking-date commission context | P0 | 8 | BKG-002,FIN-003 placeholder | S12 | AC-023; commission trigger occurs on booking date per rule. |
| QA-006 | EP-15 | Booking capacity/payment/reschedule acceptance pack | P0 | 13 | BKG-001..007 | S12 | AC-017,023..027 and concurrency/state-negative tests pass. |
| FIN-003 | EP-11 | Commission record state machine and trigger consumers | P0 | 13 | COM-004,FUL-003,BKG-002 | S13 | Prepaid/COD/pay-after-service triggers map to RECEIVABLE exactly once. |
| FIN-004 | EP-11 | Commission calculation snapshots: taxable base excluding GST/shipping | P0 | 8 | FIN-003 | S13 | AC-028; rate snapshot 4/2/1% as originating plan. |
| FIN-005 | EP-11 | Weekly consolidated commission invoice and 15-day due | P0 | 13 | FIN-003,FND-005 | S13 | AC-029; concurrent workers cannot double-invoice lines. |
| FIN-006 | EP-11 | Pay-first dispute/credit-later workflow | P0 | 8 | FIN-005 | S13 | AC-030; corrections are credits/compensations, not history rewrite. |
| FIN-007 | EP-11 | Overdue commission -> tenant/PAN-wide commerce restriction | P0 | 8 | FIN-005,EP-12 restriction base | S13 | New commerce blocked across stores; existing obligations remain manageable. |
| QA-007 | EP-15 | Commission/ledger reconstruction and duplicate-effect test pack | P0 | 13 | FIN-003..007 | S13 | AC-021..030 and finance invariant suite pass. |
| CMP-001 | EP-12 | Compliance document/category-policy/licence evidence model | P1 | 8 | CAT-001 | S14 | Controlled gates can block publication/commerce where configured. |
| CMP-002 | EP-12 | GST service case/quotation/payment/preparation workflow | P1 | 13 | FIN-001,TEN-006 | S14 | AC-031..033 chargeability boundaries represented. |
| CMP-003 | EP-12 | Immutable GST draft, tenant approval and filing acknowledgement | P0 | 13 | CMP-002 | S14 | AC-034; exact draft/tax period/approver/timestamp required before filing. |
| CMP-004 | EP-12 | Risk signal/case/restriction/lift/termination workflows | P0 | 13 | FIN-007,APR-002 | S14 | Store then tenant scope; existing obligations remain manageable. |
| CMP-005 | EP-12 | Consumer complaint/grievance tracking | P1 | 8 | CUS-001 | S14 | Complaint state/evidence and response tracking available. |
| QA-008 | EP-15 | GST/risk/compliance acceptance and authorization pack | P0 | 8 | CMP-001..005 | S14 | AC-031..034 plus risk/privileged/security tests pass. |
| ANL-001 | EP-14 | Analytics event ingestion and daily/basic store metrics | P1 | 13 | Core events | S15 | Commerce operational/basic analytics from event-derived projections. |
| ANL-002 | EP-14 | Advanced Growth/Scale metrics and reporting projections | P1 | 8 | ANL-001 | S15 | Visitor/item/form/order/booking/revenue metrics; separate GST vs GMV concepts. |
| AI-001 | EP-14 | AI usage ledger/quota/model configuration | P2 | 8 | SUB-001,ANL-001 | S15 | Scale AI only; quota controlled; usage auditable. |
| AI-002 | EP-14 | AI content/SEO/recommendation draft endpoints | P2 | 13 | AI-001,CAT-002 | S15 | AI output is draft/recommendation; public content still requires approval. |
| AI-003 | EP-14 | AI safety boundary tests: no direct financial/tax/inventory mutation | P0 | 8 | AI-002 | S15 | BR/AC safeguards; cross-tenant context impossible. |
| OPS-001 | EP-15 | Production observability dashboards/alerts and runbooks | P0 | 13 | FND-007,all async domains | S16 | API/DB/Kafka/outbox/scheduler/provider/security alerts actionable. |
| OPS-002 | EP-15 | CloudNativePG production backup/restore/failover rehearsal | P0 | 13 | Infra ready | S16 | Daily backup + 15-day retention verified; restore rehearsal documented. |
| SEC-003 | EP-15 | Threat-model remediation pass and security test matrix execution | P0 | 13 | All domains | S16 | No unresolved Critical/High tenant/funds/auth/immutable-record risk. |
| PERF-001 | EP-15 | Load/concurrency tests and resource/index/partition tuning | P0 | 13 | Core flows complete | S16 | Checkout/booking contention, webhook bursts, admin queries within agreed staging thresholds. |
| OPS-003 | EP-15 | Kubernetes HPA/PDB/NetworkPolicy/secret rotation/rollout rehearsal | P0 | 8 | Infra manifests | S16 | Staging deployment and rollback/roll-forward rehearsal passes. |
| REL-001 | EP-15 | Full AC-001..AC-090 release certification suite | P0 | 13 | All epics | S17 | All 90 ACs pass; no S0/S1 defects. |
| REL-002 | EP-15 | Provider production onboarding/certification and credentials | P0 | 8 | PAY/FUL/NTF/DOM/TEN adapters | S17 | Production webhook/secrets/callback endpoints verified and audited. |
| REL-003 | EP-15 | Data migration/seed/reference-data freeze and production dry-run | P0 | 8 | All migrations | S17 | Fresh/upgrade migration and seed run is repeatable; revisions recorded. |
| REL-004 | EP-15 | Production release, smoke, reconciliation and rollback checkpoint | P0 | 13 | REL-001..003 | S17 | Approved image digests deployed; smoke/reconciliation clean; rollback/roll-forward available. |
| REL-005 | EP-15 | Post-launch hypercare checklist and incident ownership handoff | P0 | 5 | REL-004 | S17 | Operational owners, dashboards, runbooks and escalation paths accepted. |

## **6.1 Backlog Summary**

| Measure | Count | Planning interpretation |
| --- | --- | --- |
| Total backlog items | 104 | All implementation items in the baseline registry. |
| P0 release-critical | 91 | 931 indicative SP |
| P1 required V1 | 11 | 97 indicative SP |
| P2 later-plan/optimization | 2 | 21 indicative SP |
| Epics | 16 | 16 domain/foundation epics. |
| Sprint increments | 18 | S0 through S17; 2-week planning baseline. |

The point totals are intentionally not used as a contractual capacity target. Re-estimate at sprint planning using actual team velocity, but preserve P0 dependency and release-gate sequencing.

# **7. Sprint-by-Sprint Delivery Plan**

Each sprint has one dominant integration objective. Cross-cutting security, QA, documentation, observability and provider-adapter work is included continuously even where not repeated in the sprint title.

| Sprint | Theme | Goal | Primary backlog | Exit gate |
| --- | --- | --- | --- | --- |
| S0 | Foundation / M0 | Repository, local data/event stack, service template, CI/CD, observability and Kubernetes baseline. | FND-001..008 | M0 exit: new service can be scaffolded; migrations/tests run; sample event flows idempotently. |
| S1 | Identity & Tenant Core | IAM/session, PAN tenant uniqueness, store/free entitlement, Guardian skeleton, authorization/RLS. | IAM-001..002, TEN-001..004, SEC-001 | Tenant/store isolation and registration foundations pass. |
| S2 | Free Presence Content | Catalog/CMS, Free limits, approval, immutable Free subdomain, public snapshot, notification base. | CAT-001..004, APR-001..002, DOM-001, NTF-001 | Free Store can be created, approved and published safely. |
| S3 | Customer Claim & Free Slice Completion | Store-scoped customer, guest UNCLAIMED, OTP claim, Guardian completion/reverification, Free acceptance pack. | CUS-001..003, TEN-005, NTF-002, QA-001 | M1 Free Presence vertical slice certified. |
| S4 | Subscription & Entitlement Foundation | Plans/entitlements, activation quote, advance, platform finance ledger, activation events. | SUB-001..003, FIN-001, NTF-003 | Paid activation calculation and entitlement projection are deterministic. |
| S5 | Subscription Lifecycle & Plan Changes | Periods, cancellation, grace/expiry/free conversion, reactivation, upgrade/downgrade, timer tests. | SUB-004..009, QA-002 | AC-041..075 behavior is executable and timer-safe. |
| S6 | Paid Onboarding & Domains | Custom-domain purchase/DNS/publication, production PAN/GST verification adapter, privileged security, acceptance. | DOM-002..004, TEN-006, SEC-002, QA-003 | M2/M3 paid setup/publication is ready. |
| S7 | Inventory, Cart & Checkout | Stock, reservation, cart composition and order placement snapshots/state. | INV-001..002, COM-001..003 | Product checkout creates a safe pending order without oversell. |
| S8 | Online Payments / Prepaid Commerce | Razorpay connection, payment intent/webhook/reconciliation, paid order orchestration and tests. | PAY-001..004, COM-004, QA-004 | M4 prepaid commerce path certified; UPI absent. |
| S9 | Fulfilment / COD / Digital | Shiprocket, tracking, COD trigger, reconciliation and private digital delivery. | FUL-001..005, QA-005 | M5 fulfilment paths certified. |
| S10 | Returns, Refunds & Invoicing | Returns/refunds/provider refund, seller invoices/platform documents, retention controls. | COM-005..006, PAY-005, FIN-002, RET-001 | Post-order exception flows and commercial history are auditable. |
| S11 | Booking Core | Schedules, slots, capacity, booking creation, approval/payment modes. | BKG-001..004 | Appointment and non-appointment booking core is functional. |
| S12 | Booking Lifecycle Completion | Reschedule/cancel/complete/no-show, pay-after-service and booking acceptance tests. | BKG-005..007, QA-006 | M6 booking lifecycle certified. |
| S13 | Commission & Finance | Commission triggers/rates, weekly invoice, dispute/credit and overdue suspension. | FIN-003..007, QA-007 | M7 finance/commission lifecycle certified. |
| S14 | GST, Compliance & Risk | GST case/draft/approval/file, licences, complaints, restrictions and termination. | CMP-001..005, QA-008 | M8 compliance/risk baseline certified. |
| S15 | Analytics & Scale AI | Analytics projections, quota, AI draft/recommendation endpoints and safety boundaries. | ANL-001..002, AI-001..003 | M9 analytics/AI capabilities meet entitlement and safety rules. |
| S16 | Production Hardening | Observability/runbooks, backup/restore, threat remediation, performance tuning, rollout rehearsal. | OPS-001..003, SEC-003, PERF-001 | M10 hardening gates pass in staging. |
| S17 | Release Certification & Launch | Full acceptance, provider live onboarding, migration dry-run, production rollout and hypercare handoff. | REL-001..005 | Production launch only after full release certificate and zero unresolved S0/S1. |

## **7.1 Sprint Capacity Guidance**

Do not force the full backlog into a sprint solely because the row is allocated there. Use measured team velocity after S1-S2. When capacity is lower, preserve dependency order and move lower-priority or parallelizable rows rather than reducing testing/security gates. When a second squad is available, the safest acceleration starts after M1 because service boundaries and test/contract conventions are then proven.

| Sprint | Indicative SP | Interpretation | Planning note |
| --- | --- | --- | --- |
| S0 | 63 | Indicative only | Split across domain + QA/infra streams; recalibrate against actual velocity. |
| S1 | 68 | Indicative only | Split across domain + QA/infra streams; recalibrate against actual velocity. |
| S2 | 76 | Indicative only | Split across domain + QA/infra streams; recalibrate against actual velocity. |
| S3 | 55 | Indicative only | Split across domain + QA/infra streams; recalibrate against actual velocity. |
| S4 | 52 | Indicative only | Split across domain + QA/infra streams; recalibrate against actual velocity. |
| S5 | 71 | Indicative only | Split across domain + QA/infra streams; recalibrate against actual velocity. |
| S6 | 58 | Indicative only | Split across domain + QA/infra streams; recalibrate against actual velocity. |
| S7 | 55 | Indicative only | Split across domain + QA/infra streams; recalibrate against actual velocity. |
| S8 | 63 | Indicative only | Split across domain + QA/infra streams; recalibrate against actual velocity. |
| S9 | 63 | Indicative only | Split across domain + QA/infra streams; recalibrate against actual velocity. |
| S10 | 50 | Indicative only | Split across domain + QA/infra streams; recalibrate against actual velocity. |
| S11 | 42 | Indicative only | Split across domain + QA/infra streams; recalibrate against actual velocity. |
| S12 | 42 | Indicative only | Split across domain + QA/infra streams; recalibrate against actual velocity. |
| S13 | 63 | Indicative only | Split across domain + QA/infra streams; recalibrate against actual velocity. |
| S14 | 63 | Indicative only | Split across domain + QA/infra streams; recalibrate against actual velocity. |
| S15 | 50 | Indicative only | Split across domain + QA/infra streams; recalibrate against actual velocity. |
| S16 | 60 | Indicative only | Split across domain + QA/infra streams; recalibrate against actual velocity. |
| S17 | 47 | Indicative only | Split across domain + QA/infra streams; recalibrate against actual velocity. |

# **8. Parallelization and Critical Path**

## **8.1 Critical Path**

1. M0 foundation -> IAM/Tenant/Free Store -> Catalog/Approval/Subdomain -> M1 Free Presence.
1. M1 -> Subscription core/lifecycle -> verified GSTIN/custom domain -> paid publication.
1. Paid entitlement + customer/catalog -> inventory/cart/order -> Razorpay authoritative payment -> fulfilment.
1. Commerce/booking facts -> commission/finance -> GST/risk -> launch hardening.
1. Full acceptance + provider production onboarding + migration/restore/rollout rehearsal -> production launch.

## **8.2 Safe Parallel Work**

| After | Can run in parallel | Shared dependency to protect |
| --- | --- | --- |
| S1 | Catalog/Approval vs Guardian/Customer foundations | Tenant/store identity and authorization context |
| S3 | Subscription engine vs provider-neutral paid-domain/GST adapter work | Plan/store/GST ownership contracts |
| S6 | Inventory/Commerce vs Razorpay sandbox adapter hardening | Order/payment snapshot contract |
| S9 | Returns/refunds vs booking-core implementation | Payment/customer/finance foundations |
| S12 | Finance vs compliance/risk model vs analytics projections | Stable events and immutable commercial snapshots |
| S15 | Security/performance/DR hardening streams | Production-like staging and release candidate |

# **9. QA, Security and Acceptance Strategy by Sprint**

Testing is part of implementation rather than a final phase. Every sprint must add relevant automated acceptance and engineering-invariant tests. The full AC-001..AC-090 suite remains a production release gate.

| Phase | Mandatory test emphasis | Non-negotiable examples |
| --- | --- | --- |
| S0-S3 | Foundation/isolation/free slice | Idempotency, outbox/inbox, RLS, IDOR, OTP abuse, approved-only public content |
| S4-S6 | Subscription/domain | Deterministic time boundaries, scheduler races, calculation snapshots, custom-domain publication gates |
| S7-S10 | Commerce/payment/fulfilment | Final-unit race, webhook signature/replay/out-of-order, browser redirect non-authority, refund dedupe, COD delivery |
| S11-S13 | Booking/finance | Final-capacity race, reschedule atomicity, commission trigger uniqueness, weekly invoice race, ledger reconstruction |
| S14-S15 | Compliance/AI | Exact GST draft approval, privileged actions, restrictions, AI no-autonomous-financial-mutation, tenant-scoped AI context |
| S16-S17 | Hardening/release | NetworkPolicy, privileged MFA, scans, failover, restore, performance, full AC suite, provider production certification |

# **10. Provider and Open-Decision Management**

Open vendor decisions must not stall domain development. Build and test against provider-neutral interfaces and deterministic fake adapters first; provider onboarding becomes an integration certification task once selected.

| Decision | Needed by | Backlog impact if unresolved | Mitigation |
| --- | --- | --- | --- |
| PAN/GST verification provider | S6 | TEN-006 live adapter cannot complete | Use fake/provider-neutral adapter and evidence model from S1. |
| Email/SMS provider | S3/S4 | NTF-002 production delivery pending | Use fake adapter/Mailpit; IAM validity remains internal. |
| Registrar/DNS provider | S6 | DOM-002/003 live purchase/config pending | Keep domain workflow/provider refs provider-neutral. |
| Razorpay tenant connection model | S8 | PAY-001 credential/onboarding implementation | ProviderAccount abstraction isolates the choice. |
| Shiprocket tenant/account model | S9 | FUL adapter credential routing | Store provider_connection context; fake adapter earlier. |
| Object storage/CDN provider | S2/S9 | Media/digital live delivery | S3-compatible adapter; MinIO locally. |
| Tax calculation/rounding finalization | Before commerce/finance prod | Invoice/commission outputs need qualified review | Snapshot calculation rule/version and keep tax logic configurable. |

# **11. Sprint Ceremonies and Delivery Controls**

| Control | Required behavior |
| --- | --- |
| Sprint planning | Select only READY backlog; verify dependency, AC/test and contract impact. |
| Daily engineering sync | Track blocked dependencies, migrations/contracts/provider gaps and asynchronous workflow risks. |
| Mid-sprint integration check | Generate OpenAPI/event contracts, run migrations/integration tests early; do not defer integration to final day. |
| Security/DB review | Mandatory for auth/RLS/PII/financial/provider-secret/migration/network boundary changes. |
| Sprint review | Demo end-to-end behavior using realistic synthetic data; show acceptance evidence, not only UI/API happy path. |
| Retrospective | Update velocity/estimates and remove recurring CI/test/provider bottlenecks. |
| Release train | Only immutable tested artifacts progress dev -> staging -> production; no rebuild after staging approval. |

# **12. Risk Register for Delivery Planning**

| Risk | Likelihood | Impact | Mitigation / planning response |
| --- | --- | --- | --- |
| Provider onboarding/procurement delay | Medium | High | Adapter-first development; fake/sandbox certification; isolate production credential step. |
| Subscription/finance rule misinterpretation | Medium | Critical | Treat state machine + AC suite as authority; deterministic clock/calculation tests; architecture review. |
| Cross-tenant authorization defect | Low-Med | Critical | Layered authz + RLS + IDOR tests in every impacted sprint; security release gate. |
| Concurrency oversell/overbooking | Medium | High | Row locking/conditional updates; race tests under real PostgreSQL. |
| Kafka/webhook duplicate side effects | Medium | Critical | Outbox/inbox + business-key idempotency + replay tests. |
| Database migration blocks release | Medium | High | Expand/backfill/switch/contract; staging migration rehearsal; roll-forward plan. |
| Small-team overcommitment | High | Medium | Prioritize M1/M2/M4 critical path; defer P2/advanced analytics; use measured velocity. |
| Late security/ops work | Medium | High | Security/observability/runbooks are continuous backlog, not final cleanup. |
| Tax/compliance assumptions unvalidated | Medium | High | Qualified professional review before production; keep rule versions/configuration explicit. |

# **13. Release Gates**

- All relevant state-machine transitions have positive and negative tests.
- Generated OpenAPI matches committed contracts; AsyncAPI/JSON Schemas validate and remain compatible.
- Fresh-database and previous-revision migration paths pass.
- No direct cross-service database writes or shared domain-model imports.
- Tenant/store isolation, privileged authorization, RLS and webhook/security tests pass.
- No duplicate financial, order, booking, inventory or commission side effects under retries/races.
- Provider callbacks are signed/authenticated, raw-retained appropriately, deduplicated and replay-safe.
- Backup/restore and production-like rollout/rollback or roll-forward rehearsal completed.
- Full AC-001..AC-090 plus mandatory engineering invariant suite passes for production.
- No unresolved S0/S1 defects; security Critical/High findings on tenant/funds/auth/immutable records are resolved or formally blocked from release.

# **14. Initial Jira/Linear Import Convention**

Recommended ticket hierarchy: Initiative = KarobarOne V1 Backend; Epic = EP-*; Story/Task = backlog ID in this document; Subtask = implementation split by API/domain/DB/event/test/ops. Keep the parent backlog ID in every derived ticket so scope can be traced back to this plan and higher-authority specifications.

| Field | Convention |
| --- | --- |
| Issue key / external ID | Use backlog ID, e.g. SUB-006, PAY-003, FIN-005. |
| Summary | Use the backlog-item title without rewriting business meaning. |
| Epic link | EP-* from Section 4. |
| Priority | P0/P1/P2 from registry. |
| Estimate | Story points; re-estimate only with engineering evidence. |
| Dependencies | Explicit blocks/is-blocked-by links from registry. |
| Acceptance | Copy the output/AC statement and link relevant BR/AC/API/event/state-machine refs. |
| Labels | service:<code>, milestone:M*, sprint:S*, security/db/provider/concurrency as applicable. |
| Done evidence | PR, tests, migration revision, contract diff, dashboards/runbook where required. |

# **15. Management Summary**

The recommended implementation sequence starts with M0 engineering foundation and M1 Free Presence, then adds subscription/domain foundations before transactional commerce. This ordering reduces risk because the architecture, tenant isolation, contracts, database ownership, approval/publication flow and test harness are proven before money, inventory and commission workflows are introduced.

Under the planning baseline, S0-S17 represents 18 two-week sprints. That is an indicative single-squad sequence rather than a fixed 36-week commitment. With two stable backend squads plus dedicated QA/DevOps support after M1, multiple independent epics can overlap and materially shorten calendar time. Scope, quality gates and business invariants should not be compressed merely to meet an arbitrary date.

| Immediate execution point — Start with S0 only after the approved specification set is committed to the engineering repository. S0 exit should be demonstrated by one reference FastAPI service that migrates its own PostgreSQL schema, emits an outbox event to Kafka, consumes it idempotently, exposes generated OpenAPI, passes CI/security gates and deploys to the dev Kubernetes baseline. |
| --- |

# **Appendix A - Acceptance Criteria to Planned Sprint Map**

| Acceptance range | Primary sprint(s) | Coverage |
| --- | --- | --- |
| AC-001..014 | S1-S6 | Tenant/Free/Paid entitlement, GSTIN and catalog/media rules |
| AC-015..020 | S7-S9 | Checkout composition, cross-store isolation, shipping/COD eligibility |
| AC-021..030 | S8-S13 | Payment/COD/booking commission triggers, calculation, invoice and dispute |
| AC-031..034 | S14 | GST service chargeability and exact tenant approval |
| AC-035..040 | S1-S3 | Minor/Guardian and adult reverification |
| AC-041..075 | S4-S6 | 30-day subscription lifecycle, advance, cancellation, delinquency, reactivation, upgrade |
| AC-076..078 | S3 | Customer identity, UNCLAIMED and OTP claim |
| AC-079..081 | S2 | Content approval/rejection/emergency takedown |
| AC-082..083 | S10/S16 | Commercial retention/archive |
| AC-084..088 | S2/S6 | Free/custom domain and transfer review |
| AC-089..090 | S8 | No UPI in KarobarOne checkout; platform does not hold customer purchase funds |

# **Appendix B - Product/Engineering Decision Log Required During Delivery**

- Provider selections and tenant account models (PAN/GST, email/SMS, registrar/DNS, Razorpay onboarding, Shiprocket context, object storage/CDN).
- Production cloud/Kafka topology and final resource sizing after staging/load evidence.
- Tax calculation/rounding implementation reviewed by qualified tax/accounting professionals.
- Formal RPO/RTO beyond approved daily backup + 15-day initial retention.
- Any proposal to change a BRD commercial/lifecycle rule, API/event meaning or state machine.
- Any change from PostgreSQL-backed durable scheduler to Temporal or another workflow engine.
- Any incompatible API/event version requiring /api/v2 or .v2 event type.

# **Appendix C - Backlog Health Checklist**

- Every active story has one accountable engineering owner and one QA owner/reviewer.
- Every P0 story has a test path before implementation starts.
- Every provider story has fake/sandbox behavior and ambiguous-outcome handling.
- Every financial story declares immutable snapshot/business-key/idempotency behavior.
- Every stateful story names valid source state(s) and rejection behavior.
- Every database change names the owning service/schema and migration/recovery approach.
- Every async story declares producer, consumer, outbox/inbox, retry, DLQ and reconciliation behavior where applicable.
- Every sprint closes with updated contract/migration/test evidence and no hidden manually applied production configuration.
**Engineering Planning Baseline Statement**

This Implementation Backlog & Sprint Plan V1.0 is the proposed delivery baseline for KarobarOne V1. It sequences implementation without redefining the BRD or approved technical specifications. Sprint allocation, estimates and team parallelization may be refined using measured delivery evidence, but dependency order, release gates, security/tenant isolation, financial integrity and AC-001..AC-090 traceability remain mandatory.
