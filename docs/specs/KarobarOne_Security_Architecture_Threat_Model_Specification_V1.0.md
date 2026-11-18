**KAROBARONE**

**Security Architecture &
Threat Model Specification**

Security control baseline for identity, tenant isolation, data protection, APIs, events, Kubernetes, providers, operations and release assurance

| Document Field | Value |
| --- | --- |
| Specification Version | 1.0 |
| Status | Security Implementation Baseline |
| Effective Date | 14 September 2026 |
| Business Authority | KarobarOne BRD V2.1 - Final Consolidated |
| Technical Inputs | Backend Technical Design V1.0; PostgreSQL Schema Specification V1.0; State Machine & Business Rules V1.0; REST API & Kafka Event Contract V1.0; OpenAPI/AsyncAPI Contracts V1.0; Repository & Engineering Foundation V1.0; Backend Test & Acceptance V1.0; Infrastructure & Kubernetes Deployment V1.0 |
| Target Platform | FastAPI / PostgreSQL / Kafka / Redis / S3-compatible storage / Docker / Kubernetes / Cloudflare-WAF |
| Primary Audience | Security, Backend Engineering, DevOps/SRE, Database, QA, Architecture, Platform Operations and Technical Leads |

| Authority - This specification defines security architecture and technical controls. It does not redefine commercial, legal, subscription, commission, GST or lifecycle rules. If a security design conflicts with the BRD or an approved state-machine/business invariant, the higher-authority artifact prevails and the conflict must be resolved through change control. |
| --- |

| Assurance boundary - This document is an engineering threat model and security baseline. It is not a legal opinion, statutory certification, penetration-test report or compliance attestation. |
| --- |

# **Document Contents**

1. Purpose, Scope and Normative Hierarchy

2. Approved Security Baseline and Security Design Decisions

3. Security Objectives and Engineering Principles

4. System Security Context and Trust Boundaries

5. Security Assets and Data Classification

6. Identity, Authentication and Session Security

7. Authorization, Tenant Isolation and Privileged Access

8. API and Application Security

9. External Provider and Webhook Security

10. PostgreSQL and Data-Layer Security

11. Kafka, Event and Asynchronous Processing Security

12. Object Storage, Media and Digital Fulfilment Security

13. Kubernetes, Network and Runtime Security

14. Secrets, Keys and Cryptographic Material

15. CI/CD, Dependency and Software Supply-Chain Security

16. Logging, Audit, Detection and Security Observability

17. Privacy, Retention and Data-Minimization Controls

18. AI Feature Security Boundaries

19. Abuse, Fraud and Availability Protection

20. Security Incident Response and Containment

21. Threat-Modelling Method and Risk Scoring

22. Threat Register - STRIDE Analysis

23. High-Risk Business Flow Abuse Cases

24. Security Verification and Test Matrix

25. Security Release Gates and Production Readiness

26. Security Operations, Reviews and Change Management

27. Open Security Decisions and Future Hardening

Appendix A - Role and Trust Matrix

Appendix B - Data Classification Matrix

Appendix C - Security Control Checklist

Appendix D - Threat-to-Test Traceability

# **1. Purpose, Scope and Normative Hierarchy**

## **1.1 Purpose**

This specification turns the approved KarobarOne business and technical architecture into a coherent security model. It defines preventive, detective and recovery controls around the 16 logical backend services and the shared Kubernetes/data platform, then evaluates credible threats against those controls using a STRIDE-style threat model.

## **1.2 In Scope**

- Authentication, sessions, OTP, service identity and privileged administration.
- RBAC, store/tenant assignment, object ownership, entitlement/lifecycle authorization and PostgreSQL RLS.
- PAN, GSTIN, Guardian identity data, customer PII, provider credentials, payment metadata, commercial records and audit history.
- FastAPI endpoints, public storefront APIs, internal service APIs, webhooks and machine-readable contracts.
- Kafka topics/events, outbox/inbox, consumers, retries, DLQs and scheduler/worker execution.
- PostgreSQL, Redis, object storage, Kubernetes, ingress/WAF, ServiceAccounts, secrets and container runtime controls.
- Software supply chain, CI/CD, image provenance, migrations and production promotion.
- Logging, audit, alerting, incident response, privacy/retention, abuse protection and security verification.

## **1.3 Out of Scope**

- Business-rule changes not required to implement a security control.
- Final cloud/provider selection or vendor-specific contractual security assessment.
- Formal legal/privacy certification, ISO/SOC certification or statutory compliance opinion.
- Red-team or penetration-test execution results; this document defines what such testing should target.
- End-user device security outside controls reasonably enforceable by the platform.

## **1.4 Normative Hierarchy**

| Priority | Artifact | Security authority |
| --- | --- | --- |
| 1 | KarobarOne BRD V2.1 | Business/legal/commercial invariants and acceptance criteria. |
| 2 | State Machine & Business Rules V1.0 | Allowed states, guards and state-transition effects. |
| 3 | PostgreSQL Schema Specification V1.0 | Persistence ownership, constraints, RLS and immutable history. |
| 4 | REST API & Kafka Event Contract V1.0 + OpenAPI/AsyncAPI | Allowed synchronous/asynchronous interfaces and payload rules. |
| 5 | Backend Technical Design V1.0 | Service boundaries and cross-service communication. |
| 6 | Repository/Foundation + Infrastructure/Kubernetes V1.0 | Runtime, CI/CD, container, network and deployment controls. |
| 7 | Backend Test & Acceptance V1.0 | Mandatory verification and release gates. |
| 8 | This specification | Security control architecture and threat treatment. |
| 9 | Implementation code/policy | Must conform to all higher-authority artifacts. |

# **2. Approved Security Baseline and Security Design Decisions**

The following table distinguishes controls already established by approved specifications from additional implementation decisions introduced here. Security design decisions may be tightened through ADR/security review without changing business semantics.

| ID | Classification | Control / Decision |
| --- | --- | --- |
| SEC-001 | Approved baseline | Custom JWT access/session model with refresh rotation/revocation; IAM owns issuance and session lifecycle. |
| SEC-002 | Approved baseline | Strong password hashing; Argon2id preferred. OTP values are stored only as hashes with TTL, attempt and rate limits. |
| SEC-003 | Approved baseline | Authorization = role + tenant/store assignment + resource ownership + entitlement + lifecycle + active restriction. |
| SEC-004 | Approved baseline | PAN/GSTIN/Guardian government identifiers encrypted/fingerprinted, masked in responses and excluded from ordinary logs/events. |
| SEC-005 | Approved baseline | PostgreSQL RLS is defense-in-depth for selected sensitive tenant/store scoped tables; trusted scope is set inside transactions. |
| SEC-006 | Approved baseline | Provider webhooks are authenticated/signed, raw-retained under restricted access, deduplicated and replay-safe. |
| SEC-007 | Approved baseline | DB/Kafka/Redis are private; ingress is protected by HTTPS + Cloudflare/WAF; Kubernetes NetworkPolicy restricts flows. |
| SEC-008 | Approved baseline | Containers run non-root, drop privilege where feasible, avoid baked secrets and are scanned before promotion. |
| SEC-009 | Approved baseline | Commercial/financial/audit corrections are append-only/compensating; destructive rewrite is prohibited. |
| SEC-010 | Approved baseline | Machine-readable API/event contracts and AC-001..AC-090 plus engineering invariants are release gates. |
| SDD-001 | Security design decision | Production Platform Owner/Platform Staff privileged accounts must use MFA before public production; break-glass accounts are separately controlled and audited. |
| SDD-002 | Security design decision | Access tokens are short-lived; refresh credentials are rotated, hashed/server-tracked, revocable and bound to a session record. Exact TTL is environment configuration, not hard-coded domain policy. |
| SDD-003 | Security design decision | Default-deny Kubernetes ingress/egress and least-privilege ServiceAccount/RBAC are required in production namespaces. |
| SDD-004 | Security design decision | Security-sensitive administrative commands require fresh authorization checks against current assignment/restriction state rather than trusting stale JWT claims alone. |
| SDD-005 | Security design decision | Security findings use the risk model in Section 21; unresolved Critical/High findings affecting tenant isolation, funds, authentication or immutable records block production unless explicitly security-risk accepted by authorized leadership. |
| SDD-006 | Security design decision | Credential/key rotation must be rehearsable without source-code changes; production secrets must be environment-scoped and preferably external-secret-manager backed. |

