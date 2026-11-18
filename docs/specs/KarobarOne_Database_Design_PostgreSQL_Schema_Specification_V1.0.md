**KAROBARONE**

Database Design &
PostgreSQL Schema Specification

Implementation-grade database baseline derived from BRD V2.1 and Backend Technical Design V1.0

| Document Field | Value |
| --- | --- |
| Document Version | 1.0 — Initial Database Design Baseline |
| Status | Implementation Specification |
| Effective Date | 13 September 2026 |
| Product | KarobarOne |
| Primary Database | PostgreSQL |
| ORM / Migration Target | SQLAlchemy 2.x / Alembic |
| Logical Architecture | Single PostgreSQL cluster initially; service-owned schemas; future separable |
| Purpose | Source of truth for PostgreSQL schemas, tables, constraints, indexes, RLS, retention, migrations and database implementation |

| Authority — Business behaviour remains governed by KarobarOne BRD V2.1. This document converts those rules into database structures and technical constraints. Where the BRD is silent, items labelled Design Decision are engineering defaults and may be changed without altering business rules. |
| --- |

# 1. Purpose and Design Scope

This specification converts the approved business baseline and backend architecture into an implementation-ready PostgreSQL design. It is intended for backend engineers, database engineers, QA, security reviewers and DevOps. It defines data ownership and invariants; it does not replace application-level workflow logic or professional legal/tax review.

- Concrete PostgreSQL schemas and table definitions for all 16 logical backend services.
- Primary/foreign keys, uniqueness, CHECK constraints, indexes, tenant/store scoping and RLS policy patterns.
- Audit, versioning, idempotency, transactional outbox, immutable financial/compliance history and retention rules.
- Concurrency rules for inventory, booking capacity, subscriptions, one-time entitlements and state transitions.
- Migration/build order for direct conversion into SQLAlchemy models and Alembic revisions.

| Design Decision — V1 uses one highly available PostgreSQL cluster with separate service-owned schemas and database roles. A service may read/write only its schema. Cross-service relationships use UUID references/contracts rather than direct table writes. |
| --- |

# 2. PostgreSQL Topology and Schema Ownership

One PostgreSQL cluster is used initially to minimize operational cost while retaining microservice ownership boundaries. Each service receives a dedicated schema owner role; runtime roles receive only the privileges required by that service. Cross-schema writes are prohibited.

| Schema | Owning Service | Authoritative Data | Isolation / RLS |
| --- | --- | --- | --- |
| iam | Identity & Access Service (IAM) | Credentials, sessions, OTP, RBAC and security audit. | Principal/security tables are IAM-owned; tenant/store scope is enforced on role assignments rather than treating one principal as belonging to one tenant. |
| tenant | Tenant & Store Service (TEN) | PAN-based tenant identity, Minor/Guardian workflow, GSTIN inventory, stores and the lifetime Free Store entitlement. | Tenant data uses tenant_id; store records add store_id where applicable. Platform review uses dedicated restricted roles. |
| subscription | Subscription & Entitlement Service (SUB) | Plan versions, exact 30-day periods, Third-Period Advance, cancellation, delinquency, upgrades/downgrades and reactivation. | Every subscription row is tenant/store scoped. Financial calculation history is immutable/snapshot-driven. |
| domain | Domain & Publication Service (DOM) | Immutable Free subdomains, custom-domain lifecycle, DNS verification and publication routing. | Store-scoped; Platform Staff have controlled operational domain access. |
| catalog | Catalog & CMS Service (CAT) | Products, services, variants, SKUs, media metadata, storefront content, blog/forms and SEO metadata. | Strict tenant_id/store_id RLS. Public reads use approved live pointers/read models, never draft rows. |
| approval | Approval & Governance Service (APR) | Controlled content review, rejection, approval and emergency takedown. | Tenant/store scoped requests; Platform Staff have review queue access. Decisions are append-only. |
| customer | Customer Service (CUS) | Store-scoped customers, guest/unclaimed identity, addresses, account claim and privacy requests. | Always tenant_id + store_id scoped. Email and mobile uniqueness are per store, not global. |
| inventory | Inventory Service (INV) | Transaction-safe SKU stock, checkout reservations and immutable movements. | Store-scoped. Quantity changes are only performed by Inventory service under locking/atomic updates. |
| commerce | Commerce Service (COM) | Product cart, checkout, orders, cancellations, returns and refund orchestration. | All records store-scoped. One cart/order belongs to exactly one store; commerce tables accept product transactions only. |
| booking | Booking Service (BKG) | Appointment/non-appointment service transactions, schedules, capacity holds, deadlines, rescheduling and no-show state. | Store-scoped. Appointment and non-appointment services use distinct service transactions through booking_type. |
| payment | Payment Integration Service (PAY) | Tenant-owned Razorpay/provider connections, payment intents/attempts, authoritative webhooks, refunds and reconciliation. | Store-scoped. Credentials/tokens are encrypted; provider callbacks are idempotent. KarobarOne does not own customer settlement funds. |
| fulfilment | Fulfilment Service (FUL) | Shiprocket/logistics shipping and COD plus secure digital-product entitlement/download records. | Store-scoped. Address snapshots are protected PII; digital access tokens are hashed. |
| finance | Commission & Finance Service (FIN) | Commission receivables, weekly commission invoicing, disputes/credits, platform invoices and append-only accounting ledger. | Tenant/store scoped except tenant-level invoices. This schema never represents customer purchase funds as KarobarOne-owned cash. |
| compliance | Compliance & Risk Service (CMP) | GST assistance workflow, category/licence controls, consumer grievances, risk signals and restrictions. | Mixed scope: tenant/store records are RLS-protected; platform reference rules are admin-only. Filing approval references immutable GST drafts. |
| notification | Notification Service (NTF) | Transactional Email/SMS/OTP delivery, templates, rate limits and provider callback audit. | Store/tenant scope where relevant. Notification payloads must minimize PII and never contain secrets or raw PAN/GSTIN. |
| analytics | Analytics & AI Service (ANL) | Event ingestion, store aggregates, AI usage/quota accounting and AI output provenance. | Analytics is derived data. It must not become the authority for orders, subscription, tax, price, inventory or other financially material fields. |

karobarone PostgreSQL cluster

├── iam              Identity & Access

├── tenant           Tenant & Store

├── subscription     Subscription & Billing

├── domain           Domain & Publication

├── catalog          Catalog & CMS

├── approval         Approval & Governance

├── customer         Customer

├── inventory        Inventory

├── commerce         Commerce / Orders / Refunds

├── booking          Booking

├── payment          Payment Integrations

├── fulfilment       Shipping / Digital Fulfilment

├── finance          Commission & Platform Finance

├── compliance       GST / Risk / Consumer Compliance

├── notification     Email / SMS

└── analytics        Analytics / AI

# 3. Global Data-Modelling Standards

| Concern | PostgreSQL Representation | Rule |
| --- | --- | --- |
| Core identifiers | uuid | Use gen_random_uuid(). UUIDs cross service boundaries safely and avoid sequence coupling. |
| Timestamps | timestamptz | Store UTC instants. Render tenant/customer time zones at application edge. |
| Calendar values | date / time | Use date for GST/accounting periods and local schedule dates; time for service opening windows. |
| Money | numeric(18,2) | Never float/double. Store currency_code where non-INR support is possible. |
| Rates / percentages | numeric(9,6) | Commission/tax/discount rates as decimal fractions or explicitly documented percentage units. |
| Quantities | numeric(18,3) | Supports fractional units where allowed; integer where business object is discrete. |
| Case-insensitive identity | citext | Emails and domains; enable citext extension. |
| Statuses | varchar + CHECK/catalog | Avoid PostgreSQL ENUM for frequently evolving workflow states; preserve migration flexibility. |
| Flexible/snapshot data | jsonb | Only for bounded configuration, event payloads, provider metadata and immutable snapshots—not as substitute for relational columns. |
| Sensitive identifiers | encrypted bytea + HMAC fingerprint | PAN/GSTIN/government IDs are encrypted; deterministic fingerprint supports uniqueness/search without plaintext. |
| Version control | version bigint | Optimistic-lock column on frequently updated aggregates where concurrent mutation is possible. |
| Deletion | archived_at / deleted_at | Only for records whose lifecycle permits it; financial/commercial/audit records are append-only/archived, not destructively deleted. |

Required extensions: pgcrypto and citext. pg_trgm is optional and should be enabled only if measured search requirements justify it. All production timestamps are UTC. Database and application logs must redact credentials, PAN/GSTIN plaintext, guardian government identifiers, OTP values and provider secrets.

# 4. Multi-Tenant Isolation and PostgreSQL RLS

Tenant/store isolation is enforced in both the application and PostgreSQL. API authentication establishes tenant_id, authorized store_ids and actor_id. The database transaction sets trusted session variables; RLS policies then constrain access independently of query predicates.

BEGIN;

SET LOCAL app.tenant_id = '<tenant-uuid>';

SET LOCAL app.store_id  = '<store-uuid>';

SET LOCAL app.actor_id  = '<principal-uuid>';

SELECT ...;

COMMIT;

ALTER TABLE commerce.orders ENABLE ROW LEVEL SECURITY;

CREATE POLICY orders_tenant_store_policy

ON commerce.orders

USING (

tenant_id = current_setting('app.tenant_id', true)::uuid

AND store_id = current_setting('app.store_id', true)::uuid

)

WITH CHECK (

tenant_id = current_setting('app.tenant_id', true)::uuid

AND store_id = current_setting('app.store_id', true)::uuid

);

| Context | Policy |
| --- | --- |
| Tenant dashboard | tenant_id required; store-specific operation also requires authorized store_id. |
| Storefront/public read | Resolve host/domain → store_id in trusted gateway/service; use narrowly privileged read path. |
| Platform Staff | Separate admin DB role/application permission. RLS may use explicit admin policies; never bypass by default runtime role. |
| Workers | Set tenant/store context from verified event payload before business queries. |
| Connection pooling | With transaction pooling, SET LOCAL must occur inside every transaction; never rely on session persistence. |

# 5. Cross-Service Ownership and Foreign-Key Policy

A table may have hard foreign keys to tables owned by the same service/schema. By default, IDs that refer to aggregates owned by another service are UUID references without cross-schema FK constraints. The owning service validates them synchronously when required or consumes authoritative events and maintains projections. This avoids coupling migration/deletion order across services.

| Relationship | Database Rule | Example |
| --- | --- | --- |
| Within same schema | Use FK + appropriate ON DELETE behaviour. | inventory.reservations → inventory.stock_items |
| Across service schemas | No hard FK by default; store UUID and snapshot fields where needed. | commerce.orders.customer_id → Customer Service aggregate |
| Historical commercial data | Snapshot names, price, tax, discount, commission rates and policy versions; never depend on current catalog/config. | commerce.order_items |
| Derived projections | May be rebuilt from Kafka/source APIs; never authoritative. | analytics.daily_store_metrics |
| Deletion | Owning service emits archive/delete event; dependants preserve legally/audit-required history. | Customer privacy request does not erase statutory invoices/orders. |

# 6. Standard Service Infrastructure Tables

Every service that performs durable business mutations should include the following infrastructure tables in its own schema. These tables are intentionally repeated per service so a service can be extracted to another database later without losing guarantees.

| Table | Minimum Columns | Required Behaviour |
| --- | --- | --- |
| outbox_events | id uuid PK; aggregate_type; aggregate_id; event_type; event_version; tenant_id; store_id; payload jsonb; headers jsonb; occurred_at; published_at; publish_attempts; last_error | Business mutation and event record are committed in one transaction. Partial index WHERE published_at IS NULL. |
| processed_events | consumer_name; event_id; processed_at; source_topic; source_partition; source_offset | UNIQUE(consumer_name,event_id). Insert in same transaction as consumer side effects. |
| api_idempotency | scope_id; idempotency_key; request_hash; response_status; response_body; created_at; expires_at | UNIQUE(scope_id,idempotency_key). Reusing key with different request_hash is rejected. |
| audit_events | id; tenant_id/store_id; actor_id; action; entity_type/id; old_json; new_json; reason; source; correlation_id; occurred_at | Append-only; no UPDATE/DELETE for runtime role. Use partitions only after volume justifies it. |

# 7. Detailed Schema Specifications

The following tables are the V1 implementation baseline. “BRD Source” identifies the business rules represented. “Technical rule” includes database constraints and implementation choices. Support tables are listed after each core table set; developers should implement them when the related capability enters its milestone.

## 7.1  iam — Identity & Access Service (IAM)

Credentials, sessions, OTP, RBAC and security audit.

| Isolation / access — Principal/security tables are IAM-owned; tenant/store scope is enforced on role assignments rather than treating one principal as belonging to one tenant. |
| --- |

### iam.principals

Canonical login/security principal.

BRD source: BR-050..053; Security NFRs

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Principal ID. |
| principal_type | varchar(24) | No | 'USER' | CHECK USER/SERVICE | Human or service principal. |
| email | citext | Yes | NULL | UNIQUE WHERE NOT NULL | Login/contact email. |
| mobile_e164 | varchar(20) | Yes | NULL | UNIQUE WHERE NOT NULL | Normalized mobile. |
| status | varchar(24) | No | 'ACTIVE' | IDX; CHECK | ACTIVE/LOCKED/DISABLED/PENDING_VERIFICATION. |
| email_verified_at | timestamptz | Yes | NULL | — | Verification time. |
| mobile_verified_at | timestamptz | Yes | NULL | — | Verification time. |
| last_login_at | timestamptz | Yes | NULL | IDX | Successful login time. |
| created_at | timestamptz | No | now() | IDX | Created. |
| updated_at | timestamptz | No | now() | — | Updated. |

### iam.sessions

Refresh/session lifecycle; refresh token stored only as hash.

BRD source: Security NFRs

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Session. |
| principal_id | uuid | No | — | FK iam.principals; IDX | Owner. |
| refresh_token_hash | char(64) | No | — | UNIQUE | One-way token hash. |
| issued_at | timestamptz | No | now() | IDX | Issue time. |
| expires_at | timestamptz | No | — | IDX | Expiry. |
| revoked_at | timestamptz | Yes | NULL | IDX | Revocation. |
| ip_address | inet | Yes | NULL | — | Security metadata. |
| user_agent | text | Yes | NULL | — | Security metadata. |

### iam.role_assignments

Principal-to-role assignment with global/tenant/store scope.

BRD source: BR-050..053

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Assignment. |
| principal_id | uuid | No | — | FK; IDX | Principal. |
| role_code | varchar(40) | No | — | IDX | PLATFORM_OWNER/PLATFORM_STAFF/GST_STAFF/STORE_OWNER/STORE_STAFF/GUARDIAN. |
| tenant_id | uuid | Yes | NULL | IDX | Tenant scope; NULL for platform role. |
| store_id | uuid | Yes | NULL | IDX | Optional store scope. |
| valid_from | timestamptz | No | now() | — | Start. |
| valid_until | timestamptz | Yes | NULL | IDX | Optional end. |
| granted_by | uuid | Yes | NULL | — | Granting principal. |
| revoked_at | timestamptz | Yes | NULL | — | Revocation. |

### iam.otp_challenges

Hashed OTP challenges with abuse/rate-limit state.

