**KAROBARONE**

**External Integration Specification**

Provider-adapter baseline for payments, logistics, identity verification, notifications, domains/DNS, object storage and reconciliation

| Document Field | Value |
| --- | --- |
| Specification Version | 1.0 |
| Status | Integration Implementation Baseline |
| Effective Date | 14 September 2026 |
| Business Authority | KarobarOne BRD V2.1 - Final Consolidated |
| Technical Inputs | Backend Technical Design V1.0; Database Schema V1.0; State Machine & Business Rules V1.0; REST API & Kafka Event Contract V1.0; OpenAPI/AsyncAPI V1.0; Repository/Foundation V1.0; Backend Test & Acceptance V1.0; Infrastructure/Kubernetes V1.0; Security Architecture & Threat Model V1.0 |
| Approved named providers | Razorpay for online tenant payments; Shiprocket as initial logistics provider |
| Provider-neutral integrations | PAN/GST verification, email/SMS, registrar/DNS, S3-compatible object storage/CDN |
| Primary Audience | Backend Engineering, Integration Engineering, DevOps/SRE, Security, QA, Architecture and Operations |

| Authority - This document specifies provider adapters and operational integration behavior. It does not change KarobarOne business rules. Provider capabilities must be normalized into KarobarOne domain contracts; a provider API response never becomes a new business rule by itself. |
| --- |

| Provider volatility - External APIs, authentication schemes, webhook payloads and commercial capabilities can change. Provider-specific details below are an integration baseline and must be revalidated during implementation/onboarding; KarobarOne domain contracts remain stable. |
| --- |

# **Document Contents**

1. Purpose, Scope and Normative Hierarchy

2. Integration Architecture Principles

3. Provider Adapter Architecture and Ownership

4. Common External-Provider Contract

5. Credentials, Secrets and Tenant Provider Context

6. HTTP Client, Timeouts, Retry and Circuit-Breaker Rules

7. Webhook Ingestion, Dedupe and Replay

8. Reconciliation and Provider-State Recovery

9. Razorpay Payment Integration

10. Shiprocket Logistics Integration

11. PAN and GSTIN Verification Integration

12. Email and SMS Notification Integration

13. Domain Registrar and DNS Integration

14. Object Storage and CDN Integration

15. Cloudflare / Edge Integration Boundary

16. Error Normalization and Dependency Health

17. Security, Privacy and Audit Requirements

18. Observability and Operations

19. Sandbox, Test and Certification Strategy

20. Versioning and Change Management

21. Failure Modes and Recovery Playbooks

22. Implementation Sequence

23. Open Decisions and Provider Extension Points

Appendix A - Integration Registry

Appendix B - Normalized Webhook/Event Mapping

Appendix C - External Call Policy Matrix

Appendix D - Environment/Secret Configuration Catalog

Appendix E - Integration Readiness Checklist

Appendix F - External Reference Validation Notes

# **1. Purpose, Scope and Normative Hierarchy**

## **1.1 Purpose**

This specification defines how KarobarOne communicates with external providers without leaking provider-specific semantics into core domain services. It standardizes adapters, credentials, outbound requests, inbound webhooks, idempotency, reconciliation, provider error translation, observability, security and test certification.

## **1.2 In Scope**

- Razorpay integration for tenant-direct online payment collection and normalized payment/refund facts.
- Shiprocket integration for shipping quotes, shipment creation/tracking, COD delivery confirmation and reconciliation.
- PAN/GSTIN verification adapter for tenant/GST ownership verification, with final provider selection still open.
- Email/SMS adapters for OTP and transactional notifications, with provider selection open.
- Domain registrar/DNS adapter for custom-domain availability, purchase, configuration and DNS verification.
- S3-compatible private object storage/CDN adapter for media uploads, digital fulfilment and signed access.
- Provider webhook ingestion, retry, dedupe, raw retention, normalization, reconciliation and operations.
- Credential lifecycle, environment separation, security controls and provider-sandbox testing.

## **1.3 Out of Scope**

- Redefining subscription, commission, GST, payment ownership, shipping eligibility, booking or domain commercial policy.
- Committing to a final PAN/GST, email/SMS, registrar/DNS, object-storage or CDN vendor before procurement/technical validation.
- Provider commercial pricing, SLA or legal-contract negotiation.
- Frontend provider SDK implementation details except where they affect secure backend contracts.
- Production credentials, real PAN/GSTIN values, customer payment credentials or provider secrets.

## **1.4 Normative Hierarchy**

| Priority | Artifact | Authority |
| --- | --- | --- |
| 1 | KarobarOne BRD V2.1 | Business/commercial/legal rules and acceptance criteria. |
| 2 | State Machine & Business Rules V1.0 | Allowed lifecycle transitions and authoritative guards. |
| 3 | Database Schema V1.0 | Persistence, RLS, immutable history and provider reference storage. |
| 4 | REST API & Kafka Event Contract + OpenAPI/AsyncAPI | KarobarOne-facing synchronous/asynchronous interfaces. |
| 5 | Security Architecture + Infrastructure/Kubernetes | Security and runtime controls. |
| 6 | This specification | External-provider adapter behavior and operational contracts. |
| 7 | Provider SDK/API documentation | Implementation detail; may not override higher-authority KarobarOne rules. |

# **2. Integration Architecture Principles**