# **3. Security Objectives and Engineering Principles**

| ID | Principle | Engineering consequence |
| --- | --- | --- |
| SP-01 | Tenant isolation is non-negotiable | No actor can infer authority from UUID possession. Application authorization and RLS/database controls provide layered isolation. |
| SP-02 | Fail closed for new commerce | If entitlement, restriction or authoritative payment/provider state cannot be verified, creation of new commercial obligations is denied rather than guessed. |
| SP-03 | Least privilege everywhere | Users, ServiceAccounts, DB roles, Kafka credentials and CI identities receive only required scope. |
| SP-04 | Immutable evidence over mutable history | Audit, webhook evidence, state history, commercial snapshots and financial ledgers are append-only or corrected through explicit compensating records. |
| SP-05 | Untrusted input by default | Public requests, tenant content, provider callbacks, events and uploaded files are validated before they can affect domain state. |
| SP-06 | Contracts before trust | Service-to-service communication uses authenticated APIs/events and committed schemas; repository sharing never grants data ownership. |
| SP-07 | Security context is propagated, not invented | tenant_id/store_id/actor/service/correlation IDs come from trusted authentication/context and are validated at each boundary. |
| SP-08 | Minimize sensitive data | Collect and expose only fields needed for the workflow; mask/encrypt identifiers and avoid duplicating PII into events/logs/projections. |
| SP-09 | Assume retries and partial failure | API idempotency, webhook dedupe, outbox/inbox and unique financial business keys prevent duplicated side effects. |
| SP-10 | Detect and recover | Security-relevant failures must produce auditable evidence, actionable alerts and a documented containment/reconciliation path. |

# **4. System Security Context and Trust Boundaries**

## **4.1 Security Zones**

| Zone | Examples | Trust posture |
| --- | --- | --- |
| Z0 Internet / untrusted | Anonymous storefront users, customers, bots, external browsers | Fully untrusted input. WAF/rate limiting/TLS; application authz still required. |
| Z1 External providers | Razorpay, Shiprocket, email/SMS, registrar/DNS, PAN/GST verification | Authenticated per adapter; provider data is not trusted solely because it came from the network. |
| Z2 Edge / ingress | Cloudflare/WAF, load balancer, Kubernetes ingress/API gateway | Public entry boundary. TLS termination/routing/rate controls; no business authorization decisions solely at edge. |
| Z3 Application workloads | FastAPI APIs, consumers, outbox publisher, schedulers, workers | Authenticated workloads with least ServiceAccount/network access; domain authorization required. |
| Z4 Data plane | PostgreSQL/CloudNativePG, Kafka, Redis, object storage | Private endpoints. Strong identity/ACLs. PostgreSQL is authoritative; Redis/Kafka are not authorization sources. |
| Z5 Privileged operations | Platform admin interfaces, CI/CD, cluster/database administration | Highest trust but highest impact. MFA, least privilege, audit, protected changes and break-glass controls. |
| Z6 Build/supply chain | Git, dependency registry, container registry, CI runners | Untrusted until verified through reviews/scans/immutable artifact promotion. |

## **4.2 Trust-Boundary Flow**

| Internet / Tenant Domains
        \|
   Cloudflare / WAF
        \|
 Kubernetes Ingress / API Gateway
        \|
  +-----+------------------------------+
  \| Public APIs / Storefront           \|
  \| Authenticated Tenant/Admin APIs    \|
  +-----+------------------------------+
        \| authenticated HTTP / JWT / workload identity
        v
  FastAPI service boundaries (IAM/TEN/SUB/.../ANL)
        \|                  \|
        \| local ACID       \| Kafka facts (outbox -> broker -> inbox)
        v                  v
 PostgreSQL schemas      Kafka private data plane
        \|                  \|
        +----> workers / schedulers / projections
        \|
        +----> Redis (ephemeral cache/rate limit only)
        +----> private S3-compatible object storage (signed URLs)
        +----> provider adapters -> external providers |
| --- |

## **4.3 Critical Boundary Rules**

- Ingress/WAF does not establish tenant/store authorization; application context must still validate scope.
- Provider callbacks are accepted only after adapter-specific authenticity checks and replay/dedupe handling.
- Public tenant-host resolution maps a host to a store/publication state; it must never grant administration access.
- Application pods do not receive cluster-admin, database-superuser or wildcard secrets by default.
- Kafka topic access and database permissions are service/workload scoped; a monorepo is not a trust boundary.
- No public endpoint exists for PostgreSQL, Kafka or Redis.

# **5. Security Assets and Data Classification**

## **5.1 Asset Classes**

| Class | Examples | Primary protection |
| --- | --- | --- |
| A1 Credentials / authentication secrets | Password hashes, refresh-token hashes, OTP challenges, JWT/private signing material | Highest confidentiality; hash/encrypt; strict IAM access; never log or publish. |
| A2 Government/business identifiers | PAN, GSTIN, Guardian government ID, verification evidence | Encrypt/fingerprint/mask; purpose-limited access; no ordinary logs/events. |
| A3 Provider secrets | Razorpay/Shiprocket/API tokens, webhook secrets, DNS/registrar credentials | Secret manager/Kubernetes Secret refs; environment/tenant scope; rotation. |
| A4 Customer PII | Name, email, mobile, addresses | Tenant/store scoped, minimized, access controlled; privacy/anonymization rules. |
| A5 Financial/commercial evidence | Orders, bookings, payment references, commission, invoices, GST, subscription/advance records | Integrity and auditability critical; immutable snapshots/ledger; strong authz. |
| A6 Controlled content/media | Draft/live product/page/blog content and private uploads | Versioning/approval; private storage; signed access; content scanning where appropriate. |
| A7 Operational telemetry | Logs, traces, metrics, audit events, webhook evidence | Redaction; access controls; retention; tamper resistance for audit. |
| A8 Public data | Approved/live storefront content, public plan information | Integrity/availability important; cache/CDN safe after approved projection. |

## **5.2 Classification Rules**

- Confidential data is not copied into Kafka events unless the event contract explicitly requires a safe masked/opaque reference.
- PAN/GSTIN/government ID values must never appear in ordinary operational logs, stack traces, metrics labels or analytics events.
- Payment credentials/card data are not stored by KarobarOne; provider identifiers and transaction evidence are stored only as needed for workflow/reconciliation.
- Object-storage buckets/keys for uploads and digital products are private by default; permanent public object URLs are prohibited.
- Production data must not be used in local/dev fixtures. Staging uses synthetic/masked data unless formally approved.

# **6. Identity, Authentication and Session Security**

## **6.1 Human Authentication**

| Control | Baseline |
| --- | --- |
| Password storage | Argon2id preferred; only strong one-way hashes and required metadata stored. No reversible password storage. |
| JWT access token | Short-lived signed token with sub/session/roles/scope hints. Services validate issuer/audience/signature/expiry. |
| Refresh/session | Server-side session record + hashed/rotated refresh credential; revoke on logout, compromise, admin action or policy event. |
| OTP | Hash only, short TTL, attempt cap, rate limit by contact/principal/IP/device-risk context, single-use challenge semantics where applicable. |
| Password reset | Short-lived, single-use and invalidated after completion; sensitive result never disclosed through logs. |
| Privileged MFA | Mandatory Security Design Decision for production Platform Owner/Platform Staff privileged access. |
| Enumeration resistance | Login/OTP/reset responses avoid disclosing whether a PAN/email/mobile/account exists beyond necessary business flows. |
| Session evidence | Security events retain safe metadata such as session ID, time, actor, IP/device risk metadata where appropriate; no raw tokens. |

## **6.2 Service Authentication**

- Internal calls use workload/service identity; public headers such as X-Tenant-Id are never trusted as identity.
- Service credentials are environment-scoped and rotated through secret-management procedures.
- Internal authorization still checks the calling service/command scope; network reachability alone is not permission.
- Provider-specific authentication is isolated behind adapters; provider SDK/token details do not leak into domain logic.

## **6.3 Privileged and Break-Glass Access**

- Privileged platform roles use separate admin routes and permissions; tenant_id=NULL is never interpreted as administrator status.
- Break-glass access is reserved for operational emergencies, requires strong authentication, explicit reason/ticket, short duration and post-event review.
- Database/cluster break-glass roles must not be used by application workloads and should be disabled or highly restricted outside an incident.
- All privileged changes affecting security/data boundaries are auditable and must be reconciled to source-controlled configuration when applicable.