BRD source: BR-244..246

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Challenge. |
| principal_id | uuid | Yes | NULL | IDX | Known principal if applicable. |
| channel | varchar(16) | No | — | CHECK EMAIL/SMS | Channel. |
| destination_fingerprint | char(64) | No | — | IDX | HMAC of destination. |
| purpose | varchar(32) | No | — | IDX | LOGIN/CLAIM_ACCOUNT/RESET_PASSWORD/SECURITY. |
| otp_hash | char(64) | No | — | — | OTP hash. |
| expires_at | timestamptz | No | — | IDX | Expiry. |
| attempt_count | smallint | No | 0 | CHECK >=0 | Attempts. |
| consumed_at | timestamptz | Yes | NULL | IDX | Success time. |
| created_at | timestamptz | No | now() | IDX | Created. |

### Supporting tables

| Table | Minimum structure | Purpose |
| --- | --- | --- |
| credentials | principal_id; password_hash; password_version; must_rotate; failed_attempts; locked_until; changed_at | Password credential metadata. |
| roles | role_code PK; display_name; scope_type; is_system | System role catalog. |
| permissions | permission_code PK; description | Atomic permission catalog. |
| role_permissions | role_code + permission_code PK/FK | Role-to-permission map. |
| mfa_factors | principal_id; factor_type; secret_ref/ciphertext; verified_at; disabled_at | MFA-ready factor registry. |
| auth_audit | principal_id; event_type; result; ip; user_agent; correlation_id; occurred_at | Append-only security audit. |

## 7.2  tenant — Tenant & Store Service (TEN)

PAN-based tenant identity, Minor/Guardian workflow, GSTIN inventory, stores and the lifetime Free Store entitlement.

| Isolation / access — Tenant data uses tenant_id; store records add store_id where applicable. Platform review uses dedicated restricted roles. |
| --- |

### tenant.tenants

Authoritative one-PAN-one-tenant record.

BRD source: BR-002,003,010..013,020..029

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Tenant ID. |
| pan_ciphertext | bytea | No | — | — | Encrypted PAN. |
| pan_fingerprint | char(64) | No | — | UNIQUE | Blind index enforcing one PAN→one tenant. |
| pan_masked | varchar(16) | No | — | — | Safe display. |
| legal_name | varchar(200) | No | — | IDX | Verified/declared name. |
| date_of_birth | date | Yes | NULL | — | Age/minor workflow. |
| tenant_type | varchar(24) | No | — | CHECK | INDIVIDUAL/BUSINESS/OTHER. |
| minor_status | varchar(32) | No | 'NOT_MINOR' | IDX; CHECK | Guardian/adult reverification state. |
| status | varchar(24) | No | 'PENDING' | IDX; CHECK | PENDING/ACTIVE/SUSPENDED/TERMINATED/ARCHIVED. |
| created_at | timestamptz | No | now() | IDX | Created. |
| updated_at | timestamptz | No | now() | — | Updated. |

### tenant.guardians

Guardian profile for a Minor Tenant.

BRD source: BR-023..029

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| principal_id | uuid | Yes | NULL | IDX | Optional guardian IAM principal. |
| full_name | varchar(200) | No | — | — | Name. |
| relationship_code | varchar(40) | No | — | IDX | Parent/legal guardian relationship. |
| email | citext | No | — | IDX | Email. |
| mobile_e164 | varchar(20) | No | — | IDX | Mobile. |
| verification_status | varchar(24) | No | 'PENDING' | IDX | PENDING/VERIFIED/REJECTED/MANUAL_REVIEW. |
| verified_at | timestamptz | Yes | NULL | — | Verification time. |
| active | boolean | No | true | IDX | Current mandatory relation. |

### tenant.guardian_consents

Immutable guardian acceptance bound to exact document version/hash.

BRD source: BR-026..029; AC-038..040

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| guardian_id | uuid | No | — | FK tenant.guardians; IDX | Guardian. |
| consent_type | varchar(40) | No | — | IDX | TERMS/PRIVACY/SUBSCRIPTION/SELLER/GST/DOMAIN/CANCELLATION etc. |
| document_version | varchar(40) | No | — | — | Accepted version. |
| document_hash | char(64) | No | — | — | Integrity hash. |
| accepted_at | timestamptz | No | now() | IDX | Acceptance. |
| acceptance_ip | inet | Yes | NULL | — | Evidence. |
| acceptance_evidence_ref | text | Yes | NULL | — | Signed/electronic evidence reference. |

### tenant.gstins

Verified GSTIN belonging to tenant PAN.

BRD source: BR-014..019; BR-064; AC-008..010

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | GSTIN ID. |
| tenant_id | uuid | No | — | IDX | Owner tenant. |
| gstin_ciphertext | bytea | No | — | — | Encrypted GSTIN. |
| gstin_fingerprint | char(64) | No | — | UNIQUE | Global duplicate protection. |
| gstin_masked | varchar(20) | No | — | — | Safe display. |
| state_code | char(2) | No | — | IDX | GST state code. |
| legal_name | varchar(200) | Yes | NULL | — | Verified name. |
| verification_status | varchar(24) | No | 'PENDING' | IDX | Verification state. |
| verified_at | timestamptz | Yes | NULL | — | Verified time. |
| created_at | timestamptz | No | now() | IDX | Created. |
| updated_at | timestamptz | No | now() | — | Updated. |

### tenant.stores

Canonical store; Free→Paid upgrade changes state/entitlement, not store identity.

BRD source: BR-011..019; BR-040..049; BR-063..065

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Store ID. |
| tenant_id | uuid | No | — | IDX | Owner. |
| store_code | varchar(32) | No | — | UNIQUE | Stable internal code. |
| display_name | varchar(200) | No | — | IDX | Operational name. |
| store_mode | varchar(24) | No | 'FREE_PRESENCE' | IDX; CHECK | FREE_PRESENCE/PAID_COMMERCE. |
| lifecycle_status | varchar(32) | No | 'DRAFT' | IDX; CHECK | DRAFT/REVIEW/ACTIVE/PAYMENT_GRACE/SUBSCRIPTION_EXPIRED/SUSPENDED/ARCHIVED/TERMINATED. |
| gstin_id | uuid | Yes | NULL | UNIQUE WHERE NOT NULL | Paid-store GSTIN business reference. |
| timezone | varchar(64) | No | 'Asia/Kolkata' | — | IANA timezone. |
| currency_code | char(3) | No | 'INR' | CHECK | Currency. |
| created_at | timestamptz | No | now() | IDX | Created. |
| updated_at | timestamptz | No | now() | — | Updated. |
| archived_at | timestamptz | Yes | NULL | IDX | Archive time. |

### tenant.free_store_entitlements

One lifetime Free Store entitlement per tenant.

BRD source: BR-011..013; AC-002

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| tenant_id | uuid | No | — | PK | Tenant. |
| status | varchar(16) | No | 'AVAILABLE' | CHECK AVAILABLE/CONSUMED | State. |
| consumed_store_id | uuid | Yes | NULL | UNIQUE WHERE NOT NULL | Store consuming entitlement. |
| consumed_at | timestamptz | Yes | NULL | — | Consumption time. |
| created_at | timestamptz | No | now() | — | Created. |

### Supporting tables

| Table | Minimum structure | Purpose |
| --- | --- | --- |
| pan_verifications | tenant_id; provider_code; provider_reference; status; verified_name; verified_at; encrypted_result | PAN verification history. |
| guardian_documents | guardian_id; document_type; storage_key; checksum; verification_status; retention_class | Guardian evidence metadata; binary in private storage. |
| gstin_verifications | gstin_id; provider_code; provider_reference; status; verified_pan_fingerprint; verified_at | Provider result history. |
| store_memberships | tenant_id; store_id; principal_id; membership_status; joined_at; ended_at | Operational membership. |
| seller_declarations | tenant_id; store_id nullable; declaration_type; document_version/hash; accepted_by; accepted_at | Seller undertaking evidence. |
| store_status_history | store_id; from_status; to_status; reason_code; actor_id; occurred_at; correlation_id | Append-only store state history. |

## 7.3  subscription — Subscription & Entitlement Service (SUB)

Plan versions, exact 30-day periods, Third-Period Advance, cancellation, delinquency, upgrades/downgrades and reactivation.

| Isolation / access — Every subscription row is tenant/store scoped. Financial calculation history is immutable/snapshot-driven. |
| --- |

### subscription.plan_versions

Versioned commercial plan definition; historical versions are never mutated.

BRD source: BR-030..039

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Plan version. |
| plan_code | varchar(24) | No | — | IDX | PRESENCE/COMMERCE/GROWTH/SCALE_AI. |
| version_no | integer | No | — | UNIQUE(plan_code,version_no) | Version. |
| period_days | smallint | No | 30 | CHECK =30 for paid V1 | Billing period. |
| price_amount | numeric(18,2) | No | 0 | CHECK >=0 | Price excluding GST. |
| commission_rate | numeric(9,6) | No | 0 | CHECK 0..1 | Default rate. |
| effective_from | timestamptz | No | — | IDX | Start. |
| effective_to | timestamptz | Yes | NULL | IDX | Retirement. |
| is_active | boolean | No | true | IDX | Selectable flag. |
| created_at | timestamptz | No | now() | — | Created. |

### subscription.subscriptions

Current subscription lifecycle aggregate per store.

BRD source: BR-180..192; Appendix C.1/C.2

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| plan_version_id | uuid | No | — | IDX | Current plan version. |
| state | varchar(40) | No | — | IDX; CHECK | State-machine state. |
| activation_sequence | integer | No | 0 | CHECK >=0 | Paid activation/reactivation count. |
| first_paid_activated_at | timestamptz | Yes | NULL | — | Protects complimentary first setup. |
| current_period_no | integer | Yes | NULL | CHECK >=1 | Current logical period. |
| current_period_id | uuid | Yes | NULL | UNIQUE WHERE NOT NULL | Current period reference. |
| cancellation_effective_after_period | integer | Yes | NULL | — | End boundary. |
| version | bigint | No | 0 | Optimistic lock | Concurrency. |

### subscription.subscription_periods

Exact consecutive entitlement windows.

BRD source: BR-031..033; BR-180..186; AC-041..067

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| subscription_id | uuid | No | — | FK; IDX | Subscription. |
| period_no | integer | No | — | UNIQUE(subscription_id,period_no) | Sequence. |
| plan_version_id | uuid | No | — | IDX | Plan applied. |
| starts_at | timestamptz | No | — | IDX | Inclusive start. |
| ends_at | timestamptz | No | — | IDX; CHECK end=start+30 days | Exclusive end. |
| entitlement_status | varchar(24) | No | — | IDX | SCHEDULED/ACTIVE/COMPLETED/CANCELLED. |
| charge_mode | varchar(32) | No | — | CHECK | FULL/HALF_ADVANCE_CREDIT/FULLY_PREPAID_ADVANCE/FREE. |
| base_price_snapshot | numeric(18,2) | No | 0 | CHECK >=0 | Plan price snapshot. |
| amount_due_snapshot | numeric(18,2) | No | 0 | CHECK >=0 | Period due. |
| gst_rate_snapshot | numeric(9,6) | No | 0 | CHECK >=0 | Tax rate snapshot after tax review. |
| closed_at | timestamptz | Yes | NULL | — | Closure. |

### subscription.subscription_charges

Immutable subscription/setup/upgrade/reactivation charge lines.

BRD source: BR-180..192; BR-234..235

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| subscription_id | uuid | No | — | FK; IDX | Subscription. |
| period_id | uuid | Yes | NULL | IDX | Period. |
| charge_type | varchar(40) | No | — | IDX | PERIOD_FEE/THIRD_PERIOD_ADVANCE/REACTIVATION_SETUP/UPGRADE_DIFFERENCE/UPGRADE_SETUP/TAX. |
| amount | numeric(18,2) | No | — | CHECK >=0 | Charge. |
| tax_amount | numeric(18,2) | No | 0 | CHECK >=0 | Tax. |
| status | varchar(24) | No | 'DUE' | IDX | DUE/PAID/CREDITED/SET_OFF/CANCELLED. |
| due_at | timestamptz | Yes | NULL | IDX | Due. |
| calculation_snapshot | jsonb | No | '{}'::jsonb | — | Formula/input/version evidence. |
| finance_invoice_id | uuid | Yes | NULL | IDX | Finance invoice reference. |

### subscription.advance_movements

Append-only Third-Period Advance sub-ledger.

BRD source: BR-180..186; BR-235; AC-042,046..052,062..064

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| subscription_id | uuid | No | — | FK; IDX | Subscription. |
| movement_type | varchar(40) | No | — | IDX | COLLECTED/TOP_UP/PERIOD3_CONSUMPTION/P3_CREDIT/P4_CREDIT/SET_OFF/ADJUSTMENT. |
| amount | numeric(18,2) | No | — | CHECK >0 | Amount. |
| direction | char(1) | No | — | CHECK C/D | Increase/decrease balance. |
| source_charge_id | uuid | Yes | NULL | IDX | Related charge. |
| effective_at | timestamptz | No | now() | IDX | Effective time. |
| reason | text | Yes | NULL | — | Audit explanation. |

### subscription.plan_change_requests

Upgrade/downgrade request and approval.

BRD source: BR-188..192

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| subscription_id | uuid | No | — | FK; IDX | Subscription. |
| change_type | varchar(16) | No | — | CHECK UPGRADE/DOWNGRADE | Type. |
| from_plan_version_id | uuid | No | — | IDX | Source. |
| to_plan_version_id | uuid | No | — | IDX | Target. |
| requested_at | timestamptz | No | now() | IDX | Request. |
| effective_at | timestamptz | Yes | NULL | IDX | Effective time/boundary. |
| status | varchar(24) | No | 'PENDING' | IDX | PENDING/APPROVED/REJECTED/APPLIED/CANCELLED. |
| approved_by | uuid | Yes | NULL | — | Platform Owner where required. |

### subscription.upgrade_quotes

Immutable upgrade calculation snapshot.

BRD source: BR-188..189; AC-069..075

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| plan_change_request_id | uuid | No | — | FK; IDX | Change request. |
| days_remaining | smallint | No | — | CHECK 0..30 | R. |
| prorated_difference | numeric(18,2) | No | 0 | CHECK >=0 | Current-period difference. |
| advance_top_up | numeric(18,2) | No | 0 | CHECK >=0 | Advance top-up. |
| gross_setup_fee | numeric(18,2) | No | 0 | CHECK >=0 | 50% plan-price difference. |
| approved_discount_amount | numeric(18,2) | No | 0 | CHECK >=0 | Approved setup discount. |
| net_setup_fee | numeric(18,2) | No | 0 | CHECK >=0 | Net setup fee. |
| total_ex_tax | numeric(18,2) | No | 0 | CHECK >=0 | Quote total. |
| calculation_snapshot | jsonb | No | '{}'::jsonb | — | Formula inputs/version. |

### subscription.entitlement_snapshots

Resolved store capabilities/limits for fast gating.

BRD source: BR-030..039; BR-070..094

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| subscription_id | uuid | Yes | NULL | IDX | Paid subscription if any. |
| plan_code | varchar(24) | No | — | IDX | Plan. |
| effective_from | timestamptz | No | now() | IDX | Start. |
| effective_to | timestamptz | Yes | NULL | IDX | End. |
| entitlements | jsonb | No | '{}'::jsonb | GIN selectively | Resolved capability map. |
| source_plan_version_id | uuid | Yes | NULL | IDX | Source plan. |
| reason_code | varchar(40) | No | — | — | ACTIVATION/RENEWAL/UPGRADE/DOWNGRADE/FREE_CONVERSION/SUSPENSION. |