| ID | Principle | Engineering consequence |
| --- | --- | --- |
| INT-001 | Domain first, provider second | Core services depend on KarobarOne interfaces/value objects, not provider SDK models. |
| INT-002 | Tenant funds remain tenant-direct | Razorpay payment credentials/account context belong to the tenant connection; KarobarOne never models customer purchase money as platform-held funds. |
| INT-003 | Provider callbacks are evidence, not trust | Authenticate, retain, dedupe, map and validate callback scope/amount/source before domain mutation. |
| INT-004 | Browser return is non-authoritative | Payment success requires authoritative provider webhook/API evidence, never redirect state alone. |
| INT-005 | At-least-once safe | Outbound retries and inbound duplicates must not create duplicate orders, payments, refunds, shipments, commissions or notifications. |
| INT-006 | Reconciliation is mandatory | Missed/out-of-order provider callbacks are repaired through scheduled API reconciliation; no permanent dependence on webhook perfection. |
| INT-007 | Provider outage fails safely | New operations requiring unavailable authoritative provider state fail closed or remain pending; existing obligations remain manageable. |
| INT-008 | Sensitive data minimization | Provider secrets/payment credentials/full PAN/GST identifiers stay out of logs/Kafka and are encrypted or secret-managed. |
| INT-009 | Version adapters, not domain facts | Provider API version changes are isolated behind adapters; normalized KarobarOne events keep stable semantics. |
| INT-010 | Test before live | Each provider has fake/sandbox contract fixtures, negative tests, retry/replay tests and production onboarding checklist. |

# **3. Provider Adapter Architecture and Ownership**

| Domain/Application Service
        \|
        \| Provider-neutral interface / command DTO
        v
Integration Adapter (provider-specific)
  - auth/credential resolver
  - request mapper
  - HTTP/SDK client
  - response mapper
  - error mapper
  - telemetry
        \|
        +----> External Provider API
        \|
Provider Webhook Endpoint
  -> verify raw callback/auth
  -> persist raw event + dedupe key
  -> normalize provider fact
  -> local transaction + outbox
  -> Kafka domain fact
        \|
Reconciliation Worker
  -> query provider authoritative state
  -> compare local state
  -> issue idempotent repair command / open reconciliation case |
| --- |

| Integration | Owning service | Provider adapter responsibility | Core domain never does |
| --- | --- | --- | --- |
| Razorpay | PAY | Tenant payment connection, payment intent/order creation, webhook normalization, refund calls, reconciliation | Use Razorpay SDK objects as Order/Booking/Commission domain models. |
| Shiprocket | FUL | Quotes/serviceability, shipment creation/cancel, tracking/COD callbacks, reconciliation | Expose provider shipment status strings as authoritative commerce states. |
| PAN/GST | TEN | Verification request/evidence mapping, masked result, ownership checks | Treat provider score/text as final tenant business state without validation. |
| Email/SMS | NTF / IAM | Transactional delivery, OTP dispatch, provider delivery callbacks | Store OTP plaintext or let notification provider decide authentication state. |
| Registrar/DNS | DOM | Availability/purchase/DNS records/status/verification | Let registrar state bypass KarobarOne publication gates. |
| Object storage/CDN | CAT/FUL | Presigned upload/download, object metadata, private ACLs, expiry | Persist permanent public digital-product object URLs. |
| Cloudflare edge | Platform/DOM | WAF/DNS/host routing integration where selected | Make edge configuration the source of tenant/store entitlement truth. |

# **4. Common External-Provider Contract**

## **4.1 Adapter Interface Baseline**

| class ProviderAdapter(Protocol):
    async def health(self) -> ProviderHealth: ...
    async def execute(self, command, context) -> ProviderResult: ...
    async def reconcile(self, reference, context) -> ReconciliationResult: ...
    def verify_webhook(self, raw_body, headers, context) -> VerifiedWebhook: ...
    def normalize_webhook(self, verified) -> list[NormalizedProviderFact]: ... |
| --- |

| Concern | Required behavior |
| --- | --- |
| Context | Explicit provider_connection_id, tenant_id/store_id where applicable, environment, correlation_id and idempotency/business key. |
| Timeout | Every network call has connect/read/total timeout; no unbounded client call inside request path. |
| Retry | Only retry failures known to be transient and safe; non-idempotent operations require provider or KarobarOne idempotency protection. |
| Response mapping | Provider payload mapped into provider-neutral result; raw payload retained only where needed for evidence/reconciliation. |
| Errors | Translate provider/network errors to stable integration error taxonomy; do not leak secrets/raw provider exception text to callers. |
| Telemetry | Record provider, operation, latency, result class, retry count, correlation ID and safe provider reference. |
| Audit | Material connection changes and provider-driven financial/shipping facts have immutable evidence references. |
| Version | Adapter declares provider API/version/profile and feature capabilities in configuration. |

## **4.2 Stable Integration Error Taxonomy**

| Code | Meaning | Default handling |
| --- | --- | --- |
| PROVIDER_AUTH_FAILED | Credential/token rejected | Disable/flag connection; do not blind-retry; notify owner/ops. |
| PROVIDER_RATE_LIMITED | Provider throttled request | Honor Retry-After/backoff; queue/retry where safe. |
| PROVIDER_TIMEOUT | Timeout/no definitive outcome | Do not assume failure for state-changing calls; reconcile using business/provider reference. |
| PROVIDER_UNAVAILABLE | Provider service unavailable | Fail closed/pending for new authoritative action; retry/reconcile. |
| PROVIDER_VALIDATION_FAILED | Provider rejected payload | Return mapped validation/error details safe for operator; no automatic retry. |
| PROVIDER_CONFLICT | Duplicate/already-existing provider resource | Resolve by idempotency/business reference; reconcile before creating again. |
| PROVIDER_SIGNATURE_INVALID | Webhook authenticity failed | Reject 4xx; security signal; no domain mutation. |
| PROVIDER_EVENT_UNMAPPED | Callback valid but unsupported/unmapped | Persist for investigation; no business mutation. |
| PROVIDER_STATE_MISMATCH | Local vs provider authoritative state differs | Open/execute reconciliation workflow. |
| PROVIDER_CONFIGURATION_ERROR | Missing/invalid tenant or environment configuration | Block dependent capability and surface actionable status. |