# **7. Authorization, Tenant Isolation and Privileged Access**

## **7.1 Authorization Decision**

| authorize(command) =
    authenticated_principal
AND role_allows(command)
AND principal_assigned_to_tenant_store
AND resource_belongs_to_scope
AND entitlement_allows(command)
AND lifecycle_state_allows(command)
AND no_blocking_risk_or_compliance_restriction |
| --- |

A JWT role claim is an authorization hint, not sufficient proof for mutable high-value state. Sensitive commands re-check current assignment, ownership, entitlement and restriction state.

## **7.2 Tenant Isolation Layers**

| Layer | Required control | Failure contained |
| --- | --- | --- |
| API route / command | Authenticated actor + store/tenant ownership/assignment checks | Blocks IDOR and cross-store command misuse. |
| Application repository | Scoped query/repository interface; no foreign service repository imports | Reduces accidental unscoped access. |
| PostgreSQL RLS | Trusted SET LOCAL app.tenant_id/store_id/actor_id + USING/WITH CHECK policies where implemented | Stops cross-tenant reads/writes even if a predicate is omitted. |
| DB role/schema | Service runtime role writes only service-owned schema; no cross-service writes | Contains service compromise and architectural bypass. |
| NetworkPolicy | Only authorized workloads can reach sensitive data/service endpoints | Contains lateral movement. |
| Audit/detection | Denied scope attempts and privileged actions produce security evidence | Supports detection and incident response. |

## **7.3 Role Separation**

- GUARDIAN consent authority does not automatically confer store-management authority.
- CUSTOMER identity is store-scoped and cannot enumerate or access another store customer/order/booking.
- STORE_STAFF receives only assigned store capability; STORE_OWNER manages its own tenant/store scope, not platform administration.
- PLATFORM_STAFF/OWNER roles are distinct from tenant roles and require elevated checks/audit.
- SERVICE principals are machine identities limited to explicit internal commands/events and cannot masquerade as human owners.

# **8. API and Application Security**

| Area | Required security behavior |
| --- | --- |
| Input validation | Pydantic/OpenAPI schemas reject invalid types/ranges and unknown sensitive write fields by default. Domain validation remains server-side. |
| Object authorization | Every resource UUID is resolved within trusted tenant/store/actor context; UUID knowledge never implies permission. |
| State transitions | State-changing operations use explicit action commands; generic public status PATCH is prohibited. |
| Idempotency | Retry-sensitive POST commands use Idempotency-Key + request hash. Same key/different material input -> IDEMPOTENCY_CONFLICT. |
| Optimistic concurrency | If-Match/expected_version prevents stale overwrite for conflict-prone mutations. |
| Error handling | Stable error codes; no SQL/provider/secret stack details returned to clients. |
| Rate limiting | OTP/auth/public write endpoints and abuse-prone actions have rate/attempt controls; WAF is supplemental. |
| Injection defense | SQLAlchemy parameterization; no raw client-driven SQL identifiers; provider/content fields are validated/escaped at use boundary. |
| CORS/CSRF | Browser policy is limited to approved origins; if cookie-based state is introduced, CSRF protections are mandatory. Bearer-token clients must not rely on permissive cross-origin defaults. |
| Response minimization | Responses return masked identifiers and only fields needed for actor/use case; public endpoints expose approved/live projections only. |
| File upload | Upload intent authorizes store/item/media type/size; objects remain private pending validation/approval. |
| API documentation | Production interactive docs are access-controlled or disabled for privileged/internal surfaces according to deployment policy. |

## **8.1 Sensitive API Classes**

- Authentication/session and OTP endpoints.
- Tenant PAN/GSTIN/Guardian onboarding and reverification.
- Subscription activation/upgrade/reactivation and finance payment recording.
- Order/booking cancellation/refund/reschedule and inventory reservation.
- Payment/provider connection management and webhook reconciliation.
- GST draft approval/filing, risk restrictions and tenant termination.
- Platform role assignment, emergency takedown and privileged operational controls.

# **9. External Provider and Webhook Security**

## **9.1 Webhook Acceptance Pattern**

| receive raw body + headers
  -> resolve provider/account context server-side
  -> verify signature/auth proof over required raw representation
  -> calculate provider event key / fallback canonical hash
  -> persist raw callback + validation result + received_at
  -> dedupe/replay check
  -> validate amount/account/source mapping and state monotonicity
  -> commit normalized state + outbox fact atomically
  -> return 2xx after durable acceptance |
| --- |

| Threat | Control |
| --- | --- |
| Forged callback | Adapter-specific signature/token/auth validation; reject and security-log failures. |
| Replay / duplicate callback | Provider event ID/hash + unique business keys; repeat returns success without repeating effect. |
| Out-of-order callback | State/effective-time monotonicity checks; stale regression ignored/parked/audited. |
| Wrong tenant/provider account mapping | Resolve provider connection server-side and validate account/source/amount against immutable intent/snapshot. |
| Browser redirect spoof | Browser success/return route never marks payment confirmed; authoritative provider evidence required. |
| Webhook flood | Rate/queue/backpressure controls; fast validate-persist-enqueue handler; downstream processing asynchronous. |
| Sensitive raw payload leakage | Restricted raw-event store; never log payload verbatim; retention/access reviewed. |
| Provider outage/missed callback | Reconciliation jobs query authoritative provider state and repair through idempotent commands rather than history rewrite. |

# **10. PostgreSQL and Data-Layer Security**

| Control plane | Required control |
| --- | --- |
| Service ownership | One schema per logical service. Runtime role writes only its schema; cross-service DB writes prohibited. |
| RLS | Selected sensitive tenant/store tables use ENABLE ROW LEVEL SECURITY with trusted transaction-local tenant/store context and WITH CHECK. |
| Connection identity | Application credentials are service/environment scoped; database superuser is never used by application runtime. |
| Transactions | Business mutation, history/audit and outbox commit atomically; no hidden autocommit for material writes. |
| Sensitive identifiers | Encrypted display value + normalized/fingerprint representation only where uniqueness/search requires it. |
| Money/history | No binary float for money; immutable transaction snapshots and append-only ledger/history for material evidence. |
| Migrations | Dedicated migration identity/job; runtime role cannot ALTER schema; expand/backfill/switch/contract and lock-impact review. |
| Backups | Daily PostgreSQL backup with 15-day initial retention; restore tests required. Backup storage access is restricted and encrypted according to platform capabilities. |
| Audit/admin access | Direct privileged DB access is exceptional, attributable and reviewed; manual corrections use controlled domain/reconciliation procedures where possible. |

## **10.1 RLS Security Pattern**

| BEGIN;
SET LOCAL app.tenant_id = '<trusted-tenant-uuid>';
SET LOCAL app.store_id  = '<trusted-store-uuid>';
SET LOCAL app.actor_id  = '<trusted-principal-uuid>';
-- queries execute under RLS
COMMIT;

Policy concept:
USING (tenant_id = current_setting('app.tenant_id', true)::uuid
   AND store_id  = current_setting('app.store_id', true)::uuid)
WITH CHECK (same trusted scope) |
| --- |

| Critical rule - Public/user-supplied tenant/store identifiers are never copied blindly into SET LOCAL context. Scope is derived from authenticated assignment/ownership validation. |
| --- |

# **11. Kafka, Event and Asynchronous Processing Security**

| Concern | Security rule |
| --- | --- |
| Broker access | Kafka is private; TLS/authentication follows selected platform; credentials scoped per environment/workload where feasible. |
| Topic ACL | Producer/consumer permissions limited to required topic families and consumer groups; no wildcard access by default. |
| Event authenticity | Only owning service/workload publishes authoritative domain facts. Consumers validate event_type/version/schema and expected producer/context. |
| Sensitive payload | No secrets, OTPs, raw PAN/GSTIN, payment credentials or unnecessary PII in event payloads. |
| Delivery semantics | At-least-once assumed; outbox event_id stable across retries; inbox/processed_event suppresses duplicates. |
| Financial idempotency | Unique business keys prevent duplicate charge/commission/refund effects even if transport identifiers differ. |
| Poison messages | Bounded retry then DLQ with original metadata; operations alert and controlled replay. |
| Ordering | Partition by aggregate/store where needed; stale/out-of-order events cannot regress state. |
| Scheduler security | Kafka is not a timer. Durable scheduled jobs use database claim/idempotency and least-privilege workers. |
| Replay tooling | Operational replay requires privileged access, documented reason and reconciliation checks; replay must remain idempotent. |