### Supporting tables

| Table | Minimum structure | Purpose |
| --- | --- | --- |
| plan_entitlements | plan_version_id; entitlement_code; value_json; hard_limit; technical_limit | Normalized versioned plan capabilities. |
| cancellation_notices | subscription_id; requested_by; submitted_at; status; effective_after_period_no; reason | Cancellation notice before Period 3. |
| reactivations | subscription_id; target_plan_version_id; setup_charge_id; reactivated_at | Reactivation audit. |
| discount_approvals | upgrade_quote_id; requested_discount; approved_amount; approver_id; reason; decided_at | Auditable upgrade setup-fee discount. |
| subscription_state_history | subscription_id; from_state; to_state; trigger; actor_id; occurred_at; correlation_id | Append-only state history. |
| scheduled_actions | subscription_id; action_type; due_at; status; attempt_count; last_error | Durable timer actions if no external workflow engine. |

## 7.4  domain — Domain & Publication Service (DOM)

Immutable Free subdomains, custom-domain lifecycle, DNS verification and publication routing.

| Isolation / access — Store-scoped; Platform Staff have controlled operational domain access. |
| --- |

### domain.subdomains

Immutable KarobarOne Free subdomain assignment.

BRD source: BR-040..041; BR-049; AC-084

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| label | citext | No | — | UNIQUE | Subdomain label. |
| fqdn | citext | No | — | UNIQUE | label.karobarone.com. |
| activated_at | timestamptz | Yes | NULL | — | Serving start. |
| disabled_at | timestamptz | Yes | NULL | — | Serving disabled; assignment remains immutable. |

### domain.domains

Purchased/managed custom domain.

BRD source: BR-042..048; AC-085..088

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| domain_name | citext | No | — | UNIQUE | Custom domain. |
| registrar_code | varchar(40) | No | — | IDX | Provider adapter. |
| registrar_reference | varchar(128) | Yes | NULL | UNIQUE WHERE NOT NULL | Provider ID. |
| cost_class | varchar(24) | No | — | CHECK | STANDARD/PREMIUM/NON_STANDARD. |
| purchase_cost | numeric(18,2) | Yes | NULL | CHECK >=0 | Actual cost. |
| registered_at | timestamptz | Yes | NULL | — | Registration. |
| expires_at | timestamptz | Yes | NULL | IDX | Expiry/renewal. |
| status | varchar(32) | No | 'PENDING_PURCHASE' | IDX | Lifecycle state. |

### domain.publication_routes

Current public route to approved storefront revision.

BRD source: BR-063..065; BR-049

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| route_type | varchar(24) | No | — | CHECK | FREE_SUBDOMAIN/CUSTOM_DOMAIN/SYSTEM_PREVIEW. |
| hostname | citext | No | — | UNIQUE active | Serving hostname. |
| target_revision_id | uuid | Yes | NULL | IDX | Approved revision. |
| status | varchar(24) | No | 'DISABLED' | IDX | DISABLED/ACTIVE/PENDING_DNS/SUSPENDED. |
| activated_at | timestamptz | Yes | NULL | — | Start. |
| deactivated_at | timestamptz | Yes | NULL | — | End. |

### Supporting tables

| Table | Minimum structure | Purpose |
| --- | --- | --- |
| domain_requests | store_id; requested_name; sequence_no; availability_status; checked_at; selected_at | Tenant preferred domain workflow. |
| dns_checks | domain_id; check_type; expected_value; observed_value; result; checked_at | Append-only DNS/TLS/routing checks. |
| domain_payments | domain_id; charge_class; quote_amount; payment_reference; paid_at | Premium/non-standard domain payment evidence. |
| publication_history | store_id; route_type; hostname; target_revision_id; action; actor_id; occurred_at | Append-only publication routing history. |

## 7.5  catalog — Catalog & CMS Service (CAT)

Products, services, variants, SKUs, media metadata, storefront content, blog/forms and SEO metadata.

| Isolation / access — Strict tenant_id/store_id RLS. Public reads use approved live pointers/read models, never draft rows. |
| --- |

### catalog.catalog_items

Common product/service aggregate supporting paid hybrid commerce.

BRD source: BR-070..094; BR-110..129

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| item_type | varchar(24) | No | — | IDX; CHECK | PRODUCT/SERVICE. |
| subtype | varchar(32) | No | — | IDX | PHYSICAL_PRODUCT/DIGITAL_PRODUCT/APPOINTMENT_SERVICE/NON_APPOINTMENT_SERVICE. |
| internal_name | varchar(200) | No | — | IDX | Tenant working name. |
| operational_status | varchar(24) | No | 'DRAFT' | IDX | DRAFT/ACTIVE/INACTIVE/ARCHIVED. |
| current_live_version_id | uuid | Yes | NULL | IDX | Approved public version. |
| current_draft_version_id | uuid | Yes | NULL | IDX | Working version. |
| category_code | varchar(64) | Yes | NULL | IDX | Approved category. |
| custom_category_id | uuid | Yes | NULL | IDX | Approval-gated custom category. |

### catalog.item_versions

Versioned public-facing product/service content.

BRD source: BR-210..216; AC-079..081

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| item_id | uuid | No | — | FK catalog.catalog_items; IDX | Item. |
| version_no | integer | No | — | UNIQUE(item_id,version_no) | Version. |
| title | varchar(240) | No | — | — | Public title. |
| short_description | text | Yes | NULL | — | Summary. |
| long_description | text | Yes | NULL | — | Body. |
| approval_state | varchar(32) | No | 'DRAFT' | IDX | DRAFT/PENDING/APPROVED_LIVE/REJECTED/UNPUBLISHED/EMERGENCY_TAKEDOWN. |
| content_hash | char(64) | No | — | IDX | Integrity/change hash. |
| submitted_at | timestamptz | Yes | NULL | — | Submission. |
| approved_at | timestamptz | Yes | NULL | — | Approval. |

### catalog.product_details

Product-specific attributes.

BRD source: BR-110..118

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| item_id | uuid | No | — | PK; FK catalog.catalog_items | Product. |
| product_kind | varchar(16) | No | — | CHECK PHYSICAL/DIGITAL | Fulfilment type. |
| hsn_code | varchar(16) | Yes | NULL | IDX | HSN. |
| tax_category_code | varchar(40) | Yes | NULL | IDX | Tax policy reference. |
| inventory_tracking_default | boolean | No | false | — | Default tracking. |
| returnable | boolean | No | false | — | Configured returnability subject to mandatory rights. |
| return_window_days | smallint | Yes | NULL | CHECK >=0 | Return window. |
| created_at | timestamptz | No | now() | — | Created. |
| updated_at | timestamptz | No | now() | — | Updated. |

### catalog.service_details

Service-specific transaction configuration.

BRD source: BR-120..129

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| item_id | uuid | No | — | PK; FK catalog.catalog_items | Service. |
| service_kind | varchar(24) | No | — | CHECK | APPOINTMENT/NON_APPOINTMENT. |
| sac_code | varchar(16) | Yes | NULL | IDX | SAC. |
| tax_category_code | varchar(40) | Yes | NULL | IDX | Tax policy. |
| confirmation_mode | varchar(24) | No | 'INSTANT' | CHECK | INSTANT/SELLER_APPROVAL. |
| payment_sequence | varchar(32) | No | — | CHECK | PAY_BEFORE_APPROVAL/APPROVE_BEFORE_PAY/PARTIAL_DEPOSIT/FULL_ADVANCE/PAY_AFTER_SERVICE. |
| deposit_type | varchar(16) | Yes | NULL | CHECK | FIXED/PERCENT. |
| deposit_value | numeric(18,4) | Yes | NULL | CHECK >=0 | Amount or percentage. |
| payment_deadline_minutes | integer | Yes | NULL | CHECK >0 | Approve-before-pay timeout. |
| created_at | timestamptz | No | now() | — | Created. |
| updated_at | timestamptz | No | now() | — | Updated. |

### catalog.skus

Sellable SKU/variant combinations.

BRD source: BR-111..118

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| item_id | uuid | No | — | FK; IDX | Product. |
| sku_code | varchar(80) | No | — | UNIQUE(store_id,sku_code) | Tenant SKU. |
| variant_signature | char(64) | Yes | NULL | UNIQUE(item_id,variant_signature) | Variant combination fingerprint. |
| price_amount | numeric(18,2) | No | 0 | CHECK >=0 | Current price. |
| compare_at_amount | numeric(18,2) | Yes | NULL | CHECK >=0 | Optional reference price. |
| inventory_tracking | boolean | No | false | IDX | Finite stock flag. |
| active | boolean | No | true | IDX | Operational availability. |

### catalog.media_assets

Private object-storage metadata only.

BRD source: BR-073..074; BR-090..094; BR-156..157

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| storage_key | text | No | — | UNIQUE | Private object key. |
| media_type | varchar(16) | No | — | IDX | IMAGE/VIDEO/DOCUMENT. |
| mime_type | varchar(100) | No | — | — | MIME. |
| byte_size | bigint | No | — | CHECK >=0 | Size. |
| checksum_sha256 | char(64) | No | — | IDX | Integrity hash. |
| width_px | integer | Yes | NULL | — | Width. |
| height_px | integer | Yes | NULL | — | Height. |
| duration_ms | integer | Yes | NULL | — | Video duration. |
| alt_text | varchar(500) | Yes | NULL | — | Accessibility/SEO. |
| scan_status | varchar(20) | No | 'PENDING' | IDX | PENDING/CLEAN/REJECTED. |

### catalog.store_content_versions

Versioned Hero/About/USP/Contact/Policy/Marquee content.

BRD source: BR-075; BR-210..216

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| content_section | varchar(32) | No | — | IDX | Section code. |
| version_no | integer | No | — | UNIQUE(store_id,content_section,version_no) | Version. |
| content_json | jsonb | No | '{}'::jsonb | — | Structured section content. |
| approval_state | varchar(32) | No | 'DRAFT' | IDX | Governance state. |
| content_hash | char(64) | No | — | IDX | Integrity/change hash. |
| approved_at | timestamptz | Yes | NULL | — | Approval time. |

### Supporting tables

| Table | Minimum structure | Purpose |
| --- | --- | --- |
| item_attributes | item_id; attribute_code; value_text/value_numeric/value_json; sort_order | Normalized attributes. |
| variant_definitions | item_id; variant_code; display_name; sort_order; approval_state | Variant dimensions. |
| variant_values | variant_definition_id; value_code; display_value; sort_order | Variant values. |
| sku_variant_values | sku_id; variant_value_id; UNIQUE(sku_id,variant_value_id) | SKU↔variant mapping. |
| item_media | item_version_id; media_asset_id; role; sort_order | Versioned item media links; entitlement enforces counts/video rules. |
| store_media | store_id; media_asset_id; role; sort_order | Logo/hero/about etc. not counted as per-item media. |
| seo_metadata | entity_type; entity_id; version_id; meta_title; meta_description; canonical_path; robots; structured_data_json | SEO metadata. |
| categories | category_code PK; display_name; item_type; compliance_class; active | Platform category catalog. |
| custom_categories | store_id; proposed_name; approval_state; approval_request_id | Approval-gated custom category. |
| blog_posts | store_id; live_version_id; draft_version_id; status; published_at | Growth/Scale blog aggregate. |
| blog_versions | blog_post_id; version_no; title; slug; body; approval_state; content_hash | Versioned blog content. |
| custom_forms | store_id; name; schema_json; operational_status | Growth/Scale form definition. |
| form_submissions | store_id; form_id; minimized/encrypted payload; submitted_at; retention_class | Lead/form submission data. |

## 7.6  approval — Approval & Governance Service (APR)

Controlled content review, rejection, approval and emergency takedown.

| Isolation / access — Tenant/store scoped requests; Platform Staff have review queue access. Decisions are append-only. |
| --- |

### approval.approval_requests

Generic request pointing to immutable/versioned subject owned by another service.

BRD source: BR-063; BR-067..069; BR-210..216

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| subject_type | varchar(40) | No | — | IDX | STORE_CONTENT/ITEM_VERSION/BLOG_VERSION/CUSTOM_CATEGORY/VARIANT/POLICY/BRAND_AUTH. |
| subject_id | uuid | No | — | IDX | Owning-service entity/version. |
| subject_version | varchar(64) | Yes | NULL | — | Version/hash. |
| status | varchar(24) | No | 'PENDING' | IDX | PENDING/APPROVED/REJECTED/CANCELLED/TAKEDOWN. |
| submitted_by | uuid | No | — | IDX | Submitter. |
| submitted_at | timestamptz | No | now() | IDX | Submission. |
| priority | smallint | No | 0 | IDX | Queue priority. |

### approval.approval_decisions

Append-only review decision; rejection requires reason.

BRD source: BR-211..216; AC-080

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| approval_request_id | uuid | No | — | FK; IDX | Request. |
| decision | varchar(20) | No | — | CHECK | APPROVE/REJECT/UNPUBLISH. |
| reason_code | varchar(40) | Yes | NULL | IDX | Structured reason. |
| reason_text | text | Yes | NULL | CHECK for REJECT | Reviewer explanation. |
| decided_by | uuid | No | — | IDX | Platform reviewer. |
| decided_at | timestamptz | No | now() | IDX | Decision time. |
| evidence_json | jsonb | No | '{}'::jsonb | — | Policy/evidence refs. |

### approval.takedowns

Emergency unpublish action with mandatory audit basis.

BRD source: BR-214..216; AC-081

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| subject_type | varchar(40) | No | — | IDX | Affected entity. |
| subject_id | uuid | No | — | IDX | Affected ID. |
| reason_code | varchar(40) | No | — | IDX | ILLEGAL/COUNTERFEIT/UNSAFE/FRAUDULENT/PROHIBITED etc. |
| reason_text | text | No | — | — | Basis. |
| executed_by | uuid | No | — | IDX | Platform Staff. |
| executed_at | timestamptz | No | now() | IDX | Time. |
| restored_at | timestamptz | Yes | NULL | — | Optional restoration. |

### Supporting tables

| Table | Minimum structure | Purpose |
| --- | --- | --- |
| approval_attachments | approval_request_id; document_type; storage_key; checksum; added_by; created_at | Supporting evidence metadata. |
| approval_state_history | approval_request_id; from_status; to_status; actor_id; reason; occurred_at | Append-only workflow history. |

## 7.7  customer — Customer Service (CUS)

Store-scoped customers, guest/unclaimed identity, addresses, account claim and privacy requests.

| Isolation / access — Always tenant_id + store_id scoped. Email and mobile uniqueness are per store, not global. |
| --- |

### customer.customers

Store-scoped end-customer profile.

BRD source: BR-130..136; AC-076..078

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| email | citext | No | — | UNIQUE(store_id,email) | Email. |
| mobile_e164 | varchar(20) | No | — | UNIQUE(store_id,mobile_e164) | Mobile. |
| status | varchar(24) | No | 'UNCLAIMED' | IDX | UNCLAIMED/CLAIMED/BLOCKED/ANONYMIZED. |
| iam_principal_id | uuid | Yes | NULL | UNIQUE WHERE NOT NULL | IAM principal after claim. |
| first_name | varchar(100) | Yes | NULL | — | Profile. |
| last_name | varchar(100) | Yes | NULL | — | Profile. |
| claimed_at | timestamptz | Yes | NULL | — | Claim time. |
| last_activity_at | timestamptz | Yes | NULL | IDX | Activity. |