# **5. Credentials, Secrets and Tenant Provider Context**

| Rule | Specification |
| --- | --- |
| Environment separation | Test/sandbox and production credentials are distinct. Never reuse live credentials in local/dev tests. |
| Storage | Secrets are never stored in source control or ordinary config tables. Use approved secret manager/Kubernetes Secret references; tenant provider secrets encrypted when persistence is necessary. |
| Least privilege | Each workload/provider connection receives minimum provider scope required by the adapter. |
| Rotation | Rotation must support audit and, where provider semantics permit, overlapping old/new credentials to avoid callback downtime. |
| Tenant context | Payment/logistics provider context is resolved server-side from store/provider_connection records; client-supplied account IDs never establish authority. |
| Disable/revoke | Disconnection/revocation immediately prevents new dependent operations while preserving historical references/evidence. |
| Logging | Never log Authorization headers, API secrets, webhook secrets, refresh/access tokens or raw payment credentials. |
| Access | Secret-read ability is restricted to owning workload and authorized operations; support/admin access uses audited break-glass process where necessary. |

# **6. HTTP Client, Timeouts, Retry and Circuit-Breaker Rules**

| Operation class | Retry policy | Idempotency requirement | Reconciliation requirement |
| --- | --- | --- | --- |
| Pure GET/query | Bounded retry on timeout/5xx/429 with jitter | Not normally needed | Use if result controls financial/fulfilment transition. |
| Create with provider idempotency/reference | Retry only when same stable provider/business key is reused | Mandatory stable key/reference | Yes when timeout occurs after request may have reached provider. |
| Create without provider idempotency | Do not blind-retry after ambiguous timeout | KarobarOne business uniqueness + lookup before re-create | Mandatory. |
| Cancel/refund/state mutation | Retry only if provider semantics are safe and same operation reference used | Mandatory business key | Mandatory for ambiguous outcomes. |
| Webhook processing | Provider may retry; endpoint must accept duplicates safely | Dedupe by provider event ID/hash + business key | Not for every callback; periodic reconciliation catches gaps. |
| Notification send | Provider/message idempotency if available; bounded retry | notification_job_id / provider message key | Delivery callback/status query where material. |

| Circuit breaker - Circuit breaking is an operational protection, not a business-state transition. Opening a circuit must not mark payment/shipment/verification as failed unless authoritative evidence says so. |
| --- |

# **7. Webhook Ingestion, Dedupe and Replay**

| Receive raw request
 -> capture received_at + safe headers + remote metadata
 -> resolve provider/environment/connection
 -> verify signature/auth using RAW body
 -> persist provider_webhook_event (raw encrypted/restricted as required)
 -> dedupe provider event ID / canonical hash
 -> normalize supported event type(s)
 -> validate tenant/store/source/amount/reference relationship
 -> in local transaction:
      update normalized provider state
      append history/audit
      insert outbox event(s)
 -> respond 2xx after durable accept
 -> downstream effects occur asynchronously/idempotently |
| --- |

| Control | Rule |
| --- | --- |
| Fast acknowledge | Webhook endpoint validates/persists/normalizes and responds; it does not synchronously complete every downstream workflow. |
| Signature/auth | Verification uses provider-required raw-body/header/token mechanism before any business mutation. |
| Dedupe | Prefer provider unique event ID; fallback canonical payload hash only when unavoidable. |
| Replay | Previously processed callback returns success without duplicate side effects. |
| Ordering | Callbacks may be out of order; state handlers reject regression and reconcile if sequence is ambiguous. |
| Unknown event | Retain safe evidence; mark UNMAPPED/IGNORED; no mutation. |
| Invalid signature | Reject; create security/audit signal; do not expose secret details. |
| Retention | Raw callback retention follows security/reconciliation retention policy; operational logs contain only redacted metadata. |

# **8. Reconciliation and Provider-State Recovery**

| Reconciliation family | Trigger | Authoritative comparison | Repair behavior |
| --- | --- | --- | --- |
| Payment | Webhook gap, timeout, stuck PENDING, scheduled sweep | Provider payment/order/refund status vs payment_transactions | Issue idempotent normalized confirmation/failure/refund command; never mark paid from browser return. |
| Shipment/COD | Tracking webhook gap, stale shipment, COD uncertainty | Shiprocket shipment/tracking/delivery/COD facts | Normalize latest monotonic shipment state; delivery fact may trigger COD commission once. |
| Verification | Provider timeout/manual review | Latest verification request/evidence | Complete VERIFIED/REJECTED/PENDING only from accepted evidence; preserve attempts. |
| Domain/DNS | Purchase timeout, DNS not active | Registrar/DNS provider resource and record status | Link recovered domain/record reference; re-run publication gate only after verified. |
| Notifications | Callback missing where delivery evidence matters | Provider message status | Update delivery attempt only; do not change domain transaction state. |
| Object storage | Upload intent expired/incomplete | Object HEAD/metadata vs media record | Finalize valid object or expire intent; never trust client claim alone. |

- Reconciliation jobs are durable scheduled jobs, not Kafka timers.
- Each repair command carries a stable business key and correlation/causation evidence.
- Reconciliation does not destructively rewrite financial/commercial history; corrections use normal domain commands/compensating records.

# **9. Razorpay Payment Integration**

## **9.1 Business Boundary**