# **12. Object Storage, Media and Digital Fulfilment Security**

- Buckets/objects are private by default; application issues time-bound signed upload/download access.
- Permanent public object URLs for digital products are prohibited.
- Digital entitlements enforce initial 24-hour link validity and audited download-count policy from the business specification; reissue is an explicit controlled action.
- Upload intents validate actor/store/item/media entitlement, expected content type/size and object key prefix; client cannot choose arbitrary bucket/key outside assigned prefix.
- Media used publicly must still pass the normal content approval/governance flow where controlled content rules apply.
- Malware/content scanning is recommended for relevant uploaded content before public/digital delivery, with quarantine on failed/unknown scans.
- Signed URLs must not expose provider credentials and should avoid sensitive identifiers in object names/query metadata.
- Download and entitlement events retain enough audit evidence to investigate abuse without logging signed URLs or secrets.

# **13. Kubernetes, Network and Runtime Security**

## **13.1 Namespace and Network Controls**

| Control | Production baseline |
| --- | --- |
| Ingress exposure | Only required public API/storefront Services are exposed through ingress/WAF. Internal services are ClusterIP-only. |
| Default deny | Production namespaces use default-deny ingress/egress NetworkPolicy; explicit dependency flows are allow-listed. |
| Data services | PostgreSQL/Kafka/Redis have no public endpoints; only approved workload selectors/identities can connect. |
| ServiceAccount | Dedicated ServiceAccount per workload/service class; automounted tokens disabled where not required. |
| RBAC | Least privilege; no application cluster-admin. Namespace/resource access limited to operational need. |
| Pod security | runAsNonRoot, allowPrivilegeEscalation=false, drop ALL capabilities, readOnlyRootFilesystem where feasible, explicit writable mounts only. |
| Image | Immutable digest/SHA promotion, minimal runtime image, scan gate, locked dependencies. |
| Secrets | Injected at runtime; not baked into image, ConfigMap or Git. Secret read scope limited to workload. |
| Admin access | Human cluster access through separately controlled operational identities with MFA/provider controls and audit. |
| Egress | Provider/API egress constrained by platform/network capabilities; unnecessary internet egress is denied. |

## **13.2 Runtime Hardening**

- API pods, Kafka consumers, schedulers and migration jobs are separate workloads/identities where practical.
- Application pods never manage PostgreSQL/Kafka lifecycle.
- Health endpoints reveal only operational readiness and do not leak dependency credentials, tenant data or stack detail.
- Production resource requests/limits reduce noisy-neighbor/DoS blast radius and are tuned from staging evidence.
- NetworkPolicy is defense-in-depth and never substitutes for JWT/workload identity, authorization or RLS.

# **14. Secrets, Keys and Cryptographic Material**

| Secret/key type | Storage / lifecycle rule |
| --- | --- |
| JWT signing material | IAM-owned; private signing key in secret manager/Kubernetes Secret reference; verification material distributed safely. Rotation supports overlap/key IDs where implementation permits. |
| DB credentials | Environment/service scoped; application role only; rotate without source changes. |
| Kafka credentials | Environment/workload scoped; topic permissions least privilege. |
| Provider API credentials | Environment and tenant/provider connection scoped where applicable; encrypted/secret-managed; never logged. |
| Webhook signing secrets | Environment/provider scoped; rotation with overlap when provider supports it; signature failures monitored. |
| Object-storage credentials | Workload scoped; prefer workload identity/short-lived credentials where platform supports it. |
| TLS certificates | Automated/managed rotation preferred; expiry monitored; private keys restricted. |
| Break-glass/admin credentials | Separately controlled, MFA-protected and audited; not shared with workloads. |

## **14.1 Cryptographic Usage Rules**

- Use modern platform-supported TLS for data in transit; insecure cleartext external protocols are prohibited.
- Use one-way hashes for passwords, OTPs and refresh-token lookup/storage where reversible plaintext is unnecessary.
- Use encryption for values that must be recovered/displayed (for example sensitive identifiers), while fingerprints/hashes support uniqueness/search.
- Key material must never be copied into logs, metrics, traces, support tickets or analytics payloads.
- Cryptographic algorithms/parameters are implementation security configuration and should be reviewed periodically rather than embedded as business policy.

# **15. CI/CD, Dependency and Software Supply-Chain Security**

| Stage | Required security gate |
| --- | --- |
| Source control | Protected main, CODEOWNERS, PR review; no direct production patches outside version control except documented break-glass reconciliation. |
| Secrets | Pre-commit/CI secret scanning; leaked credentials are revoked/rotated and history exposure assessed. |
| Dependencies | Pinned lockfile; vulnerability scan; controlled update PR; framework major upgrades require regression/security review. |
| Static analysis | Lint/type/import-boundary plus SAST/security rules as configured; suppressions narrow and documented. |
| Contracts | OpenAPI/AsyncAPI/JSON Schema validation prevents unreviewed interface expansion or unsafe payload drift. |
| Containers | Minimal image, non-root, vulnerability scan, immutable digest. SBOM/provenance recommended and may become mandatory. |
| Migrations | Fresh DB + previous-revision upgrade tests; migration privileges separated from runtime; backup/lock impact documented. |
| Staging | Security/resilience tests, provider sandboxes, network-policy verification, restore/release rehearsal. |
| Production | Promote the tested artifact digest rather than rebuild; migration gate; health/reconciliation checks; rollback/roll-forward plan. |

# **16. Logging, Audit, Detection and Security Observability**

## **16.1 Operational Logs vs Audit Evidence**

Operational logs are diagnostic and may rotate. Audit/state-history records are business/security evidence and are append-only according to the owning schema. A log line is not a substitute for a required audit row.

| Signal | Minimum safe fields / rule |
| --- | --- |
| HTTP/application logs | timestamp, service, environment, request_id, correlation_id, route template, result/error code, safe actor/tenant/store UUID context; no secrets/sensitive identifier plaintext. |
| Kafka processing | event_id, event_type, topic/partition/offset, consumer group, correlation_id, processing result/retry/DLQ metadata. |
| Security audit | actor/service, role, tenant/store, command, resource, old/new/reference version, timestamp, reason/source where applicable, correlation ID. |
| Authentication security | login/OTP/session/security event category, safe source/risk metadata and outcome; no password/OTP/token. |
| Provider webhook evidence | provider event key, validation outcome, mapped aggregate/account context, received_at; raw payload stored separately under restricted retention. |
| Kubernetes/security | RBAC denials, WAF attack spikes, NetworkPolicy-denied anomalies where observable, image/secret scan findings, privileged administrative actions. |

## **16.2 Alert Classes**

- Repeated authentication/OTP abuse, privileged login anomalies and session revocation spikes.
- Cross-tenant/IDOR/RLS denial anomalies or unexpected access to sensitive endpoints.
- Webhook signature failures, replay spikes, missing callbacks and reconciliation mismatches.
- Kafka DLQ growth, repeated consumer failures, unauthorized broker access or unusual topic traffic.
- Outbox backlog, duplicate-financial-effect guard violations, scheduler duplicate-claim anomalies.
- Secret leak findings, image vulnerability gate failures and unexpected privileged Kubernetes changes.
- Database backup/restore failure, database failover anomalies and access by unexpected roles.

# **17. Privacy, Retention and Data-Minimization Controls**

| Data / activity | Security/privacy treatment |
| --- | --- |
| Customer profile | Store-scoped; collect mandatory/needed data only; deletion/anonymization requests may remove deletable fields but preserve legally required transaction evidence. |
| Guardian data | Collect required minimum; government ID encrypted/restricted; consent history retained as required by product baseline. |
| Commercial records | Orders/invoices/GST/commission/subscription/advance/setup/audit retained/archived; seller cannot destructively delete historical transactions. |
| Soft-deleted content | Recoverable initially for 60 days unless statutory/security/financial retention overrides. |
| Provider webhooks | Retain raw verified callback for configured reconciliation/audit period with access restriction and redaction in operational logs. |
| Analytics | Separate retention/aggregation policy; do not automatically inherit full transactional PII. |
| Backups | Retention and access follow backup policy; deletion/anonymization workflows account for backup restoration/reconciliation procedures. |
| Logs/traces | Shorter operational retention as practical; strict redaction and access; never used as uncontrolled PII archive. |