### customer.addresses

Customer shipping/billing address.

BRD source: BR-136

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| customer_id | uuid | No | — | FK; IDX | Customer. |
| address_type | varchar(16) | No | — | CHECK | SHIPPING/BILLING/BOTH. |
| recipient_name | varchar(200) | No | — | — | Recipient. |
| line1 | varchar(240) | No | — | — | Address. |
| line2 | varchar(240) | Yes | NULL | — | Address. |
| city | varchar(120) | No | — | IDX | City. |
| state_code | varchar(16) | No | — | IDX | State. |
| postal_code | varchar(12) | No | — | IDX | PIN. |
| country_code | char(2) | No | 'IN' | CHECK | Country. |
| is_default | boolean | No | false | IDX | Default. |

### customer.account_claims

UNCLAIMED→CLAIMED customer workflow.

BRD source: BR-133..135; AC-077..078

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| customer_id | uuid | No | — | FK; IDX | Customer. |
| otp_challenge_id | uuid | No | — | IDX | IAM OTP challenge. |
| status | varchar(20) | No | 'PENDING' | IDX | PENDING/VERIFIED/EXPIRED/FAILED. |
| requested_at | timestamptz | No | now() | IDX | Request. |
| verified_at | timestamptz | Yes | NULL | — | Verified. |
| resulting_principal_id | uuid | Yes | NULL | IDX | Linked IAM principal. |

### customer.privacy_requests

Data-principal/privacy request while retaining statutory commercial records.

BRD source: BR-136; BR-285; BR-290..295

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| customer_id | uuid | No | — | IDX | Customer. |
| request_type | varchar(24) | No | — | IDX | ACCESS/CORRECT/DELETE/WITHDRAW_CONSENT. |
| status | varchar(32) | No | 'OPEN' | IDX | OPEN/IN_REVIEW/COMPLETED/PARTIAL/REJECTED_LEGAL_RETENTION. |
| requested_at | timestamptz | No | now() | IDX | Request. |
| completed_at | timestamptz | Yes | NULL | — | Completion. |
| retention_basis | text | Yes | NULL | — | Legal/statutory retention reason. |

### Supporting tables

| Table | Minimum structure | Purpose |
| --- | --- | --- |
| customer_status_history | customer_id; from_status; to_status; actor_id; occurred_at; reason | Append-only lifecycle. |
| customer_consents | customer_id; purpose_code; policy_version/hash; granted_at; withdrawn_at | Purpose/consent history. |

## 7.8  inventory — Inventory Service (INV)

Transaction-safe SKU stock, checkout reservations and immutable movements.

| Isolation / access — Store-scoped. Quantity changes are only performed by Inventory service under locking/atomic updates. |
| --- |

### inventory.stock_balances

Current finite stock state per tracked SKU.

BRD source: BR-112..118

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| sku_id | uuid | No | — | UNIQUE(store_id,sku_id) | Catalog SKU. |
| on_hand_qty | numeric(18,3) | No | 0 | CHECK >=0 | Physical stock. |
| reserved_qty | numeric(18,3) | No | 0 | CHECK >=0 and <=on_hand | Active holds. |
| version | bigint | No | 0 | Optimistic lock | Concurrency. |
| last_movement_at | timestamptz | Yes | NULL | IDX | Last movement. |

### inventory.reservations

Time-bound checkout stock hold; default target 10 minutes.

BRD source: BR-115..117

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| sku_id | uuid | No | — | IDX | SKU. |
| checkout_reference | uuid | No | — | IDX | Checkout/order correlation. |
| quantity | numeric(18,3) | No | — | CHECK >0 | Reserved qty. |
| status | varchar(20) | No | 'ACTIVE' | IDX | ACTIVE/CONSUMED/RELEASED/EXPIRED. |
| expires_at | timestamptz | No | — | IDX | Expiry. |
| consumed_at | timestamptz | Yes | NULL | — | Sale conversion. |
| released_at | timestamptz | Yes | NULL | — | Release/expiry. |

### inventory.stock_movements

Immutable inventory movement ledger.

BRD source: BR-116

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| sku_id | uuid | No | — | IDX | SKU. |
| movement_type | varchar(32) | No | — | IDX | OPENING/ADJUSTMENT/RESERVE/RELEASE/SALE/CANCEL_RESTORE/RETURN_RESTORE. |
| quantity_delta | numeric(18,3) | No | — | CHECK <>0 | Signed movement. |
| reference_type | varchar(24) | Yes | NULL | IDX | ORDER/RESERVATION/RETURN/ADMIN. |
| reference_id | uuid | Yes | NULL | IDX | Business source. |
| occurred_at | timestamptz | No | now() | IDX | Effective time. |
| reason | text | Yes | NULL | — | Reason. |

### Supporting tables

| Table | Minimum structure | Purpose |
| --- | --- | --- |
| inventory_settings | store_id; reservation_minutes; oversell_allowed=false; low_stock_threshold_default | Store inventory technical settings. |

## 7.9  commerce — Commerce Service (COM)

Product cart, checkout, orders, cancellations, returns and refund orchestration.

| Isolation / access — All records store-scoped. One cart/order belongs to exactly one store; commerce tables accept product transactions only. |
| --- |

### commerce.carts

Product-only cart aggregate for one store.

BRD source: BR-100..104; AC-015..018

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| customer_id | uuid | Yes | NULL | IDX | Known customer. |
| session_key | varchar(128) | Yes | NULL | IDX | Guest session. |
| status | varchar(20) | No | 'ACTIVE' | IDX | ACTIVE/CHECKED_OUT/ABANDONED/EXPIRED. |
| currency_code | char(3) | No | 'INR' | CHECK | Currency. |
| expires_at | timestamptz | Yes | NULL | IDX | Expiry. |
| version | bigint | No | 0 | Optimistic lock | Concurrency. |

### commerce.orders

Product order header with commercial snapshots.

BRD source: BR-140..145; BR-220..235

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| order_number | varchar(64) | No | — | UNIQUE(store_id,order_number) | Store order number. |
| customer_id | uuid | No | — | IDX | Customer. |
| status | varchar(32) | No | — | IDX; CHECK | PLACED/PAYMENT_PENDING/PAID/PROCESSING/SHIPPED/DELIVERED/CANCELLED/RETURNED/REFUNDED/FAILED/DISPUTED. |
| payment_mode | varchar(24) | No | — | IDX | ONLINE/COD/PERMITTED_OFFLINE. |
| currency_code | char(3) | No | 'INR' | CHECK | Currency. |
| taxable_value | numeric(18,2) | No | 0 | CHECK >=0 | Taxable item value after discount. |
| discount_amount | numeric(18,2) | No | 0 | CHECK >=0 | Discount. |
| tax_amount | numeric(18,2) | No | 0 | CHECK >=0 | Tax. |
| shipping_amount | numeric(18,2) | No | 0 | CHECK >=0 | Shipping. |
| total_amount | numeric(18,2) | No | 0 | CHECK >=0 | Grand total. |
| commission_rate_snapshot | numeric(9,6) | No | 0 | CHECK 0..1 | Commission rate at creation. |
| placed_at | timestamptz | No | now() | IDX | Order time. |
| payment_confirmed_at | timestamptz | Yes | NULL | IDX | Authoritative payment time. |
| version | bigint | No | 0 | Optimistic lock | Concurrency. |

### commerce.order_items

Immutable order-line commercial/tax snapshot.

BRD source: BR-145; BR-230..233

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| order_id | uuid | No | — | FK; IDX | Order. |
| item_id | uuid | No | — | IDX | Catalog product. |
| sku_id | uuid | No | — | IDX | SKU. |
| title_snapshot | varchar(240) | No | — | — | Historical title. |
| sku_snapshot | varchar(80) | No | — | — | Historical SKU code. |
| hsn_snapshot | varchar(16) | Yes | NULL | — | HSN. |
| quantity | numeric(18,3) | No | — | CHECK >0 | Qty. |
| unit_price | numeric(18,2) | No | — | CHECK >=0 | Unit price. |
| discount_amount | numeric(18,2) | No | 0 | CHECK >=0 | Line discount. |
| taxable_value | numeric(18,2) | No | 0 | CHECK >=0 | Taxable line. |
| tax_amount | numeric(18,2) | No | 0 | CHECK >=0 | Tax. |
| line_total | numeric(18,2) | No | 0 | CHECK >=0 | Line total. |

### commerce.order_status_history

Append-only order state transitions.

BRD source: BR-220

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| order_id | uuid | No | — | FK; IDX | Order. |
| from_status | varchar(32) | Yes | NULL | — | Previous. |
| to_status | varchar(32) | No | — | IDX | New status. |
| trigger_type | varchar(32) | No | — | IDX | USER/API/WEBHOOK/SHIPMENT/SCHEDULER/ADMIN. |
| actor_id | uuid | Yes | NULL | IDX | Actor. |
| reason_code | varchar(40) | Yes | NULL | — | Reason. |
| occurred_at | timestamptz | No | now() | IDX | Time. |
| correlation_id | uuid | Yes | NULL | IDX | Correlation. |

### commerce.refund_requests

Refund orchestration; provider execution belongs to Payment.

BRD source: BR-226..228

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| order_id | uuid | No | — | IDX | Order. |
| return_request_id | uuid | Yes | NULL | IDX | Optional return. |
| status | varchar(24) | No | 'REQUESTED' | IDX | REQUESTED/APPROVED/PROCESSING/REFUNDED/REJECTED. |
| refund_amount | numeric(18,2) | No | — | CHECK >0 | Amount. |
| refund_method | varchar(24) | No | — | IDX | ONLINE_PROVIDER/COD_EXTERNAL/MANUAL_APPROVED. |
| provider_refund_id | uuid | Yes | NULL | IDX | Payment service ref. |
| requested_at | timestamptz | No | now() | IDX | Request. |
| completed_at | timestamptz | Yes | NULL | — | Completion. |

### Supporting tables

| Table | Minimum structure | Purpose |
| --- | --- | --- |
| cart_items | cart_id; sku_id; item_id; quantity; unit_price_snapshot; added_at | Cart lines; product SKUs only. |
| cancellation_requests | order_id; customer_id; reason; requested_at; seller_decision; decided_at; refund_request_id | Pre-shipment cancellation workflow. |
| return_requests | order_id; customer_id; status; reason_code; requested_at; seller_decided_at; received_at | Physical return workflow. |
| return_items | return_request_id; order_item_id; quantity; condition_code; resolution | Returned lines. |
| refund_items | refund_request_id; order_item_id; amount; tax_amount; commission_credit_basis | Refund allocation. |
| checkout_idempotency | store_id; idempotency_key; request_hash; order_id; response_code; created_at; expires_at | Duplicate order prevention. |

## 7.10  booking — Booking Service (BKG)

Appointment/non-appointment service transactions, schedules, capacity holds, deadlines, rescheduling and no-show state.

| Isolation / access — Store-scoped. Appointment and non-appointment services use distinct service transactions through booking_type. |
| --- |

### booking.service_schedules

Recurring local appointment schedule.

BRD source: BR-120..129

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| service_item_id | uuid | No | — | IDX | Catalog service. |
| day_of_week | smallint | No | — | CHECK 0..6 | Local weekday. |
| start_time | time | No | — | — | Opening. |
| end_time | time | No | — | CHECK end>start | Closing. |
| slot_duration_minutes | smallint | No | — | CHECK >0 | Slot duration. |
| capacity | integer | No | 1 | CHECK >0 | Concurrent capacity. |
| buffer_before_minutes | smallint | No | 0 | CHECK >=0 | Pre-buffer. |
| buffer_after_minutes | smallint | No | 0 | CHECK >=0 | Post-buffer. |
| active | boolean | No | true | IDX | Active. |

### booking.capacity_reservations

Temporary appointment-capacity hold.

BRD source: BR-125; BR-129

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| service_item_id | uuid | No | — | IDX | Service. |
| slot_start | timestamptz | No | — | IDX | Slot start. |
| slot_end | timestamptz | No | — | IDX | Slot end. |
| units | integer | No | 1 | CHECK >0 | Capacity units. |
| status | varchar(20) | No | 'ACTIVE' | IDX | ACTIVE/CONFIRMED/RELEASED/EXPIRED. |
| expires_at | timestamptz | No | — | IDX | Expiry. |
| checkout_reference | uuid | No | — | IDX | Flow correlation. |

### booking.bookings

Service transaction aggregate with price/tax/commission snapshots.

BRD source: BR-120..129; BR-166..171; BR-221

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| booking_number | varchar(64) | No | — | UNIQUE(store_id,booking_number) | Store booking no. |
| customer_id | uuid | No | — | IDX | Customer. |
| service_item_id | uuid | No | — | IDX | Service. |
| booking_type | varchar(24) | No | — | IDX | APPOINTMENT/NON_APPOINTMENT. |
| status | varchar(32) | No | — | IDX | REQUESTED/APPROVED/PAYMENT_PENDING/CONFIRMED/COMPLETED/CANCELLED/REJECTED/RESCHEDULED/NO_SHOW/REFUNDED. |
| payment_sequence | varchar(32) | No | — | IDX | Payment sequence snapshot. |
| scheduled_start | timestamptz | Yes | NULL | IDX | Appointment start. |
| scheduled_end | timestamptz | Yes | NULL | IDX | Appointment end. |
| taxable_value | numeric(18,2) | No | 0 | CHECK >=0 | Taxable value. |
| discount_amount | numeric(18,2) | No | 0 | CHECK >=0 | Discount. |
| tax_amount | numeric(18,2) | No | 0 | CHECK >=0 | Tax. |
| total_amount | numeric(18,2) | No | 0 | CHECK >=0 | Total. |
| deposit_amount | numeric(18,2) | No | 0 | CHECK >=0 | Deposit. |
| commission_rate_snapshot | numeric(9,6) | No | 0 | CHECK 0..1 | Commission rate. |
| version | bigint | No | 0 | Optimistic lock | Concurrency. |

### booking.booking_status_history

Append-only booking transitions.

BRD source: BR-126..129; BR-166..171

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| booking_id | uuid | No | — | FK; IDX | Booking. |
| from_status | varchar(32) | Yes | NULL | — | Previous. |
| to_status | varchar(32) | No | — | IDX | New. |
| actor_id | uuid | Yes | NULL | IDX | Actor. |
| trigger_type | varchar(32) | No | — | IDX | USER/PAYMENT/SCHEDULER/ADMIN. |
| reason_code | varchar(40) | Yes | NULL | — | Reason. |
| occurred_at | timestamptz | No | now() | IDX | Time. |
| correlation_id | uuid | Yes | NULL | IDX | Correlation. |

### booking.booking_reschedules

Reschedule history preserving old/new schedule.

BRD source: BR-126; BR-171

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| booking_id | uuid | No | — | IDX | Booking. |
| old_start | timestamptz | Yes | NULL | — | Old start. |
| old_end | timestamptz | Yes | NULL | — | Old end. |
| new_start | timestamptz | Yes | NULL | IDX | New start. |
| new_end | timestamptz | Yes | NULL | — | New end. |
| rescheduled_by | uuid | No | — | IDX | Actor. |
| rescheduled_at | timestamptz | No | now() | IDX | Time. |
| reason | text | Yes | NULL | — | Reason. |

