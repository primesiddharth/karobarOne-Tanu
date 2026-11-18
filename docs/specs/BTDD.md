# KAROBARONE

**Backend Technical Design Document**

**Multi-Tenant SaaS Portfolio, Hybrid Commerce, Booking, GST Compliance & AI Platform**

**Technical Design Version 1.0**

**Source Business Baseline: KarobarOne BRD V2.1 - Final Consolidated - 11 September 2026**

---

| Document Field | Value |
| --- | --- |
| Document Type | Backend Technical Design Document (BTDD) |
| Version | 1.0 |
| Status | Engineering Baseline for V1 Implementation |
| Source of Business Truth | KarobarOne BRD V2.1 |
| Target Backend | Python / FastAPI microservices |
| Primary Database | PostgreSQL |
| Event Backbone | Apache Kafka |
| Runtime | Docker + Kubernetes |
| Primary Audience | Backend, Database, DevOps, QA, Architecture, Product, Security and Operations teams |

Authority and interpretation

This document converts the approved business baseline into an implementable backend architecture. It does not replace or amend the BRD. If a technical design conflicts with an explicit BRD rule, the BRD rule prevails. Business-rule changes require BRD change control; technical implementation choices may evolve while preserving externally observable behavior.

# Document Contents

- 1. Purpose, Scope and Design Inputs

- 2. Architecture Principles

- 3. System Context and Runtime Topology

- 4. Domain and Service Decomposition

- 5. Data Architecture and Multi-Tenant Isolation

- 6. API Architecture and Standards

- 7. Kafka/Event Architecture

- 8. Workflow, Scheduling and Time-Based Processing

- 9. Detailed Microservice Designs

- 10. Core State Machines

- 11. End-to-End Business Workflows

- 12. Security Architecture

- 13. Financial Integrity and Ledger Design

- 14. Media, Files and Digital Fulfilment

- 15. Observability and Operational Controls

- 16. Performance, Scalability and Availability

- 17. Data Retention, Archival and Deletion

- 18. Testing and Quality Strategy

- 19. CI/CD, Repository and Deployment Design

- 20. Development Sequence and Delivery Milestones

- 21. Technical Decisions Still to Finalize

- Appendix A. BRD-to-Service Traceability

- Appendix B. Acceptance Criteria Ownership Matrix

- Appendix C. Initial Kafka Topic Catalog

- Appendix D. Initial Database Schema Catalog

# 1. Purpose, Scope and Design Inputs

## 1.1 Purpose

The purpose of this BTDD is to turn the BRD into a backend system that can be implemented by multiple engineering teams without independently re-interpreting commercial, compliance or lifecycle rules. The document defines ownership boundaries, persistence rules, service contracts, state transitions, transactional guarantees and deployment conventions.

## 1.2 In Scope

- Tenant/PAN/GSTIN/Guardian identity and onboarding.

- Free Presence and paid store lifecycle.

- Plans, entitlements, 30-day subscription periods, Third-Period Advance, cancellation, upgrade, downgrade and reactivation.

- Catalog, CMS, product/service content, versions, approval and media.

- Customer accounts and guest checkout.

- Product carts/orders, inventory, payments, refunds and returns.

- Appointment and non-appointment booking workflows.

- Razorpay tenant-account integration and authoritative webhook processing.

- Shiprocket logistics, COD and digital fulfilment.

- Commission ledger, weekly invoicing, credits and commercial suspension.

- GST service workflow, compliance/risk controls and consumer grievance workflow.

- Notifications, analytics event capture and Scale AI usage controls.

- Security, auditability, observability, retention, backup and deployment.

## 1.3 Explicitly Out of Scope for this Design Baseline

- UI/UX component design and Next.js visual implementation.

- Selection of a specific PAN/GST verification vendor, SMS vendor, email vendor, registrar or cloud vendor.

- Professional legal/tax validation of the BRD rules.

- Features explicitly listed by the BRD as out of scope, including UPI checkout, self-shipping, local pickup, cross-store checkout and combined product/service checkout.

## 1.4 Technical Inputs

| Input | Baseline |
| --- | --- |
| Backend framework | FastAPI, Python 3.12+ |
| Persistence | PostgreSQL; one initial cluster with schema-per-service ownership |
| Messaging | Apache Kafka for asynchronous domain/integration events |
| Packaging | Docker per deployable service/worker |
| Orchestration | Kubernetes; horizontal scaling of stateless APIs/workers |
| Database HA/operations | CloudNativePG is the preferred Kubernetes PostgreSQL operator |
| Object storage | S3-compatible private object storage with signed URLs |
| Caching/rate limiting | Redis where useful; never the financial/source-of-truth store |
| Edge | HTTPS + Cloudflare/WAF in front of ingress |
| Observability | OpenTelemetry + Prometheus/Grafana + centralized logs |
| Testing | Pytest + integration/contract tests; AC-001..AC-090 become executable acceptance suites |

> [!NOTE]
> **Design Decision:** Design decision: The first production implementation should optimize for correctness and operability rather than maximum microservice count. Services are separated by business consistency boundary; deployment units can be merged temporarily if the team is small, provided schema and code ownership boundaries remain intact.

# 2. Architecture Principles

| Principle | Implementation consequence |
| --- | --- |
| BRD is authoritative | Technical behavior must remain traceable to BRD requirement IDs and acceptance criteria. |
| Tenant/store context is mandatory | Every tenant/store-scoped command carries tenant_id and store_id; no implicit global lookup. |
| Service owns its writes | Only the owning service writes to its schema. Other services use APIs/events; direct cross-schema writes are forbidden. |
| No cross-service distributed transaction | Use local ACID transaction + transactional outbox + idempotent consumers. |
| State transitions, not arbitrary status updates | Commercial, order, booking, content, payment and commission states change only through validated commands. |
| Historical snapshots are immutable | Plan price, commission rate, tax-relevant values, seller identity and order/booking commercial facts are snapshotted. |
| Configuration over hard-coding | Prices, limits, fair-use controls, timeouts and policy gates that BRD calls configurable are versioned configuration. |
| PostgreSQL is source of truth | Kafka transports facts; Redis accelerates reads/rate limits; neither replaces authoritative persisted state. |
| Webhooks are untrusted external inputs | Validate signatures, deduplicate, retain raw events, process asynchronously and reconcile. |
| Public content is versioned | Pending/rejected content never overwrites currently approved LIVE content. |
| Audit is a product requirement | Material commercial, legal, approval, risk and admin actions generate immutable audit entries. |
| Fail closed for commerce entitlement | If entitlement or restriction cannot be verified safely, new commerce creation is denied while existing obligations remain accessible where BRD requires. |

# 3. System Context and Runtime Topology

## 3.1 Logical Context

`
Clients  - KarobarOne marketing/onboarding app  - Tenant dashboard  - Platform admin/GST operations dashboard  - Public tenant storefronts          | HTTPS          vCloudflare / WAF          |          vKubernetes Ingress / API Gateway          |          +--> FastAPI domain services          |        |          |        +--> PostgreSQL schemas          |        +--> Redis (cache/rate limits)          |        +--> Kafka (domain/integration events)          |          +--> Public Storefront Read API / publication snapshotsExternal adapters  - PAN/GST verification provider(s)  - Razorpay tenant accounts  - Shiprocket  - Email/SMS provider(s)  - Domain registrar/DNS provider  - S3-compatible object storage
`

## 3.2 Kubernetes Runtime

- Each API service runs as a stateless Kubernetes Deployment with readiness/liveness probes and horizontal scaling.

- Long-running consumers/schedulers run as separate Deployments, not inside API pods.

- Kafka consumers use consumer groups so work scales horizontally without duplicate partition ownership.

- PostgreSQL runs through CloudNativePG or an equivalent production PostgreSQL control plane; application pods never manage database lifecycle.

- Ingress exposes public/API routes; internal services remain ClusterIP-only.

- NetworkPolicy restricts service-to-service and database access by namespace/service account.

- Separate production and development environments; staging is strongly recommended before public launch.

## 3.3 Initial Deployment Granularity

The logical design contains multiple services. If the initial backend team is small, related services may share one code repository and even one deployable process during early development, but each must retain separate modules, database schemas and API/event contracts so it can be extracted without a data rewrite.

# 4. Domain and Service Decomposition

| Code | Service | Primary ownership | Schema |
| --- | --- | --- | --- |
| IAM | Identity & Access | Credentials, sessions, JWT, OTP, roles and service authentication | iam |
| TEN | Tenant & Store | PAN tenant identity, Guardian, GSTIN, stores, memberships, Free entitlement | tenant |
| SUB | Subscription & Entitlement | Plans, periods, charges, Third-Period Advance, upgrades, delinquency, reactivation | subscription |
| DOM | Domain & Publication | Free subdomain, custom domain workflow, DNS state, publication routing | domain |
| CAT | Catalog & CMS | Products/services, variants, public content, media metadata, store pages/blog | catalog |
| APR | Approval & Governance | Submission/approval/rejection/emergency takedown workflows | approval |
| CUS | Customer | Store-scoped customers, guest/unclaimed identity, addresses, claim flow | customer |
| INV | Inventory | SKU stock, reservations and movements | inventory |
| COM | Commerce | Product cart, checkout, product orders, returns/refunds orchestration | commerce |
| BKG | Booking | Schedules, capacity, service transactions, reschedule/no-show | booking |
| PAY | Payment Integration | Razorpay connections, payment intent/state, webhooks, reconciliation | payment |
| FUL | Fulfilment | Shiprocket shipping/COD, digital entitlements and secure downloads | fulfilment |
| FIN | Commission & Finance | Commission lifecycle, platform invoices, credits, receipts, financial ledger | finance |
| CMP | Compliance, GST & Risk | GST workflow, licences, grievances, risk signals/restrictions | compliance |
| NTF | Notification | Email/SMS/OTP delivery, templates, retries and delivery audit | notification |
| ANL | Analytics & AI | Analytics event processing, aggregates, AI quota/usage and recommendation records | analytics |