# **18. AI Feature Security Boundaries**

- Scale AI features operate under entitlement/quota and return drafts/recommendations, not autonomous financial or tax mutations.
- AI output cannot directly change price, inventory, subscription charge, financial ledger, GST return or payment state.
- AI-generated public content follows the ordinary controlled-content approval workflow before LIVE publication.
- Prompt/user content is untrusted input. AI tools must not be given provider secrets, raw credentials or unrestricted cross-tenant context.
- Retrieval/context supplied to an AI feature is scoped to the authorized tenant/store and minimized for the requested use case.
- AI usage/output logs follow the same sensitive-data redaction and retention rules as other telemetry.
- Provider/model changes require security/privacy review of data handling and contractual exposure before production use.

# **19. Abuse, Fraud and Availability Protection**

| Abuse case | Control family |
| --- | --- |
| Credential stuffing / password spraying | WAF/rate controls, authentication throttling, MFA for privileged users, security-event monitoring. |
| OTP abuse / SMS-email bombing | Per-contact/principal/IP/device rate limits, challenge TTL/attempt caps, dedupe/cooldown. |
| Account/resource enumeration | Uniform error behavior where possible; authorization before detailed disclosure; request throttling. |
| Checkout/order spam | Store entitlement/restriction checks, rate limiting, idempotency, inventory reservation TTL and abuse monitoring. |
| Booking capacity exhaustion | Rate controls, atomic capacity reservation, payment/approval deadlines and expiry workers. |
| Webhook flood | Fast durable handler, provider authentication, dedupe, queue/backpressure and alerts. |
| Kafka/worker backlog DoS | Consumer lag monitoring, bounded retries, DLQ, autoscaling where justified and workload resource limits. |
| Large upload abuse | Size/type/quota/entitlement validation, signed upload intents, private storage, scanning/quarantine. |
| Admin abuse | Least privileged roles, MFA, reason/evidence requirements for material actions, append-only audit, periodic access review. |
| Tenant fraud / policy evasion | Risk/compliance cases, restrictions, immutable transaction/provider evidence and reconciliation; security model does not silently reinterpret business rules. |

# **20. Security Incident Response and Containment**

## **20.1 Incident Lifecycle**

**1. **Detect and classify: identify affected environment, tenant/store, credentials, services, data classes and whether financial/identity integrity is at risk.

**2. **Contain: revoke/rotate credentials, terminate sessions, restrict ingress/egress, suspend compromised workload/account or enable documented risk restriction where authorized.

**3. **Preserve evidence: retain relevant audit, webhook, Kafka, DB and deployment evidence; avoid destructive cleanup before evidence is secured.

**4. **Eradicate and remediate: patch code/config, replace artifacts/secrets, correct state through controlled idempotent commands/compensating records.

**5. **Recover: redeploy approved artifacts, validate DB/event consistency, reconcile providers, restore service, monitor for recurrence.

**6. **Review: document root cause, affected scope, control failure, corrective action, regression/security tests and required disclosure/escalation process.

## **20.2 Security Runbooks Required**

- Privileged account/session compromise.
- Provider credential or webhook-secret compromise.
- Cross-tenant access or suspected RLS/authorization bypass.
- Leaked PAN/GSTIN/Guardian/customer data.
- Malicious/compromised container image or CI credential.
- Unauthorized Kubernetes/DB access.
- Webhook/Kafka replay causing potential duplicate financial effects.
- Object-storage exposure or leaked digital download links.
- Denial-of-service / WAF abuse spike.
- Database backup/restore security incident.

# **21. Threat-Modelling Method and Risk Scoring**

## **21.1 STRIDE Categories**

| Category | Meaning in KarobarOne |
| --- | --- |
| S - Spoofing | Impersonating a customer, tenant, admin, service or provider callback. |
| T - Tampering | Unauthorized modification of state, events, financial history, content, configs or artifacts. |
| R - Repudiation | Actor denies material action because evidence/attribution is missing or alterable. |
| I - Information Disclosure | Exposure of PII, PAN/GSTIN/Guardian IDs, secrets, cross-tenant data or private media. |
| D - Denial of Service | Exhausting API, database, inventory/booking capacity, Kafka, workers or provider-facing resources. |
| E - Elevation of Privilege | Gaining tenant/admin/service privileges beyond assigned role/scope. |

## **21.2 Risk Score**

Security Design Decision: each threat is scored using Likelihood (1-5) x Impact (1-5). Inherent risk is the pre-control score; residual risk is reassessed after mandatory controls. The scoring system prioritizes engineering effort and does not replace incident severity or legal impact assessment.

| Score | Rating | Treatment expectation |
| --- | --- | --- |
| 20-25 | Critical | Must be mitigated before production or explicitly accepted by authorized leadership/security with documented rationale; tenant isolation/fund-integrity Critical risk is normally non-acceptable. |
| 12-19 | High | Mitigation and verification required before production unless exceptional written risk acceptance. |
| 6-11 | Medium | Mitigate through normal delivery plan; track owner/test and monitor residual exposure. |
| 1-5 | Low | Accept or mitigate proportionately; retain documentation and monitor if conditions change. |

## **21.3 Impact Dimensions**

- Confidentiality: exposure of sensitive tenant/customer/government/provider data.
- Integrity: incorrect identity, payment, inventory, booking, commission, GST, subscription or audit state.
- Availability: loss of storefront/commerce/administrative service against the 99.5% initial availability target.
- Isolation: cross-tenant/store data/action exposure is treated as severe even if the dataset is small.
- Financial/compliance evidence: corruption or unauditable change to commercial, tax or consent history carries elevated impact.

# **22. Threat Register - STRIDE Analysis**

The table below identifies credible application/platform threats and the mandatory treatment. Scores are initial engineering assessments and should be updated after implementation testing, provider selection and penetration testing.