### Supporting tables

| Table | Minimum structure | Purpose |
| --- | --- | --- |
| blackout_periods | service_item_id; starts_at; ends_at; reason; created_by | Schedule exceptions. |
| booking_payment_deadlines | booking_id; due_at; status; expired_at; payment_intent_id | Approve-before-pay deadline. |
| service_policy_snapshots | booking_id; cancellation/refund/no_show policy json; policy_version | Seller policy snapshot. |
| booking_idempotency | store_id; idempotency_key; request_hash; booking_id; created_at; expires_at | Duplicate booking protection. |

## 7.11  payment — Payment Integration Service (PAY)

Tenant-owned Razorpay/provider connections, payment intents/attempts, authoritative webhooks, refunds and reconciliation.

| Isolation / access — Store-scoped. Credentials/tokens are encrypted; provider callbacks are idempotent. KarobarOne does not own customer settlement funds. |
| --- |

### payment.provider_connections

Store/provider account connection.

BRD source: BR-140..145; AC-089..090

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| provider_code | varchar(24) | No | 'RAZORPAY' | UNIQUE active per store/provider | Provider. |
| provider_account_ref | varchar(128) | No | — | IDX | Tenant merchant/account ref. |
| credential_ciphertext | bytea | Yes | NULL | — | Encrypted secret/token if required. |
| status | varchar(24) | No | 'PENDING' | IDX | PENDING/CONNECTED/DISCONNECTED/SUSPENDED/ERROR. |
| connected_at | timestamptz | Yes | NULL | — | Connected. |
| disconnected_at | timestamptz | Yes | NULL | — | Disconnected. |
| capabilities | jsonb | No | '{}'::jsonb | — | Capability snapshot; UPI disabled by policy. |

### payment.payment_intents

Internal payment orchestration for order/booking/platform billing purpose.

BRD source: BR-140..145

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| purpose_type | varchar(24) | No | — | IDX | ORDER/BOOKING/PLATFORM_INVOICE etc. |
| purpose_id | uuid | No | — | IDX | Business aggregate. |
| provider_connection_id | uuid | No | — | FK; IDX | Connection. |
| amount | numeric(18,2) | No | — | CHECK >0 | Expected amount. |
| currency_code | char(3) | No | 'INR' | CHECK | Currency. |
| status | varchar(24) | No | 'CREATED' | IDX | CREATED/PENDING/SUCCEEDED/FAILED/CANCELLED/EXPIRED. |
| provider_order_ref | varchar(128) | Yes | NULL | UNIQUE WHERE NOT NULL | Provider order context. |
| expires_at | timestamptz | Yes | NULL | IDX | Expiry. |
| succeeded_at | timestamptz | Yes | NULL | — | Verified success. |

### payment.payment_attempts

Provider payment attempts; browser redirect is not authoritative.

BRD source: BR-143

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| payment_intent_id | uuid | No | — | FK; IDX | Intent. |
| provider_payment_ref | varchar(128) | Yes | NULL | UNIQUE WHERE NOT NULL | Provider payment ID. |
| method_code | varchar(32) | Yes | NULL | IDX | Payment method; UPI is rejected/not exposed. |
| status | varchar(24) | No | — | IDX | PENDING/SUCCEEDED/FAILED/REVERSED. |
| amount | numeric(18,2) | No | — | CHECK >0 | Attempt amount. |
| provider_status | varchar(64) | Yes | NULL | — | Normalized provider state. |
| initiated_at | timestamptz | No | now() | IDX | Start. |
| confirmed_at | timestamptz | Yes | NULL | IDX | Authoritative confirmation. |

### payment.webhook_events

Signed provider webhook retention and replay/idempotency control.

BRD source: BR-143; Security NFRs

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Event. |
| provider_code | varchar(24) | No | — | IDX | Provider. |
| provider_event_id | varchar(160) | No | — | UNIQUE(provider_code,provider_event_id) | Idempotency key. |
| store_id | uuid | Yes | NULL | IDX | Resolved store. |
| event_type | varchar(100) | No | — | IDX | Event type. |
| signature_valid | boolean | No | false | IDX | Signature result. |
| payload_json | jsonb | No | — | — | Sanitized raw payload. |
| received_at | timestamptz | No | now() | IDX | Receipt. |
| processed_at | timestamptz | Yes | NULL | IDX | Processed. |
| process_status | varchar(20) | No | 'RECEIVED' | IDX | RECEIVED/PROCESSED/FAILED/IGNORED. |
| retry_count | integer | No | 0 | — | Retries. |

### payment.provider_refunds

Provider-side online refund execution.

BRD source: BR-226..228

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| payment_attempt_id | uuid | No | — | IDX | Successful payment. |
| business_refund_id | uuid | No | — | UNIQUE | Commerce/booking refund ref. |
| amount | numeric(18,2) | No | — | CHECK >0 | Refund amount. |
| provider_refund_ref | varchar(128) | Yes | NULL | UNIQUE WHERE NOT NULL | Provider refund ID. |
| status | varchar(24) | No | 'PENDING' | IDX | PENDING/PROCESSING/SUCCEEDED/FAILED. |
| requested_at | timestamptz | No | now() | IDX | Request. |
| completed_at | timestamptz | Yes | NULL | — | Completion. |

### Supporting tables

| Table | Minimum structure | Purpose |
| --- | --- | --- |
| reconciliation_results | store_id; reference_type/id; provider_reference; platform_status; provider_status; result; checked_at; resolution_status | Scheduled provider/platform comparison. |
| payment_state_history | payment_intent_id; from_status; to_status; trigger; provider_event_id; occurred_at | Append-only payment state. |
| provider_api_calls | store_id; operation; idempotency_key; provider_reference; request_hash; result_code; duration_ms; occurred_at | Sanitized integration audit. |

## 7.12  fulfilment — Fulfilment Service (FUL)

Shiprocket/logistics shipping and COD plus secure digital-product entitlement/download records.

| Isolation / access — Store-scoped. Address snapshots are protected PII; digital access tokens are hashed. |
| --- |

### fulfilment.shipping_connections

Approved logistics provider connection.

BRD source: BR-150..155; AC-019..021

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| provider_code | varchar(24) | No | 'SHIPROCKET' | UNIQUE active per store/provider | Provider. |
| account_ref | varchar(128) | Yes | NULL | IDX | Tenant/provider account. |
| credential_ciphertext | bytea | Yes | NULL | — | Encrypted credentials/tokens. |
| status | varchar(24) | No | 'PENDING' | IDX | PENDING/CONNECTED/SUSPENDED/DISCONNECTED. |
| connected_at | timestamptz | Yes | NULL | — | Connected. |

### fulfilment.shipments

Physical-order shipment aggregate.

BRD source: BR-150..158

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| order_id | uuid | No | — | IDX | Commerce order. |
| provider_connection_id | uuid | No | — | IDX | Shipping connection. |
| provider_shipment_ref | varchar(128) | Yes | NULL | UNIQUE WHERE NOT NULL | Provider shipment ID. |
| awb_number | varchar(80) | Yes | NULL | UNIQUE WHERE NOT NULL | AWB. |
| status | varchar(32) | No | 'CREATED' | IDX | CREATED/READY/PICKED_UP/IN_TRANSIT/OUT_FOR_DELIVERY/DELIVERED/RTO/CANCELLED/FAILED. |
| payment_mode | varchar(16) | No | — | IDX | PREPAID/COD. |
| shipping_charge | numeric(18,2) | No | 0 | CHECK >=0 | Shipping charge. |
| estimated_delivery_at | timestamptz | Yes | NULL | IDX | ETA. |
| delivered_at | timestamptz | Yes | NULL | IDX | Authoritative delivery. |
| address_snapshot_ciphertext | bytea | No | — | — | Encrypted address snapshot. |

### fulfilment.shipment_events

Append-only tracking/provider events.

BRD source: BR-154..155

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| shipment_id | uuid | No | — | FK; IDX | Shipment. |
| provider_event_id | varchar(160) | Yes | NULL | UNIQUE WHERE NOT NULL | Provider idempotency. |
| event_code | varchar(64) | No | — | IDX | Normalized event. |
| provider_status | varchar(100) | Yes | NULL | — | Raw provider status. |
| location_text | varchar(240) | Yes | NULL | — | Location. |
| occurred_at | timestamptz | No | — | IDX | Provider time. |
| received_at | timestamptz | No | now() | IDX | Receipt. |

### fulfilment.digital_entitlements

Purchased customer right to download digital product.

BRD source: BR-156..157

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| order_item_id | uuid | No | — | IDX | Digital order line. |
| customer_id | uuid | No | — | IDX | Customer. |
| media_asset_id | uuid | No | — | IDX | Private object ref. |
| status | varchar(20) | No | 'ACTIVE' | IDX | ACTIVE/REVOKED/EXPIRED. |
| max_downloads | smallint | No | 3 | CHECK >0 | Initial limit. |
| downloads_used | smallint | No | 0 | CHECK >=0 | Used count. |
| issued_at | timestamptz | No | now() | IDX | Issue. |
| revoked_at | timestamptz | Yes | NULL | — | Revoke. |

### fulfilment.download_tokens

Short-lived secure download-link issuance.

BRD source: BR-156..157

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| digital_entitlement_id | uuid | No | — | FK; IDX | Entitlement. |
| token_hash | char(64) | No | — | UNIQUE | One-way token. |
| issued_at | timestamptz | No | now() | IDX | Issue. |
| expires_at | timestamptz | No | — | IDX | 24h default. |
| used_at | timestamptz | Yes | NULL | IDX | Use. |
| revoked_at | timestamptz | Yes | NULL | — | Revoke. |

### Supporting tables

| Table | Minimum structure | Purpose |
| --- | --- | --- |
| cod_events | shipment_id; event_type; amount; provider_reference; occurred_at | Delivery/remittance evidence; delivery triggers COD commission. |
| download_events | entitlement_id; token_id; occurred_at; ip; user_agent; result | Auditable download activity. |
| shipping_quotes | store_id; cart/order ref; provider; service_code; charge; eta; expires_at | Provider quote cache/audit. |
| ewaybill_requirements | shipment_id; required; reason; status; document/reference; satisfied_at | E-way bill gate metadata. |

## 7.13  finance — Commission & Finance Service (FIN)

Commission receivables, weekly commission invoicing, disputes/credits, platform invoices and append-only accounting ledger.

| Isolation / access — Tenant/store scoped except tenant-level invoices. This schema never represents customer purchase funds as KarobarOne-owned cash. |
| --- |

### finance.commission_records

One commission obligation per source transaction/trigger, with immutable commercial snapshots.

BRD source: BR-160..175; AC-021..030

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| source_type | varchar(20) | No | — | IDX | ORDER/BOOKING. |
| source_id | uuid | No | — | IDX | Source transaction. |
| source_event_id | uuid | No | — | UNIQUE | Event id that created the obligation. |
| state | varchar(32) | No | 'PENDING_TRIGGER' | IDX | PENDING_TRIGGER/RECEIVABLE/INVOICED/PAID/DISPUTED_AFTER_PAYMENT/CREDIT_PENDING/CREDIT_APPLIED/CANCELLED_NON_PAYABLE. |
| commission_rate | numeric(9,6) | No | — | CHECK >=0 | Snapshotted commission rate. |
| commission_base | numeric(18,2) | No | — | CHECK >=0 | Taxable value after discounts/refunds, excluding GST/shipping. |
| commission_amount | numeric(18,2) | No | — | CHECK >=0 | Calculated commission. |
| trigger_type | varchar(40) | No | — | IDX | PAYMENT_CONFIRMED/DELIVERY_CONFIRMED/BOOKING_DATE etc. |
| receivable_at | timestamptz | Yes | NULL | IDX | When commission became receivable. |
| invoice_line_id | uuid | Yes | NULL | IDX | Assigned invoice line. |

### finance.commission_adjustments

Credits/reversals against a commission record.

BRD source: BR-167..171; BR-226; AC-024..030

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| commission_record_id | uuid | No | — | FK; IDX | Commission record. |
| adjustment_type | varchar(32) | No | — | IDX | CANCELLATION_CREDIT/REFUND_CREDIT/RESCHEDULE_REVERSAL/DISPUTE_CREDIT/MANUAL_APPROVED. |
| amount | numeric(18,2) | No | — | CHECK >0 | Credit/reversal amount. |
| source_event_id | uuid | No | — | UNIQUE | Event idempotency. |
| status | varchar(24) | No | 'PENDING' | IDX | PENDING/APPLIED/CANCELLED. |
| effective_at | timestamptz | No | now() | IDX | Financial effective time. |
| reason | text | Yes | NULL | — | Reason/evidence summary. |

### finance.commission_invoices

Weekly consolidated commission demand to tenant.

BRD source: BR-172..175; AC-029..030

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Invoice. |
| tenant_id | uuid | No | — | IDX | Tenant/PAN scope. |
| invoice_number | varchar(64) | No | — | UNIQUE | Platform invoice number. |
| period_start | date | No | — | IDX | Covered period start. |
| period_end | date | No | — | IDX | Covered period end. |
| issued_at | timestamptz | No | now() | IDX | Issue time. |
| due_at | timestamptz | No | — | IDX | 15-calendar-day due time. |
| subtotal | numeric(18,2) | No | 0 | CHECK >=0 | Commission subtotal net of included credits. |
| tax_amount | numeric(18,2) | No | 0 | CHECK >=0 | Applicable tax on platform invoice. |
| total_amount | numeric(18,2) | No | 0 | CHECK >=0 | Total due. |
| paid_amount | numeric(18,2) | No | 0 | CHECK >=0 | Allocated receipts. |
| status | varchar(24) | No | 'ISSUED' | IDX | DRAFT/ISSUED/PART_PAID/PAID/OVERDUE/CANCELLED. |
| paid_at | timestamptz | Yes | NULL | — | Full payment time. |

### finance.commission_invoice_lines

Commission/credit detail lines on weekly invoice.

BRD source: BR-172..175

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Line. |
| invoice_id | uuid | No | — | FK; IDX | Commission invoice. |
| store_id | uuid | No | — | IDX | Store source. |
| commission_record_id | uuid | Yes | NULL | IDX | Commission record. |
| adjustment_id | uuid | Yes | NULL | IDX | Optional credit adjustment. |
| line_type | varchar(16) | No | — | CHECK | COMMISSION/CREDIT. |
| amount | numeric(18,2) | No | — | CHECK >=0 | Absolute line amount. |
| description | varchar(500) | Yes | NULL | — | Human-readable detail. |
| created_at | timestamptz | No | now() | — | Created. |

### finance.commission_disputes

Pay-first commission dispute workflow.

BRD source: BR-169; BR-174; AC-030

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| commission_record_id | uuid | No | — | IDX | Disputed commission. |
| status | varchar(24) | No | 'OPEN' | IDX | OPEN/IN_REVIEW/APPROVED_CREDIT/REJECTED/CLOSED. |
| reason_code | varchar(40) | No | — | IDX | FRAUD/DUPLICATE/TECHNICAL_INVALID/SYSTEM_ERROR/OTHER. |
| reason_text | text | No | — | — | Tenant explanation. |
| evidence_json | jsonb | No | '{}'::jsonb | — | Evidence references. |
| opened_at | timestamptz | No | now() | IDX | Opened. |
| decided_at | timestamptz | Yes | NULL | — | Decision. |
| decided_by | uuid | Yes | NULL | IDX | Platform actor. |
| credit_adjustment_id | uuid | Yes | NULL | IDX | Later credit if approved. |