- End customer pays the tenant directly through the tenant-connected Razorpay context. KarobarOne does not receive, hold, split or settle the sale proceeds.
- UPI through KarobarOne checkout is not supported. The payment adapter must not expose UPI as an allowed method in KarobarOne-generated payment intents.
- Provider webhook/API evidence is authoritative for server-side payment confirmation; browser redirects/callback UI responses are never sufficient.
- Commission becomes receivable for prepaid transactions only after verified tenant payment receipt.

## **9.2 Connection Model**

The final tenant onboarding/credential model remains an open technical decision: direct tenant API credentials, a Razorpay partner/linked-account model, or another approved secure connection mechanism may be used. The Payment service exposes one normalized ProviderAccount/Connection interface so business services do not change when the connection method changes.

| Capability | Normalized contract |
| --- | --- |
| Connect | Create/update provider account context; verify usable status; persist provider account reference and credential reference, not plaintext secret. |
| Create payment intent | Input source_type/source_id, immutable amount/currency snapshot, allowed methods and business key; output KarobarOne payment_id + provider references/client payload. |
| Webhook | Verify raw-body signature, dedupe event, validate account/source/amount, normalize payment/refund/provider-connection facts. |
| Refund | Execute only after KarobarOne refund approval; stable refund business key; ambiguous result reconciled before retry. |
| Reconcile | Fetch authoritative provider state for stuck/ambiguous payment/refund; emit normalized fact only once. |
| Disconnect | Stop new online payment intents immediately; historical references remain; eligible COD may continue per business rules. |

## **9.3 Razorpay Webhook Verification Profile**

| Item | Rule |
| --- | --- |
| Signature | Validate X-Razorpay-Signature against the raw request body using the configured webhook secret and HMAC-SHA256. |
| Raw body | Do not parse/cast before signature verification. |
| Event dedupe | Use x-razorpay-event-id where available as unique provider event identifier. |
| Ordering | Do not assume events arrive in business order; later authoritative state must not regress due to older callback. |
| Secrets | Webhook secret is separate from application API key material and must be rotated/audited independently. |
| HTTP success | 2xx means the callback was durably accepted/deduplicated; downstream order/commission reactions may continue asynchronously. |

## **9.4 Payment Fact Mapping**

| Provider-level observation | KarobarOne normalized outcome | Guard |
| --- | --- | --- |
| Authoritative successful receipt/capture/paid evidence | payment.confirmed.v1 | Provider account/source/amount/currency match immutable snapshot; not already confirmed. |
| Authoritative failure | payment.failed.v1 | Do not overwrite already-confirmed payment with stale failure. |
| Refund accepted/processing | refund.processing / payment refund-initiated fact as contracted | Refund request is approved and amount <= remaining refundable. |
| Refund completed | refund.completed.v1 / payment refund-confirmed fact as contracted | Provider refund reference and amount match approved refund. |
| Connection invalid/revoked | payment.provider-disconnected.v1 | Mark connection unusable; block new online intents only. |

# **10. Shiprocket Logistics Integration**

## **10.1 Business Boundary**

- Shiprocket is the initial logistics provider for V1 physical-product fulfilment.
- Self-shipping and local pickup are unsupported in V1; the API must not offer them as KarobarOne fulfilment modes.
- COD is allowed only through approved logistics; confirmed delivery is the COD commission trigger.
- Provider tracking states are normalized into KarobarOne shipment states and cannot bypass Commerce order transition guards.

## **10.2 Adapter Capabilities**

| Capability | Input | Output / normalized behavior |
| --- | --- | --- |
| Serviceability / quote | Origin/destination pincodes, weight/dimensions, COD flag, store/provider context | Provider options normalized to quote/serviceability result; no provider courier object leaks into Commerce. |
| Create shipment | Order snapshot, package data, addresses, payment mode | shipment_id + provider shipment/order/AWB references; shipment.created fact. |
| Cancel shipment | KarobarOne shipment reference + reason | Provider cancellation result mapped to eligible shipment.cancelled fact. |
| Track shipment | Provider shipment/AWB reference | Monotonic normalized tracking status and evidence timestamp. |
| Webhook tracking | Raw provider callback | Verify adapter-specific authenticity; dedupe; normalize in-transit/delivered/returned/COD facts. |
| Reconcile | Stale shipment or webhook gap | Query authoritative provider tracking state and repair through idempotent command. |

## **10.3 COD Safety**

- COD commission remains PENDING_TRIGGER until approved logistics reports authoritative delivered status.
- Duplicate delivered callbacks cannot create duplicate commission receivables.
- Out-of-order tracking callbacks cannot move a shipment backward from DELIVERED to IN_TRANSIT.
- COD remittance timing is not the commission trigger unless the BRD is formally changed; delivery confirmation is the V1 trigger.
- Provider-reported COD amount is compared to immutable order/payment-mode snapshot; mismatches open reconciliation rather than silently adjusting finance.

# **11. PAN and GSTIN Verification Integration**

| Open provider decision - No final PAN/GST verification vendor is approved in the current baseline. The implementation must use a provider-neutral adapter and preserve provider evidence so the vendor can change without rewriting tenant/store rules. |
| --- |

| Operation | Required inputs | Normalized output | Business guard |
| --- | --- | --- | --- |
| PAN verification | PAN value via secure endpoint + tenant/application context | verification_status, masked PAN, normalized legal name/type where available, provider_ref, evidence timestamp | One verified PAN maps to one tenant account; fingerprint uniqueness enforced locally. |
| GSTIN verification | GSTIN + tenant PAN fingerprint/context | status, masked GSTIN, PAN relationship result, legal/trade metadata where permitted, provider_ref | Paid activation only when GSTIN is verified as belonging to tenant PAN. |
| Reverification | Existing verification reference + reason | New immutable verification attempt/evidence | Does not destructively replace historical evidence. |
| Provider unavailable | Same as operation | PENDING/DEPENDENCY_UNAVAILABLE | Do not activate paid commerce by guessing ownership. |