| ID | S | Threat scenario | Inherent | Mandatory controls | Residual |
| --- | --- | --- | --- | --- | --- |
| TM-001 | S | Credential stuffing against tenant/customer login | 4x4=16 High | Rate limits/WAF, strong hashes, session telemetry; privileged MFA. | 8 Medium |
| TM-002 | S | Stolen/replayed refresh credential | 3x5=15 High | Hash+rotation+server session/revocation; short access token; logout/compromise revoke. | 6 Medium |
| TM-003 | S | OTP brute force/replay or challenge abuse | 4x3=12 High | OTP hash, TTL, attempt/rate limits, single-use, cooldown and monitoring. | 4 Low |
| TM-004 | E | Tenant user escalates to store/admin role | 3x5=15 High | Server-side role assignment, scope checks, no tenant_id-null shortcut, admin MFA/audit. | 5 Low |
| TM-005 | E | Guardian role used for operational store control | 3x4=12 High | Separate Guardian authority from store roles; explicit assignment needed; regression tests. | 4 Low |
| TM-006 | I/E | IDOR exposes another tenant/store resource | 4x5=20 Critical | Ownership/assignment checks, RLS defense-in-depth, UUID not authority, negative tests. | 5 Low |
| TM-007 | I/T | Unscoped repository query leaks/mutates cross-tenant data | 3x5=15 High | RLS USING/WITH CHECK + transaction-local trusted scope + scoped repositories. | 5 Low |
| TM-008 | E/T | Public client forges tenant/store context header | 4x5=20 Critical | Derive scope from authenticated server context; never trust public X-Tenant/Store headers. | 4 Low |
| TM-009 | T | Generic status mutation bypasses state machine | 3x5=15 High | Explicit command endpoints only; typed state guards; no arbitrary status PATCH. | 5 Low |
| TM-010 | T | Retry duplicates order/booking/refund/subscription action | 4x5=20 Critical | Idempotency-Key+request hash; unique business keys; optimistic concurrency. | 5 Low |
| TM-011 | T/S | Forged Razorpay/payment-provider callback | 4x5=20 Critical | Raw-body signature verification, account/source/amount validation, restricted endpoint. | 4 Low |
| TM-012 | T | Duplicate/replayed payment webhook creates duplicate financial effects | 4x5=20 Critical | Provider-event dedupe + inbox/business-key idempotency + append-only evidence. | 4 Low |
| TM-013 | T | Browser redirect falsely marks payment successful | 3x5=15 High | Redirect non-authoritative; only verified provider webhook/API evidence can confirm. | 3 Low |
| TM-014 | T | Out-of-order provider event regresses state | 3x4=12 High | Monotonic state/effective-time checks; park/ignore stale event; reconciliation. | 4 Low |
| TM-015 | S/T | Forged Shiprocket/logistics delivery triggers COD commission | 3x5=15 High | Provider authenticity + shipment mapping + authoritative delivery event + dedupe. | 4 Low |
| TM-016 | I | PAN/GSTIN/Guardian ID appears in logs/events | 3x5=15 High | Redaction, event payload prohibition, encryption/fingerprint, automated log tests. | 5 Low |
| TM-017 | I | Provider secret leaked through config/image/repo | 3x5=15 High | Secret manager/K8s Secret refs, CI secret scan, no baked secrets, rotation runbook. | 5 Low |
| TM-018 | T/E | Compromised service writes another service schema | 2x5=10 Medium | Schema-scoped runtime DB roles; no cross-schema writes/FKs; NetworkPolicy. | 4 Low |
| TM-019 | E/I | Database superuser used by application | 2x5=10 Medium | Dedicated least-privilege runtime roles; superuser operational only; access audit. | 3 Low |
| TM-020 | I | Backup snapshot/object store exposed | 2x5=10 Medium | Private encrypted storage/access controls, restricted backup credentials, restore/audit process. | 4 Low |
| TM-021 | T/R | Financial ledger/history manually rewritten | 2x5=10 Medium | Append-only/compensating records; runtime restrictions; controlled admin/reconciliation; audit. | 3 Low |
| TM-022 | T | Kafka duplicate event creates duplicate side effect | 4x5=20 Critical | Inbox/processed_events in same transaction; financial business-key uniqueness. | 4 Low |
| TM-023 | S/T | Unauthorized producer injects authoritative event | 3x5=15 High | Private broker auth/TLS, topic ACLs, expected producer/type/schema checks. | 5 Low |
| TM-024 | I | Sensitive PII/secrets published to Kafka | 3x4=12 High | Contract/schema review; payload minimization; no secrets/raw identifiers; security tests. | 4 Low |
| TM-025 | D | Poison event causes infinite retry / consumer outage | 3x3=9 Medium | Bounded retry, DLQ, alerts, controlled replay and idempotency. | 3 Low |
| TM-026 | D/T | Scheduler race duplicates subscription charge/transition | 3x5=15 High | DB claim SKIP LOCKED + unique business key/idempotent transitions + concurrency tests. | 4 Low |
| TM-027 | I | Private media/digital object becomes publicly accessible | 3x4=12 High | Private bucket, signed URLs, no permanent public URLs, access audit. | 4 Low |
| TM-028 | I/D | Signed digital link shared/reused beyond policy | 4x3=12 High | Short expiry, entitlement/download limits, explicit reissue, download audit. | 6 Medium |
| TM-029 | T/D | Malicious file upload served to users/operators | 3x4=12 High | Type/size validation, private staging, malware/content scanning/quarantine where appropriate. | 5 Low |
| TM-030 | E | Kubernetes ServiceAccount/RBAC overly broad | 3x5=15 High | Dedicated SA, least RBAC, no app cluster-admin, manifest policy/test review. | 5 Low |
| TM-031 | E/I | Privileged/host-capable container facilitates breakout/lateral movement | 2x5=10 Medium | Non-root, no privilege escalation, drop caps, read-only FS, minimal images, NetworkPolicy. | 4 Low |
| TM-032 | I/D | PostgreSQL/Kafka/Redis exposed publicly | 2x5=10 Medium | Private services/endpoints, firewall/security groups, NetworkPolicy; readiness tests. | 2 Low |
| TM-033 | T/E | Compromised dependency/container enters release | 3x5=15 High | Lockfile, reviews, vulnerability/SAST/image scan, immutable artifact promotion, SBOM/provenance. | 6 Medium |
| TM-034 | T/E | CI credential compromised to deploy malicious artifact | 2x5=10 Medium | Least CI identity, protected environments/approvals, immutable digest, secret rotation/audit. | 5 Low |
| TM-035 | R/T | Privileged admin action lacks attributable audit | 3x4=12 High | Material commands audit actor/role/reason/resource/version/correlation; append-only audit. | 4 Low |
| TM-036 | I | Operational trace/error exposes secret or PII | 3x4=12 High | Structured logging/redaction, safe error envelope, log-security tests and restricted telemetry access. | 4 Low |
| TM-037 | D | Credential/OTP/API bot flood exhausts service/provider quotas | 4x3=12 High | WAF/rate limits/cooldowns/quotas/resource limits/alerts; fail safe. | 6 Medium |
| TM-038 | D | Webhook flood or provider callback storm overwhelms API | 3x4=12 High | Fast durable acceptance, dedupe, backpressure/queue, resource limits/autoscaling/alerts. | 5 Low |
| TM-039 | D | Kafka lag/outbox backlog delays security/commercial transitions | 3x4=12 High | Lag/outbox alerts, consumer scaling, retry/DLQ, reconciliation and operational runbook. | 5 Low |
| TM-040 | E/I | AI prompt/context causes cross-tenant data disclosure | 3x5=15 High | Tenant-scoped retrieval/context, minimized data, provider review, no secrets, security tests. | 5 Low |
| TM-041 | T | AI output directly changes financial/tax/inventory state | 2x5=10 Medium | Architectural prohibition: AI returns draft/recommendation only; normal commands/approval required. | 2 Low |
| TM-042 | T | Malicious AI-generated public content bypasses approval | 3x3=9 Medium | AI public content follows ordinary content approval/versioning before LIVE. | 3 Low |
| TM-043 | I | Privacy deletion accidentally destroys required commercial evidence | 2x5=10 Medium | Anonymize deletable profile fields; preserve statutory/commercial history and referential audit. | 3 Low |
| TM-044 | T/I | Production secrets/data copied into local/dev | 3x4=12 High | Environment separation, synthetic test data, secret policy, access controls, CI checks. | 4 Low |
| TM-045 | E/T | Emergency break-glass change persists outside source control | 2x4=8 Medium | Reason/time-bound access, audit, post-incident review and mandatory source reconciliation. | 3 Low |

# **23. High-Risk Business Flow Abuse Cases**

| Flow | Abuse objective | Security treatment |
| --- | --- | --- |
| Tenant registration | Reuse another PAN / enumerate registrations / bypass Guardian | PAN verification + fingerprint uniqueness; masked responses; Guardian branch; rate/abuse controls; immutable consent evidence. |
| Paid activation | Use GSTIN belonging to another PAN / reuse GSTIN on second paid store | Verified PAN-GSTIN ownership; unique binding; quote/activation guards; audit. |
| Content publication | Publish draft/rejected/prohibited content directly | Immutable versions; approval service; public projection only LIVE; emergency takedown audit. |
| Product checkout | Cross-store or mixed product/service checkout; oversell final stock | Store/cart invariant; item-type rules; entitlement/restriction checks; atomic reservation and concurrency tests. |
| Online payment | Spoof browser success or webhook; wrong provider account | Provider connection resolved server-side; signature + amount/source match; webhook authoritative; dedupe/reconciliation. |
| COD | Mark delivery without logistics evidence to trigger commission | Approved provider only; provider-authenticated delivery/COD fact; immutable shipment mapping. |
| Booking | Double-book final capacity; manipulate reschedule to avoid commission | Atomic capacity reservation; expected_version; new slot reserved before old released; commission reversal/new record rules. |
| Refund | Duplicate/refund more than remaining amount; rewrite payment history | Remaining-refundable guard; idempotency; provider/manual evidence; compensating refund/credit records. |
| Commission | Avoid invoice/payment or tamper rate/base | Rate/base snapshotted at transaction; append-only commission states/ledger; pay-first dispute/credit-later; unique invoice lines. |
| Subscription | Manipulate clock/period boundary or duplicate scheduler charge | UTC deterministic time; persisted period snapshots; scheduler unique business keys; boundary tests. |
| GST filing | File different draft than tenant approved | Immutable draft_version_id/tax period/approver/timestamp; filing blocked until exact draft approved. |
| Risk/admin | Use admin endpoint with tenant role; suppress audit | Separate privileged routes/roles + MFA; server-side checks; material action audit; no tenant_id=NULL shortcut. |