### finance.platform_invoices

KarobarOne invoice/demand for subscription, setup, GST, domain and other charges.

BRD source: BR-234..235

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Invoice. |
| tenant_id | uuid | No | — | IDX | Tenant. |
| store_id | uuid | Yes | NULL | IDX | Store when store-specific. |
| invoice_number | varchar(64) | No | — | UNIQUE | Number. |
| invoice_type | varchar(32) | No | — | IDX | SUBSCRIPTION/SETUP_REACTIVATION/UPGRADE_SETUP/GST_SERVICE/PREMIUM_DOMAIN/OTHER. |
| source_type | varchar(32) | No | — | IDX | Owning commercial source. |
| source_id | uuid | No | — | IDX | Source. |
| issued_at | timestamptz | No | now() | IDX | Issue. |
| due_at | timestamptz | Yes | NULL | IDX | Due. |
| subtotal | numeric(18,2) | No | 0 | CHECK >=0 | Subtotal. |
| tax_amount | numeric(18,2) | No | 0 | CHECK >=0 | Tax. |
| total_amount | numeric(18,2) | No | 0 | CHECK >=0 | Total. |
| status | varchar(24) | No | 'ISSUED' | IDX | DRAFT/ISSUED/PART_PAID/PAID/OVERDUE/CANCELLED. |
| paid_at | timestamptz | Yes | NULL | — | Paid. |

### finance.journal_entries

Append-only accounting journal header for platform commercial accounting.

BRD source: BR-235; Security Financial Integrity

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Journal entry. |
| tenant_id | uuid | Yes | NULL | IDX | Tenant context. |
| store_id | uuid | Yes | NULL | IDX | Store context. |
| entry_type | varchar(40) | No | — | IDX | SUBSCRIPTION_CHARGE/ADVANCE_RECEIPT/ADVANCE_CREDIT/COMMISSION/etc. |
| source_type | varchar(40) | No | — | IDX | Source aggregate type. |
| source_id | uuid | No | — | IDX | Source aggregate. |
| source_event_id | uuid | Yes | NULL | UNIQUE WHERE NOT NULL | Event idempotency. |
| entry_date | date | No | CURRENT_DATE | IDX | Accounting date. |
| description | varchar(500) | Yes | NULL | — | Description. |
| posted_at | timestamptz | No | now() | IDX | Post time. |
| reverses_entry_id | uuid | Yes | NULL | IDX | Explicit reversal relationship. |
| metadata | jsonb | No | '{}'::jsonb | — | Audit metadata. |

### finance.journal_postings

Debit/credit lines; total debits must equal total credits per journal entry.

BRD source: Security Financial Integrity

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Posting. |
| journal_entry_id | uuid | No | — | FK; IDX | Journal. |
| account_code | varchar(40) | No | — | IDX | Chart-of-account code. |
| debit_amount | numeric(18,2) | No | 0 | CHECK >=0 | Debit. |
| credit_amount | numeric(18,2) | No | 0 | CHECK >=0 | Credit. |
| currency_code | char(3) | No | 'INR' | CHECK | Currency. |
| created_at | timestamptz | No | now() | — | Created. |

### Supporting tables

| Table | Minimum structure | Purpose |
| --- | --- | --- |
| platform_receipts | tenant_id; store_id; receipt_type; amount; received_at; external_reference; status | Money paid by tenant to KarobarOne for platform liabilities only. |
| receipt_allocations | receipt_id; target_type; target_id; amount; allocated_at | Allocate receipts to platform invoices/commission invoices. |
| invoice_state_history | invoice_type/id; from_status; to_status; actor/trigger; occurred_at | Append-only lifecycle. |
| chart_of_accounts | account_code PK; account_name; account_type; active | Minimal configurable accounting catalog. |
| weekly_invoice_runs | run_date; tenant_count; status; started_at; completed_at; error_summary | Batch execution audit. |

## 7.14  compliance — Compliance & Risk Service (CMP)

GST assistance workflow, category/licence controls, consumer grievances, risk signals and restrictions.

| Isolation / access — Mixed scope: tenant/store records are RLS-protected; platform reference rules are admin-only. Filing approval references immutable GST drafts. |
| --- |

### compliance.category_rules

Platform category compliance policy.

BRD source: BR-067..069; BR-283..287

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Rule. |
| category_code | varchar(80) | No | — | UNIQUE active version | Catalog category. |
| policy_version | integer | No | 1 | UNIQUE(category_code,policy_version) | Version. |
| classification | varchar(24) | No | — | IDX | PERMITTED/MANUAL_REVIEW/LICENCE_GATED/PROHIBITED. |
| requirements_json | jsonb | No | '{}'::jsonb | — | Required evidence/licences. |
| effective_from | timestamptz | No | now() | IDX | Effective. |
| effective_to | timestamptz | Yes | NULL | IDX | End. |
| active | boolean | No | true | IDX | Current flag. |

### compliance.licences

Tenant/store/category licence or authorization evidence metadata.

BRD source: BR-067..069; BR-283

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| category_code | varchar(80) | Yes | NULL | IDX | Relevant category. |
| document_type | varchar(80) | No | — | IDX | Licence/permit/brand authorization etc. |
| document_number_ciphertext | bytea | Yes | NULL | — | Protected number. |
| document_fingerprint | char(64) | Yes | NULL | IDX | Dedup/search blind index. |
| storage_key | text | No | — | — | Private object key. |
| status | varchar(24) | No | 'PENDING' | IDX | PENDING/VERIFIED/REJECTED/EXPIRED/REVOKED. |
| valid_from | date | Yes | NULL | — | Validity. |
| valid_to | date | Yes | NULL | IDX | Expiry. |
| verified_by | uuid | Yes | NULL | IDX | Reviewer. |
| verified_at | timestamptz | Yes | NULL | — | Verification. |

### compliance.gst_service_requests

Per-store/GSTIN GST assistance request and quotation workflow.

BRD source: BR-200..209; AC-031..034

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| gstin_id | uuid | No | — | IDX | Tenant GSTIN. |
| tax_period | varchar(7) | No | — | IDX | YYYY-MM. |
| return_scope | varchar(24) | No | — | IDX | NIL_GSTR1_GSTR3B/NON_NIL/OTHER. |
| plan_snapshot | varchar(24) | No | — | — | Entitlement at request. |
| included_service | boolean | No | false | — | Commerce NIL benefit. |
| quotation_amount | numeric(18,2) | Yes | NULL | CHECK >=0 | Separate charge when applicable. |
| status | varchar(32) | No | 'DATA_COLLECTION' | IDX | DATA_COLLECTION/QUOTED/AWAITING_PAYMENT/PREPARATION/REVIEW/AWAITING_TENANT_APPROVAL/APPROVED/FILED/FAILED/CANCELLED. |
| created_at | timestamptz | No | now() | IDX | Created. |
| updated_at | timestamptz | No | now() | — | Updated. |

### compliance.gst_return_versions

Immutable prepared GST draft/version payload.

BRD source: BR-207..208; AC-034

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| gst_service_request_id | uuid | No | — | FK; IDX | Request. |
| version_no | integer | No | — | UNIQUE(gst_service_request_id,version_no) | Version. |
| draft_payload | jsonb | No | — | — | Normalized return data. |
| source_summary | jsonb | No | '{}'::jsonb | — | Platform/external data sources. |
| content_hash | char(64) | No | — | UNIQUE(gst_service_request_id,content_hash) | Immutable hash. |
| prepared_by | uuid | No | — | IDX | Compliance staff. |
| prepared_at | timestamptz | No | now() | IDX | Prepared. |
| immutable | boolean | No | true | CHECK true | Approved/final versions are never edited. |

### compliance.gst_approvals

Tenant approval of exact immutable GST draft.

BRD source: BR-208; AC-034

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| gst_service_request_id | uuid | No | — | IDX | Request. |
| gst_return_version_id | uuid | No | — | FK; IDX | Exact draft. |
| approver_id | uuid | No | — | IDX | Tenant authorized actor. |
| approved | boolean | No | — | — | Approval/rejection. |
| approved_at | timestamptz | No | now() | IDX | Time. |
| approval_text_version | varchar(32) | No | — | — | Consent wording version. |
| signature_hash | char(64) | No | — | — | Approval evidence. |

### compliance.grievances

Consumer complaint/ticket mechanism.

BRD source: BR-280..281

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| ticket_number | varchar(40) | No | — | UNIQUE | Trackable ticket. |
| customer_id | uuid | Yes | NULL | IDX | Customer when known. |
| order_id | uuid | Yes | NULL | IDX | Order context. |
| booking_id | uuid | Yes | NULL | IDX | Booking context. |
| category | varchar(40) | No | — | IDX | Complaint category. |
| status | varchar(24) | No | 'OPEN' | IDX | OPEN/ACKNOWLEDGED/IN_PROGRESS/RESOLVED/CLOSED. |
| summary | text | No | — | — | Complaint. |
| opened_at | timestamptz | No | now() | IDX | Opened. |
| resolved_at | timestamptz | Yes | NULL | — | Resolved. |

### compliance.risk_signals

Append-only risk indicators generated by workflows/events.

BRD source: BR-250..257

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Immutable surrogate identifier. |
| tenant_id | uuid | No | — | IDX | Tenant isolation key. |
| store_id | uuid | No | — | IDX | Store isolation key. |
| created_at | timestamptz | No | now() | IDX where useful | Creation UTC timestamp. |
| updated_at | timestamptz | No | now() | — | Last update UTC timestamp. |
| signal_type | varchar(64) | No | — | IDX | CANCELLATION_PATTERN/SELLER_REJECTION/PAYMENT_ANOMALY/APPROVAL_VIOLATION/COMMISSION_AVOIDANCE/etc. |
| severity | smallint | No | 1 | CHECK BETWEEN 1 AND 5 | Severity. |
| source_type | varchar(40) | No | — | IDX | Source. |
| source_id | uuid | Yes | NULL | IDX | Source entity. |
| source_event_id | uuid | Yes | NULL | UNIQUE WHERE NOT NULL | Event idempotency. |
| details_json | jsonb | No | '{}'::jsonb | — | Supporting details. |
| detected_at | timestamptz | No | now() | IDX | Detected. |
| resolved_at | timestamptz | Yes | NULL | IDX | Resolution. |

### compliance.restrictions

Store or tenant/PAN-level restriction/suspension.

BRD source: BR-250..257; AC-057..058

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Restriction. |
| tenant_id | uuid | No | — | IDX | Tenant. |
| store_id | uuid | Yes | NULL | IDX | NULL means tenant-wide. |
| restriction_type | varchar(32) | No | — | IDX | COMMISSION_SUSPENDED/RISK_SUSPENDED/ADMIN_SUSPENDED/TERMINATED. |
| scope_json | jsonb | No | '{}'::jsonb | — | Allowed/blocked capabilities. |
| reason_code | varchar(64) | No | — | IDX | Reason. |
| status | varchar(16) | No | 'ACTIVE' | IDX | ACTIVE/RELEASED. |
| starts_at | timestamptz | No | now() | IDX | Start. |
| ends_at | timestamptz | Yes | NULL | IDX | Optional end. |
| created_by | uuid | Yes | NULL | IDX | Actor/system. |
| released_by | uuid | Yes | NULL | IDX | Actor. |
| released_at | timestamptz | Yes | NULL | — | Release. |

### Supporting tables

| Table | Minimum structure | Purpose |
| --- | --- | --- |
| gst_acknowledgements | gst_service_request_id; return_type; arn/reference; filed_at; document_storage_key; checksum | Filing evidence. |
| gst_quotes | gst_service_request_id; quote_version; amount; tax; status; approved_at; paid_at | Separate professional-service quote. |
| risk_reviews | tenant_id/store_id; status; assigned_to; decision; rationale; opened_at; closed_at | Human risk review. |
| restriction_history | restriction_id; from_status; to_status; actor; reason; occurred_at | Append-only restriction history. |
| grievance_messages | grievance_id; sender_type/id; body; attachment refs; created_at | Ticket conversation. |
| compliance_data_imports | gst_service_request_id; source_type; storage_key; checksum; row_count; validation_status | External/off-platform GST data provenance. |

## 7.15  notification — Notification Service (NTF)

Transactional Email/SMS/OTP delivery, templates, rate limits and provider callback audit.

| Isolation / access — Store/tenant scope where relevant. Notification payloads must minimize PII and never contain secrets or raw PAN/GSTIN. |
| --- |

### notification.templates

Versioned transactional notification templates.

BRD source: BR-240..246

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Template. |
| template_code | varchar(80) | No | — | IDX | Logical event template. |
| channel | varchar(12) | No | — | CHECK | EMAIL/SMS. |
| locale | varchar(16) | No | 'en-IN' | — | Locale. |
| version_no | integer | No | 1 | UNIQUE(template_code,channel,locale,version_no) | Version. |
| subject_template | text | Yes | NULL | — | Email subject. |
| body_template | text | No | — | — | Template body. |
| active | boolean | No | true | IDX | Usable version. |
| effective_from | timestamptz | No | now() | IDX | Effective. |
| created_at | timestamptz | No | now() | — | Created. |

### notification.notification_jobs

Durable notification queue item.

BRD source: BR-241..246

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Job. |
| tenant_id | uuid | Yes | NULL | IDX | Tenant context. |
| store_id | uuid | Yes | NULL | IDX | Store context. |
| event_id | uuid | Yes | NULL | UNIQUE WHERE NOT NULL | Source event idempotency. |
| event_type | varchar(100) | No | — | IDX | Order/payment/booking/subscription/etc. |
| channel | varchar(12) | No | — | IDX | EMAIL/SMS. |
| template_id | uuid | No | — | FK; IDX | Template version. |
| recipient_ciphertext | bytea | No | — | — | Protected recipient address/number. |
| recipient_hash | char(64) | No | — | IDX | Dedup/rate-limit fingerprint. |
| payload_json | jsonb | No | '{}'::jsonb | — | Minimized template variables. |
| status | varchar(20) | No | 'QUEUED' | IDX | QUEUED/SENDING/SENT/FAILED/CANCELLED. |
| priority | smallint | No | 0 | IDX | Priority. |
| scheduled_at | timestamptz | No | now() | IDX | Earliest send. |
| sent_at | timestamptz | Yes | NULL | IDX | Sent. |
| attempt_count | smallint | No | 0 | — | Attempts. |

### notification.delivery_attempts

Per-provider send attempt audit.

BRD source: BR-240..246

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Attempt. |
| notification_job_id | uuid | No | — | FK; IDX | Job. |
| provider_code | varchar(32) | No | — | IDX | Email/SMS provider. |
| provider_message_ref | varchar(160) | Yes | NULL | IDX | Provider ref. |
| status | varchar(24) | No | — | IDX | ACCEPTED/DELIVERED/FAILED/BOUNCED/REJECTED. |
| error_code | varchar(80) | Yes | NULL | IDX | Normalized error. |
| attempted_at | timestamptz | No | now() | IDX | Attempt. |
| completed_at | timestamptz | Yes | NULL | — | Completion. |
| response_metadata | jsonb | No | '{}'::jsonb | — | Sanitized provider metadata. |