## **11.1 Sensitive Identifier Handling**

- Full PAN/GSTIN appears only in authorized secure request/verification processing; responses are masked.
- Store encrypted/display representation separately from deterministic fingerprint/hash used for uniqueness/search.
- Do not publish full PAN/GSTIN into Kafka, analytics or ordinary operational logs.
- Provider evidence/reference and decision metadata are retained for audit/reverification subject to applicable retention policy.

# **12. Email and SMS Notification Integration**

| Use case | Channel | Security / reliability rules |
| --- | --- | --- |
| OTP challenge | Email and/or SMS as configured | Notification provider transports OTP but does not own OTP validity. OTP value is generated/hashed/validated by IAM; short TTL, attempt/rate limits; provider logs must not expose long-lived secrets. |
| Transactional notification | Email/SMS | Notification job is created from domain fact; retries do not repeat the domain transaction. |
| Delivery callback | Provider webhook/API | Authenticate/dedupe callback; update delivery_attempt only; callback never changes order/payment/subscription state directly. |
| Template versioning | Provider or KarobarOne template | Template code/version is captured on notification job for auditability. |
| Opt-out/preference | Where applicable | Transactional/security messages follow product/legal policy; provider preference state must be reconciled with KarobarOne preference source. |

| Provider selection - Email/SMS vendor remains open. The Notification service should support multiple adapters with capability metadata (email, SMS, delivery receipts, template IDs, rate limits). |
| --- |

# **13. Domain Registrar and DNS Integration**

## **13.1 Domain Workflow Boundary**

| Step | Integration responsibility | KarobarOne authoritative state |
| --- | --- | --- |
| Options/availability | Query registrar/provider for candidate availability/cost classification | domain_request records options; availability is time-bound evidence, not ownership. |
| Selection | Persist tenant-selected available option | SELECTED; no purchase until platform workflow authorizes. |
| Purchase/register | Registrar purchase using approved platform account/workflow | PURCHASED only after provider confirmation and provider domain reference recorded. |
| DNS configure | Create required A/CNAME/TXT/etc through DNS adapter where managed | DNS_PENDING until provider/public verification succeeds. |
| Verify | Resolve/provider-check required records and TLS/host readiness | DNS_VERIFIED; paid publication gate may proceed if all other guards pass. |
| Renewal | Provider renewal/status check according to commercial policy | Renewal evidence recorded; failure alerts before customer impact. |
| Closure/transfer review | Query provider transfer eligibility/lock/status | Transfer is not automatic; follows approved review workflow. |

## **13.2 DNS Adapter Rules**

- No DNS/registrar provider may decide whether a store is entitled to publish; Domain service applies KarobarOne guards.
- DNS changes are idempotent by zone/hostname/record identity and use safe upsert/delete semantics with audit.
- Custom domain host mappings are verified against the target store; hostile tenant input cannot claim another store/domain.
- Provider token is scoped to required zones/accounts and environment where possible.
- Centralized host routing is preferred; do not create a Kubernetes ingress object per tenant domain unless architecture is deliberately changed.

# **14. Object Storage and CDN Integration**

| Flow | Specification |
| --- | --- |
| Upload intent | Catalog/fulfilment creates an intent with store scope, object key prefix, size/type constraints and short expiry; client receives presigned upload or equivalent capability. |
| Finalize upload | Server verifies object exists, metadata/size/type/checksum policy, and links it to the intended record; client claim alone is insufficient. |
| Public catalog media | Only approved/live media is exposed through configured CDN/public delivery policy; draft/private objects remain inaccessible. |
| Digital product | Object remains private; Fulfilment issues short-lived signed download link only to entitled customer; initial policy 24h and max 3 downloads is enforced by KarobarOne entitlement data, not permanent URL secrecy alone. |
| Delete/retention | Logical unlink/soft-delete follows record retention; physical object cleanup is asynchronous and must not remove evidence-required assets prematurely. |
| Credentials | Workload access uses least-privilege bucket/prefix permissions; no public bucket credentials or permanent public object URLs. |
| Malware/content checks | Where introduced, scan status is provider-neutral metadata and can gate publication/download without changing business ownership. |

## **14.1 Signed URL Principle**

Presigned/signed URLs grant time-limited capability to a private object. KarobarOne must keep the authoritative entitlement/download-count state server-side and may reissue a link only after rechecking entitlement, expiry and usage policy. The signed URL itself is not a durable entitlement record.

# **15. Cloudflare / Edge Integration Boundary**

| Capability | Integration rule |
| --- | --- |
| WAF/DDoS | Cloudflare/WAF is an edge protection layer; application authorization and rate rules still apply behind it. |
| DNS | Cloudflare DNS may be used if selected; Domain adapter abstracts record CRUD and verification so another provider can replace it. |
| TLS | Public HTTPS is mandatory; certificate lifecycle is automated through the selected edge/ingress approach. |
| Cache/CDN | Cache only data safe for public delivery; authenticated/admin/payment responses are not broadly cached. |
| Purge | Content publication/unpublication may trigger safe cache invalidation by hostname/path/tag where supported. |
| Host routing | Host header/domain mapping is validated against Domain service projection; arbitrary Host values never choose tenant scope without verified mapping. |

# **16. Error Normalization and Dependency Health**