# **24. Security Verification and Test Matrix**

| ID | Scenario | Action | Expected |
| --- | --- | --- | --- |
| SEC-TST-001 | Cross-tenant API IDOR | Tenant A user requests Tenant B resource UUID | Denied/not found; no data leakage. |
| SEC-TST-002 | RLS cross-tenant read | Query under Tenant A context without tenant predicate | Tenant B rows remain inaccessible. |
| SEC-TST-003 | RLS cross-tenant write | Tenant A context updates Tenant B row | Denied/zero affected; no mutation. |
| SEC-TST-004 | Role-only bypass | Actor has role but lacks entitlement/restriction allows no commerce | Command fails closed. |
| SEC-TST-005 | Guardian privilege separation | Guardian consent identity calls store-management endpoint | Denied absent explicit operational role. |
| SEC-TST-006 | Expired/revoked JWT/session | Use expired/revoked access/session material | Authentication denied; no business mutation. |
| SEC-TST-007 | Refresh replay | Replay rotated/revoked refresh credential | Denied and security event generated as designed. |
| SEC-TST-008 | OTP abuse | Expired/wrong/replayed/high-attempt challenge | Rejected; rate/attempt state enforced. |
| SEC-TST-009 | Idempotency replay | Same key/same request then same key/different request | Same result/no duplicate; conflicting payload -> 409. |
| SEC-TST-010 | Generic status mutation | Attempt arbitrary status PATCH/state rewind | No supported endpoint / stable invalid transition. |
| SEC-TST-011 | Webhook invalid signature | Send fake Razorpay/Shiprocket callback | 4xx/rejected; no state mutation; security evidence. |
| SEC-TST-012 | Webhook duplicate | Replay valid callback | Single state/financial side effect. |
| SEC-TST-013 | Webhook out-of-order | Send older status after later authoritative status | No state regression; audited/parked. |
| SEC-TST-014 | Browser redirect authority | Call success redirect without provider evidence | Payment remains unconfirmed. |
| SEC-TST-015 | Kafka duplicate | Redeliver same event_id | Inbox suppresses duplicate side effect. |
| SEC-TST-016 | Kafka forged/invalid schema | Produce unsupported event type/schema to consumer test harness | Rejected/parked/DLQ; no unsafe side effect. |
| SEC-TST-017 | Financial duplicate key | Equivalent financial event with different transport attempt | Unique business key prevents duplicate charge/commission/refund. |
| SEC-TST-018 | Sensitive log redaction | Exercise PAN/GSTIN/OTP/provider errors | No prohibited plaintext in logs/traces/errors. |
| SEC-TST-019 | Object privacy | Attempt unauthenticated direct access to private media/digital object | Denied; only signed authorized access succeeds. |
| SEC-TST-020 | Signed link expiry/download limit | Use link after expiry/limit or from invalid entitlement | Denied; audit preserved. |
| SEC-TST-021 | NetworkPolicy isolation | Unauthorized pod attempts DB/Kafka/Redis/internal API connectivity | Connection denied; authorized flow succeeds. |
| SEC-TST-022 | Pod security | Render/deploy manifest with privileged/root/capabilities violation | Policy/CI gate rejects or fails readiness review. |
| SEC-TST-023 | Secret scan | Commit fixture resembling production secret | CI secret gate fails; remediation workflow exercised. |
| SEC-TST-024 | Dependency/image vulnerability gate | Introduce known blocked-severity dependency/image finding | Promotion blocked per security policy. |
| SEC-TST-025 | Privileged admin MFA | Attempt production privileged login without MFA | Privileged access denied. |
| SEC-TST-026 | Audit completeness | Execute material admin/commercial command | Audit row contains actor/scope/command/state/reference/time/reason/correlation as applicable. |
| SEC-TST-027 | Scheduler race | Two workers claim same due transition | Exactly one transition/charge. |
| SEC-TST-028 | Malicious upload | Upload disallowed type/size or scanning failure | Rejected/quarantined; not publicly served. |
| SEC-TST-029 | AI financial boundary | Prompt AI feature to modify price/ledger/GST/payment state | AI cannot perform direct mutation; only governed output returned. |
| SEC-TST-030 | AI tenant context | Tenant A AI request attempts to reference Tenant B data | No cross-tenant context or output disclosure. |

## **24.1 Existing Mandatory Engineering Tests Reused**

- FND-TST-001/002 API idempotency and idempotency conflict.
- FND-TST-003/004/005 transactional outbox, duplicate Kafka delivery and financial business-key dedupe.
- FND-TST-008/009/010 tenant RLS and IDOR isolation.
- FND-TST-011/012/013 authorization/state/concurrency protections.
- FND-TST-016/017/018/019 webhook duplicate/signature/replay/browser-authority tests.
- FND-TST-020/021 scheduler and commission-invoice duplicate protection.
- Full AC-001..AC-090 acceptance suite remains release blocking.

# **25. Security Release Gates and Production Readiness**

| Gate | Production requirement |
| --- | --- |
| Authentication | Privileged MFA enforced; session/refresh/OTP tests pass; no known auth bypass. |
| Tenant isolation | Cross-tenant API + RLS read/write negative suite passes. Any unresolved cross-tenant exposure is an S0/Critical release blocker. |
| Provider security | Webhook signature, replay, out-of-order and browser-non-authority tests pass; reconciliation path tested. |
| Financial integrity | Idempotency/outbox/inbox/business-key concurrency tests pass; no duplicate financial effect defects. |
| Secrets/PII | Secret scan clean within policy; prohibited PII/credentials absent from logs/events/fixtures. |
| Kubernetes | ServiceAccounts/RBAC/NetworkPolicy/pod security/ingress exposure validated; no public DB/Kafka/Redis. |
| Supply chain | Dependency/SAST/image scans meet severity policy; approved immutable artifact digest promoted. |
| Data protection | Private object storage/signed URL tests pass; backups protected and restore rehearsal completed. |
| Audit/detection | Material actions produce audit evidence; core security alerts/dashboards/runbooks active. |
| Contracts/acceptance | OpenAPI/AsyncAPI compatibility gates pass; full AC-001..AC-090 + engineering invariant suite passes. |
| Defects | No unresolved S0/S1. Critical/High security findings require remediation or authorized documented risk acceptance according to Section 21. |

# **26. Security Operations, Reviews and Change Management**

| Cadence / trigger | Required review |
| --- | --- |
| Every PR touching sensitive surface | CODEOWNERS + relevant security/DB/platform review; contract and tests updated. |
| Every production release | Security scan results, changed routes/events/migrations/network rules, secret/config changes and release evidence reviewed. |
| Privileged access change | Role/ServiceAccount/database permission rationale, least privilege and owner verified. |
| Provider integration/change | Auth/webhook/data handling, credential scope, callback verification and reconciliation threat review. |
| Major framework/dependency change | ADR + regression + threat/control re-evaluation. |
| New sensitive data field | Classification, encryption/masking, event/log exposure, retention and authorization review. |
| New public endpoint | Authn/authz/IDOR/rate limit/schema/error/logging/threat tests added. |
| Material incident | Post-incident threat model/control update and regression test added. |
| Periodic access review | Platform/admin/service/database/cluster privileges reviewed and stale access revoked. |
| Periodic restore/recovery review | Backup restore, provider reconciliation, event replay and security runbooks exercised. |

# **27. Open Security Decisions and Future Hardening**

| Decision | Status / required outcome |
| --- | --- |
| Final IAM token/session TTLs | Set secure production defaults during IAM implementation; remain configuration-controlled and tested. |
| MFA mechanism/provider | Select implementation for Platform Owner/Staff before production; recovery/break-glass must not weaken assurance. |
| External secret manager | Select cloud/platform mechanism; Kubernetes Secret alone may be development fallback, but production external management is preferred. |
| Kafka hosting/auth model | Select managed/operator platform, TLS/auth and topic ACL implementation while preserving contract/least privilege. |
| Internal mTLS | Not mandatory baseline for V1; evaluate when platform maturity/risk justifies service mesh or equivalent workload-to-workload encryption/auth. |
| WAF/rate policies | Tune from staging/production abuse patterns; do not encode business authorization into WAF rules. |
| Upload malware scanning | Choose scanner/workflow before accepting risky executable/document formats or broad public uploads. |
| SIEM/security analytics | Centralized logs/alerts exist baseline; dedicated SIEM can be added as operational maturity grows. |
| Key management/HSM | Use provider KMS/HSM where available/justified for high-value production key material; final cloud determines implementation. |
| Formal penetration test | Required before material public production or major high-risk release is strongly recommended; scope must include tenant isolation, admin, payments/webhooks, object storage and Kubernetes exposure. |
| Privacy/legal retention validation | Retention/minimization implementation must be reviewed with qualified legal/privacy advisers before production where statutory requirements apply. |