### notification.rate_limit_counters

OTP/transactional fair-use counters.

BRD source: BR-242..245; Security NFRs

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Counter. |
| scope_type | varchar(24) | No | — | IDX | TENANT/STORE/RECIPIENT/IP. |
| scope_hash | char(64) | No | — | IDX | Protected scope key. |
| counter_type | varchar(32) | No | — | IDX | OTP_SMS/OTP_EMAIL/TRANSACTIONAL_SMS/etc. |
| window_start | timestamptz | No | — | UNIQUE(scope_type,scope_hash,counter_type,window_start) | Window. |
| count | integer | No | 0 | CHECK >=0 | Count. |
| expires_at | timestamptz | No | — | IDX | Cleanup. |

### Supporting tables

| Table | Minimum structure | Purpose |
| --- | --- | --- |
| provider_callbacks | provider_code; provider_event_id UNIQUE; message_ref; event_type; payload_json; received_at; processed_at | Delivery receipt callbacks. |
| notification_preferences | customer/user scope; channel; event category; enabled; legal_override flag | Optional preferences; mandatory transactional/legal notices can override where lawful. |
| suppression_list | channel; recipient_hash; reason; source; expires_at | Bounce/abuse suppression. |
| notification_dead_letters | job_id; final_error; payload snapshot; failed_at; resolved_at | Operational remediation queue. |

## 7.16  analytics — Analytics & AI Service (ANL)

Event ingestion, store aggregates, AI usage/quota accounting and AI output provenance.

| Isolation / access — Analytics is derived data. It must not become the authority for orders, subscription, tax, price, inventory or other financially material fields. |
| --- |

### analytics.analytics_events

Append-only product/business analytics event stream projection.

BRD source: BR-260..264

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Event. |
| event_id | uuid | No | — | UNIQUE | Source/event idempotency. |
| tenant_id | uuid | Yes | NULL | IDX | Tenant context. |
| store_id | uuid | Yes | NULL | IDX | Store context. |
| event_type | varchar(100) | No | — | IDX | Visitor/view/form/order/booking/revenue event. |
| entity_type | varchar(40) | Yes | NULL | IDX | Product/service/order/etc. |
| entity_id | uuid | Yes | NULL | IDX | Entity. |
| occurred_at | timestamptz | No | — | IDX | Event time. |
| received_at | timestamptz | No | now() | IDX | Ingestion. |
| dimensions | jsonb | No | '{}'::jsonb | GIN selectively | Low-cardinality dimensions. |
| metrics | jsonb | No | '{}'::jsonb | — | Event metrics. |
| anonymous_subject_hash | char(64) | Yes | NULL | IDX | Privacy-preserving visitor key. |

### analytics.daily_store_metrics

Daily pre-aggregated store analytics.

BRD source: BR-260..263

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| store_id | uuid | No | — | PK part | Store. |
| metric_date | date | No | — | PK part; IDX | Date. |
| visitors | bigint | No | 0 | CHECK >=0 | Visitors. |
| product_views | bigint | No | 0 | CHECK >=0 | Product views. |
| service_views | bigint | No | 0 | CHECK >=0 | Service views. |
| form_submissions | bigint | No | 0 | CHECK >=0 | Forms. |
| orders_count | bigint | No | 0 | CHECK >=0 | Orders. |
| bookings_count | bigint | No | 0 | CHECK >=0 | Bookings. |
| gmv_amount | numeric(18,2) | No | 0 | CHECK >=0 | KarobarOne-originated GMV metric, not GST-return turnover. |
| revenue_amount | numeric(18,2) | No | 0 | CHECK >=0 | Selected business revenue metric. |
| updated_at | timestamptz | No | now() | — | Updated. |

### analytics.ai_quota_accounts

Configurable Scale AI quota/credit account.

BRD source: BR-270..271

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Quota account. |
| tenant_id | uuid | No | — | IDX | Tenant. |
| store_id | uuid | No | — | UNIQUE active account | Store. |
| plan_version_id | uuid | Yes | NULL | IDX | Entitlement source. |
| quota_period_start | timestamptz | No | — | IDX | Quota period. |
| quota_period_end | timestamptz | No | — | IDX | Quota period end. |
| credit_limit | numeric(18,4) | No | 0 | CHECK >=0 | Configured credits. |
| credits_used | numeric(18,4) | No | 0 | CHECK >=0 | Usage. |
| status | varchar(16) | No | 'ACTIVE' | IDX | ACTIVE/EXHAUSTED/SUSPENDED. |
| updated_at | timestamptz | No | now() | — | Updated. |

### analytics.ai_usage

Append-only AI model usage/cost/credit event.

BRD source: BR-270

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Usage. |
| tenant_id | uuid | No | — | IDX | Tenant. |
| store_id | uuid | No | — | IDX | Store. |
| quota_account_id | uuid | No | — | IDX | Quota account. |
| request_id | uuid | No | — | UNIQUE | Idempotent AI request. |
| capability_code | varchar(64) | No | — | IDX | CONTENT/SEO/COMMERCE_ANALYST/etc. |
| model_code | varchar(80) | No | — | IDX | Permitted model. |
| input_units | numeric(18,4) | No | 0 | CHECK >=0 | Usage units. |
| output_units | numeric(18,4) | No | 0 | CHECK >=0 | Usage units. |
| credits_consumed | numeric(18,4) | No | 0 | CHECK >=0 | Quota debit. |
| occurred_at | timestamptz | No | now() | IDX | Usage time. |
| metadata | jsonb | No | '{}'::jsonb | — | Non-sensitive operational metadata. |

### analytics.ai_outputs

AI-generated draft/output provenance; financially material fields cannot be silently modified.

BRD source: BR-264; BR-271

| Column | Type | Null | Default | Constraint / Index | Purpose |
| --- | --- | --- | --- | --- | --- |
| id | uuid | No | gen_random_uuid() | PK | Output. |
| tenant_id | uuid | No | — | IDX | Tenant. |
| store_id | uuid | No | — | IDX | Store. |
| ai_usage_id | uuid | No | — | IDX | Usage. |
| subject_type | varchar(40) | No | — | IDX | CATALOG_CONTENT/SEO/BLOG/ANALYSIS/etc. |
| subject_id | uuid | Yes | NULL | IDX | Target entity. |
| output_json | jsonb | No | — | — | Generated draft/recommendation. |
| content_hash | char(64) | No | — | IDX | Integrity. |
| approval_required | boolean | No | false | IDX | Public content governance. |
| applied_at | timestamptz | Yes | NULL | IDX | If explicitly applied. |
| applied_by | uuid | Yes | NULL | IDX | Human/system actor under permitted workflow. |
| created_at | timestamptz | No | now() | IDX | Created. |

### Supporting tables

| Table | Minimum structure | Purpose |
| --- | --- | --- |
| daily_item_metrics | store_id; item_id; metric_date; views; conversions; quantity; revenue | Item aggregates. |
| analytics_processing_checkpoints | consumer_name; topic; partition; offset; updated_at | Projection recovery checkpoint. |
| ai_feedback | ai_output_id; actor_id; rating; feedback; created_at | Quality feedback. |
| ai_model_registry | model_code; provider; capability; enabled; configuration_version; effective dates | Permitted model/config catalog. |

# 8. Critical Database Invariants

| Invariant | Implementation | Traceability |
| --- | --- | --- |
| PAN uniqueness | tenant.tenants.pan_fingerprint UNIQUE. Registration must lock/check before tenant creation. | AC-001 |
| Lifetime Free entitlement | tenant.free_store_entitlements UNIQUE(tenant_id) with consumed_at/store_id set atomically. | AC-002 |
| One GSTIN → one paid store | Partial UNIQUE on tenant.store_gstin_assignments(gstin_id) WHERE released_at IS NULL; activation also validates GSTIN belongs to tenant PAN. | AC-008..010 |
| Free Store ≤6 showcase items | Enforce in Catalog application transaction while locking store entitlement/projection; avoid row-count trigger as primary mechanism. | AC-003..005 |
| Product/service transaction separation | commerce.carts/transactions carry transaction_type and CHECK; service layer rejects incompatible item types. | AC-015..018 |
| No negative stock | Atomic UPDATE/row lock in inventory.stock_items; available = on_hand-reserved; CHECK nonnegative. | BR-115..117 |
| Booking capacity | Slot/capacity reservation serialized by advisory/row locks; confirmed+reserved cannot exceed configured capacity. | BR-121..129 |
| Exactly 30-day billing period | subscription_periods CHECK(period_end = period_start + 29 days) for inclusive date model, or canonical half-open timestamp equivalent. | AC-041 |
| Third-Period Advance integrity | Advance ledger is append-only; utilization via allocation rows, not mutable overwrite. | AC-042..064 |
| Historical commercial snapshots | Order/booking/subscription/commission records persist plan price, tax, discount and commission-rate snapshots. | BR-145; BR-163 |
| Approved content only LIVE | Catalog/CMS live pointer can target only an approved version; approval decision remains append-only. | AC-079..081 |
| Webhook idempotency | UNIQUE(provider_code, provider_event_id) plus signature result and raw/sanitized payload retention. | BR-143 |
| Commission idempotency | finance.commission_records.source_event_id UNIQUE; reschedule/refund adjustments also unique by event. | AC-021..030 |
| Commercial history retention | Runtime roles have no DELETE privilege on orders, invoices, commission, subscription, GST approval and material audit records. | AC-082..083 |
| Journal integrity | Journal postings for one entry must balance; application/posting function validates debit=credit before final post. | Financial NFR |

# 9. Indexing Strategy

Indexes are workload-driven. Every FK inside a service schema should normally have a supporting index. Tenant/store leading columns should be used for tenant-scoped access paths. Do not create speculative GIN indexes on every JSONB field.

| Use Case | Index Pattern | Notes |
| --- | --- | --- |
| Tenant/store lists | (tenant_id, store_id, created_at DESC) | Orders, bookings, catalog items, customers. |
| Active catalog | (store_id, status, item_type) WHERE archived_at IS NULL | Storefront/admin lists. |
| Customer identity | UNIQUE(store_id,email); UNIQUE(store_id,mobile_e164) | Per-store uniqueness. |
| Outbox | (occurred_at) WHERE published_at IS NULL | Publisher work queue. |
| Due scheduled actions | (due_at) WHERE status='PENDING' | Subscription transitions / durable scheduler. |
| Inventory expiry | (expires_at) WHERE status='ACTIVE' | Release worker. |
| Booking deadlines | (due_at) WHERE status='PENDING' | Payment expiry. |
| Webhook processing | (received_at) WHERE processed_at IS NULL | Webhook recovery. |
| Commission receivable | (tenant_id, receivable_at) WHERE state='RECEIVABLE' | Weekly billing. |
| Overdue invoices | (due_at) WHERE status IN ('ISSUED','PART_PAID') | Collections/suspension. |
| Analytics | (store_id, occurred_at); BRIN(occurred_at) when very large | Time-range analytics. |

# 10. Partitioning, Archival and Retention

Do not partition all tables on day one. Partition only append-heavy tables after real volume or maintenance evidence justifies it. Candidate monthly partitions: analytics.analytics_events, payment.webhook_events, notification.delivery_attempts/provider_callbacks, service audit_events and high-volume state histories.

| Data Class | Retention / Closure Rule |
| --- | --- |
| Ordinary soft-deleted content | Recoverable for 60 days unless superseded by statutory/security/financial requirements. |
| Orders / invoices / GST / commission / subscription / advance / setup billing | Retain after store/tenant closure; archive rather than destructive delete. |
| Guardian consent | Retain required historical consent according to legal retention policy; adult re-verification does not erase history. |
| Store with commercial history | ARCHIVED/CLOSED, not hard deleted. |
| Store without commercial history | May be permanently deleted after normal retention and safety checks. |
| Provider/webhook/event payloads | Retain according to operational/legal policy; redact secrets and minimize PII. |
| Media/object storage | DB stores keys/checksums/metadata; object lifecycle policy must honor legal holds and entity retention. |

# 11. Transaction and Concurrency Patterns

| Operation | Database Pattern |
| --- | --- |
| Inventory reservation | SELECT ... FOR UPDATE or atomic conditional UPDATE; create reservation + increment reserved_quantity + outbox in one transaction. |
| Booking capacity | Lock capacity bucket/slot before reserve/confirm; serialize overlapping capacity updates; release expiry in durable scheduled action. |
| Free Store entitlement | Lock entitlement row; transition AVAILABLE→CONSUMED atomically with store_id. |
| State transition | UPDATE ... WHERE id=? AND status=:expected AND version=:expected_version; increment version; append history/outbox. |
| Subscription due processing | Scheduled action has UNIQUE action_key and idempotent handler; lock subscription aggregate before transition/charge generation. |
| Payment webhook | Insert unique provider_event_id first; verify signature; mutate payment; write outbox; mark processed in same transaction. |
| Commission creation | Unique source_event_id prevents duplicate receivable on Kafka redelivery. |
| External API calls | Never hold DB transaction open while calling Razorpay/Shiprocket/SMS/email; persist intent, commit, call externally, persist result via idempotent follow-up. |
| Deadlock handling | Use deterministic lock order and bounded retries only for idempotent transactions. |

# 12. Migration and Release Standards

- Use SQLAlchemy 2.x declarative models and Alembic. Each service owns its migration directory/version lineage even when all schemas share one cluster.
- Use expand → migrate/backfill → switch application → contract. Never combine a breaking destructive schema change with the first application release that stops using the old shape.
- Large-table constraints should use PostgreSQL NOT VALID / VALIDATE CONSTRAINT where appropriate. Large indexes should use CREATE INDEX CONCURRENTLY in an operational migration step.
- Data migrations must be resumable/idempotent and separately observable from DDL migrations.
- Seed data such as plans, roles, category rules and templates is versioned. Do not overwrite historical plan/config versions used by commercial records.
- Every migration receives: forward plan, rollback/forward-fix plan, expected lock impact, estimated rows touched, backup prerequisite and owner.
- CI must run migrations from empty database and from the previous production schema snapshot, then execute RLS and acceptance/invariant tests.
# Recommended repository convention

services/subscription-service/

app/models/

migrations/

env.py

versions/

tests/db/

# Alembic owns schema='subscription'; runtime role cannot ALTER schema.

# 13. Backup, Restore and Database Operations

| Control | V1 Requirement |
| --- | --- |
| Availability target | Architecture targets 99.5% platform availability; database topology should support automated primary recovery. |
| Backups | Daily database backup; initial 15-day retention baseline. Add WAL/PITR where infrastructure budget permits and validate restore procedures. |
| Restore testing | Scheduled restore test into isolated environment; verify migrations, RLS policies, row counts and critical financial ledgers. |
| Secrets | Database credentials and encryption keys reside in secret manager/Kubernetes secrets; rotate independently of schema data. |
| Connections | Per-service connection pool and DB role; cap pool sizes to protect PostgreSQL. Consider PgBouncer after measured need. |
| Observability | Track connection utilization, transaction latency, locks/deadlocks, replication lag, WAL growth, slow queries, autovacuum health, disk and backup success. |
| Audit access | Production ad-hoc write access prohibited. Break-glass actions use named privileged identity and external audit record. |

# 14. SQLAlchemy and Alembic Implementation Guidance