| Health state | Meaning | KarobarOne behavior |
| --- | --- | --- |
| HEALTHY | Expected provider operations succeed | Normal operations. |
| DEGRADED | Partial/rate-limited/high latency | Allow safe operations; queue/retry; surface operator warning; avoid cascading timeouts. |
| UNAVAILABLE | Provider cannot provide authoritative operation | Block/pending new dependent operation; preserve existing obligations; activate reconciliation/retry. |
| AUTH_ERROR | Credential/account invalid | Mark provider connection attention-required; stop new dependent operations; notify owner/ops. |
| MISCONFIGURED | Missing webhook/endpoint/account mapping/config | Fail configuration/readiness checks; do not silently fall back to unsafe behavior. |

## **16.1 Readiness vs Liveness**

- A provider outage should not necessarily make an API pod liveness fail.
- Readiness should fail only when the service cannot safely serve its intended workload; optional/degradable provider dependencies are reported through dependency health, not by restarting healthy pods.
- Provider health metrics/alerts must distinguish credential/configuration failure from provider-wide outage.

# **17. Security, Privacy and Audit Requirements**

| Control | Requirement |
| --- | --- |
| Transport | HTTPS/TLS for provider APIs/webhooks; private/internal endpoints follow infrastructure security baseline. |
| Authentication | Provider-specific authenticated client; webhook signatures/tokens verified before mutation. |
| Scope | Resolve tenant/store/provider connection server-side; reject mismatched provider references. |
| Secrets | Secret manager/encrypted reference; never Git/log/Kafka/client response. |
| PII | Transmit only provider-required fields; redact operational telemetry; retain evidence under policy. |
| Payment data | KarobarOne never stores raw card/payment credentials; use provider tokens/IDs/client payloads only. |
| Raw callbacks | Restricted access; encrypted where required; log only safe metadata/hash/provider event ID. |
| Audit | Connection changes, manual reconciliation, refund/shipment/domain overrides and credential rotation are auditable. |
| Admin | Manual provider repair/reconciliation endpoints require elevated authorization and immutable reason/evidence. |
| Deletion | Provider evidence tied to required commercial/legal history is retained even when ordinary profile data is anonymized. |

# **18. Observability and Operations**

| Signal | Required dimensions / examples |
| --- | --- |
| Outbound call metrics | provider, operation, status class, latency, timeout, retry, rate-limit, tenant/store only where cardinality policy allows. |
| Webhook metrics | received, verified, signature_failed, duplicate, unmapped, normalized, processing_failed, age/lag. |
| Reconciliation | cases opened/resolved, stuck age, mismatches, repair outcome. |
| Connection health | active/degraded/auth_error/disconnected by provider/environment. |
| Business protection | payment pending age, shipment stale age, COD delivered without commission, DNS pending age, upload-intent orphan count. |
| Tracing | correlation_id across API -> provider call -> webhook/reconciliation -> normalized event where possible. |
| Logs | safe provider references/event IDs; no secret headers, full PAN/GSTIN, OTP or payment credentials. |
| Alerts | signature failure spike, webhook silence, auth failures, latency/5xx spike, reconciliation backlog, rate-limit saturation. |

# **19. Sandbox, Test and Certification Strategy**

| Layer | Required test |
| --- | --- |
| Fake adapter | Deterministic success/validation/timeout/429/5xx/ambiguous-result fixtures for every provider interface. |
| Contract | Provider fixture -> normalized DTO/event schema; unknown/additive fields tolerated safely. |
| Webhook | Valid signature/auth, invalid signature, duplicate event, replay, out-of-order, unknown event, malformed payload. |
| Retry/idempotency | Ambiguous timeout followed by lookup/reconciliation; duplicate create does not duplicate provider/domain effect. |
| Security | Credential isolation, secret redaction, tenant/store provider-reference mismatch, forged callback. |
| Sandbox | Real provider test/sandbox for critical happy/negative paths before production onboarding. |
| Staging | Production-like webhooks, TLS/DNS, provider callback reachability, reconciliation, rate limits and outage simulation. |
| Release | Relevant AC tests + engineering integration tests pass; provider production credentials/configuration validated without exposing secrets. |

## **19.1 Minimum Provider Certification Cases**

☐ Connection/authentication succeeds and can be revoked/rotated safely.

☐ State-changing outbound call is idempotent or has documented ambiguity/reconciliation procedure.

☐ Webhook authenticity and duplicate/replay handling verified.

☐ Provider outage does not create false success or duplicate financial/fulfilment effect.

☐ Sandbox/test and production configuration are separated.

☐ Operational dashboards/alerts and runbook exist before live enablement.

# **20. Versioning and Change Management**

| Change | Required action |
| --- | --- |
| Additive provider response field | Adapter ignores/tolerates unless explicitly mapped; regression fixtures updated. |
| Provider enum/status added | Do not auto-map to business state; treat as UNKNOWN/unmapped until reviewed. |
| Provider API version change | Adapter/API profile version bump + contract/sandbox regression; domain contract unchanged unless approved business change. |
| Breaking provider auth/webhook change | Security/integration review, credential migration, dual-read/dual-verify window where possible. |
| KarobarOne event/API contract change | Follow OpenAPI/AsyncAPI compatibility/versioning rules; provider adapter updated to conform. |
| Provider replacement | Implement new adapter, migrate connections/references with reconciliation; core service interfaces remain stable. |
| Emergency provider deprecation | Feature flag/connection disable, fail closed for new operation, preserve historical obligations/evidence, execute migration runbook. |

# **21. Failure Modes and Recovery Playbooks**