| Change-control rule - Security hardening may become stricter without BRD change so long as it does not alter promised commercial behavior or violate an approved business/state invariant. Any security control that materially changes user eligibility, funds handling, commission, GST, subscription behavior or legal responsibility requires business change control. |
| --- |

# **Appendix A - Role and Trust Matrix**

| Actor | Typical scope | Security requirements / prohibitions |
| --- | --- | --- |
| PUBLIC | Unauthenticated storefront | Read approved/live content only; selected checkout/bootstrap endpoints; strict validation/rate controls. |
| CUSTOMER | One store customer identity | Store-scoped data/orders/bookings; cannot infer access from UUID; claim via approved auth flow. |
| STORE_STAFF | Assigned store | Only assigned operational capabilities; entitlement/lifecycle/restriction still apply. |
| STORE_OWNER | Tenant-owned stores | Higher tenant/store management authority but no platform-admin authority. |
| GUARDIAN | Minor consent workflow | Consent/required identity actions only; not implicit store operator. |
| PLATFORM_STAFF | Authorized platform functions | Separate admin routes/permission; production MFA; full audit. |
| PLATFORM_OWNER | Highest platform administrative authority | Production MFA, least routine use, high-value actions audited/reasoned; break-glass separately controlled. |
| SERVICE PRINCIPAL | One or more internal workloads | Workload identity, explicit service/API/event/topic/secret/DB access; no human impersonation. |
| EXTERNAL PROVIDER | Signed/authenticated callbacks | Adapter-specific proof, dedupe/replay validation; no JWT tenant authority. |
| CI/CD IDENTITY | Build/deploy automation | Protected environment/repo scope; artifact promotion only; secrets least privilege and auditable. |

# **Appendix B - Data Classification Matrix**

| Data | Class | At rest | In logs/events | Exposure |
| --- | --- | --- | --- | --- |
| Passwords | Secret | One-way hash only | Never | Authentication verification only. |
| Refresh tokens | Secret | Hash/server session metadata | Never | Returned only when protocol requires; never persisted plaintext. |
| OTP | Secret | Hash + TTL/attempt state | Never | Challenge verification only. |
| JWT signing/provider secrets | Secret | Secret manager/K8s Secret reference | Never | Owning workload only. |
| PAN | Restricted PII/business ID | Encrypted + fingerprint/normalized as required | Never plaintext; safe opaque/masked references only | Authorized onboarding/compliance flows only. |
| GSTIN | Restricted business ID | Encrypted/masked/fingerprint where needed | No plaintext ordinary logs; masked event value only if contract requires | Authorized tenant/compliance flows. |
| Guardian government ID | Restricted identity | Encrypted | Never plaintext | Authorized Guardian/compliance workflow. |
| Customer email/mobile/address | Confidential PII | Tenant/store-scoped DB | Minimize/redact; events only as contract requires | Authorized customer/store use. |
| Order/payment/booking/commission/GST/subscription evidence | Confidential + integrity critical | Authoritative DB/ledger/history | Opaque IDs/amount facts only as required | Authorized actors/services; retained evidence. |
| Approved storefront content | Public | DB/projection/CDN | Safe | Public after approval. |
| Draft/rejected content | Confidential tenant content | Private DB/storage | No public event/body beyond safe IDs | Authorized owner/reviewer only. |
| Digital product files | Confidential entitlement content | Private object storage | Never URL/token in logs | Signed time-bound authorized link. |

# **Appendix C - Security Control Checklist**

☐ Privileged Platform Owner/Staff production access requires MFA.

☐ JWT issuer/audience/signature/expiry and server-side session revocation are validated.

☐ Password/OTP/refresh credentials are never stored plaintext.

☐ Every sensitive state-changing API enforces role + assignment + ownership + entitlement + lifecycle + restriction.

☐ No public/admin endpoint trusts a caller-supplied tenant/store UUID as authority.

☐ RLS context is derived from trusted authorization context and tested for cross-tenant read/write denial.

☐ Application DB roles cannot ALTER schema or write another service schema.

☐ PAN/GSTIN/Guardian government IDs are encrypted/fingerprinted/masked and absent from ordinary logs/events.

☐ Payment success is never based on browser redirect alone.

☐ Provider webhooks verify authenticity, dedupe/replay, retain restricted raw evidence and validate aggregate/account/amount mapping.

☐ Outbox/inbox and unique financial business keys prevent duplicate effects.

☐ Kafka is private; topic/workload access is least privilege; events contain no secrets/raw sensitive identifiers.

☐ Object storage is private; signed URL flows are time-bound; permanent public digital URLs are impossible.

☐ Kubernetes uses least ServiceAccounts/RBAC and default-deny NetworkPolicy in production.

☐ Containers run non-root, prohibit privilege escalation, drop capabilities and use read-only root where feasible.

☐ Secrets are externalized/environment-scoped and rotation runbooks exist.

☐ CI performs secret, dependency, SAST and container scans according to policy.

☐ Production promotes tested immutable image digests rather than rebuilding after staging approval.

☐ Material admin/commercial/security actions produce append-only audit evidence.

☐ Logs/traces/errors do not expose secrets, PAN/GSTIN/Guardian IDs, OTP or provider credentials.

☐ Security alerts and runbooks exist for auth abuse, cross-tenant attempts, webhook failures, secret leaks and data-plane anomalies.

☐ Full security/invariant tests and AC-001..AC-090 pass before production; no unresolved S0/S1 exists.

# **Appendix D - Threat-to-Test Traceability**

| Threat IDs | Verification | Control area |
| --- | --- | --- |
| TM-001..005 | SEC-TST-005..008, SEC-TST-025 | IAM/role/Guardian/privileged access |
| TM-006..009 | SEC-TST-001..004, SEC-TST-010 | Tenant isolation, RLS, role/state authorization |
| TM-010 | SEC-TST-009 + FND-TST-001/002 | API idempotency |
| TM-011..015 | SEC-TST-011..014 + FND-TST-016..019 | Provider/webhook/payment/logistics authority |
| TM-016..017 | SEC-TST-018, SEC-TST-023 | Sensitive logging/secrets |
| TM-018..021 | SEC-TST-002/003/026 + migration/DB suites | DB role, RLS, ledger/audit integrity |
| TM-022..026 | SEC-TST-015..017/027 + FND-TST-003..007/020/021 | Kafka/outbox/inbox/scheduler |
| TM-027..029 | SEC-TST-019/020/028 | Object storage/digital/upload security |
| TM-030..034 | SEC-TST-021..024 | Kubernetes/RBAC/supply chain |
| TM-035..039 | SEC-TST-026 + resilience/observability suites | Audit, logging, DoS/backlog |
| TM-040..042 | SEC-TST-029/030 + AI entitlement/content tests | AI isolation and non-autonomous mutation |
| TM-043..045 | Privacy/retention tests + privileged/change review | Privacy deletion, environment separation, break-glass |

# **Engineering Baseline Statement**

This Security Architecture & Threat Model Specification V1.0 is the proposed security engineering baseline for KarobarOne V1. It consolidates security controls already required by the approved architecture and adds explicit threat treatment, privileged-access, verification and operational controls needed for production. It must evolve as implementation evidence, provider selection, penetration testing and incidents reveal new risks, while business behavior remains governed by BRD V2.1 and the approved state-machine/contract specifications.

Derived from KarobarOne BRD V2.1 and the approved Backend Technical Design, Database Design, State Machine & Business Rules, REST API & Kafka Event Contract, OpenAPI/AsyncAPI machine-readable contracts, Repository/Foundation, Backend Test & Acceptance, and Infrastructure/Kubernetes specifications.