class Order(Base):

__tablename__ = 'orders'

__table_args__ = (

UniqueConstraint('store_id', 'order_number'),

{'schema': 'commerce'},

)

id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True,

server_default=text('gen_random_uuid()'))

tenant_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

store_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

status: Mapped[str] = mapped_column(String(32), nullable=False)

version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default='1')

Use Pydantic/API enums independently of database CHECK constraints. Database CHECKs protect invariant values; application transition matrices protect legal transitions. Repository code must not expose generic “update status” operations for state-machine aggregates.

# 15. Database Build Sequence

| Stage | Deliverable |
| --- | --- |
| DB-0 Foundation | Extensions, service roles/schemas, migration framework, standard audit/outbox/idempotency patterns, RLS test harness. |
| DB-1 Identity/Tenant | iam + tenant. Complete PAN fingerprint uniqueness, Guardian records, Free Store entitlement and store/GSTIN assignment. |
| DB-2 Free Presence | catalog + approval + domain minimum. Content versions, six-item enforcement support, media metadata, subdomain and publication records. |
| DB-3 Subscription | subscription + platform invoice foundations. Implement plan versions, entitlement snapshots, periods, advance ledger, scheduled actions and state history. |
| DB-4 Customer/Catalog/Inventory | customer + remaining catalog + inventory reservations/movements. |
| DB-5 Product Commerce/Payment | commerce + payment. Orders, immutable snapshots, webhooks, refunds, outbox/idempotency. |
| DB-6 Fulfilment | fulfilment. Shipments/COD events/digital entitlements/download tokens. |
| DB-7 Booking | booking. Schedules, capacity, reservations, deadlines, reschedule history. |
| DB-8 Commission/Finance | finance. Commission records/adjustments/invoices/disputes, receipts and balanced ledger. |
| DB-9 Compliance/Risk | compliance. GST versions/approvals, licences, grievances, risk signals/restrictions. |
| DB-10 Notifications/Analytics/AI | notification + analytics; partitioning only after volume evidence. |

# Appendix A — Schema and Table Catalogue

| Schema | Table | Class | BRD Trace |
| --- | --- | --- | --- |
| iam | principals | Core | BR-050..053; Security NFRs |
| iam | sessions | Core | Security NFRs |
| iam | role_assignments | Core | BR-050..053 |
| iam | otp_challenges | Core | BR-244..246 |
| iam | credentials | Supporting | — |
| iam | roles | Supporting | — |
| iam | permissions | Supporting | — |
| iam | role_permissions | Supporting | — |
| iam | mfa_factors | Supporting | — |
| iam | auth_audit | Supporting | — |
| tenant | tenants | Core | BR-002,003,010..013,020..029 |
| tenant | guardians | Core | BR-023..029 |
| tenant | guardian_consents | Core | BR-026..029; AC-038..040 |
| tenant | gstins | Core | BR-014..019; BR-064; AC-008..010 |
| tenant | stores | Core | BR-011..019; BR-040..049; BR-063..065 |
| tenant | free_store_entitlements | Core | BR-011..013; AC-002 |
| tenant | pan_verifications | Supporting | — |
| tenant | guardian_documents | Supporting | — |
| tenant | gstin_verifications | Supporting | — |
| tenant | store_memberships | Supporting | — |
| tenant | seller_declarations | Supporting | — |
| tenant | store_status_history | Supporting | — |
| subscription | plan_versions | Core | BR-030..039 |
| subscription | subscriptions | Core | BR-180..192; Appendix C.1/C.2 |
| subscription | subscription_periods | Core | BR-031..033; BR-180..186; AC-041..067 |
| subscription | subscription_charges | Core | BR-180..192; BR-234..235 |
| subscription | advance_movements | Core | BR-180..186; BR-235; AC-042,046..052,062..064 |
| subscription | plan_change_requests | Core | BR-188..192 |
| subscription | upgrade_quotes | Core | BR-188..189; AC-069..075 |
| subscription | entitlement_snapshots | Core | BR-030..039; BR-070..094 |
| subscription | plan_entitlements | Supporting | — |
| subscription | cancellation_notices | Supporting | — |
| subscription | reactivations | Supporting | — |
| subscription | discount_approvals | Supporting | — |
| subscription | subscription_state_history | Supporting | — |
| subscription | scheduled_actions | Supporting | — |
| domain | subdomains | Core | BR-040..041; BR-049; AC-084 |
| domain | domains | Core | BR-042..048; AC-085..088 |
| domain | publication_routes | Core | BR-063..065; BR-049 |
| domain | domain_requests | Supporting | — |
| domain | dns_checks | Supporting | — |
| domain | domain_payments | Supporting | — |
| domain | publication_history | Supporting | — |
| catalog | catalog_items | Core | BR-070..094; BR-110..129 |
| catalog | item_versions | Core | BR-210..216; AC-079..081 |
| catalog | product_details | Core | BR-110..118 |
| catalog | service_details | Core | BR-120..129 |
| catalog | skus | Core | BR-111..118 |
| catalog | media_assets | Core | BR-073..074; BR-090..094; BR-156..157 |
| catalog | store_content_versions | Core | BR-075; BR-210..216 |
| catalog | item_attributes | Supporting | — |
| catalog | variant_definitions | Supporting | — |
| catalog | variant_values | Supporting | — |
| catalog | sku_variant_values | Supporting | — |
| catalog | item_media | Supporting | — |
| catalog | store_media | Supporting | — |
| catalog | seo_metadata | Supporting | — |
| catalog | categories | Supporting | — |
| catalog | custom_categories | Supporting | — |
| catalog | blog_posts | Supporting | — |
| catalog | blog_versions | Supporting | — |
| catalog | custom_forms | Supporting | — |
| catalog | form_submissions | Supporting | — |
| approval | approval_requests | Core | BR-063; BR-067..069; BR-210..216 |
| approval | approval_decisions | Core | BR-211..216; AC-080 |
| approval | takedowns | Core | BR-214..216; AC-081 |
| approval | approval_attachments | Supporting | — |
| approval | approval_state_history | Supporting | — |
| customer | customers | Core | BR-130..136; AC-076..078 |
| customer | addresses | Core | BR-136 |
| customer | account_claims | Core | BR-133..135; AC-077..078 |
| customer | privacy_requests | Core | BR-136; BR-285; BR-290..295 |
| customer | customer_status_history | Supporting | — |
| customer | customer_consents | Supporting | — |
| inventory | stock_balances | Core | BR-112..118 |
| inventory | reservations | Core | BR-115..117 |
| inventory | stock_movements | Core | BR-116 |
| inventory | inventory_settings | Supporting | — |
| commerce | carts | Core | BR-100..104; AC-015..018 |
| commerce | orders | Core | BR-140..145; BR-220..235 |
| commerce | order_items | Core | BR-145; BR-230..233 |
| commerce | order_status_history | Core | BR-220 |
| commerce | refund_requests | Core | BR-226..228 |
| commerce | cart_items | Supporting | — |
| commerce | cancellation_requests | Supporting | — |
| commerce | return_requests | Supporting | — |
| commerce | return_items | Supporting | — |
| commerce | refund_items | Supporting | — |
| commerce | checkout_idempotency | Supporting | — |
| booking | service_schedules | Core | BR-120..129 |
| booking | capacity_reservations | Core | BR-125; BR-129 |
| booking | bookings | Core | BR-120..129; BR-166..171; BR-221 |
| booking | booking_status_history | Core | BR-126..129; BR-166..171 |
| booking | booking_reschedules | Core | BR-126; BR-171 |
| booking | blackout_periods | Supporting | — |
| booking | booking_payment_deadlines | Supporting | — |
| booking | service_policy_snapshots | Supporting | — |
| booking | booking_idempotency | Supporting | — |
| payment | provider_connections | Core | BR-140..145; AC-089..090 |
| payment | payment_intents | Core | BR-140..145 |
| payment | payment_attempts | Core | BR-143 |
| payment | webhook_events | Core | BR-143; Security NFRs |
| payment | provider_refunds | Core | BR-226..228 |
| payment | reconciliation_results | Supporting | — |
| payment | payment_state_history | Supporting | — |
| payment | provider_api_calls | Supporting | — |
| fulfilment | shipping_connections | Core | BR-150..155; AC-019..021 |
| fulfilment | shipments | Core | BR-150..158 |
| fulfilment | shipment_events | Core | BR-154..155 |
| fulfilment | digital_entitlements | Core | BR-156..157 |
| fulfilment | download_tokens | Core | BR-156..157 |
| fulfilment | cod_events | Supporting | — |
| fulfilment | download_events | Supporting | — |
| fulfilment | shipping_quotes | Supporting | — |
| fulfilment | ewaybill_requirements | Supporting | — |
| finance | commission_records | Core | BR-160..175; AC-021..030 |
| finance | commission_adjustments | Core | BR-167..171; BR-226; AC-024..030 |
| finance | commission_invoices | Core | BR-172..175; AC-029..030 |
| finance | commission_invoice_lines | Core | BR-172..175 |
| finance | commission_disputes | Core | BR-169; BR-174; AC-030 |
| finance | platform_invoices | Core | BR-234..235 |
| finance | journal_entries | Core | BR-235; Security Financial Integrity |
| finance | journal_postings | Core | Security Financial Integrity |
| finance | platform_receipts | Supporting | — |
| finance | receipt_allocations | Supporting | — |
| finance | invoice_state_history | Supporting | — |
| finance | chart_of_accounts | Supporting | — |
| finance | weekly_invoice_runs | Supporting | — |
| compliance | category_rules | Core | BR-067..069; BR-283..287 |
| compliance | licences | Core | BR-067..069; BR-283 |
| compliance | gst_service_requests | Core | BR-200..209; AC-031..034 |
| compliance | gst_return_versions | Core | BR-207..208; AC-034 |
| compliance | gst_approvals | Core | BR-208; AC-034 |
| compliance | grievances | Core | BR-280..281 |
| compliance | risk_signals | Core | BR-250..257 |
| compliance | restrictions | Core | BR-250..257; AC-057..058 |
| compliance | gst_acknowledgements | Supporting | — |
| compliance | gst_quotes | Supporting | — |
| compliance | risk_reviews | Supporting | — |
| compliance | restriction_history | Supporting | — |
| compliance | grievance_messages | Supporting | — |
| compliance | compliance_data_imports | Supporting | — |
| notification | templates | Core | BR-240..246 |
| notification | notification_jobs | Core | BR-241..246 |
| notification | delivery_attempts | Core | BR-240..246 |
| notification | rate_limit_counters | Core | BR-242..245; Security NFRs |
| notification | provider_callbacks | Supporting | — |
| notification | notification_preferences | Supporting | — |
| notification | suppression_list | Supporting | — |
| notification | notification_dead_letters | Supporting | — |
| analytics | analytics_events | Core | BR-260..264 |
| analytics | daily_store_metrics | Core | BR-260..263 |
| analytics | ai_quota_accounts | Core | BR-270..271 |
| analytics | ai_usage | Core | BR-270 |
| analytics | ai_outputs | Core | BR-264; BR-271 |
| analytics | daily_item_metrics | Supporting | — |
| analytics | analytics_processing_checkpoints | Supporting | — |
| analytics | ai_feedback | Supporting | — |
| analytics | ai_model_registry | Supporting | — |

# Appendix B — Core Relationship Map

iam.principals

│

├── tenant.tenants ── tenant.stores ── tenant.store_gstin_assignments

│                         │

│                         ├── subscription.subscriptions ── periods/advance/scheduled_actions

│                         ├── domain.domains/publication_routes

│                         ├── catalog.catalog_items ── skus/content/media

│                         ├── customer.customers

│                         ├── inventory.stock_items/reservations/movements

│                         ├── commerce.orders/order_items/refunds

│                         ├── booking.bookings/capacity_reservations

│                         ├── payment.payment_intents/webhook_events

│                         ├── fulfilment.shipments/digital_entitlements

│                         ├── finance.commission_records/invoices

│                         └── compliance.gst_service_requests/risk_signals

│

└── approval / notification / analytics consume references & events

Hard FK lines are applied only within an owning schema by default. Cross-service arrows are UUID contracts/events.

# Appendix C — BRD Rule-to-Database Coverage

| BRD Domain | Owning Schema(s) | Database Coverage |
| --- | --- | --- |
| Tenant/PAN/GSTIN/Minor | tenant + iam | Fingerprint uniqueness, entitlement, guardian/consent/version records, store-GSTIN assignment. |
| Plans/subscriptions/advance/upgrades | subscription + finance | Versioned plan config, periods, ledger allocations, scheduled transitions, quotes/approvals, invoices. |
| Domains/publication | domain | Domains, DNS attempts, host routing, publication versions. |
| Free/Paid catalog/CMS | catalog + approval | Versioned item/content records, media entitlements, approval pointers/history. |
| Customers/guest claim | customer + iam | Per-store unique email/mobile; UNCLAIMED profile; OTP claim. |
| Inventory | inventory | Stock, reservations, movement ledger; no-negative invariant. |
| Product checkout/orders/refunds | commerce | Cart/order snapshots, state history, cancellation/return/refund records. |
| Bookings | booking | Schedules, capacity, reservations, state/reschedule history and policy snapshots. |
| Online payments | payment | Tenant provider connections, intents/attempts, signed idempotent webhooks, refunds/reconciliation. |
| Shipping/COD/digital | fulfilment | Shiprocket context, tracking/delivery/COD events, signed-token entitlement records. |
| Commission/platform finance | finance | Commission trigger snapshot, adjustments, weekly invoices, pay-first disputes, balanced platform ledger. |
| GST/consumer/risk | compliance | GST request/version/approval/acknowledgement, licences, grievances, signals/restrictions. |
| Email/SMS/OTP | notification + iam | Durable delivery queue, attempts/callbacks, OTP challenge/rate limits. |
| Analytics/AI | analytics | Derived events/aggregates, quota/usage/output provenance; no silent financial mutation. |

# Appendix D — Reference DDL Patterns

-- One tenant per PAN fingerprint

CREATE UNIQUE INDEX uq_tenant_pan_fingerprint

ON tenant.tenants (pan_fingerprint);

-- Same GSTIN cannot actively back two paid stores

CREATE UNIQUE INDEX uq_active_store_gstin

ON tenant.store_gstin_assignments (gstin_id)

WHERE released_at IS NULL;

-- Customer identities are store-scoped

CREATE UNIQUE INDEX uq_customer_store_email

ON customer.customers (store_id, email);

CREATE UNIQUE INDEX uq_customer_store_mobile

ON customer.customers (store_id, mobile_e164);

-- Fast unpublished outbox scan

CREATE INDEX ix_commerce_outbox_unpublished

ON commerce.outbox_events (occurred_at)

WHERE published_at IS NULL;

-- Durable due-action scan

CREATE INDEX ix_subscription_due_actions

ON subscription.scheduled_actions (due_at)

WHERE status = 'PENDING';

# Engineering Baseline Statement

This Database Design & PostgreSQL Schema Specification V1.0 is the implementation baseline for KarobarOne V1 database development. SQLAlchemy models, Alembic migrations, repository queries, RLS policies, database tests and operational procedures should conform to it unless a formally approved BRD/BTDD/database-spec revision supersedes it. Business-rule conflicts are resolved in favour of the latest approved BRD; database design changes that do not alter business behaviour may be revised through technical change control.