| Failure | Immediate containment | Recovery / reconciliation |
| --- | --- | --- |
| Razorpay webhook outage | Do not infer payment failure/success from UI; keep PENDING; alert | Poll/query provider authoritative state; normalize confirmed/failed once; replay-safe downstream effects. |
| Razorpay auth revoked | Stop new online intents; existing COD eligibility unaffected | Notify tenant/ops; reconnect/rotate; reconcile pending payments. |
| Shiprocket webhook outage | Keep shipment at last authoritative state; no fake delivery | Poll tracking; apply monotonic state; COD commission only after authoritative delivery. |
| Shiprocket API outage | Block new shipment creation/quote or queue where safe | Retry/reconcile when restored; existing obligations remain visible. |
| Verification provider outage | Keep verification PENDING; do not activate paid commerce | Retry later/manual approved verification process if formally supported. |
| Notification provider outage | Queue/retry; security UX may degrade but auth state remains server-owned | Switch adapter if configured; preserve notification_job history. |
| DNS/registrar timeout | Do not mark domain purchased/verified | Query by request/domain reference before repurchase; recover linkage. |
| Object storage outage | Reject/queue new uploads/download link creation as appropriate | Retry; existing DB entitlement/history remains authoritative. |
| Credential leak | Disable/rotate credential, audit access, block compromised connection | Reconcile provider actions during compromise window; review logs/security events. |

# **22. Implementation Sequence**

| Phase | Deliverables | Exit condition |
| --- | --- | --- |
| E0 - Common foundation | Provider adapter interfaces, HTTP client policy, error taxonomy, credential resolver, webhook base, reconciliation framework | One fake provider supports outbound call + verified webhook + reconciliation end-to-end. |
| E1 - Identity/notification | PAN/GST adapter contract + email/SMS/OTP adapter | Tenant verification and OTP flows pass fake/sandbox tests without sensitive leakage. |
| E2 - Razorpay | Connection, payment intent, webhook, refund, reconciliation | Prepaid checkout/payment/refund idempotency and authoritative webhook tests pass. |
| E3 - Shiprocket | Quote/serviceability, create/cancel shipment, tracking/COD webhook, reconciliation | Physical/COD fulfilment workflow and delivery-trigger commission tests pass. |
| E4 - Domains/storage | Registrar/DNS adapter + object storage/CDN adapter | Free/paid publication + media/digital fulfilment flows pass. |
| E5 - Production certification | Secrets, dashboards/alerts, runbooks, sandbox/live config, failure drills | Provider go-live checklist signed; relevant acceptance/security suites pass. |

# **23. Open Decisions and Provider Extension Points**

| Decision | Current baseline | Must be resolved before |
| --- | --- | --- |
| Razorpay tenant onboarding model | Open: direct credentials vs approved partner/linked-account mechanism | M4 paid payment production enablement. |
| Shiprocket account model | Open: per-tenant connection vs approved delegated/platform model; adapter supports store provider context | M5 fulfilment production enablement. |
| PAN/GST verification provider | Provider not selected | Paid onboarding production enablement. |
| Email/SMS provider | Provider not selected; multi-adapter design | Production OTP/notification enablement. |
| Registrar/DNS provider | Provider not selected; Cloudflare may participate at DNS/edge layer | Paid custom-domain production enablement. |
| Object storage/CDN provider | S3-compatible private storage required; final vendor open | Media/digital production enablement. |
| Webhook raw retention period | Configured security/reconciliation retention; exact duration open | Production data-retention signoff. |
| Provider circuit-breaker thresholds | Operational configuration based on staging evidence | Production SRE readiness. |

# **Appendix A - Integration Registry**

| ID | Provider/Class | Owner | Purpose | Status | Critical invariant |
| --- | --- | --- | --- | --- | --- |
| PAY-RZP | Razorpay | PAY | Online tenant payment/refund | Named/approved | Tenant-direct funds; UPI excluded; authoritative webhook/API. |
| FUL-SR | Shiprocket | FUL | Shipping/tracking/COD | Named/initial | Self-shipping/local pickup unsupported; delivery is COD commission trigger. |
| TEN-IDV | PAN/GST provider | TEN | PAN/GST ownership verification | Provider open | Secure adapter; masked output; evidence retained. |
| NTF-EMAIL | Email provider | NTF/IAM | OTP + transactional email | Provider open | Provider transports; IAM owns OTP validity. |
| NTF-SMS | SMS provider | NTF/IAM | OTP + transactional SMS | Provider open | Rate/attempt abuse controls remain in KarobarOne. |
| DOM-REG | Registrar | DOM | Availability/purchase/renewal/transfer status | Provider open | Commercial policy remains KarobarOne-owned. |
| DOM-DNS | DNS provider | DOM/Platform | Record CRUD/verification | Provider open | May be Cloudflare; host routing verified server-side. |
| OBJ-S3 | S3-compatible storage | CAT/FUL | Private media/digital objects + signed URLs | Provider open | No permanent public digital URL. |
| EDGE-CF | Cloudflare/WAF | Platform | WAF/DDoS/TLS/DNS/CDN as selected | Approved edge baseline | Not an authorization source. |

# **Appendix B - Normalized Webhook/Event Mapping**

| Source | Provider observation | Normalized KarobarOne fact | Primary consumers |
| --- | --- | --- | --- |
| Razorpay | Authoritative payment success | payment.confirmed.v1 | COM/BKG/FIN/NTF/CMP |
| Razorpay | Authoritative payment failure | payment.failed.v1 | COM/BKG/FIN/NTF/CMP |
| Razorpay | Refund completion | refund.completed.v1 / contracted payment refund fact | COM/BKG/FIN/INV/NTF |
| Razorpay | Connection unusable | payment.provider-disconnected.v1 | COM/BKG/FIN/NTF |
| Shiprocket | In transit | shipment.in-transit.v1 | COM/FIN/NTF/ANL |
| Shiprocket | Delivered | shipment.delivered.v1 | COM/FIN/NTF/ANL |
| Shiprocket | COD delivered | cod.delivery-confirmed.v1 | FIN/COM/NTF/ANL |
| Shiprocket | Returned/RTO normalized | shipment.returned.v1 | COM/FIN/NTF/ANL |
| Email/SMS | Provider delivery callback | notification.delivery-updated.v1 | NTF/Operations/ANL |
| Registrar/DNS | Purchase/verification evidence | domain lifecycle facts after Domain guards | DOM/NTF/ANL/storefront projection |