> [!NOTE]
> **Design Decision:** Design decision: No service should be created merely because the BRD has a chapter. The decomposition above groups requirements by data ownership, transaction boundary and change cadence.

# 5. Data Architecture and Multi-Tenant Isolation

## 5.1 PostgreSQL Topology

V1 uses one PostgreSQL cluster with one schema per logical service. Every service uses a dedicated database role with write access only to its own schema and read access only where explicitly unavoidable. Cross-service business reads should normally use API calls or local projections, not direct joins.

`
karobarone PostgreSQL cluster  iam.*  tenant.*  subscription.*  domain.*  catalog.*  approval.*  customer.*  inventory.*  commerce.*  booking.*  payment.*  fulfilment.*  finance.*  compliance.*  notification.*  analytics.*  platform_outbox / optional per-schema outbox tables
`

## 5.2 Identifier Rules

| Field | Rule |
| --- | --- |
| Primary keys | UUID/UUIDv7 where supported; never expose sequential database IDs as security boundaries. |
| tenant_id | Required on all tenant-owned aggregates and projections. |
| store_id | Required on all store-owned aggregates. |
| customer_id | Store-scoped identity; same email/mobile may exist independently in another store. |
| external_id | Provider identifiers stored separately and never reused as internal PK. |
| correlation_id | Propagated across HTTP, Kafka and background jobs. |
| idempotency_key | Required for retry-sensitive creation/payment/refund operations. |

## 5.3 Tenant Isolation

- Application layer injects tenant/store context from authenticated principal; frontend-supplied tenant_id is never trusted by itself.

- PostgreSQL Row-Level Security should be enabled for highly sensitive tenant/store tables where operationally practical.

- Unique constraints include tenant/store scope where business uniqueness is scoped (for example customer email/mobile by store).

- Platform roles use explicitly elevated administrative paths; no “tenant_id = null means admin” shortcut.

- Background consumers reconstruct authorization context from trusted event payload and aggregate ownership, not user input.

## 5.4 Cross-Service References

Cross-service identifiers are stored as UUID values without database foreign keys across service schemas. This avoids tight coupling and preserves the option to move a schema to another database later. Referential validity is enforced when commands are accepted and by reconciliation jobs.

## 5.5 Money, Dates and Time

| Concern | Rule |
| --- | --- |
| Money | Use integer minor units (paise) or NUMERIC with a single platform convention. Never use floating point for commercial calculations. |
| Currency | Persist currency code; V1 defaults to INR but schema must not assume INR-only numeric semantics. |
| Billing period | Exactly 30 consecutive calendar days; calculate by date arithmetic, never “one calendar month”. |
| Timestamps | Store UTC timestamptz; retain business-effective local date where required for tax/booking logic. |
| Snapshots | Persist calculated base, tax, shipping, discount, commission rate and rule/version inputs with transaction records. |

# 6. API Architecture and Standards

## 6.1 External API Style

- Base path: /api/v1/...

- JSON request/response; OpenAPI generated by FastAPI and committed as a versioned contract artifact.

- Commands use explicit action endpoints when a state transition is more precise than generic PATCH (for example /subscriptions/{id}/cancel or /orders/{id}/cancel).

- Pagination uses opaque cursor where high-volume data is expected; simple page/limit may be used for administrative low-volume lists.

- Create/update endpoints that may be safely retried accept Idempotency-Key.

- Provider callbacks use dedicated /webhooks/{provider} routes and are never treated as authenticated tenant requests.

## 6.2 Standard Error Envelope

`
{  "error": {    "code": "SUBSCRIPTION_NOT_ACTIVE",    "message": "New checkout is not allowed for this store.",    "details": {...},    "request_id": "uuid"  }}
`

## 6.3 HTTP Status Guidance

| Status | Use |
| --- | --- |
| 200/201 | Successful query/create. |
| 202 | Asynchronous operation accepted (for example domain provisioning). |
| 400 | Malformed request or invalid command syntax. |
| 401 | Authentication required/invalid. |
| 403 | Authenticated but not authorized, or entitlement/restriction denies action. |
| 404 | Resource not found within permitted scope. |
| 409 | Business conflict / illegal state transition / duplicate PAN or GSTIN. |
| 422 | Field/domain validation failure. |
| 429 | Rate limit or OTP abuse limit. |
| 503 | Dependency unavailable where operation cannot safely continue. |

## 6.4 Service-to-Service Calls

Use synchronous HTTP only when the caller requires an immediate authoritative answer to complete its command. Use short timeouts, explicit retry policy for idempotent calls, circuit breaking at the client/gateway layer and correlation IDs. Do not cascade long dependency chains through many synchronous services.

# 7. Kafka/Event Architecture

## 7.1 Event Use

| Use synchronous API when... | Use Kafka event when... |
| --- | --- |
| The current command needs an immediate decision or reservation. | A durable fact has already occurred and multiple downstream services may react. |
| Examples: check entitlement, reserve stock, obtain shipping quote. | Examples: payment confirmed, order delivered, subscription expired, content approved. |

## 7.2 Standard Event Envelope

`
{  "event_id": "uuid",  "event_type": "payment.confirmed.v1",  "event_version": 1,  "aggregate_type": "payment",  "aggregate_id": "uuid",  "tenant_id": "uuid|null",  "store_id": "uuid|null",  "occurred_at": "UTC timestamp",  "correlation_id": "uuid",  "causation_id": "uuid|null",  "producer": "payment-service",  "payload": {...}}
`

## 7.3 Delivery Guarantees

- Assume at-least-once delivery at application level.

- Every consumer has a processed_events table keyed by event_id + consumer name, or equivalent inbox implementation.

- Producers use transactional outbox in the same database transaction as aggregate changes.

- Outbox publisher retries until Kafka acknowledges; published_at is tracked.

- Consumers are idempotent; financial effects use unique business keys in addition to event deduplication.

- Event schemas are versioned. Breaking changes create a new version rather than silently changing old payloads.

## 7.4 Topic Naming

Preferred pattern: <domain>.<aggregate-or-capability>.<event-family>. Examples: payment.lifecycle, order.lifecycle, subscription.lifecycle. Event type inside the envelope is more granular. Partition by aggregate/store key when ordering is required.

# 8. Workflow, Scheduling and Time-Based Processing

Kafka is not used as a timer. KarobarOne has many time-based rules: inventory TTL, booking payment deadlines, subscription due/grace/expiry/free-conversion, weekly commission invoicing, commission due dates, signed-download expiry and Minor Tenant adult reverification.

> [!NOTE]
> **Design Decision:** Design decision: V1 should use a dedicated Scheduler/Workflow Worker backed by PostgreSQL job tables. Jobs are claimed using SELECT ... FOR UPDATE SKIP LOCKED, carry idempotency keys and can be processed by multiple replicas. Temporal can replace this component later if workflow complexity warrants it.

| Job family | Examples |
| --- | --- |
| Inventory | Expire reservation after configurable target (initially 10 minutes). |
| Booking | Expire unpaid approve-before-pay reservation; release slot capacity. |
| Subscription | Create period charge; enter grace; enter expired; convert to Free on Day 23; apply scheduled downgrade. |
| Commission | Generate weekly invoice; mark overdue after 15 calendar days; reevaluate commerce restriction. |
| Digital fulfilment | Expire/reissue signed download entitlements according to policy. |
| Minor/Guardian | Trigger adult reverification on reaching 18. |
| Reconciliation | Payment/shipping provider reconciliation and stuck-state detection. |

# 9. Detailed Microservice Designs

The table/list names below are an initial logical schema. Physical normalization may evolve, but ownership and invariants should remain stable.

## 9.1. Identity & Access Service

Owns authentication and authorization primitives for platform users, tenant operators, store staff, customers where shared authentication is used, guardians and internal service principals. It does not own tenant commercial identity.