# **Appendix C - External Call Policy Matrix**

| Operation | Sync request path? | Timeout ambiguity? | Retry | Needs reconciliation |
| --- | --- | --- | --- | --- |
| Payment intent create | Yes/internal | Yes | Same stable business/provider key only | Yes |
| Refund create | Usually async/internal | Yes | Safe/idempotent only | Yes |
| Shipment create | Yes/internal | Yes | Lookup before recreate | Yes |
| Tracking query | Worker/query | Low | Bounded transient retry | Sometimes |
| PAN/GST verify | Workflow | Yes | Bounded; preserve attempt | Yes/manual if supported |
| Notification send | Worker | Moderate | Bounded/idempotent job | Delivery status only |
| Domain purchase | Workflow | High | Do not blind repurchase | Mandatory |
| DNS upsert | Workflow | Moderate | Idempotent upsert | Verify |
| Presigned URL create | Yes | Low | Safe local/provider call | No |
| Object finalize HEAD | Yes/worker | Low | Bounded | Yes if upload incomplete |

# **Appendix D - Environment / Secret Configuration Catalog**

| Family | Examples | Secret? | Owner / rule |
| --- | --- | --- | --- |
| RAZORPAY_* | API endpoint/profile, credential ref, webhook secret ref | Yes for credentials/secrets | PAY; per environment/connection. |
| SHIPROCKET_* | API base/profile, credential ref, webhook verification config | Yes where credential | FUL; per environment/account. |
| IDENTITY_VERIFY_* | Provider base/profile/credential ref | Yes credential | TEN; provider open. |
| EMAIL_* / SMS_* | Provider endpoints/template/account refs | Yes credential | NTF/IAM. |
| REGISTRAR_* / DNS_* | Account/zone/token refs | Yes credential | DOM/Platform. |
| OBJECT_STORAGE_* | Endpoint, bucket, region, access ref, CDN host | Access key secret | CAT/FUL/Platform. |
| INTEGRATION_* | timeouts, retry counts, breaker thresholds | No | Bounded operational tuning. |
| WEBHOOK_* | public callback base, retention, verification flags | Secrets separate | Per adapter; HTTPS only. |

# **Appendix E - Integration Readiness Checklist**

☐ Provider adapter is behind a provider-neutral interface; no provider SDK model appears in domain entities.

☐ Production/sandbox credentials are isolated and externally secret-managed/encrypted.

☐ Outbound state-changing operations have idempotency/business-key and ambiguous-timeout strategy.

☐ Webhook authenticity, raw-body handling, dedupe, replay and out-of-order tests pass.

☐ Unknown provider events cannot mutate business state.

☐ Reconciliation worker exists for payment/shipment/domain or other integrations where callback loss can affect correctness.

☐ Provider connection ownership is validated server-side against tenant/store scope.

☐ No sensitive provider secret, OTP, full PAN/GSTIN or raw payment credential enters logs/Kafka.

☐ Provider outage behavior is fail-safe and documented; existing obligations remain manageable.

☐ Dashboards/alerts cover auth failure, latency/5xx, callback silence/signature failures and reconciliation backlog.

☐ Runbook exists for credential rotation, provider outage, webhook gap and ambiguous state-changing call.

☐ Sandbox/staging certification and relevant AC/security/engineering tests pass before production enablement.

☐ Open provider decisions have explicit owner and deadline/milestone.

☐ Provider documentation/API version was revalidated immediately before production onboarding.

# **Appendix F - External Reference Validation Notes**

The following provider-specific implementation facts were checked against current official documentation while preparing this V1.0 baseline. They are included only where they reinforce the approved KarobarOne architecture and should be rechecked at implementation/go-live because external documentation can change.

| Provider / reference | Validated implementation point |
| --- | --- |
| Razorpay - API Authentication | Razorpay documents authenticated API access using provider-issued credentials; KarobarOne still abstracts the tenant connection model because partner/linked-account onboarding remains an open decision. |
| Razorpay - Webhook validation/testing | Webhook signature is validated over the raw body using HMAC-SHA256 and the configured secret; duplicate events can be identified using x-razorpay-event-id; webhook delivery order is not guaranteed. |
| Razorpay - Webhooks overview | Server-to-server webhooks are distinct from client callback/redirect behavior and should be used for server-side state tracking. |
| Shiprocket - API documentation | Shiprocket exposes API integration and tracking webhook capability; KarobarOne normalizes tracking updates into its own shipment/COD facts rather than depending on provider status strings. |
| Amazon S3 documentation | Private objects can be shared using time-limited presigned URLs; KarobarOne keeps entitlement/download state in its own database. |
| Cloudflare documentation | Cloudflare provides API-managed DNS/WAF/CDN capabilities; the Domain/Platform adapter keeps provider choice separate from KarobarOne publication/authorization logic. |

| Final baseline - This External Integration Specification V1.0 is the provider-integration implementation baseline for KarobarOne. Business state remains owned by KarobarOne services. External providers supply capabilities and authoritative evidence only within their approved boundaries; adapters must normalize that evidence, preserve idempotency/auditability, and recover safely from retries, gaps, reordering and outages. |
| --- |