| Aspect | Design |
| --- | --- |
| Owned PostgreSQL schema | iam |
| Core tables | principals, credentials, sessions, refresh_tokens, otp_challenges, role_assignments, service_principals, security_events |
| Primary synchronous interfaces | POST /auth/login; POST /auth/refresh; POST /auth/logout; POST /auth/otp/*; GET /me; admin role-assignment APIs |
| Publishes | identity.principal.created; identity.session.revoked; identity.security-event.recorded |
| Consumes | None |

Critical business rules:

- Access JWT contains principal identity plus authorized tenant/store claims; authorization still checks current role/entitlement where necessary.

- Passwords are strongly hashed; refresh tokens are rotated/revocable.

- OTP values are not stored in plaintext; rate limiting and attempt limits are mandatory.

- Platform-admin roles are separated from tenant/store roles; guardian role does not imply store-management rights.

> [!NOTE]
> **Design Decision:** Design decision: Access-token lifetime, refresh lifetime and MFA policy are configuration values; recommended defaults should be validated during security hardening, not treated as BRD rules.

## 9.2. Tenant & Store Service

Owns the business identity hierarchy: PAN-identified tenant, Minor Tenant/Guardian relationship, verified GSTINs, stores, store memberships and the one-lifetime-Free-Store entitlement.

| Aspect | Design |
| --- | --- |
| Owned PostgreSQL schema | tenant |
| Core tables | tenants, pan_verifications, guardian_profiles, guardian_links, guardian_consents, gstins, gstin_verifications, stores, free_store_entitlements, store_memberships, seller_identity_snapshots |
| Primary synchronous interfaces | POST /tenants/register; POST /tenants/{id}/guardian; POST /tenants/{id}/gstins; POST /stores; GET /stores/{id}; staff membership APIs |
| Publishes | tenant.created; tenant.guardian-required; guardian.consent-accepted; gstin.verified; store.created; store.free-entitlement-consumed |
| Consumes | identity.principal.created |

Critical business rules:

- PAN normalized/hash-search representation must enforce one verified PAN -> one tenant.

- One PAN receives one lifetime Free Store entitlement; upgrading the Free Store changes its plan/status rather than creating a duplicate.

- Paid activation requires GSTIN verified as belonging to the same tenant PAN; one GSTIN cannot activate two paid stores.

- Minor registration cannot complete required legal acceptance until Guardian verification and consent are recorded.

- Historical seller identity is snapshotted and not retrospectively rewritten.

## 9.3. Subscription & Entitlement Service

Owns plan configuration, effective plan versions, store subscription state, exact 30-day billing periods, Third-Period Advance accounting, cancellation notices, upgrades, downgrades, reactivation and entitlement evaluation.

| Aspect | Design |
| --- | --- |
| Owned PostgreSQL schema | subscription |
| Core tables | plans, plan_versions, plan_entitlements, subscriptions, subscription_periods, subscription_charges, subscription_payments, advances, advance_allocations, cancellation_notices, plan_change_requests, upgrade_quotes, upgrade_discount_requests, lifecycle_events, store_entitlement_projection |
| Primary synchronous interfaces | POST /stores/{id}/subscriptions/activate; GET /stores/{id}/entitlements; POST /subscriptions/{id}/cancel; POST /subscriptions/{id}/upgrade-quote; POST /subscriptions/{id}/upgrade; POST /subscriptions/{id}/downgrade; POST /subscriptions/{id}/reactivate |
| Publishes | subscription.activated; subscription.period-started; subscription.payment-due; subscription.grace-entered; subscription.expired; subscription.free-converted; subscription.upgraded; subscription.downgraded; subscription.reactivated; entitlement.changed |
| Consumes | store.created; finance.platform-payment-recorded |

Critical business rules:

- Billing periods are exactly 30 consecutive calendar days.

- First activation charges Period 1 price S + Third-Period Advance S; first-ever setup fee for that store is zero.

- Period 2 is full S. Cancellation recorded before Period 3 causes advance to fund Period 3 and paid service ends after Period 3.

- If continuing, Period 3 and Period 4 each require 0.5S and the original advance is economically credited across those periods.

- Unpaid required charge: Days 1-7 PAYMENT_GRACE; Days 8-22 SUBSCRIPTION_EXPIRED; Day 23 Free conversion.

- Reactivation after non-payment Free conversion charges new period S + 0.5S setup fee and starts a fresh 30-day period.

- Upgrade pricing and advance/top-up calculations are persisted as quote inputs/results and require auditable owner approval for setup-fee discount.

- Entitlements are evaluated from effective plan version plus lifecycle/restriction state; do not infer entitlement solely from plan name.

> [!NOTE]
> **Design Decision:** Design decision: Every charge calculation is generated by a versioned calculation policy and stored with inputs/result so historical invoices are reproducible.

## 9.4. Domain & Publication Service

Owns immutable Free subdomains, paid custom-domain requests, registrar/DNS lifecycle and the mapping that determines whether a store is publicly served on a subdomain/custom domain.

| Aspect | Design |
| --- | --- |
| Owned PostgreSQL schema | domain |
| Core tables | free_subdomains, domain_requests, domains, domain_cost_classifications, dns_checks, store_domain_mappings, publication_routes |
| Primary synchronous interfaces | POST /stores/{id}/subdomain; POST /stores/{id}/domains/options; POST /domain-requests/{id}/select; POST /domain-requests/{id}/purchase; GET /stores/{id}/domain-status |
| Publishes | domain.subdomain-assigned; domain.custom-purchased; domain.dns-verified; domain.ready; publication.route-changed |
| Consumes | store.created; subscription.activated; subscription.free-converted; approval.content-live |

Critical business rules:

- Free subdomain is immutable once created.

- Paid public launch requires custom domain and successful configuration.

- Standard-domain inclusion vs premium/non-standard cost classification is configurable and auditable.

- On Free conversion, custom-domain serving stops and Free subdomain becomes active; direct-paid stores receive an available immutable Free subdomain when required.

## 9.5. Catalog & CMS Service

Owns the tenant storefront content model: unified product/service catalog, variant definitions, media metadata, SEO fields, website sections, blog and policy/public content. Operational fields such as price/active/inventory reference are separated from approval-controlled public versions.

| Aspect | Design |
| --- | --- |
| Owned PostgreSQL schema | catalog |
| Core tables | catalog_items, product_details, service_details, item_public_versions, categories, variant_types, variants, variant_values, item_media, store_pages, page_versions, blog_posts, blog_versions, seo_metadata, store_content_config |
| Primary synchronous interfaces | POST /stores/{id}/items; PATCH /items/{id}/operational; POST /items/{id}/versions; POST /stores/{id}/pages/*; GET public catalog/storefront read APIs |
| Publishes | catalog.item-created; catalog.version-submitted; catalog.item-operational-changed; catalog.item-unpublished; storefront.snapshot-invalidated |
| Consumes | entitlement.changed; approval.version-approved; approval.version-rejected; approval.emergency-takedown |

Critical business rules:

- Free Store supports products and services together but maximum six combined showcase items.

- Paid store may contain physical product, digital product, appointment service and non-appointment service simultaneously.

- Commerce media <=5 images/no video; Growth <=10 images +1 video; Scale AI uses technical/fair-use limits.

- Price, inventory, active/inactive and service availability do not require prior content approval; public title/description/media/category/custom variant and similar controlled content do.

- Higher-plan data is retained but hidden/disabled on downgrade.

- Blog exists only where entitlement allows; comments are not supported in V1.

> [!NOTE]
> **Design Decision:** Design decision: Use a unified catalog_items base table with item_type so Free six-item limits and paid hybrid catalog rules can be enforced consistently.

## 9.6. Approval & Governance Service

Owns generic review workflow for controlled public-facing versions and records platform decisions. Domain services continue to own the content itself.

| Aspect | Design |
| --- | --- |
| Owned PostgreSQL schema | approval |
| Core tables | approval_submissions, approval_decisions, review_assignments, emergency_takedowns, governance_audit |
| Primary synchronous interfaces | POST /approvals; POST /approvals/{id}/approve; POST /approvals/{id}/reject; POST /approvals/{id}/emergency-takedown; GET /approvals/queue |
| Publishes | approval.version-approved; approval.version-rejected; approval.emergency-takedown; approval.resubmitted |
| Consumes | catalog.version-submitted; compliance.restriction-raised |

Critical business rules:

- States: DRAFT -> PENDING -> APPROVED/LIVE or REJECTED; LIVE may become UNPUBLISHED/EMERGENCY_TAKEDOWN.

- A pending version cannot replace current LIVE content.

- Rejection requires reason; rejected version may be modified and resubmitted.

- Authorized Platform Staff can emergency-unpublish suspected illegal/counterfeit/unsafe/fraudulent/prohibited content.

- Every decision records actor, reason, timestamp and referenced immutable content version.

## 9.7. Customer Service

Owns end-customer profiles separately per store, guest/unclaimed lifecycle, addresses and account claiming.

| Aspect | Design |
| --- | --- |
| Owned PostgreSQL schema | customer |
| Core tables | customers, customer_credentials_link, customer_addresses, customer_claim_challenges, customer_privacy_requests |
| Primary synchronous interfaces | POST /stores/{id}/customers/guest; POST /customers/{id}/claim; GET/PATCH /customers/{id}; address APIs; privacy request APIs |
| Publishes | customer.created; customer.unclaimed-created; customer.claimed; customer.privacy-requested |
| Consumes | order.created; booking.created |

Critical business rules:

- Email and mobile are mandatory and each unique within one store.

- The same email/mobile may exist in another store.

- Guest checkout creates or resolves an UNCLAIMED store-scoped profile.

- Returning UNCLAIMED account claim uses Email OTP where required; permanent password may be created after claim.

- Deletion/privacy requests cannot destroy statutory commercial/audit records.

## 9.8. Inventory Service

Owns transactional stock for physical SKUs, optional inventory tracking, time-bound reservations and stock movement history.

| Aspect | Design |
| --- | --- |
| Owned PostgreSQL schema | inventory |
| Core tables | skus, stock_balances, stock_reservations, stock_movements, inventory_adjustments |
| Primary synchronous interfaces | POST /inventory/reservations; POST /inventory/reservations/{id}/consume; POST /inventory/reservations/{id}/release; POST /inventory/adjustments; GET /inventory/availability |
| Publishes | inventory.reserved; inventory.reservation-expired; inventory.consumed; inventory.released; inventory.low-stock |
| Consumes | order.cancelled; refund.completed |

Critical business rules:

- Inventory tracking is optional for physical SKU and effectively unlimited by default for digital product unless restricted.

- Negative inventory/overselling is prohibited.

- Reservation duration is configurable; initial BRD target is 10 minutes.

- Reservation/consume/release operations are atomic and use row-level/conditional-write protection.

- Stock movements are append-only audit records; current balance is a derived/maintained aggregate.

## 9.9. Commerce Service

Owns physical/digital product cart, checkout orchestration, product orders, order-item commercial snapshots, cancellation/return/refund request state and seller invoice trigger.

| Aspect | Design |
| --- | --- |
| Owned PostgreSQL schema | commerce |
| Core tables | carts, cart_items, checkouts, orders, order_items, order_state_history, cancellation_requests, return_requests, refund_requests, seller_invoice_snapshots |
| Primary synchronous interfaces | POST /stores/{id}/carts; POST /carts/{id}/checkout; GET /orders/{id}; POST /orders/{id}/cancel; POST /orders/{id}/returns; POST /orders/{id}/refunds |
| Publishes | order.created; order.payment-pending; order.paid; order.processing; order.shipped; order.delivered; order.cancelled; order.returned; order.refunded; refund.requested |
| Consumes | payment.confirmed; payment.failed; inventory.reserved; inventory.reservation-expired; shipment.status-changed; refund.completed; entitlement.changed |

Critical business rules:

- Exactly one store per cart/checkout/order; cross-store cart is impossible.

- Product checkout may combine physical + digital products but may not contain services.

- Free Store and restricted/expired stores cannot create new commercial orders.

- Order item snapshots include seller identity, product/variant, price, discount, tax, shipping allocation and commission rate/base inputs.

- Order statuses follow BRD minimum state model; transitions are command-validated.

- Physical return/refund rules and partial refunds are supported; COD refund execution occurs outside KarobarOne but evidence is recorded.

## 9.10. Booking Service

Owns appointment and non-appointment service transactions, calendars, capacity, reservations, payment sequence, reschedule and no-show behavior.

| Aspect | Design |
| --- | --- |
| Owned PostgreSQL schema | booking |
| Core tables | service_schedules, schedule_windows, blackouts, service_slots, slot_capacity, booking_reservations, bookings, booking_state_history, booking_payment_terms, reschedule_history |
| Primary synchronous interfaces | POST /services/{id}/availability; POST /services/{id}/bookings; POST /bookings/{id}/approve; POST /bookings/{id}/pay; POST /bookings/{id}/reschedule; POST /bookings/{id}/cancel; POST /bookings/{id}/no-show |
| Publishes | booking.created; booking.approved; booking.payment-pending; booking.confirmed; booking.rescheduled; booking.completed; booking.cancelled; booking.rejected; booking.no-show; booking.refunded |
| Consumes | payment.confirmed; refund.completed; entitlement.changed |

Critical business rules:

- Appointment and non-appointment services use separate service transactions in V1.

- Slots support day/time, duration, capacity, buffers and blackout periods.

- Confirmation may be instant or seller approval required.

- Payment sequence supports pay-before-approval, approve-before-pay, deposit, full advance and pay-after-service.

- Unpaid reservation deadline expiry releases capacity.

- Service price/tax/discount/commission inputs are snapshotted at booking creation.

- Rescheduling creates auditable old/new schedule references and coordinates commission reversal/new commission record.

## 9.11. Payment Integration Service

Owns tenant payment-provider connection metadata, payment intents/attempts, authoritative provider events, verified payment state, provider refund interaction and reconciliation. It never receives/settles customer funds into a KarobarOne merchant account.

| Aspect | Design |
| --- | --- |
| Owned PostgreSQL schema | payment |
| Core tables | provider_accounts, payment_intents, payment_attempts, provider_webhook_events, payment_transactions, provider_refunds, reconciliation_cases |
| Primary synchronous interfaces | POST /stores/{id}/payment-intents; GET /payments/{id}; POST /webhooks/razorpay; POST /payments/{id}/refund; connection/reconciliation APIs |
| Publishes | payment.intent-created; payment.confirmed; payment.failed; payment.refund-initiated; payment.refund-confirmed; payment.provider-disconnected |
| Consumes | order.created; booking.payment-required; refund.requested |

Critical business rules:

- Online payment uses tenant-owned connected Razorpay account/provider context.

- UPI must be excluded from KarobarOne checkout configuration.

- Provider webhook/API event is authoritative; browser redirect alone does not confirm payment.

- Webhook signature is verified; raw payload/headers retained; duplicates ignored by provider-event key.

- Payment record snapshots price/tax/discount/commission-relevant values or references immutable transaction snapshot.

- If provider connection is suspended/disconnected, online payment stops; eligible logistics COD may continue.

## 9.12. Fulfilment Service

Owns integrated logistics, shipping quote/booking/tracking, COD delivery confirmation and digital download entitlement.

| Aspect | Design |
| --- | --- |
| Owned PostgreSQL schema | fulfilment |
| Core tables | logistics_connections, shipping_quotes, shipments, shipment_packages, tracking_events, cod_delivery_status, digital_entitlements, download_links, download_events |
| Primary synchronous interfaces | POST /shipping/quotes; POST /orders/{id}/shipments; POST /webhooks/shiprocket; GET /shipments/{id}; POST /digital-entitlements/{id}/link |
| Publishes | shipment.created; shipment.status-changed; shipment.delivered; cod.delivery-confirmed; digital.entitlement-issued; digital.downloaded |
| Consumes | order.paid; order.processing; payment.confirmed |

Critical business rules:

- Self-shipping and local pickup are not supported.

- Physical fulfilment uses approved integrated logistics; initial provider is Shiprocket.

- COD is valid only through logistics integration capable of authoritative delivery state.

- COD commission trigger is confirmed delivery.

- Digital product delivery uses expiring signed URLs; initial validity 24 hours and maximum 3 downloads per issued entitlement.

- Permanent object-storage URLs are never exposed publicly; download events are auditable.

## 9.13. Commission & Finance Service

Owns commission records, weekly commission invoice/demand, tenant platform invoices for subscription/setup/GST/domain services, credits, receipts and the auditable platform financial ledger.

| Aspect | Design |
| --- | --- |
| Owned PostgreSQL schema | finance |
| Core tables | commission_records, commission_state_history, commission_credits, platform_invoices, platform_invoice_lines, tenant_receipts, financial_ledger, disputes, credit_notes, billing_documents |
| Primary synchronous interfaces | GET /tenants/{id}/commissions; POST /commissions/{id}/dispute; GET /platform-invoices; POST /platform-invoices/{id}/record-payment; finance admin APIs |
| Publishes | commission.receivable; commission.invoiced; commission.paid; commission.overdue; commission.credit-created; finance.platform-payment-recorded; finance.due-cleared |
| Consumes | payment.confirmed; cod.delivery-confirmed; booking.created; booking.cancelled; booking.rejected; booking.no-show; booking.rescheduled; refund.completed; subscription.charge-created |

Critical business rules:

- Commission base = taxable product/service value after discount and eligible refunds, excluding GST and shipping.

- Rate is snapshotted at order/booking creation: Commerce 4%, Growth 2%, Scale AI 1%.

- Prepaid product/service commission becomes receivable on verified tenant payment receipt signal.

- Pay-after-service commission becomes receivable automatically on booking date; customer NO_SHOW does not remove it; valid cancellation may reverse/credit it; seller rejection does not automatically remove it.

- Reschedule reverses old commission and creates new record so only one final commission is payable.

- Weekly consolidated commission invoice/demand per tenant; 15 calendar days to pay; disputes are pay-first/credit-later.

- Overdue commission may trigger tenant/PAN-wide block on new commerce while existing obligations remain manageable.

- Financial ledger is append-only; corrections use reversal/credit entries rather than destructive update.

## 9.14. Compliance, GST & Risk Service

Owns restricted-category policy, licences/authorizations, GST professional-service workflow, grievance tickets, risk indicators and store/tenant restriction decisions.

| Aspect | Design |
| --- | --- |
| Owned PostgreSQL schema | compliance |
| Core tables | category_policies, licence_requirements, seller_documents, gst_cases, gst_data_batches, gst_drafts, gst_approvals, gst_acknowledgements, consumer_complaints, risk_signals, risk_cases, restrictions, restriction_history |
| Primary synchronous interfaces | POST /compliance/documents; POST /gst/cases; POST /gst/cases/{id}/approve; POST /complaints; POST /risk/cases/{id}/restrict; GET /stores/{id}/restrictions |
| Publishes | compliance.document-approved; gst.draft-ready; gst.tenant-approved; gst.filed; risk.signal-raised; restriction.changed |
| Consumes | order.lifecycle events; booking lifecycle events; payment anomalies; approval.emergency-takedown; commission.overdue |

Critical business rules:

- Commerce includes NIL GSTR-1/GSTR-3B service only; non-NIL is separately chargeable. Growth/Scale GST filing is separately chargeable.

- Chargeable GST workflow is quote -> approval/payment -> preparation -> review -> tenant approval -> authorized filing -> acknowledgement storage.

- Tenant approval references immutable draft/version and approver/timestamp/tax period.

- Risk can start store-level and escalate to tenant/PAN level.

- Restrictions must preserve access to existing orders/bookings/shipping/refunds/GST/support/payment of dues where BRD requires.

- Regulated/prohibited categories are configuration-driven and may block approval/commerce until evidence is accepted.

## 9.15. Notification Service

Owns transactional email/SMS/OTP dispatch, templates, retry/delivery tracking and channel rate limits. It does not decide business state.

| Aspect | Design |
| --- | --- |
| Owned PostgreSQL schema | notification |
| Core tables | templates, notification_jobs, delivery_attempts, provider_messages, channel_rate_limits, notification_preferences |
| Primary synchronous interfaces | POST /internal/notifications; template admin APIs; delivery status webhook APIs |
| Publishes | notification.sent; notification.failed; otp.delivery-attempted |
| Consumes | order.*; booking.*; payment.*; subscription.*; commission.*; domain.*; guardian.*; security events |

Critical business rules:

- V1 transactional channels are Email and SMS.

- OTP abuse protection is mandatory.

- Business services publish facts; Notification Service maps facts to templates so notification failure cannot roll back a committed commercial transaction.

- Guardian receives required Minor Tenant legal/consent notifications.

## 9.16. Analytics & AI Service

Owns event-derived reporting models, advanced analytics and Scale AI usage/quota records. It is deliberately downstream of transactional services.

| Aspect | Design |
| --- | --- |
| Owned PostgreSQL schema | analytics |
| Core tables | analytics_events, daily_store_metrics, funnel_metrics, ai_usage_ledger, ai_requests, ai_outputs, ai_recommendations, ai_quota_config |
| Primary synchronous interfaces | GET /stores/{id}/analytics; POST /ai/content; POST /ai/seo; POST /ai/recommendations; AI usage admin APIs |
| Publishes | analytics.metric-updated; ai.usage-recorded; ai.recommendation-created |
| Consumes | catalog views/events; order.*; booking.*; customer events; subscription/entitlement changes |

Critical business rules:

- Commerce receives basic operational analytics; Growth advanced; Scale AI advanced + AI according to entitlement.

- AI usage is quota/credit/model controlled and logged.

- AI recommendations cannot silently modify prices, inventory, tax returns, subscription charges or financial records.

- AI-generated public content passes ordinary content approval where applicable.

# 10. Core State Machines

## 10.1 Subscription State Machine

`
INITIAL_PAID_ACTIVATION  -> ACTIVE_PERIOD_1  -> ACTIVE_PERIOD_2       | cancellation notice before P3       +-> P3_FULLY_PREPAID -> END_PAID_AFTER_P3 -> FREE_PRESENCE       | no cancellation       +-> P3_50_PERCENT_DUE -> P4_50_PERCENT_DUE -> STANDARD_RENEWALAny required due charge not paid:PAYMENT_DUE -> PAYMENT_GRACE (days 1-7)            -> SUBSCRIPTION_EXPIRED (days 8-22)            -> FREE_PRESENCE (day 23)
`

## 10.2 Order State Machine

`
PLACED / PAYMENT_PENDING -> PAID -> PROCESSING -> SHIPPED -> DELIVERED       |                     |          |       +-> FAILED            +-> CANCELLED                                      |                                      +-> RETURNED -> REFUNDEDAny applicable state may enter DISPUTED according to defined workflow.
`

## 10.3 Booking State Machine

`
REQUESTED -> APPROVED -> PAYMENT_PENDING -> CONFIRMED -> COMPLETED    |           |              |            |    |           +-> REJECTED   +-> CANCELLED +-> NO_SHOW    +-> CONFIRMED (instant mode)CONFIRMED/APPROVED -> RESCHEDULED -> new effective booking schedule/stateRefund path -> REFUNDED where applicable
`

## 10.4 Content State Machine

`
DRAFT -> PENDING -> APPROVED/LIVE             |            |             +-> REJECTED |                          +-> UNPUBLISHED                          +-> EMERGENCY_TAKEDOWN
`

## 10.5 Commission State Machine

`
PENDING_TRIGGER -> RECEIVABLE -> INVOICED -> PAID                         |             |                         |             +-> DISPUTED_AFTER_PAYMENT -> CREDIT_PENDING -> CREDIT_APPLIED                         +-> CANCELLED/NON_PAYABLE (only when rule permits)
`

Rule: State-machine transitions must be expressed as domain commands. Generic PATCH status endpoints are prohibited for these aggregates.

# 11. End-to-End Business Workflows

## 11.1 Tenant Registration and Free Presence Publication

1.  Create identity principal and start registration.

2.  Normalize/verify PAN; reject if verified PAN already maps to a tenant.

3.  Perform age determination required by onboarding workflow.

4.  If under 18: create Guardian requirement, verify minimum Guardian information and capture required consent before completing mandatory legal acceptance.

5.  Create tenant and one lifetime Free Store entitlement.

6.  Create Free Store and immutable available storename.karobarone.com subdomain.

7.  Tenant submits website/CMS/catalog content subject to Free limits (maximum six combined products/services; one image/item; no item video).

8.  Controlled content version is submitted to Approval Service.

9.  On approval, Catalog/CMS promotes version LIVE and Publication Service activates public route/snapshot.

10.  Free Store remains non-transactional: no cart, checkout, booking, payment or COD creation APIs succeed.

## 11.2 First Paid Activation

1.  Verify selected store and paid-plan eligibility.

2.  Verify GSTIN belongs to tenant PAN and is unused by another paid store.

3.  Create activation quote: Period 1 price S + Third-Period Advance S + first-ever setup fee 0 + applicable GST.

4.  Record/verify platform subscription payment.

5.  Create subscription, Period 1 and separate advance liability/credit record.

6.  Apply paid plan entitlements and emit entitlement.changed.

7.  Initiate custom-domain selection/purchase/DNS flow.

8.  Paid store can be publicly launched only after custom-domain configuration and required content/compliance approvals are satisfied.

## 11.3 Product Checkout - Prepaid

`
Storefront -> Commerce: create checkoutCommerce -> Subscription: check commerce entitlement/restrictionsCommerce -> Inventory: reserve tracked SKUsCommerce: create order + immutable item/commercial snapshotsCommerce -> Payment: create provider payment intent in tenant Razorpay contextCustomer -> Razorpay: pays tenantRazorpay -> Payment webhook: signed authoritative eventPayment: verify + deduplicate + commit + outbox payment.confirmedCommerce consumes -> mark order PAID; Inventory consumes reservationFinance consumes -> commission RECEIVABLENotification consumes -> receipts/notificationsFulfilment consumes -> shipping/digital entitlement flow
`

Rule: Browser success redirect may update UX, but cannot mark payment successful without authoritative provider confirmation/reconciliation.

## 11.4 COD Physical Product

1.  Order created only if COD is available through approved logistics integration.

2.  Inventory reservation/consumption follows ordinary product rules.

3.  Fulfilment creates Shiprocket shipment/COD context.

4.  Commission remains pending until logistics provider confirms delivery.

5.  cod.delivery-confirmed event makes applicable commission receivable.

## 11.5 Appointment Booking

1.  Booking Service calculates available slot/capacity considering schedule, blackout, buffer and active reservations.

2.  Create atomic slot/capacity reservation.

3.  Apply configured confirmation mode (instant or seller approval) and payment sequence.

4.  For pay-before/advance flows, use Payment Service and authoritative webhook.

5.  For approve-before-pay, scheduler expires unpaid reservation after deadline and releases capacity.

6.  For pay-after-service, Finance creates commission receivable on booking date according to BRD trigger.

7.  Reschedule reverses old commission where applicable, moves capacity safely, creates new commission context and preserves full history.

## 11.6 Subscription Delinquency and Free Conversion

`
Due payment missingDay 1: PAYMENT_GRACE -> reminders; paid functions may continueDay 8: SUBSCRIPTION_EXPIRED -> website visible, existing obligations manageable, no new orders/bookingsDay 23: FREE_PRESENCE conversion  - commerce disabled  - custom domain serving stops  - Free subdomain active  - max 6 showcase items selected/defaulted  - higher-plan data retained but hidden/disabled  - unused Third-Period Advance may be accounting-set-off where BRD allows  - delinquency event is NOT reversed by that set-off
`

## 11.7 Weekly Commission Invoicing and Suspension

1.  Finance selects uninvoiced RECEIVABLE commission records by tenant and invoice cutoff.

2.  Create one consolidated weekly commission invoice/demand with immutable line references.

3.  Due date = invoice date + 15 calendar days.

4.  Tenant payment records settle invoice; disputes occur after payment and successful disputes create credits.

5.  If overdue threshold/state is reached, Compliance/Risk restriction blocks new commerce across tenant/PAN stores while preserving management of existing obligations and payment of dues.

6.  When dues are cleared and no other restriction remains, restriction may be lifted through explicit rule/decision.

## 11.8 Content Approval Without Live Overwrite

`
LIVE v3 remains servedTenant creates DRAFT v4 -> submit -> PENDING v4    -> REJECTED: v3 stays LIVE; v4 editable/resubmittable    -> APPROVED: atomic promotion v4 LIVE; v3 retained historicallyEmergency takedown may unpublish current LIVE immediately with audit record.
`

# 12. Security Architecture

## 12.1 Authentication and Session Security

- Custom JWT access tokens with secure refresh/session management as required by BRD.

- Strong password hashing (Argon2id preferred) and password-reset tokens with short TTL/single use.

- Refresh-token rotation and server-side revocation/session record.

- MFA-ready platform-admin model; production admin MFA is strongly recommended.

- OTP hashed at rest, short-lived, attempt-limited and rate-limited by principal/contact/IP/device risk context.

## 12.2 Authorization

Authorization combines RBAC + resource ownership + plan entitlement + lifecycle/restriction state. A role alone is not sufficient to create commerce if subscription/risk state denies it.

`
authorize(command) =  authenticated_principal  AND role permits command  AND principal assigned to tenant/store  AND resource belongs to tenant/store  AND plan entitlement permits capability  AND lifecycle state permits capability  AND risk/compliance restriction does not block capability
`

## 12.3 Sensitive Data

- PAN/GSTIN/Guardian government-ID data is encrypted at rest where supported, access-controlled and excluded from ordinary logs.

- Store searchable normalized/hash form separately from display/encrypted value where uniqueness/search is required.

- Secrets and provider credentials use Kubernetes Secrets backed by an external secret manager where available; never commit to source control.

- Raw webhooks may contain sensitive data; encrypt/limit retention and redact from operational logs.

## 12.4 Network and Platform Security

- TLS at edge; internal TLS/mTLS can be introduced based on infrastructure maturity.

- Cloudflare/WAF + Kubernetes ingress + per-service rate limits.

- Kubernetes NetworkPolicy restricts DB/Kafka/Redis access.

- Container images run non-root where practical, use read-only filesystem where practical, and undergo dependency/image scanning.

- No public PostgreSQL/Kafka/Redis endpoints.

# 13. Financial Integrity and Ledger Design

## 13.1 Ledger Principle

Commercial balances must be derived from append-only financial records rather than mutable “balance” columns. Balance columns may exist as caches but must be reconstructable from ledger entries.

| Ledger entry type | Example effect |
| --- | --- |
| SUBSCRIPTION_CHARGE | Debit tenant receivable for current 30-day period. |
| THIRD_PERIOD_ADVANCE_RECEIVED | Record advance separately from current-period revenue treatment. |
| ADVANCE_APPLICATION | Apply advance against Period 3 or permitted set-off. |
| ADVANCE_CREDIT_P3/P4 | Economic credit against continuation charge. |
| REACTIVATION_SETUP_FEE | Separate charge = 50% selected plan price. |
| UPGRADE_SETUP_FEE | Separate differential setup component; discount approval recorded separately. |
| COMMISSION_RECEIVABLE | Commission due from originating transaction. |
| COMMISSION_CREDIT | Proportional/approved reversal or dispute credit. |
| TENANT_PAYMENT | Settlement of platform invoice/charge. |

## 13.2 Subscription Calculation Policy

`
Let S = selected plan price per 30-day period.Initial activation: Period1 = S; Third-Period Advance A3 = S; collection before GST = 2S.Period2: due = S.Cancellation before P3: additional P3 payment = 0; A3 consumed against P3; paid ends after P3.Continuation: P3 due = 0.5S; P4 due = 0.5S; P5 onward = S.Reactivation after non-payment Free conversion: new period S + setup fee 0.5S.Upgrade lower L -> higher H with R days remaining:  prorated_subscription_difference = (H - L) * R / 30  advance_top_up = max(0, required_advance - eligible_existing_advance)  gross_upgrade_setup_fee = 0.5 * (H - L)  net_setup_fee = gross_setup_fee - approved_discount_amount  total_additional = prorated_difference + advance_top_up + net_setup_fee + applicable GST
`

Rule: Rounding rules, GST treatment of individual charge components and invoice/tax-document treatment must be finalized with qualified tax/accounting review before production. The engine stores unrounded inputs, configured rounding policy and final amount.

## 13.3 Commission Policy Engine

Commission trigger logic is implemented as explicit policy functions keyed by transaction type/payment sequence. The policy returns trigger state, commission base, snapshotted rate, amount, and reversal eligibility. Recalculation never uses the tenant current plan for an old transaction.

# 14. Media, Files and Digital Fulfilment

- Uploads first create a media record and pre-signed upload URL; application pods do not proxy large binaries unless required for security scanning.

- Object keys are non-guessable and private. Public images are delivered through controlled CDN/proxy URLs, while digital products use time-limited signed URLs.

- Media metadata records MIME type, size, checksum, dimensions/duration, owner tenant/store, content classification, scan status and approval-version reference.

- Image/video technical limits are configuration-driven by plan and fair-use policy.

- Digital download entitlement tracks issued link, expiry, maximum downloads, actual download count and audit events.

- Malware/content scanning is recommended before making uploaded files available.

# 15. Observability and Operational Controls

## 15.1 Structured Logging

Every log line should be structured JSON and carry service, environment, request_id/correlation_id, trace_id, principal_id where safe, tenant_id/store_id where safe, event_id for consumers and a stable error code. PAN/GSTIN/government ID/payment sensitive payloads must not be logged in plaintext.

## 15.2 Metrics

| Category | Examples |
| --- | --- |
| API | request rate, p50/p95/p99 latency, error rate, 429 rate |
| Kafka | consumer lag, publish failures, DLQ count, event processing latency |
| Database | connections, slow queries, lock waits, replication/backup health |
| Business | orders/booking creations, payment confirmation rate, subscription conversions, overdue commission |
| Integration | Razorpay/Shiprocket webhook delay/failure, reconciliation mismatch |
| Scheduler | due jobs, execution delay, retry count, dead jobs |

## 15.3 Audit Log

A platform audit facility records material admin/commercial/legal actions with actor, role, tenant/store, command, old/new/reference version, timestamp, reason, source IP/device metadata where appropriate and correlation ID. Audit records are append-only; sensitive values may be redacted or represented by hashes/references.

# 16. Performance, Scalability and Availability

BRD initial availability target is 99.5%. The design therefore favors horizontal stateless API/consumer scaling and controlled database contention rather than premature multi-region complexity.

| Area | V1 design |
| --- | --- |
| API scaling | Kubernetes HPA based on CPU plus request/latency metrics where available. |
| Kafka scaling | Partition topics by store/aggregate key; add consumer replicas by lag. |
| Database | Indexes begin with tenant_id/store_id on scoped high-volume tables; use partial/indexes for active state queues. |
| Read models | Analytics/public storefront projections prevent expensive cross-domain joins on transactional tables. |
| Caching | Redis for rate limits, ephemeral cache and read acceleration; correctness never depends on cache survival. |
| Backups | Daily PostgreSQL backup with initial 15-day retention; periodic restore test is mandatory. |
| Media | Object storage + CDN; do not store binary media in PostgreSQL. |
| Reconciliation | Scheduled provider reconciliation detects missed/out-of-order webhooks and stuck transactions. |

## 16.1 Scaling Constraints to Watch

- Hot inventory SKU row contention during spikes.

- Appointment-slot capacity contention.

- Large tenant admin list queries without tenant/store/date indexes.

- Kafka partition imbalance if partition key is only tenant_id for very large tenants.

- Approval queue and analytics queries sharing transactional database resources.

- Long-lived subscription/commission scheduler scans without due_at indexes.

# 17. Data Retention, Archival and Deletion

| Data class | Treatment |
| --- | --- |
| Ordinary soft-deleted content | Recoverable for 60 days unless statutory/security/financial rule overrides. |
| Orders/invoices/GST/commission/subscription/advance/setup/audit/required Guardian consent | Do not permanently erase merely because tenant/store closes; retain per applicable policy/law. |
| Store with no commercial history | May be permanently deleted after retention/safety checks. |
| Store with commercial history | Archive/close; retain required records. |
| Provider webhooks | Retain raw verified event for reconciliation/audit for a configured period; redact/encrypt sensitive fields. |
| Analytics | Use retention/aggregation policy separate from statutory transaction history. |
| Privacy deletion | Anonymize deletable personal profile fields while maintaining legally required transaction evidence and referential auditability. |

# 18. Testing and Quality Strategy

## 18.1 Test Layers

| Layer | Purpose |
| --- | --- |
| Unit | Calculation policies, validators, state transitions, permission/entitlement decisions. |
| Repository/DB | Constraints, RLS, transactions, concurrent reservation tests. |
| API integration | FastAPI endpoint + PostgreSQL/Redis/Kafka test environment. |
| Contract | OpenAPI compatibility and producer/consumer event schema compatibility. |
| Workflow | End-to-end multi-service flows including failure/retry/reconciliation. |
| Security | Authz isolation, IDOR, rate limits, secret/log leakage, webhook verification. |
| Performance | Checkout/reservation concurrency, webhook bursts, approval/admin queries. |
| Acceptance | Direct executable mapping of AC-001 through AC-090. |

## 18.2 Mandatory Concurrency Tests

- Two customers attempt to buy the final tracked SKU simultaneously: only one reservation succeeds.

- Two customers attempt to reserve final appointment capacity simultaneously: capacity is never exceeded.

- Duplicate Razorpay webhook: only one payment transition/commission effect occurs.

- Same idempotency key retried after client timeout: returns same creation result.

- Concurrent subscription scheduler replicas: only one lifecycle transition/charge is created.

- Concurrent commission invoice generation: same commission record cannot be invoiced twice.

## 18.3 Acceptance Criteria as Code

Each BRD AC receives a stable test ID, e.g. test_ac_041_billing_period_exactly_30_days. CI must fail if a mandatory V1 AC test is broken. Appendix B assigns an owning service/test suite.

# 19. CI/CD, Repository and Deployment Design

## 19.1 Recommended Monorepo Layout

`
karobarone-backend/  services/    iam-service/    tenant-service/    subscription-service/    domain-service/    catalog-service/    approval-service/    customer-service/    inventory-service/    commerce-service/    booking-service/    payment-service/    fulfilment-service/    finance-service/    compliance-service/    notification-service/    analytics-service/  libs/    platform-contracts/      # event envelopes, common errors, tracing helpers only    test-fixtures/  deploy/    helm/ or kustomize/  contracts/    openapi/    events/  docs/  .github/workflows/ or equivalent
`

Rule: Do not place domain entities/calculation logic in a shared library. Shared domain models create a distributed monolith and prevent independent evolution.

## 19.2 CI Pipeline

1.  Format/lint/type checks.

2.  Unit tests.

3.  Database migration validation on clean database and upgrade path.

4.  OpenAPI/event schema compatibility checks.

5.  Integration tests using ephemeral PostgreSQL/Kafka/Redis.

6.  Security/dependency/container scan.

7.  Build immutable image tagged by commit SHA.

8.  Deploy to development/staging; run smoke + mandatory acceptance subset.

9.  Production deployment with migration gate, readiness checks and rollback procedure.

## 19.3 Database Migration Rules

- Alembic per service/schema.

- Expand/contract changes for zero/low downtime: add nullable/new columns first, backfill, switch code, later remove old fields.

- Never make an irreversible destructive migration in the same deployment that first stops using data.

- Migrations do not rewrite immutable historical snapshots unless a formally approved correction process exists.

# 20. Development Sequence and Delivery Milestones

| Milestone | Backend deliverable |
| --- | --- |
| M0 - Engineering Foundation | Repo/service template, local Docker environment, PostgreSQL schemas, Kafka/outbox, Redis, logging/tracing, CI, auth skeleton, migration conventions. |
| M1 - Free Presence Vertical Slice | IAM + Tenant/PAN/Guardian + Free entitlement/store + Catalog/CMS + Approval + immutable subdomain + publish/read model. Proves multi-tenancy and governance. |
| M2 - Subscription Core | Plan versions/entitlements, first activation, 30-day periods, advance, cancellation, delinquency, Free conversion, reactivation, upgrade/downgrade quotes and tests. |
| M3 - Paid Domain & Publication | GSTIN paid activation gates, custom-domain workflow, DNS/publication, paid storefront entitlement projection. |
| M4 - Product Commerce | Customers, paid catalog/variants, inventory reservation, product cart/order, Razorpay, webhooks, refunds. |
| M5 - Fulfilment | Shiprocket, shipping quote/status, COD, delivery trigger, digital entitlements/downloads. |
| M6 - Booking | Schedules/capacity, all payment sequences, approval, reschedule, no-show and refund interactions. |
| M7 - Commission & Finance | Commission policies, weekly invoice, pay-first disputes/credits, platform ledger and overdue restriction. |
| M8 - Compliance/GST/Risk | Licences, regulated categories, GST service workflow, grievances, risk/suspension and admin operations. |
| M9 - Analytics & Scale AI | Event-derived analytics, advanced dashboards, AI usage/quota and governed AI output workflow. |
| M10 - Hardening | Load/concurrency tests, security review, backup restore test, DR runbook, alert tuning, full AC-001..AC-090 certification. |

## 20.1 Definition of Done per Service

- Schema/migrations reviewed and rollback/forward plan documented.

- OpenAPI endpoints and event schemas versioned.

- Business state machine and illegal transitions tested.

- Outbox/inbox/idempotency implemented for relevant events.

- Authorization/tenant isolation tests included.

- Metrics/logs/traces and operational dashboards/alerts defined.

- BR/AC traceability updated.

- No direct write dependency on another service schema.

# 21. Technical Decisions Still to Finalize

The BRD does not define the following provider/implementation choices. They are not blockers for core domain development because adapters are specified, but they should be finalized before the related integration milestone.

| Decision | Needed by | Recommended design constraint |
| --- | --- | --- |
| PAN/GST verification provider/API | M1/M3 | Adapter interface; persist request/result/provider reference; do not couple tenant model to one vendor. |
| Email/SMS provider | M1 | Notification adapter; delivery status callback support; OTP rate limits. |
| Domain registrar and DNS provider | M3 | Registrar/DNS adapter; idempotent purchase/configuration and periodic verification. |
| Razorpay tenant onboarding/credential model | M4 | Tenant-specific provider account context; encrypted secrets/token lifecycle; UPI excluded. |
| Shiprocket tenant account model | M5 | Clarify whether each tenant connects account or platform delegates; data model supports per-store connection context. |
| Object storage/CDN provider | M1/M4 | Private S3-compatible API, signed URL support, lifecycle rules. |
| Tax calculation/rounding rules | M4/M7 | Qualified tax review; versioned rounding/tax policy; snapshot results. |
| Production cloud/Kafka topology | Before production | Keep app contracts independent of provider; choose managed vs self-hosted based on cost/ops capacity. |
| Admin MFA enforcement | Before production | MFA-ready is BRD minimum; mandatory MFA recommended for Platform Owner/Staff. |
| Analytics privacy/cookie event policy | M9 | Collect only approved metrics; consent/purpose policy where required. |

# Appendix A. BRD-to-Service Traceability

| BRD range | Business area | Primary technical owner(s) |
| --- | --- | --- |
| BR-001..007 | Core platform principles, tenant isolation, seller/payment model, 30-day periods | TEN, SUB, platform architecture |
| BR-010..029 | PAN/GSTIN/Minor/Guardian/store identity | TEN, IAM |
| BR-030..039 | Plan entitlement/pricing/setup | SUB |
| BR-040..049 | Domains and Free/custom-domain transitions | DOM, SUB |
| BR-050..053 | Roles/permissions/Guardian scope | IAM, TEN |
| BR-060..069 | Onboarding/publication/licences/categories | TEN, APR, CMP, DOM |
| BR-070..075 | Free Presence behavior/sections/limits | CAT, SUB, DOM |
| BR-080..083 | Paid hybrid commerce/CMS | CAT, SUB |
| BR-090..094 | Media limits/downgrade retention | CAT, SUB |
| BR-100..104 | Checkout separation/store isolation | COM, BKG |
| BR-110..118 | Products/variants/inventory | CAT, INV |
| BR-120..129 | Service/booking | BKG, PAY, FIN |
| BR-130..136 | Customer/guest/claim | CUS, IAM |
| BR-140..145 | Payment model/Razorpay/webhooks | PAY, COM, BKG |
| BR-150..158 | Shipping/COD/digital fulfilment | FUL, FIN |
| BR-160..175 | Commission/invoice/dispute/suspension | FIN, CMP |
| BR-180..192 | Subscription lifecycle/advance/upgrade/downgrade/reactivation | SUB, FIN |
| BR-200..209 | GST compliance workflow | CMP, FIN |
| BR-210..216 | Approval/versioning/content governance | APR, CAT, CMP |
| BR-220..228 | Orders/cancellations/returns/refunds | COM, PAY, INV, FUL |
| BR-230..235 | Seller/platform invoices/tax docs | COM, FIN |
| BR-240..246 | Notification/OTP | NTF, IAM |
| BR-250..257 | Risk/suspension/termination | CMP, SUB/COM/BKG enforcement |
| BR-260..264 | Analytics/reporting | ANL, FIN, SUB |
| BR-270..271 | Scale AI | ANL, APR |
| BR-280..287 | Consumer/tax/regulatory controls | CMP, CAT, TEN |
| Section 30 NFR | Security, isolation, audit, webhooks, backup, scaling, observability | All; platform architecture |
| BR-290..295 | Retention/export/closure | All owners + TEN/CMP governance |

# Appendix B. Acceptance Criteria Ownership Matrix

| AC | Criterion | Owner | Primary automated test |
| --- | --- | --- | --- |
| AC-001 | One PAN cannot create a second tenant account | TEN | API + invariant integration test |
| AC-002 | One PAN cannot create a second lifetime Free Store after entitlement is consumed | TEN | API + invariant integration test |
| AC-003 | Free Store cannot create carts, orders, bookings or checkout transactions | CAT/SUB | API + invariant integration test |
| AC-004 | Free Store cannot showcase more than 6 products/services combined | CAT/SUB | API + invariant integration test |
| AC-005 | Each Free showcase item supports max 1 image and no video | CAT/SUB | Domain/API acceptance test |
| AC-006 | Paid catalog is not blocked by the Free six-item limit | TEN/CAT/SUB | Domain/API acceptance test |
| AC-007 | Paid store may contain products and services | TEN/CAT/SUB | Domain/API acceptance test |
| AC-008 | Paid commerce cannot activate until GSTIN is verified against tenant PAN | TEN/CAT/SUB | API + invariant integration test |
| AC-009 | Same GSTIN cannot activate two paid stores | TEN/CAT/SUB | API + invariant integration test |
| AC-010 | Different GSTIN-based stores under same PAN may use different paid plans | TEN/CAT/SUB | Domain/API acceptance test |
| AC-011 | No turnover-based mandatory upgrade exists | TEN/CAT/SUB | Domain/API acceptance test |
| AC-012 | Commerce item media allows max 5 images and no video | TEN/CAT/SUB | Domain/API acceptance test |
| AC-013 | Growth item media allows max 10 images + 1 video | TEN/CAT/SUB | Domain/API acceptance test |
| AC-014 | Scale AI has no commercial media-count ceiling, subject to technical limits | TEN/CAT/SUB | Domain/API acceptance test |
| AC-015 | Product/service checkout cannot be combined | COM/BKG | API + invariant integration test |
| AC-016 | Physical and digital products may share Product Checkout | COM/BKG | Domain/API acceptance test |
| AC-017 | Appointment and non-appointment services use separate transactions | COM/BKG | Domain/API acceptance test |
| AC-018 | Cross-store cart/checkout is impossible | COM/BKG | API + invariant integration test |
| AC-019 | Self-shipping/local pickup unavailable | FUL | API + invariant integration test |
| AC-020 | COD requires approved logistics | FUL | API + invariant integration test |
| AC-021 | COD commission becomes receivable on confirmed delivery | FIN/COM/BKG/FUL | Financial/event integration test |
| AC-022 | Prepaid commission trigger uses confirmed/verified payment receipt | FIN/COM/BKG/FUL | Financial/event integration test |
| AC-023 | Pay-after-service commission becomes receivable on booking date | FIN/COM/BKG/FUL | Financial/event integration test |
| AC-024 | Eligible customer cancellation may reverse pay-after-service commission | FIN/COM/BKG/FUL | Financial/event integration test |
| AC-025 | Seller rejection of valid booking does not automatically remove commission | FIN/COM/BKG/FUL | API + invariant integration test |
| AC-026 | NO\_SHOW does not remove applicable commission | FIN/COM/BKG/FUL | API + invariant integration test |
| AC-027 | Rescheduling prevents double commission | FIN/COM/BKG/FUL | Financial/event integration test |
| AC-028 | Commission calculation excludes GST and shipping | FIN/COM/BKG/FUL | Financial/event integration test |
| AC-029 | Weekly commission demand has 15-calendar-day payment window | FIN/COM/BKG/FUL | Financial/event integration test |
| AC-030 | Commission disputes use pay-first/credit-later model | FIN/COM/BKG/FUL | Financial/event integration test |
| AC-031 | Commerce includes NIL GSTR-1/GSTR-3B only | CMP | Domain/API acceptance test |
| AC-032 | Commerce non-NIL GST work requires separate quotation | CMP | API + invariant integration test |
| AC-033 | Growth/Scale GST filing is separately chargeable | CMP | Domain/API acceptance test |
| AC-034 | GST filing requires recorded tenant approval | CMP | API + invariant integration test |
| AC-035 | Registrant below 18 cannot complete required onboarding without Guardian workflow | TEN/IAM | API + invariant integration test |
| AC-036 | Minor Tenant uses own verified PAN | TEN/IAM | Domain/API acceptance test |
| AC-037 | Minor Paid Store GSTIN must belong to Minor Tenant PAN | TEN/IAM | Domain/API acceptance test |
| AC-038 | Guardian government ID and signed consent must be recorded | TEN/IAM | Domain/API acceptance test |
| AC-039 | Guardian data collection is limited to required minimum | TEN/IAM | Domain/API acceptance test |
| AC-040 | Minor reaching 18 triggers adult reverification | TEN/IAM | Domain/API acceptance test |
| AC-041 | Subscription Billing Period is exactly 30 calendar days | SUB/FIN | Policy/state-machine + scheduler test |
| AC-042 | First paid activation collects Period 1 fee plus 100% Third-Period Advance | SUB/FIN | Policy/state-machine + scheduler test |
| AC-043 | First-ever setup of each individual store is complimentary | SUB/FIN | Domain/API acceptance test |
| AC-044 | Period 2 requires full applicable subscription payment | SUB/FIN | API + invariant integration test |
| AC-045 | Cancellation notice can be submitted any time before Period 3 starts | SUB/FIN | Policy/state-machine + scheduler test |
| AC-046 | Valid cancellation before Period 3 produces ₹0 additional Period-3 payment | SUB/FIN | Policy/state-machine + scheduler test |
| AC-047 | Valid cancellation allows full paid functionality during Period 3 | SUB/FIN | Policy/state-machine + scheduler test |
| AC-048 | Valid cancellation causes paid subscription to end after Period 3 | SUB/FIN | Policy/state-machine + scheduler test |
| AC-049 | No cancellation notice means subscription continuation | SUB/FIN | Domain/API acceptance test |
| AC-050 | Continuing Period 3 charge equals 50% of applicable plan price | SUB/FIN | Policy/state-machine + scheduler test |
| AC-051 | Continuing Period 4 charge equals 50% of applicable plan price | SUB/FIN | Policy/state-machine + scheduler test |
| AC-052 | Advance credits across Period 3 and 4 total 100% of original advance | SUB/FIN | Policy/state-machine + scheduler test |
| AC-053 | Period 5 onward returns to full normal subscription | SUB/FIN | Domain/API acceptance test |
| AC-054 | Missing required payment triggers 7-day PAYMENT\_GRACE | SUB/FIN | Policy/state-machine + scheduler test |
| AC-055 | Days 8–22 become SUBSCRIPTION\_EXPIRED | SUB/FIN | Policy/state-machine + scheduler test |
| AC-056 | Day 23 unpaid converts store to Free Presence | SUB/FIN | Policy/state-machine + scheduler test |
| AC-057 | During SUBSCRIPTION\_EXPIRED, no new orders/bookings may be created | SUB/FIN | API + invariant integration test |
| AC-058 | Existing obligations remain manageable during delinquency | SUB/FIN | Domain/API acceptance test |
| AC-059 | Free conversion stops custom-domain serving | SUB/FIN | Domain/API acceptance test |
| AC-060 | Free conversion leaves no more than 6 showcase items | SUB/FIN | Domain/API acceptance test |
| AC-061 | Higher-plan data is retained but disabled after Free conversion | SUB/FIN | Domain/API acceptance test |
| AC-062 | Third-Period Advance does not automatically settle Period 2 while Period 2 payment is still within its normal payment/grace lifecycle | SUB/FIN | API + invariant integration test |
| AC-063 | Unused advance may be set off against outstanding subscription at Free conversion | SUB/FIN | Policy/state-machine + scheduler test |
| AC-064 | Such set-off does not automatically restore paid status | SUB/FIN | API + invariant integration test |
| AC-065 | Reactivation requires full new 30-day subscription fee | SUB/FIN | API + invariant integration test |
| AC-066 | Reactivation Setup Fee equals 50% of selected plan fee | SUB/FIN | Policy/state-machine + scheduler test |
| AC-067 | Reactivation date starts a new 30-day Billing Period | SUB/FIN | Policy/state-machine + scheduler test |
| AC-068 | Complimentary Initial Setup cannot be reused for reactivation | SUB/FIN | API + invariant integration test |
| AC-069 | Mid-period upgrade subscription difference is prorated by remaining days | SUB/FIN | Policy/state-machine + scheduler test |
| AC-070 | Upgrade before Period 3 recalculates Third-Period Advance | SUB/FIN | Policy/state-machine + scheduler test |
| AC-071 | Advance Top-Up equals required advance minus existing eligible advance | SUB/FIN | Policy/state-machine + scheduler test |
| AC-072 | Gross Upgrade Setup Fee equals 50% of plan-price difference | SUB/FIN | Policy/state-machine + scheduler test |
| AC-073 | Upgrade Setup Fee discount requires Platform Owner approval | SUB/FIN | API + invariant integration test |
| AC-074 | Setup discount approval is auditable | SUB/FIN | Domain/API acceptance test |
| AC-075 | Upgrade setup discount does not automatically waive subscription-price difference | SUB/FIN | API + invariant integration test |
| AC-076 | Customer email/mobile are mandatory and unique within store | CUS/IAM | Domain/API acceptance test |
| AC-077 | Guest checkout creates UNCLAIMED customer | CUS/IAM | Domain/API acceptance test |
| AC-078 | Email OTP is used to claim UNCLAIMED account | CUS/IAM | Domain/API acceptance test |
| AC-079 | Controlled content cannot go LIVE without approval | APR/CAT | API + invariant integration test |
| AC-080 | Rejected content records reason | APR/CAT | Domain/API acceptance test |
| AC-081 | Platform Staff can emergency-unpublish suspicious/prohibited content | APR/CAT | Domain/API acceptance test |
| AC-082 | Sellers cannot delete historical commercial transactions | COM/TEN | API + invariant integration test |
| AC-083 | Store with commercial history is archived rather than destructively erased | COM/TEN | Domain/API acceptance test |
| AC-084 | Free subdomain is immutable | DOM | Domain/API acceptance test |
| AC-085 | Paid public launch requires custom domain | DOM | API + invariant integration test |
| AC-086 | Standard qualifying domain cost is included according to commercial policy | DOM | Domain/API acceptance test |
| AC-087 | Premium domain requires additional approval/payment | DOM | API + invariant integration test |
| AC-088 | Domain transfer after closure is not automatic | DOM | Domain/API acceptance test |
| AC-089 | UPI through KarobarOne checkout is unavailable | PAY/Platform | API + invariant integration test |
| AC-090 | Platform does not hold customer purchase funds | PAY/Platform | API + invariant integration test |

# Appendix C. Initial Kafka Topic Catalog

| Topic | Producer | Purpose |
| --- | --- | --- |
| identity.lifecycle | IAM | Principal/security lifecycle facts. |
| tenant.lifecycle | TEN | Tenant/Guardian/GSTIN/store lifecycle. |
| subscription.lifecycle | SUB | Activation, period, grace, expiry, conversion, upgrade, reactivation. |
| entitlement.changed | SUB | Store capability projection changes. |
| domain.lifecycle | DOM | Subdomain/custom-domain/DNS/publication route changes. |
| catalog.lifecycle | CAT | Catalog operational/public version changes. |
| approval.lifecycle | APR | Approval/rejection/takedown decisions. |
| customer.lifecycle | CUS | Customer/claim/privacy events. |
| inventory.lifecycle | INV | Reserve/consume/release/expiry/low-stock. |
| order.lifecycle | COM | Order state changes. |
| refund.lifecycle | COM/PAY | Refund request/provider completion. |
| booking.lifecycle | BKG | Booking state/reschedule/no-show. |
| payment.lifecycle | PAY | Payment/refund/provider connection events. |
| shipment.lifecycle | FUL | Shipment/tracking/delivery/COD. |
| digital-fulfilment.lifecycle | FUL | Digital entitlement/download events. |
| commission.lifecycle | FIN | Commission trigger/invoice/payment/credit. |
| platform-finance.lifecycle | FIN | Subscription/platform payment/invoice facts. |
| compliance.lifecycle | CMP | GST/licence/compliance workflow. |
| risk.lifecycle | CMP | Signals/restriction changes. |
| notification.delivery | NTF | Delivery result events, mainly for operations. |
| analytics.ingest | ANL | Normalized behavior/operational events where direct domain topics are not used. |

# Appendix D. Initial Database Schema Catalog

| Schema | Owning service | Ownership summary |
| --- | --- | --- |
| iam | Identity & Access | Credentials, sessions, JWT, OTP, roles and service authentication |
| tenant | Tenant & Store | PAN tenant identity, Guardian, GSTIN, stores, memberships, Free entitlement |
| subscription | Subscription & Entitlement | Plans, periods, charges, Third-Period Advance, upgrades, delinquency, reactivation |
| domain | Domain & Publication | Free subdomain, custom domain workflow, DNS state, publication routing |
| catalog | Catalog & CMS | Products/services, variants, public content, media metadata, store pages/blog |
| approval | Approval & Governance | Submission/approval/rejection/emergency takedown workflows |
| customer | Customer | Store-scoped customers, guest/unclaimed identity, addresses, claim flow |
| inventory | Inventory | SKU stock, reservations and movements |
| commerce | Commerce | Product cart, checkout, product orders, returns/refunds orchestration |
| booking | Booking | Schedules, capacity, service transactions, reschedule/no-show |
| payment | Payment Integration | Razorpay connections, payment intent/state, webhooks, reconciliation |
| fulfilment | Fulfilment | Shiprocket shipping/COD, digital entitlements and secure downloads |
| finance | Commission & Finance | Commission lifecycle, platform invoices, credits, receipts, financial ledger |
| compliance | Compliance, GST & Risk | GST workflow, licences, grievances, risk signals/restrictions |
| notification | Notification | Email/SMS/OTP delivery, templates, retries and delivery audit |
| analytics | Analytics & AI | Analytics event processing, aggregates, AI quota/usage and recommendation records |

# Appendix E. Engineering Rules Checklist

- No direct cross-service database writes.

- No money represented using binary floating point.

- No arbitrary update of state-machine status fields.

- No payment success based only on browser redirect.

- No Kafka consumer that is not idempotent.

- No event publish without transactional outbox for transactionally significant facts.

- No hard-delete of statutory/commercial history.

- No public permanent object-storage URL for digital products.

- No tenant/store query without explicit scope.

- No use of current plan/rate to recalculate historical order/booking commission.

- No deployment of a DB migration without integration test and recovery plan.

- No new business rule added only in frontend; backend remains enforcement authority.

# Engineering Baseline Statement

This Backend Technical Design Document V1.0 is the proposed implementation baseline derived from KarobarOne BRD V2.1. It is intentionally specific enough for database design, API/event contract work, sprint decomposition and QA automation. Provider selections and compliance-sensitive implementation details listed in Section 21 remain technical decisions to finalize; they do not change the approved business behavior unless the BRD is formally amended.

Source analysis covered 219 explicit BR-* requirements and 90 AC-* acceptance criteria in the supplied BRD.
