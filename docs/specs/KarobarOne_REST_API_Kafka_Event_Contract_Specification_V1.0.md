**KAROBARONE**

**REST API & Kafka Event Contract Specification**

Multi-Tenant SaaS Portfolio, Hybrid Commerce, Booking, GST Compliance & AI Platform

**Specification Version 1.0  •  14 September 2026**

| Field | Contract |
| --- | --- |
| Document status | Implementation Contract Baseline |
| Business authority | KarobarOne BRD V2.1 — Final Consolidated |
| Technical inputs | Backend Technical Design V1.0; PostgreSQL Schema Specification V1.0; State Machine & Business Rules Specification V1.0 |
| Target API stack | Python 3.12+ / FastAPI / JSON / OpenAPI 3.1 |
| Event backbone | Apache Kafka; JSON event schemas initially, versioned for AsyncAPI/Schema Registry compatibility |
| Primary users | Backend, Frontend, QA, Architecture, Integration, DevOps, Product, Security and Operations teams |
| Purpose | Define the stable synchronous and asynchronous contracts that connect clients, domain services and external providers without reinterpreting business rules. |

*Normative rule: if this document conflicts with an explicit BRD rule, the BRD prevails. If it conflicts with a state-machine transition, the State Machine & Business Rules Specification prevails unless the BRD is changed.*

# Document Contents

- 1. Purpose, Scope and Normative Hierarchy
- 2. Contract Design Principles
- 3. REST API Global Standards
- 4. Authentication, Authorization and Context Contracts
- 5. Common Request / Response Schemas
- 6. API Error Contract
- 7. Service API Catalog — 16 Logical Services
- 8. Detailed Critical Command Contracts
- 9. External Provider Webhook Contracts
- 10. Kafka Event Architecture Standards
- 11. Kafka Topic and Event-Type Catalog
- 12. Event Payload Contracts
- 13. Producer / Consumer Matrix
- 14. Cross-Domain Orchestration Contracts
- 15. Idempotency, Ordering, Retry and DLQ Rules
- 16. Security, Privacy and Audit Contract Rules
- 17. OpenAPI / AsyncAPI Artifact Rules
- 18. Contract Testing and Compatibility Gates
- 19. Implementation Sequence
- Appendix A — Endpoint Registry
- Appendix B — Event Registry
- Appendix C — Standard Error Code Registry
- Appendix D — State/API/Event Traceability
- Appendix E — Contract Checklist

# 1. Purpose, Scope and Normative Hierarchy

This specification converts the approved domain architecture and deterministic state machines into explicit network contracts. It is the implementation agreement between frontend clients, FastAPI services, internal workers, Kafka consumers and external provider adapters. The document deliberately distinguishes synchronous commands/queries from asynchronous facts.

## 1.1 Normative hierarchy

| Priority | Artifact | Authority |
| --- | --- | --- |
| 1 | KarobarOne BRD V2.1 | Business behavior, commercial policy, entitlements and acceptance criteria. |
| 2 | State Machine & Business Rules Specification V1.0 | Allowed states, transitions, guards, side effects, timer behavior and rejection taxonomy. |
| 3 | Backend Technical Design V1.0 | Service ownership, runtime architecture, communication and deployment boundaries. |
| 4 | PostgreSQL Schema Specification V1.0 | Persistence structures, constraints, RLS and migration rules. |
| 5 | This API/Event Contract Specification | HTTP and Kafka surface that implements all above artifacts. |
| 6 | Generated OpenAPI / AsyncAPI / code | Must conform to this specification and higher-authority artifacts. |

## 1.2 Contract scope

- Public storefront and customer APIs.
- Tenant-owner and store-staff APIs.
- Platform Owner/Staff/GST operations APIs.
- Internal service-to-service HTTP commands/queries.
- Provider webhooks for Razorpay, Shiprocket, notification providers and future adapters.
- Kafka topics, granular event types, envelopes, partitioning, delivery and compatibility rules.
- Idempotency, error, concurrency, trace, audit and retry semantics.
- Contract-test obligations and versioning rules.

## 1.3 Non-goals

- UI/UX field layout and visual design.
- Provider-specific credentials or vendor secrets.
- Replacing the state-machine rules with API behavior.
- Using Kafka events as commands or timers unless explicitly defined as an internal technical event.
- Defining legal/tax policy beyond the approved BRD.

# 2. Contract Design Principles

| ID | Principle | Implementation consequence |
| --- | --- | --- |
| CTR-001 | State-changing APIs expose explicit commands, not generic status mutation. | Example: POST /bookings/{id}/cancel; never PATCH {status:"CANCELLED"}. |
| CTR-002 | Queries do not create side effects. | GET/HEAD must be safe and idempotent. |
| CTR-003 | All tenant/store resources are scope-checked server-side. | Frontend-supplied tenant_id/store_id is never sufficient authorization. |
| CTR-004 | Commands that may be retried use Idempotency-Key. | Create checkout/order/payment/refund/reschedule/subscription actions are retry-safe. |
| CTR-005 | HTTP returns authoritative command acceptance/result; Kafka publishes durable facts after commit. | A command may complete synchronously while downstream reactions remain asynchronous. |
| CTR-006 | No distributed DB transaction across services. | Local transaction + outbox + idempotent consumer + compensation. |
| CTR-007 | Provider callbacks are untrusted inputs. | Signature validation, raw-event retention, replay detection and normalization are mandatory. |
| CTR-008 | Historical commercial snapshots never depend on current master data. | Events and responses reference immutable snapshot IDs/values where financially material. |
| CTR-009 | Contracts are additive by default. | Breaking request/response/event changes require new API/event version. |
| CTR-010 | Business errors have stable machine codes. | Human-readable messages may change; code semantics do not. |

# 3. REST API Global Standards

| Field | Contract |
| --- | --- |
| Base path | /api/v1 |
| Media type | application/json; UTF-8 |
| Date/time | RFC 3339 UTC timestamps; business-local date/time explicitly labelled |
| Identifiers | UUID strings; provider IDs remain separate external_id fields |
| Money | Decimal string with currency_code in API payloads; never binary float |
| Pagination | Cursor-based for high-volume lists; limit default 50, max configurable <= 200 |
| Sorting | Explicit allow-listed sort fields only |
| Filtering | Query-string filters; tenant/store scope is authorization context, not arbitrary filter |
| Idempotency | Idempotency-Key header on retry-sensitive commands |
| Tracing | X-Request-Id accepted/generated; correlation_id propagated internally and into Kafka |
| Optimistic concurrency | If-Match or expected_version for conflict-prone updates; STALE_VERSION on mismatch |
| OpenAPI | FastAPI-generated OpenAPI is committed/versioned and contract-tested |

## 3.1 Standard headers

| Header | Direction | Required | Rule |
| --- | --- | --- | --- |
| Authorization: Bearer <JWT> | Request | Most authenticated APIs | Principal identity; resource scope checked server-side. |
| Idempotency-Key | Request | Retry-sensitive POST commands | Opaque client key, scoped server-side; same key + different request hash => IDEMPOTENCY_CONFLICT. |
| X-Request-Id | Both | Recommended | Accepted if valid UUID; otherwise generated. Returned in response. |
| X-Correlation-Id | Internal both | Required internally | Propagates across HTTP, Kafka and scheduled jobs. External clients may omit. |
| If-Match | Request | Where optimistic concurrency exposed | Carries version/ETag; stale write rejected. |
| Retry-After | Response | 429/selected 503 | Seconds or HTTP date. |
| Content-Type | Both | Yes for bodies | application/json; webhook routes may retain provider content type raw. |

## 3.2 HTTP status contract

| Status | Meaning |
| --- | --- |
| 200 | Successful query/command returning existing resource/result. |
| 201 | Resource created synchronously. |
| 202 | Durable asynchronous workflow accepted; operation/status resource returned. |
| 204 | Successful command with intentionally empty body. |
| 400 | Malformed syntax or structurally invalid command. |
| 401 | Missing/invalid authentication. |
| 403 | Authenticated but role/entitlement/restriction denies action. |
| 404 | Resource absent or not visible in caller scope. |
| 409 | Business conflict, illegal state transition, duplicate identity, idempotency conflict, stale state. |
| 422 | Field/domain validation failure where request is structurally valid. |
| 429 | Rate/OTP abuse limit. |
| 503 | Required dependency unavailable and command cannot safely continue. |

# 4. Authentication, Authorization and Context Contracts

Authorization is evaluated as a conjunction of identity, role, assignment, ownership, entitlement, lifecycle state and active restriction. A role alone is never sufficient for commercial actions.

authorize(command) = authenticated_principal AND role_allows(command) AND principal_assigned_to_scope AND resource_in_scope AND entitlement_allows(command) AND lifecycle_allows(command) AND no_blocking_restriction

## 4.1 JWT claim baseline

{
  "sub": "principal_uuid",
  "session_id": "uuid",
  "roles": ["STORE_OWNER"],
  "tenant_ids": ["uuid"],
  "store_ids": ["uuid"],
  "iat": 0,
  "exp": 0
}

Token claims are authorization hints, not the sole source for mutable entitlements/restrictions. High-value commands re-check current assignment and business state.

## 4.2 Actor classes

| Actor | Scope | Examples |
| --- | --- | --- |
| PUBLIC | Unauthenticated | Storefront reads, selected checkout bootstrap, provider webhooks on dedicated routes. |
| CUSTOMER | One store | Cart, checkout, booking, account, addresses, cancellation/return/refund requests. |
| STORE_OWNER | Tenant/store | Catalog, price, inventory, orders, bookings, integrations, subscription commands. |
| STORE_STAFF | Assigned stores + permissions | Delegated operations according to plan and explicit permission. |
| GUARDIAN | Minor legal/consent scope | Verification and required acknowledgements; no automatic store management. |
| PLATFORM_STAFF | Explicit elevated scope | Content review, support, risk/admin workflows according to granted permissions. |
| GST_STAFF | Compliance scope | GST preparation/review workflow only. |
| PLATFORM_OWNER | Global privileged | Pricing/config, upgrade discount approval, suspension/termination, staff admin. |
| SERVICE | Internal mTLS/service auth | Service-to-service calls and workers. |

# 5. Common Request / Response Schemas

## 5.1 Resource metadata

{
  "id": "uuid",
  "tenant_id": "uuid",
  "store_id": "uuid|null",
  "version": 12,
  "created_at": "2026-09-14T00:00:00Z",
  "updated_at": "2026-09-14T00:00:00Z"
}

## 5.2 Money

{ "amount": "1000.00", "currency_code": "INR" }

## 5.3 Cursor page

{
  "items": [...],
  "page": { "next_cursor": "opaque|null", "has_more": true }
}

## 5.4 Accepted asynchronous operation

{
  "operation_id": "uuid",
  "status": "ACCEPTED",
  "resource_id": "uuid|null",
  "poll_after_seconds": 5
}

## 5.5 Command result

{
  "resource": {...},
  "transition": {"from":"PENDING","to":"CONFIRMED"},
  "request_id": "uuid"
}

# 6. API Error Contract

{
  "error": {
    "code": "INVALID_STATE_TRANSITION",
    "message": "The requested transition is not allowed from the current state.",
    "details": {"current_state":"DELIVERED","requested_command":"cancel"},
    "request_id": "uuid"
  }
}

| Code | HTTP | Meaning |
| --- | --- | --- |
| INVALID_STATE_TRANSITION | 409 | Command not permitted from persisted state. |
| TENANT_PAN_ALREADY_REGISTERED | 409 | PAN already mapped to tenant. |
| FREE_STORE_ENTITLEMENT_CONSUMED | 409 | Lifetime Free Store already consumed. |
| GSTIN_REQUIRED | 422 | Paid activation lacks GSTIN. |
| GSTIN_NOT_OWNED | 409 | GSTIN does not belong to tenant PAN. |
| GSTIN_ALREADY_USED | 409 | GSTIN already bound to another paid store. |
| GUARDIAN_REQUIRED | 409 | Minor flow requires Guardian completion. |
| ENTITLEMENT_REQUIRED | 403 | Current plan/state lacks capability. |
| COMMERCE_SUSPENDED | 403 | Restriction blocks new commerce. |
| SUBSCRIPTION_EXPIRED | 403 | Expired/free state blocks new commerce. |
| CROSS_STORE_CHECKOUT_NOT_ALLOWED | 409 | Mixed store checkout attempted. |
| MIXED_CHECKOUT_NOT_ALLOWED | 409 | Disallowed product/service or service-type mixing. |
| INSUFFICIENT_INVENTORY | 409 | Atomic stock reservation failed. |
| CAPACITY_UNAVAILABLE | 409 | Slot capacity unavailable. |
| PAYMENT_NOT_CONFIRMED | 409 | No authoritative provider confirmation. |
| UPI_NOT_SUPPORTED | 422 | UPI requested through KarobarOne checkout. |
| CUSTOM_DOMAIN_REQUIRED | 409 | Paid publication without verified custom domain. |
| CONTENT_APPROVAL_REQUIRED | 409 | Controlled content not approved. |
| CANCELLATION_WINDOW_CLOSED | 409 | Initial cancellation notice at/after P3 start. |
| UPGRADE_APPROVAL_REQUIRED | 409 | Upgrade/discount approval or payment missing. |
| REFUND_NOT_ALLOWED | 409 | Refund disallowed by state/policy/rights evaluation. |
| IDEMPOTENCY_CONFLICT | 409 | Same idempotency key used with different request. |
| STALE_VERSION | 409 | Optimistic concurrency mismatch. |
| RATE_LIMITED | 429 | Rate/abuse threshold exceeded. |
| DEPENDENCY_UNAVAILABLE | 503 | Required provider/service unavailable. |

# 7. Service API Catalog — 16 Logical Services

The following is the V1 endpoint registry. Detailed field-level contracts for the most commercially or concurrency-sensitive commands are specified in Section 8. All paths are prefixed by /api/v1 unless explicitly marked as webhook/internal-only.

## IAM — Identity & Access

| ID | Method | Path | Actor | Idempotency | Purpose | Primary emitted fact |
| --- | --- | --- | --- | --- | --- | --- |
| IAM-001 | POST | /auth/login | PUBLIC | No | Authenticate principal | identity.security-event.recorded.v1 |
| IAM-002 | POST | /auth/refresh | Authenticated session | Yes | Rotate refresh session | identity.session.refreshed.v1 |
| IAM-003 | POST | /auth/logout | Authenticated | Yes | Revoke current session | identity.session.revoked.v1 |
| IAM-004 | POST | /auth/otp/challenges | PUBLIC/CUSTOMER | Yes | Create OTP challenge | identity.otp.challenge-created.v1 |
| IAM-005 | POST | /auth/otp/challenges/{challenge_id}/verify | PUBLIC/CUSTOMER | Yes | Verify OTP | identity.otp.verified.v1 |
| IAM-006 | GET | /me | Authenticated | N/A | Current principal + assignments | — |
| IAM-007 | POST | /admin/role-assignments | PLATFORM_OWNER/authorized admin | Yes | Grant scoped role | identity.role-assigned.v1 |
| IAM-008 | DELETE | /admin/role-assignments/{id} | PLATFORM_OWNER/authorized admin | Yes | Revoke role assignment | identity.role-revoked.v1 |

## TEN — Tenant & Store

| ID | Method | Path | Actor | Idempotency | Purpose | Primary emitted fact |
| --- | --- | --- | --- | --- | --- | --- |
| TEN-001 | POST | /tenants/register | Authenticated principal | Yes | Register PAN tenant / start age flow | tenant.registration-started.v1 |
| TEN-002 | GET | /tenants/{tenant_id} | Tenant/Admin | N/A | Read tenant profile/state | — |
| TEN-003 | POST | /tenants/{tenant_id}/guardians | Tenant/Guardian workflow | Yes | Submit Guardian | guardian.verification-started.v1 |
| TEN-004 | POST | /tenants/{tenant_id}/guardians/{guardian_id}/consents | GUARDIAN | Yes | Accept required terms | guardian.consent.accepted.v1 |
| TEN-005 | POST | /tenants/{tenant_id}/adult-reverification | Tenant | Yes | Complete adult reverification | tenant.adult-reverified.v1 |
| TEN-006 | POST | /tenants/{tenant_id}/gstins | STORE_OWNER | Yes | Register/verify GSTIN | gstin.verification-requested.v1 |
| TEN-007 | GET | /tenants/{tenant_id}/gstins | Tenant/Admin | N/A | List GSTINs | — |
| TEN-008 | POST | /stores | STORE_OWNER | Yes | Create Free/direct-paid store shell | store.created.v1 |
| TEN-009 | GET | /stores/{store_id} | Assigned/Admin | N/A | Read store | — |
| TEN-010 | POST | /stores/{store_id}/staff | STORE_OWNER | Yes | Assign staff within entitlement | store.staff-assigned.v1 |
| TEN-011 | DELETE | /stores/{store_id}/staff/{assignment_id} | STORE_OWNER | Yes | Revoke store staff | store.staff-revoked.v1 |

## SUB — Subscription & Entitlement

| ID | Method | Path | Actor | Idempotency | Purpose | Primary emitted fact |
| --- | --- | --- | --- | --- | --- | --- |
| SUB-001 | GET | /plans | PUBLIC/Authenticated | N/A | List current plan offerings | — |
| SUB-002 | POST | /stores/{store_id}/subscriptions/activation-quote | STORE_OWNER | Yes | Calculate first activation | subscription.activation-quote-created.v1 |
| SUB-003 | POST | /stores/{store_id}/subscriptions/activate | STORE_OWNER | Yes | Activate paid subscription after payment | subscription.activated.v1 |
| SUB-004 | GET | /stores/{store_id}/entitlements | Assigned/internal | N/A | Resolve current capabilities | — |
| SUB-005 | GET | /subscriptions/{subscription_id} | Assigned/Admin | N/A | Read subscription lifecycle | — |
| SUB-006 | POST | /subscriptions/{id}/cancel | STORE_OWNER | Yes | Record initial cancellation notice | subscription.cancellation-notice-recorded.v1 |
| SUB-007 | POST | /subscriptions/{id}/upgrade-quote | STORE_OWNER | Yes | Calculate upgrade | subscription.upgrade-quote-created.v1 |
| SUB-008 | POST | /subscriptions/{id}/upgrade | STORE_OWNER | Yes | Apply approved/paid upgrade | subscription.upgraded.v1 |
| SUB-009 | POST | /subscriptions/{id}/downgrade | STORE_OWNER | Yes | Request future downgrade | subscription.downgrade-requested.v1 |
| SUB-010 | POST | /subscriptions/{id}/reactivate | STORE_OWNER | Yes | Reactivate after Free conversion | subscription.reactivated.v1 |
| SUB-011 | POST | /admin/upgrade-discounts/{request_id}/decision | PLATFORM_OWNER | Yes | Approve/reject setup-fee discount | subscription.upgrade-discount-decided.v1 |

## DOM — Domain & Publication

| ID | Method | Path | Actor | Idempotency | Purpose | Primary emitted fact |
| --- | --- | --- | --- | --- | --- | --- |
| DOM-001 | POST | /stores/{store_id}/subdomain | STORE_OWNER/internal | Yes | Assign immutable Free subdomain | domain.subdomain-assigned.v1 |
| DOM-002 | POST | /stores/{store_id}/domains/options | STORE_OWNER | Yes | Submit preferred domains / check availability | domain.options-checked.v1 |
| DOM-003 | POST | /domain-requests/{id}/select | STORE_OWNER | Yes | Select available domain | domain.selected.v1 |
| DOM-004 | POST | /domain-requests/{id}/purchase | Platform workflow | Yes | Approve/purchase domain | domain.purchased.v1 |
| DOM-005 | GET | /stores/{store_id}/domain-status | Assigned/Admin | N/A | Read domain/DNS/publication status | — |
| DOM-006 | POST | /domain-requests/{id}/verify-dns | Platform/internal | Yes | Trigger DNS verification | domain.dns-verification-requested.v1 |
| DOM-007 | POST | /stores/{store_id}/publish | Platform/internal | Yes | Activate route if all gates pass | store.published.v1 |
| DOM-008 | POST | /domains/{id}/transfer-review | STORE_OWNER/Admin | Yes | Open post-closure transfer review | domain.transfer-review-opened.v1 |

## CAT — Catalog & CMS

| ID | Method | Path | Actor | Idempotency | Purpose | Primary emitted fact |
| --- | --- | --- | --- | --- | --- | --- |
| CAT-001 | POST | /stores/{store_id}/items | STORE_OWNER/STAFF | Yes | Create product/service item | catalog.item-created.v1 |
| CAT-002 | GET | /stores/{store_id}/items | Assigned/Public variant | N/A | List catalog | — |
| CAT-003 | GET | /items/{item_id} | Assigned/Public variant | N/A | Read item | — |
| CAT-004 | PATCH | /items/{item_id}/operational | STORE_OWNER/STAFF | Yes | Update price/active/service availability | catalog.item-operational-changed.v1 |
| CAT-005 | POST | /items/{item_id}/versions | STORE_OWNER/STAFF | Yes | Create controlled public version | catalog.version-created.v1 |
| CAT-006 | POST | /items/{item_id}/versions/{version_id}/submit | STORE_OWNER/STAFF | Yes | Submit for approval | content.submitted.v1 |
| CAT-007 | POST | /stores/{store_id}/pages/{page_type}/versions | STORE_OWNER/STAFF | Yes | Create page content version | catalog.page-version-created.v1 |
| CAT-008 | POST | /stores/{store_id}/media/upload-intents | STORE_OWNER/STAFF | Yes | Create private upload URL | catalog.media-upload-intent-created.v1 |
| CAT-009 | POST | /items/{item_id}/unpublish | STORE_OWNER/STAFF | Yes | Soft unpublish item | catalog.item-unpublished.v1 |
| CAT-010 | GET | /public/stores/{store_id}/snapshot | PUBLIC | N/A | Approved storefront read model | — |

## APR — Approval & Governance

| ID | Method | Path | Actor | Idempotency | Purpose | Primary emitted fact |
| --- | --- | --- | --- | --- | --- | --- |
| APR-001 | POST | /approvals | Internal/domain service | Yes | Create review request | content.submitted.v1 |
| APR-002 | GET | /approvals/queue | PLATFORM_STAFF | N/A | Review queue | — |
| APR-003 | GET | /approvals/{id} | PLATFORM_STAFF/owner | N/A | Review detail | — |
| APR-004 | POST | /approvals/{id}/approve | PLATFORM_STAFF | Yes | Approve immutable version | content.approved.v1 |
| APR-005 | POST | /approvals/{id}/reject | PLATFORM_STAFF | Yes | Reject with reason | content.rejected.v1 |
| APR-006 | POST | /approvals/{id}/emergency-takedown | PLATFORM_STAFF | Yes | Immediate takedown | content.emergency-takedown.v1 |

## CUS — Customer

| ID | Method | Path | Actor | Idempotency | Purpose | Primary emitted fact |
| --- | --- | --- | --- | --- | --- | --- |
| CUS-001 | POST | /stores/{store_id}/customers/guest | PUBLIC checkout | Yes | Create/resolve UNCLAIMED customer | customer.unclaimed-created.v1 |
| CUS-002 | POST | /customers/{id}/claim/challenge | PUBLIC/CUSTOMER | Yes | Start Email OTP claim | customer.claim-challenge-created.v1 |
| CUS-003 | POST | /customers/{id}/claim/verify | PUBLIC/CUSTOMER | Yes | Verify OTP and claim | customer.claimed.v1 |
| CUS-004 | GET | /customers/{id} | CUSTOMER/assigned staff | N/A | Read customer | — |
| CUS-005 | PATCH | /customers/{id} | CUSTOMER/assigned staff | Yes | Update profile fields | customer.profile-updated.v1 |
| CUS-006 | POST | /customers/{id}/addresses | CUSTOMER | Yes | Create address | customer.address-created.v1 |
| CUS-007 | POST | /customers/{id}/privacy-requests | CUSTOMER | Yes | Open privacy request | customer.privacy-requested.v1 |

## INV — Inventory

| ID | Method | Path | Actor | Idempotency | Purpose | Primary emitted fact |
| --- | --- | --- | --- | --- | --- | --- |
| INV-001 | GET | /inventory/availability | Internal/STORE_STAFF | N/A | Read SKU availability | — |
| INV-002 | POST | /inventory/reservations | Internal commerce | Yes | Atomic stock reservation | inventory.reserved.v1 |
| INV-003 | POST | /inventory/reservations/{id}/consume | Internal commerce | Yes | Consume reservation | inventory.consumed.v1 |
| INV-004 | POST | /inventory/reservations/{id}/release | Internal commerce/scheduler | Yes | Release reservation | inventory.released.v1 |
| INV-005 | POST | /inventory/adjustments | STORE_OWNER/STAFF | Yes | Manual stock adjustment | inventory.adjusted.v1 |
| INV-006 | GET | /stores/{store_id}/inventory | STORE_OWNER/STAFF | N/A | Inventory view | — |

## COM — Commerce

| ID | Method | Path | Actor | Idempotency | Purpose | Primary emitted fact |
| --- | --- | --- | --- | --- | --- | --- |
| COM-001 | POST | /stores/{store_id}/carts | PUBLIC/CUSTOMER | Yes | Create product cart | cart.created.v1 |
| COM-002 | POST | /carts/{cart_id}/items | PUBLIC/CUSTOMER | Yes | Add/update product item | cart.changed.v1 |
| COM-003 | POST | /carts/{cart_id}/checkout | PUBLIC/CUSTOMER | Yes | Create checkout/order + reserve stock | order.placed.v1 |
| COM-004 | GET | /orders/{order_id} | CUSTOMER/STORE_STAFF | N/A | Read order | — |
| COM-005 | GET | /stores/{store_id}/orders | STORE_STAFF | N/A | List orders | — |
| COM-006 | POST | /orders/{order_id}/processing | STORE_STAFF | Yes | Start fulfilment processing | order.processing.v1 |
| COM-007 | POST | /orders/{order_id}/cancel | CUSTOMER/STORE_STAFF | Yes | Request/execute eligible cancellation | order.cancelled.v1 |
| COM-008 | POST | /orders/{order_id}/returns | CUSTOMER | Yes | Create return request | return.requested.v1 |
| COM-009 | POST | /returns/{id}/decision | STORE_STAFF | Yes | Approve/reject return | return.decision-recorded.v1 |
| COM-010 | POST | /orders/{order_id}/refunds | CUSTOMER/STORE_STAFF | Yes | Create refund request | refund.requested.v1 |

## BKG — Booking

| ID | Method | Path | Actor | Idempotency | Purpose | Primary emitted fact |
| --- | --- | --- | --- | --- | --- | --- |
| BKG-001 | POST | /services/{service_id}/availability | PUBLIC/CUSTOMER | No | Compute available slots/capacity | — |
| BKG-002 | POST | /services/{service_id}/bookings | PUBLIC/CUSTOMER | Yes | Create service booking + capacity hold | booking.requested.v1 |
| BKG-003 | GET | /bookings/{booking_id} | CUSTOMER/STORE_STAFF | N/A | Read booking | — |
| BKG-004 | POST | /bookings/{id}/approve | STORE_STAFF | Yes | Seller approval | booking.approved.v1 |
| BKG-005 | POST | /bookings/{id}/reject | STORE_STAFF | Yes | Seller rejection | booking.rejected.v1 |
| BKG-006 | POST | /bookings/{id}/payment-intent | CUSTOMER/internal | Yes | Create required payment/deposit intent | booking.payment-required.v1 |
| BKG-007 | POST | /bookings/{id}/reschedule | CUSTOMER/STORE_STAFF | Yes | Atomic reschedule | booking.rescheduled.v1 |
| BKG-008 | POST | /bookings/{id}/cancel | CUSTOMER/STORE_STAFF | Yes | Cancel eligible booking | booking.cancelled.v1 |
| BKG-009 | POST | /bookings/{id}/complete | STORE_STAFF | Yes | Mark completed | booking.completed.v1 |
| BKG-010 | POST | /bookings/{id}/no-show | STORE_STAFF | Yes | Record no-show | booking.no-show.v1 |

## PAY — Payment Integration

| ID | Method | Path | Actor | Idempotency | Purpose | Primary emitted fact |
| --- | --- | --- | --- | --- | --- | --- |
| PAY-001 | POST | /stores/{store_id}/payment-connections/razorpay | STORE_OWNER | Yes | Connect/update tenant provider context | payment.provider-connected.v1 |
| PAY-002 | DELETE | /stores/{store_id}/payment-connections/{id} | STORE_OWNER | Yes | Disconnect provider | payment.provider-disconnected.v1 |
| PAY-003 | POST | /stores/{store_id}/payment-intents | Internal commerce/booking | Yes | Create provider payment intent | payment.intent-created.v1 |
| PAY-004 | GET | /payments/{payment_id} | Customer/Store/Internal | N/A | Read normalized payment | — |
| PAY-005 | POST | /payments/{payment_id}/refund | Internal approved refund | Yes | Initiate provider refund | refund.processing.v1 |
| PAY-006 | POST | /webhooks/razorpay | Razorpay webhook | Provider event ID | Verify/dedupe/normalize provider event | payment.* / refund.* |
| PAY-007 | POST | /admin/payments/{id}/reconcile | Platform staff | Yes | Manual/scheduled reconciliation | payment.reconciled.v1 |

## FUL — Fulfilment

| ID | Method | Path | Actor | Idempotency | Purpose | Primary emitted fact |
| --- | --- | --- | --- | --- | --- | --- |
| FUL-001 | POST | /shipping/quotes | Internal commerce | Yes | Get integrated logistics quote | — |
| FUL-002 | POST | /orders/{order_id}/shipments | STORE_STAFF/internal | Yes | Create Shiprocket shipment | shipment.created.v1 |
| FUL-003 | GET | /shipments/{shipment_id} | CUSTOMER/STORE_STAFF | N/A | Read shipment/tracking | — |
| FUL-004 | POST | /shipments/{shipment_id}/cancel | STORE_STAFF | Yes | Cancel eligible shipment | shipment.cancelled.v1 |
| FUL-005 | POST | /webhooks/shiprocket | Shiprocket webhook | Provider event ID | Normalize tracking/delivery/COD facts | shipment.* / cod.delivery-confirmed.v1 |
| FUL-006 | POST | /digital-entitlements/{id}/link | CUSTOMER/internal | Yes | Issue/reissue signed download link | digital.link-issued.v1 |
| FUL-007 | GET | /digital-download/{token} | CUSTOMER token | Token single policy | Validate and redirect/stream signed object | digital.downloaded.v1 |

## FIN — Commission & Finance

| ID | Method | Path | Actor | Idempotency | Purpose | Primary emitted fact |
| --- | --- | --- | --- | --- | --- | --- |
| FIN-001 | GET | /tenants/{tenant_id}/commissions | Tenant/Admin | N/A | List commission records | — |
| FIN-002 | GET | /commission-invoices | Tenant/Admin | N/A | List weekly commission invoices | — |
| FIN-003 | GET | /commission-invoices/{id} | Tenant/Admin | N/A | Read invoice/lines | — |
| FIN-004 | POST | /commission-invoices/{id}/record-payment | Finance/Internal | Yes | Record platform dues payment | commission.invoice-paid.v1 |
| FIN-005 | POST | /commissions/{id}/dispute | STORE_OWNER | Yes | Open pay-first dispute | commission.dispute-opened.v1 |
| FIN-006 | POST | /commission-disputes/{id}/decision | Platform finance | Yes | Apply decision/credit | commission.credit-applied.v1 |
| FIN-007 | GET | /tenants/{tenant_id}/platform-invoices | Tenant/Admin | N/A | Subscriptions/setup/GST/domain invoices | — |
| FIN-008 | POST | /internal/platform-payments | Internal payment adapter | Yes | Record platform fee payment | finance.platform-payment-recorded.v1 |

## CMP — Compliance, GST & Risk

| ID | Method | Path | Actor | Idempotency | Purpose | Primary emitted fact |
| --- | --- | --- | --- | --- | --- | --- |
| CMP-001 | POST | /compliance/documents | STORE_OWNER | Yes | Submit licence/brand/compliance evidence | compliance.document-submitted.v1 |
| CMP-002 | POST | /gst/cases | STORE_OWNER/GST_STAFF | Yes | Open GST service case | gst.requested.v1 |
| CMP-003 | GET | /gst/cases/{id} | Tenant/GST_STAFF | N/A | Read GST workflow | — |
| CMP-004 | POST | /gst/cases/{id}/drafts | GST_STAFF | Yes | Create immutable return draft | gst.draft-ready.v1 |
| CMP-005 | POST | /gst/cases/{id}/approve | STORE_OWNER authorized approver | Yes | Tenant approval of exact draft | gst.tenant-approved.v1 |
| CMP-006 | POST | /gst/cases/{id}/file | GST_STAFF | Yes | Record authorized filing | gst.filed.v1 |
| CMP-007 | POST | /complaints | PUBLIC/CUSTOMER | Yes | Open consumer grievance | compliance.complaint-opened.v1 |
| CMP-008 | GET | /stores/{store_id}/restrictions | Assigned/Internal | N/A | Resolve active restrictions | — |
| CMP-009 | POST | /risk/cases/{id}/restrict | Platform authorized | Yes | Apply store/tenant restriction | risk.restriction-applied.v1 |
| CMP-010 | POST | /restrictions/{id}/lift | Platform authorized | Yes | Lift restriction after guards | risk.restriction-lifted.v1 |
| CMP-011 | POST | /tenants/{tenant_id}/terminate | PLATFORM_OWNER | Yes | Permanent termination | risk.tenant-terminated.v1 |

## NTF — Notification

| ID | Method | Path | Actor | Idempotency | Purpose | Primary emitted fact |
| --- | --- | --- | --- | --- | --- | --- |
| NTF-001 | POST | /internal/notifications | SERVICE | Yes | Queue transactional notification | notification.queued.v1 |
| NTF-002 | GET | /admin/notifications/{id} | Platform staff | N/A | Inspect delivery state | — |
| NTF-003 | POST | /admin/templates | Platform authorized | Yes | Create template version | notification.template-created.v1 |
| NTF-004 | POST | /webhooks/notifications/{provider} | Provider webhook | Provider event ID | Record delivery callback | notification.delivery-updated.v1 |

## ANL — Analytics & AI

| ID | Method | Path | Actor | Idempotency | Purpose | Primary emitted fact |
| --- | --- | --- | --- | --- | --- | --- |
| ANL-001 | GET | /stores/{store_id}/analytics | Entitled store user | N/A | Basic/advanced analytics by entitlement | — |
| ANL-002 | POST | /ai/content | Scale AI user | Yes | Generate governed content draft | ai.output-created.v1 |
| ANL-003 | POST | /ai/seo | Scale AI user | Yes | Generate SEO suggestions | ai.output-created.v1 |
| ANL-004 | POST | /ai/recommendations | Scale AI user | Yes | Generate non-autonomous recommendations | ai.recommendation-created.v1 |
| ANL-005 | GET | /stores/{store_id}/ai/usage | Scale AI user/Admin | N/A | Usage/quota ledger | — |

# 8. Detailed Critical Command Contracts

These contracts define minimum request/response/guard semantics for commands where incorrect implementation could violate a BRD invariant, financial rule, concurrency guarantee or lifecycle transition. Other endpoint schemas follow the same conventions and are generated in OpenAPI from service models.

## TEN-001 — Register tenant

| Field | Contract |
| --- | --- |
| Endpoint | POST /api/v1/tenants/register |
| Authorization / retry | Authenticated principal; Idempotency-Key required |
| Minimum request | {"pan":"encrypted at edge/handled securely","legal_name":"...","tenant_type":"INDIVIDUAL\|BUSINESS\|OTHER","date_of_birth":"YYYY-MM-DD\|null","acceptance_refs":[{"document_code":"TERMS","version":"..."}]} |
| Success response | {"tenant_id":"uuid","registration_state":"AGE_CHECK\|GUARDIAN_REQUIRED\|STANDARD_TENANT","pan_masked":"ABCDE*****"} |
| Guards / invariants | PAN verification succeeds; pan_fingerprint unique; age branch evaluated; adult required acceptance present or Guardian flow initiated. |
| Emitted facts | tenant.registration-started.v1; tenant.activated.v1 only when onboarding complete. |

## TEN-006 — Register/verify GSTIN

| Field | Contract |
| --- | --- |
| Endpoint | POST /api/v1/tenants/{tenant_id}/gstins |
| Authorization / retry | STORE_OWNER; Idempotency-Key required |
| Minimum request | {"gstin":"..."} |
| Success response | {"gstin_id":"uuid","status":"PENDING\|VERIFIED\|REJECTED","masked_gstin":"..."} |
| Guards / invariants | GSTIN belongs to tenant PAN; same GSTIN cannot activate another paid store; provider response/evidence retained. |
| Emitted facts | gstin.verified.v1 on success. |

## SUB-002 — First paid activation quote

| Field | Contract |
| --- | --- |
| Endpoint | POST /api/v1/stores/{store_id}/subscriptions/activation-quote |
| Authorization / retry | STORE_OWNER; Idempotency-Key required |
| Minimum request | {"plan_code":"COMMERCE\|GROWTH\|SCALE_AI","gstin_id":"uuid"} |
| Success response | {"quote_id":"uuid","period_1":{"amount":"S"},"third_period_advance":{"amount":"S"},"setup_fee":{"amount":"0.00"},"gst":{"amount":"..."},"total":{"amount":"..."},"expires_at":"..."} |
| Guards / invariants | Verified GSTIN belongs to tenant PAN and is unused; first activation vs reactivation distinguished; plan version snapshotted. |
| Emitted facts | subscription.activation-quote-created.v1. |

## SUB-006 — Cancellation notice

| Field | Contract |
| --- | --- |
| Endpoint | POST /api/v1/subscriptions/{id}/cancel |
| Authorization / retry | STORE_OWNER; Idempotency-Key required |
| Minimum request | {"reason":"optional","expected_version":12} |
| Success response | {"subscription_id":"uuid","notice_recorded_at":"...","paid_through_period":3,"additional_period_3_due":"0.00","end_after_period":3} |
| Guards / invariants | Current subscription is within initial commitment and notice is recorded strictly before Period 3 starts; otherwise CANCELLATION_WINDOW_CLOSED. |
| Emitted facts | subscription.cancellation-notice-recorded.v1. |

## SUB-007 — Upgrade quote

| Field | Contract |
| --- | --- |
| Endpoint | POST /api/v1/subscriptions/{id}/upgrade-quote |
| Authorization / retry | STORE_OWNER; Idempotency-Key required |
| Minimum request | {"target_plan_code":"GROWTH","effective":"IMMEDIATE"} |
| Success response | {"quote_id":"uuid","lower_price":"L","higher_price":"H","days_remaining":15,"prorated_difference":"...","advance_top_up":"...","gross_upgrade_setup_fee":"...","approved_discount":"0.00","total_before_gst":"..."} |
| Guards / invariants | Target is higher paid plan; quote uses immutable current plan/period inputs; if before P3, advance top-up is calculated. |
| Emitted facts | subscription.upgrade-quote-created.v1. |

## DOM-007 — Publish store

| Field | Contract |
| --- | --- |
| Endpoint | POST /api/v1/stores/{store_id}/publish |
| Authorization / retry | Platform/internal; Idempotency-Key required |
| Minimum request | {"expected_version":4} |
| Success response | {"store_id":"uuid","publication_state":"PUBLIC_LIVE","active_host":"example.com"} |
| Guards / invariants | Free: required content approved + Free subdomain. Paid: active subscription + verified GSTIN + custom domain DNS verified + required approvals/restrictions clear. |
| Emitted facts | store.published.v1; domain.route.activated.v1. |

## CAT-001 — Create catalog item

| Field | Contract |
| --- | --- |
| Endpoint | POST /api/v1/stores/{store_id}/items |
| Authorization / retry | STORE_OWNER/STAFF; Idempotency-Key required |
| Minimum request | {"item_type":"PHYSICAL_PRODUCT\|DIGITAL_PRODUCT\|APPOINTMENT_SERVICE\|NON_APPOINTMENT_SERVICE","operational":{"price":"...","currency_code":"INR","active":true},"draft":{"title":"...","description":"...","category_id":"uuid"}} |
| Success response | {"item_id":"uuid","draft_version_id":"uuid","approval_state":"DRAFT"} |
| Guards / invariants | Entitlement permits item type/count/media; Free combined showcase <=6; public controlled fields remain draft until approval. |
| Emitted facts | catalog.item-created.v1. |

## APR-004 — Approve content

| Field | Contract |
| --- | --- |
| Endpoint | POST /api/v1/approvals/{id}/approve |
| Authorization / retry | PLATFORM_STAFF; Idempotency-Key required |
| Minimum request | {"expected_version":3,"comment":"optional"} |
| Success response | {"approval_id":"uuid","state":"APPROVED/LIVE","content_version_id":"uuid","decided_at":"..."} |
| Guards / invariants | Approval request PENDING; reviewer authorized; referenced content version immutable. Current LIVE pointer changes only after approval. |
| Emitted facts | content.approved.v1. |

## INV-002 — Reserve stock

| Field | Contract |
| --- | --- |
| Endpoint | POST /api/v1/inventory/reservations |
| Authorization / retry | SERVICE; Idempotency-Key required |
| Minimum request | {"store_id":"uuid","checkout_id":"uuid","lines":[{"sku_id":"uuid","quantity":"2"}],"ttl_seconds":600} |
| Success response | {"reservation_group_id":"uuid","reservations":[{"id":"uuid","sku_id":"uuid","quantity":"2","expires_at":"..."}]} |
| Guards / invariants | Atomic conditional update/row lock; available quantity must remain >=0; all-or-nothing group by checkout unless command explicitly supports partial. |
| Emitted facts | inventory.reserved.v1. |

## COM-003 — Product checkout

| Field | Contract |
| --- | --- |
| Endpoint | POST /api/v1/carts/{cart_id}/checkout |
| Authorization / retry | PUBLIC/CUSTOMER; Idempotency-Key required |
| Minimum request | {"customer":{"email":"...","mobile":"..."},"shipping_address_id":"uuid\|null","payment_method":"ONLINE\|COD","expected_cart_version":8} |
| Success response | {"checkout_id":"uuid","order_id":"uuid","order_state":"PLACED\|PAYMENT_PENDING","inventory_reservation_group_id":"uuid","payment_action":{"payment_intent_id":"uuid\|null","provider_payload":{}}} |
| Guards / invariants | One store only; products only; commerce entitlement active; no blocking restriction; UPI rejected; COD requires approved logistics; inventory reservation succeeds; commercial snapshots persisted. |
| Emitted facts | order.placed.v1; order.payment-pending.v1 as applicable. |

## PAY-003 — Create payment intent

| Field | Contract |
| --- | --- |
| Endpoint | POST /api/v1/stores/{store_id}/payment-intents |
| Authorization / retry | Internal commerce/booking; Idempotency-Key required |
| Minimum request | {"source_type":"ORDER\|BOOKING","source_id":"uuid","amount":"...","currency_code":"INR","allowed_methods":["CARD","NETBANKING", "..."],"snapshot_ref":"uuid"} |
| Success response | {"payment_id":"uuid","state":"PENDING","provider":"RAZORPAY","provider_order_id":"...","client_payload":{}} |
| Guards / invariants | Tenant provider connection ACTIVE; amount/source matches immutable snapshot; UPI not included; client cannot choose unsupported provider method. |
| Emitted facts | payment.intent-created.v1. |

## PAY-006 — Razorpay webhook

| Field | Contract |
| --- | --- |
| Endpoint | POST /api/v1/webhooks/razorpay |
| Authorization / retry | Provider callback; no tenant JWT |
| Minimum request | Raw provider body + signature headers. |
| Success response | {"accepted":true} |
| Guards / invariants | Signature valid; raw event stored; dedupe by provider event ID/hash; event amount/account/source match; browser redirect never substitutes for this. |
| Emitted facts | payment.confirmed.v1 / payment.failed.v1 / refund.completed.v1 / payment.provider-disconnected.v1 as normalized. |

## BKG-002 — Create booking

| Field | Contract |
| --- | --- |
| Endpoint | POST /api/v1/services/{service_id}/bookings |
| Authorization / retry | PUBLIC/CUSTOMER; Idempotency-Key required |
| Minimum request | {"store_id":"uuid","booking_type":"APPOINTMENT\|NON_APPOINTMENT","slot":{"starts_at":"..."},"quantity":1,"customer":{"email":"...","mobile":"..."},"payment_mode":"..."} |
| Success response | {"booking_id":"uuid","state":"REQUESTED\|CONFIRMED\|PAYMENT_PENDING","capacity_reservation_id":"uuid\|null","payment_deadline":"...\|null"} |
| Guards / invariants | Paid commerce entitlement; service transaction type isolated; appointment capacity reserved atomically; price/tax/discount/commission snapshots fixed at creation. |
| Emitted facts | booking.requested.v1 or booking.confirmed.v1. |

## BKG-007 — Reschedule booking

| Field | Contract |
| --- | --- |
| Endpoint | POST /api/v1/bookings/{id}/reschedule |
| Authorization / retry | CUSTOMER/STORE_STAFF; Idempotency-Key required |
| Minimum request | {"new_slot":{"starts_at":"..."},"reason":"...","expected_version":5} |
| Success response | {"booking_id":"uuid","state":"RESCHEDULED","new_occurrence_id":"uuid","old_slot":"...","new_slot":"..."} |
| Guards / invariants | Current state eligible; reserve new capacity before releasing old; preserve full history; commission old record reversed/new context created. |
| Emitted facts | booking.rescheduled.v1. |

## COM-010 — Request refund

| Field | Contract |
| --- | --- |
| Endpoint | POST /api/v1/orders/{order_id}/refunds |
| Authorization / retry | CUSTOMER/STORE_STAFF; Idempotency-Key required |
| Minimum request | {"lines":[{"order_item_id":"uuid","amount":"..."}],"reason_code":"...","evidence_refs":[]} |
| Success response | {"refund_request_id":"uuid","state":"REQUESTED","requested_amount":"..."} |
| Guards / invariants | Requested amount <= remaining refundable amount; state/policy/mandatory rights evaluated; partial refund supported. |
| Emitted facts | refund.requested.v1. |

## FUL-002 — Create shipment

| Field | Contract |
| --- | --- |
| Endpoint | POST /api/v1/orders/{order_id}/shipments |
| Authorization / retry | STORE_STAFF/Internal; Idempotency-Key required |
| Minimum request | {"package":{"weight":"...","dimensions":{}},"service_level":"..."} |
| Success response | {"shipment_id":"uuid","provider":"SHIPROCKET","awb":"...\|null","state":"SHIPMENT_CREATED"} |
| Guards / invariants | Physical order eligible; approved logistics connection; self-shipping/local pickup rejected; e-way data satisfied where required. |
| Emitted facts | shipment.created.v1. |

## FUL-005 — Shiprocket webhook

| Field | Contract |
| --- | --- |
| Endpoint | POST /api/v1/webhooks/shiprocket |
| Authorization / retry | Provider callback |
| Minimum request | Raw provider body + provider verification metadata. |
| Success response | {"accepted":true} |
| Guards / invariants | Validate provider authenticity per adapter; dedupe; preserve raw event; normalize monotonic shipment state. Delivery is authoritative for COD commission. |
| Emitted facts | shipment.in-transit.v1 / shipment.delivered.v1 / cod.delivery-confirmed.v1. |

## FIN-005 — Commission dispute

| Field | Contract |
| --- | --- |
| Endpoint | POST /api/v1/commissions/{id}/dispute |
| Authorization / retry | STORE_OWNER; Idempotency-Key required |
| Minimum request | {"reason_code":"...","description":"...","evidence_refs":[]} |
| Success response | {"dispute_id":"uuid","state":"OPEN_AFTER_PAYMENT"} |
| Guards / invariants | Pay-first rule: underlying invoice/commission must be paid before ordinary dispute resolution; successful decision creates later credit, not historical rewrite. |
| Emitted facts | commission.dispute-opened.v1. |

## CMP-005 — Tenant GST approval

| Field | Contract |
| --- | --- |
| Endpoint | POST /api/v1/gst/cases/{id}/approve |
| Authorization / retry | Authorized tenant approver; Idempotency-Key required |
| Minimum request | {"draft_version_id":"uuid","declaration":true} |
| Success response | {"case_id":"uuid","state":"TENANT_APPROVED","approved_draft_version_id":"uuid","approved_at":"..."} |
| Guards / invariants | Draft immutable and belongs to store/GSTIN/tax period; exact approver/timestamp/version recorded; no filing before approval. |
| Emitted facts | gst.tenant-approved.v1. |

## CMP-009 — Apply restriction

| Field | Contract |
| --- | --- |
| Endpoint | POST /api/v1/risk/cases/{id}/restrict |
| Authorization / retry | Authorized Platform Staff/Owner; Idempotency-Key required |
| Minimum request | {"scope":"STORE\|TENANT","restriction_type":"COMMISSION_SUSPENDED\|RISK_SUSPENDED\|ADMIN_SUSPENDED","reason":"...","evidence_refs":[]} |
| Success response | {"restriction_id":"uuid","active":true,"effective_at":"..."} |
| Guards / invariants | Authorized decision; scope/severity valid; existing obligations remain manageable; no destructive data mutation. |
| Emitted facts | risk.restriction-applied.v1. |

# 9. External Provider Webhook Contracts

| Provider / route | Authentication | Dedupe key | Persistence | Normalized output |
| --- | --- | --- | --- | --- |
| Razorpay — POST /api/v1/webhooks/razorpay | Provider signature over raw payload; tenant/provider account context resolved server-side | Provider event ID; fallback hash if unavoidable | Raw headers/body + validation result + received_at + normalized references | payment.confirmed/failed; refund.completed; provider connection events |
| Shiprocket — POST /api/v1/webhooks/shiprocket | Adapter-specific verification; source controls; never trust order IDs alone | Provider tracking/event key or canonical payload hash | Raw callback + shipment mapping + normalized status | shipment.in-transit/delivered/returned; cod.delivery-confirmed |
| Email/SMS provider — /api/v1/webhooks/notifications/{provider} | Adapter signature/token | Provider message/event ID | Delivery callback audit | notification.delivery-updated |
| Future registrar/DNS callbacks | Adapter validation | Provider event/request ID | Raw event + domain_request mapping | domain purchase/DNS facts |

- Webhook HTTP 2xx means the callback was durably accepted/deduplicated, not that every downstream business reaction has finished.
- Webhook handlers must be fast: validate, persist raw event, dedupe, normalize/enqueue, respond.
- Replay of an already processed provider event returns success without repeating financial/state side effects.
- Unknown/unmapped provider events are retained for investigation and do not mutate business state.
- Signature failure returns 4xx and creates a security/audit signal; sensitive raw payloads are never logged verbatim.

# 10. Kafka Event Architecture Standards

## 10.1 Standard event envelope

{
  "event_id": "uuid",
  "event_type": "payment.confirmed.v1",
  "event_version": 1,
  "aggregate_type": "payment",
  "aggregate_id": "uuid",
  "tenant_id": "uuid|null",
  "store_id": "uuid|null",
  "occurred_at": "2026-09-14T00:00:00Z",
  "correlation_id": "uuid",
  "causation_id": "uuid|null",
  "producer": "payment-service",
  "payload": {}
}

| Field | Rule |
| --- | --- |
| event_id | Globally unique UUID. Consumer dedupe key. |
| event_type | Specific, versioned fact name: <domain>.<fact>.vN. |
| event_version | Integer matching schema version. |
| aggregate_type / aggregate_id | Authoritative aggregate whose state produced the fact. |
| tenant_id / store_id | Scope; nullable only for truly global/platform facts. |
| occurred_at | UTC time of committed business fact, not Kafka publish time. |
| correlation_id | End-to-end trace correlation. |
| causation_id | Prior command/event ID when known. |
| producer | Stable logical service name. |
| payload | Event-specific immutable fact fields; no secrets/OTP/raw PAN/GSTIN. |

## 10.2 Delivery and storage guarantees

- Application semantics assume at-least-once delivery.
- Producer commits aggregate mutation + state history + audit + outbox event in one PostgreSQL transaction.
- Outbox publisher retries until Kafka acknowledges; event_id remains stable across publish retries.
- Consumer writes processed_events/inbox marker in the same local transaction as its side effects.
- Financial side effects also use unique business keys, not event dedupe alone.
- Kafka is not a timer. Inventory expiry, subscription deadlines, commission due dates and similar rules are driven by scheduler/workflow jobs that may themselves emit facts.

## 10.3 Partition key contract

| Topic family | Default partition key | Reason |
| --- | --- | --- |
| tenant/subscription/domain/approval/customer | tenant_id or aggregate_id | Preserve per-tenant/aggregate ordering. |
| inventory | sku_id / reservation aggregate | Serialize hot stock aggregate where necessary. |
| order/payment/shipment/refund | order_id or source aggregate ID | Preserve commercial flow ordering. |
| booking | booking_id or service-slot aggregate | Booking order; capacity concurrency remains DB-authoritative. |
| commission/platform-finance | tenant_id for invoice facts; commission_id otherwise | Tenant invoice ordering. |
| risk/compliance | tenant_id/store_id | Restriction ordering by scope. |
| notification | notification_job_id | Delivery attempts for one job ordered. |
| analytics | store_id | Store-level aggregation locality. |

# 11. Kafka Topic and Event-Type Catalog

## identity.lifecycle

| Producer | Primary consumers | Event types |
| --- | --- | --- |
| IAM | TEN, NTF, security/analytics as applicable | identity.principal.created.v1
identity.session.revoked.v1
identity.role-assigned.v1
identity.role-revoked.v1
identity.otp.verified.v1
identity.security-event.recorded.v1 |

## tenant.lifecycle

| Producer | Primary consumers | Event types |
| --- | --- | --- |
| TEN | SUB, DOM, NTF, CMP, ANL | tenant.registration-started.v1
tenant.activated.v1
tenant.guardian-required.v1
guardian.verification-started.v1
guardian.consent.accepted.v1
tenant.adult-reverified.v1
gstin.verified.v1
store.created.v1
store.free-entitlement-consumed.v1
store.staff-assigned.v1 |

## subscription.lifecycle

| Producer | Primary consumers | Event types |
| --- | --- | --- |
| SUB | DOM, COM, BKG, NTF, ANL, FIN | subscription.activation-quote-created.v1
subscription.activated.v1
subscription.period-started.v1
subscription.payment-due.v1
subscription.grace-entered.v1
subscription.expired.v1
subscription.converted-to-free.v1
subscription.cancellation-notice-recorded.v1
subscription.upgrade-quote-created.v1
subscription.upgraded.v1
subscription.downgrade-requested.v1
subscription.downgraded.v1
subscription.reactivated.v1 |

## entitlement.changed

| Producer | Primary consumers | Event types |
| --- | --- | --- |
| SUB | CAT, COM, BKG, DOM, storefront projection | entitlement.changed.v1 |

## domain.lifecycle

| Producer | Primary consumers | Event types |
| --- | --- | --- |
| DOM | NTF, ANL, storefront projection | domain.subdomain-assigned.v1
domain.options-checked.v1
domain.selected.v1
domain.purchased.v1
domain.dns-verified.v1
domain.activated.v1
domain.stopped.v1
domain.transfer-review-opened.v1
store.published.v1 |

## catalog.lifecycle

| Producer | Primary consumers | Event types |
| --- | --- | --- |
| CAT | APR, INV, ANL, storefront projection | catalog.item-created.v1
catalog.item-operational-changed.v1
catalog.version-created.v1
catalog.item-unpublished.v1
catalog.media-uploaded.v1
storefront.snapshot-invalidated.v1 |

## approval.lifecycle

| Producer | Primary consumers | Event types |
| --- | --- | --- |
| APR | CAT, DOM, CMP, NTF, storefront projection | content.submitted.v1
content.approved.v1
content.rejected.v1
content.resubmitted.v1
content.emergency-takedown.v1
content.unpublished.v1 |

## customer.lifecycle

| Producer | Primary consumers | Event types |
| --- | --- | --- |
| CUS | COM/BKG projections, NTF, ANL | customer.unclaimed-created.v1
customer.claim-challenge-created.v1
customer.claimed.v1
customer.profile-updated.v1
customer.address-created.v1
customer.privacy-requested.v1 |

## inventory.lifecycle

| Producer | Primary consumers | Event types |
| --- | --- | --- |
| INV | COM, NTF/ANL where relevant | inventory.reserved.v1
inventory.consumed.v1
inventory.released.v1
inventory.expired.v1
inventory.restored.v1
inventory.adjusted.v1
inventory.low-stock.v1 |

## order.lifecycle

| Producer | Primary consumers | Event types |
| --- | --- | --- |
| COM | PAY, FUL, FIN, NTF, ANL, CMP | order.placed.v1
order.payment-pending.v1
order.paid.v1
order.processing.v1
order.shipped.v1
order.delivered.v1
order.cancelled.v1
order.returned.v1
order.refunded.v1
order.failed.v1
order.disputed.v1 |

## refund.lifecycle

| Producer | Primary consumers | Event types |
| --- | --- | --- |
| COM/PAY | COM/BKG, FIN, INV, NTF, ANL | refund.requested.v1
refund.approved.v1
refund.rejected.v1
refund.processing.v1
refund.completed.v1 |

## booking.lifecycle

| Producer | Primary consumers | Event types |
| --- | --- | --- |
| BKG | PAY, FIN, NTF, ANL, CMP | booking.requested.v1
booking.approved.v1
booking.payment-required.v1
booking.confirmed.v1
booking.rescheduled.v1
booking.completed.v1
booking.cancelled.v1
booking.rejected.v1
booking.no-show.v1
booking.refunded.v1 |

## payment.lifecycle

| Producer | Primary consumers | Event types |
| --- | --- | --- |
| PAY | COM, BKG, FIN, NTF, CMP | payment.intent-created.v1
payment.confirmed.v1
payment.failed.v1
payment.refund-initiated.v1
payment.refund-confirmed.v1
payment.provider-connected.v1
payment.provider-disconnected.v1
payment.reconciled.v1 |

## shipment.lifecycle

| Producer | Primary consumers | Event types |
| --- | --- | --- |
| FUL | COM, FIN, NTF, ANL | shipment.created.v1
shipment.in-transit.v1
shipment.delivered.v1
shipment.returned.v1
shipment.cancelled.v1
cod.delivery-confirmed.v1 |

## digital-fulfilment.lifecycle

| Producer | Primary consumers | Event types |
| --- | --- | --- |
| FUL | COM, NTF, ANL | digital.entitlement-issued.v1
digital.link-issued.v1
digital.downloaded.v1
digital.link-expired.v1
digital.entitlement-exhausted.v1 |

## commission.lifecycle

| Producer | Primary consumers | Event types |
| --- | --- | --- |
| FIN | CMP, NTF, ANL, SUB where dues affect state | commission.pending-trigger.v1
commission.receivable.v1
commission.invoiced.v1
commission.invoice-paid.v1
commission.invoice-overdue.v1
commission.dispute-opened.v1
commission.credit-created.v1
commission.credit-applied.v1
commission.cancelled-nonpayable.v1 |

## platform-finance.lifecycle

| Producer | Primary consumers | Event types |
| --- | --- | --- |
| FIN | SUB, DOM, CMP, NTF | finance.platform-invoice-issued.v1
finance.platform-payment-recorded.v1
finance.due-cleared.v1
finance.credit-note-issued.v1 |

## compliance.lifecycle

| Producer | Primary consumers | Event types |
| --- | --- | --- |
| CMP | NTF, ANL, APR/CAT where gates apply | compliance.document-submitted.v1
compliance.document-approved.v1
gst.requested.v1
gst.draft-ready.v1
gst.tenant-approved.v1
gst.filed.v1
gst.acknowledged.v1
compliance.complaint-opened.v1 |

## risk.lifecycle

| Producer | Primary consumers | Event types |
| --- | --- | --- |
| CMP | COM, BKG, DOM, SUB, NTF, ANL | risk.signal-created.v1
risk.restriction-applied.v1
risk.restriction-lifted.v1
risk.tenant-terminated.v1 |

## notification.delivery

| Producer | Primary consumers | Event types |
| --- | --- | --- |
| NTF | Operations/ANL | notification.queued.v1
notification.sent.v1
notification.failed.v1
notification.delivery-updated.v1 |

## analytics.ingest

| Producer | Primary consumers | Event types |
| --- | --- | --- |
| ANL/edge | ANL | analytics.page-view.v1
analytics.item-view.v1
analytics.form-submitted.v1 |

# 12. Event Payload Contracts

Payloads contain the minimum immutable fact necessary for downstream action. Consumers that need richer/current data query the owning service using aggregate IDs, subject to authorization and consistency requirements. Do not publish provider secrets, OTPs, full PAN/GSTIN, raw payment credentials or unnecessary PII.

| Event type | Minimum payload | Meaning |
| --- | --- | --- |
| tenant.activated.v1 | tenant_id, tenant_type, minor_status, activated_at | Tenant onboarding completed. |
| guardian.consent.accepted.v1 | tenant_id, guardian_id, consent_set_id, accepted_at, document_versions[] | Immutable guardian consent captured. |
| gstin.verified.v1 | tenant_id, gstin_id, gstin_masked, verification_provider_ref, verified_at | GSTIN verified against tenant PAN. |
| store.created.v1 | tenant_id, store_id, store_mode(FREE\|DIRECT_PAID_SETUP), created_at | Store aggregate created. |
| subscription.activated.v1 | tenant_id, store_id, subscription_id, plan_code, plan_version_id, period_id, period_start, period_end, third_period_advance_amount, activated_at | Paid subscription became active. |
| subscription.expired.v1 | tenant_id, store_id, subscription_id, due_charge_id, expired_at | Day-8 expired state entered. |
| subscription.converted-to-free.v1 | tenant_id, store_id, subscription_id, converted_at, reason, free_subdomain_required | Day-23 or end-after-P3 conversion. |
| entitlement.changed.v1 | tenant_id, store_id, entitlement_snapshot_id, plan_code, capabilities{}, effective_at | Resolved capability snapshot changed. |
| content.approved.v1 | tenant_id, store_id, approval_id, content_type, content_id, content_version_id, reviewer_id, decided_at | Controlled version approved/live. |
| inventory.reserved.v1 | tenant_id, store_id, reservation_group_id, checkout_id, reservations[{id,sku_id,quantity,expires_at}] | Tracked stock reserved. |
| order.placed.v1 | tenant_id, store_id, order_id, customer_id, payment_mode, currency_code, total_amount, commission_snapshot_ref, placed_at | Product order created with immutable commercial snapshot. |
| payment.confirmed.v1 | tenant_id, store_id, payment_id, source_type, source_id, provider, provider_payment_id, amount, currency_code, confirmed_at | Authoritative tenant-receipt signal confirmed. |
| refund.completed.v1 | tenant_id, store_id, refund_id, source_type, source_id, amount, currency_code, completion_method, completed_at | Refund completion/evidence recorded. |
| booking.confirmed.v1 | tenant_id, store_id, booking_id, customer_id, service_id, booking_type, occurrence_start, payment_mode, commission_snapshot_ref, confirmed_at | Booking confirmed. |
| booking.rescheduled.v1 | tenant_id, store_id, booking_id, old_occurrence_ref, new_occurrence_ref, old_start, new_start, rescheduled_at | Booking occurrence changed with history. |
| shipment.delivered.v1 | tenant_id, store_id, shipment_id, order_id, provider, provider_status, delivered_at, cod | Approved logistics confirmed delivery. |
| cod.delivery-confirmed.v1 | tenant_id, store_id, shipment_id, order_id, delivered_at, cod_amount | COD commission trigger fact. |
| commission.receivable.v1 | tenant_id, store_id, commission_id, source_type, source_id, base_amount, rate, amount, currency_code, trigger_type, triggered_at | Commission became payable. |
| commission.invoice-overdue.v1 | tenant_id, invoice_id, due_at, outstanding_amount, overdue_at | Potential PAN-wide commerce restriction trigger. |
| gst.tenant-approved.v1 | tenant_id, store_id, gst_case_id, gstin_id, tax_period, draft_version_id, approver_id, approved_at | Exact GST draft approved by tenant. |
| risk.restriction-applied.v1 | tenant_id, store_id\|null, restriction_id, restriction_type, scope, reason_code, effective_at | New-commerce or other restriction became active. |

# 13. Producer / Consumer Matrix

| Topic | Producer | Consumers / required reactions |
| --- | --- | --- |
| identity.lifecycle | IAM | TEN, NTF, security/analytics as applicable |
| tenant.lifecycle | TEN | SUB, DOM, NTF, CMP, ANL |
| subscription.lifecycle | SUB | DOM, COM, BKG, NTF, ANL, FIN |
| entitlement.changed | SUB | CAT, COM, BKG, DOM, storefront projection |
| domain.lifecycle | DOM | NTF, ANL, storefront projection |
| catalog.lifecycle | CAT | APR, INV, ANL, storefront projection |
| approval.lifecycle | APR | CAT, DOM, CMP, NTF, storefront projection |
| customer.lifecycle | CUS | COM/BKG projections, NTF, ANL |
| inventory.lifecycle | INV | COM, NTF/ANL where relevant |
| order.lifecycle | COM | PAY, FUL, FIN, NTF, ANL, CMP |
| refund.lifecycle | COM/PAY | COM/BKG, FIN, INV, NTF, ANL |
| booking.lifecycle | BKG | PAY, FIN, NTF, ANL, CMP |
| payment.lifecycle | PAY | COM, BKG, FIN, NTF, CMP |
| shipment.lifecycle | FUL | COM, FIN, NTF, ANL |
| digital-fulfilment.lifecycle | FUL | COM, NTF, ANL |
| commission.lifecycle | FIN | CMP, NTF, ANL, SUB where dues affect state |
| platform-finance.lifecycle | FIN | SUB, DOM, CMP, NTF |
| compliance.lifecycle | CMP | NTF, ANL, APR/CAT where gates apply |
| risk.lifecycle | CMP | COM, BKG, DOM, SUB, NTF, ANL |
| notification.delivery | NTF | Operations/ANL |
| analytics.ingest | ANL/edge | ANL |

## 13.1 Consumer reaction rules

- A consumer must ignore event types it does not explicitly support.
- A consumer must not infer missing business facts from topic name alone; event_type controls behavior.
- Consumers must tolerate additive unknown payload fields.
- Consumers must not republish the same semantic fact under a different event_id merely due to retry.
- When ordering matters, consumers compare aggregate version/effective timestamp and reject/park stale regressions rather than force earlier states.

# 14. Cross-Domain Orchestration Contracts

## 14.1 Free Presence publication

1. POST /tenants/register → tenant state
1. POST /stores → Free entitlement consumed + store.created
1. POST /stores/{id}/subdomain → immutable subdomain
1. Catalog/CMS draft APIs
1. POST /.../submit → approval queue
1. POST /approvals/{id}/approve → content.approved
1. POST /stores/{id}/publish → PUBLIC_LIVE on Free subdomain

## 14.2 First paid activation

1. Verify GSTIN
1. Create activation quote (S + A3 = 2S before GST)
1. Record platform payment via finance/payment path
1. POST /stores/{id}/subscriptions/activate
1. entitlement.changed consumed by CAT/COM/BKG/DOM
1. Custom-domain workflow
1. Publish only after DNS + approval gates

## 14.3 Prepaid product checkout

1. Commerce checks current entitlement/restriction
1. Inventory atomic reservation
1. Commerce persists order snapshot
1. Payment creates tenant-Razorpay intent
1. Razorpay webhook → payment.confirmed
1. Commerce → order.paid; Inventory → consume
1. Finance → commission.receivable
1. Fulfilment → shipment/digital entitlement
1. Notification/Analytics react asynchronously

## 14.4 COD product order

1. Commerce allows COD only if approved logistics capability
1. Fulfilment creates COD shipment
1. No prepaid commission trigger
1. Shiprocket delivery webhook → shipment.delivered + cod.delivery-confirmed
1. Finance creates commission.receivable

## 14.5 Booking approve-before-pay

1. Booking creates REQUESTED with capacity hold
1. Seller POST /approve
1. Booking enters PAYMENT_PENDING with payment deadline
1. Payment webhook before deadline → CONFIRMED
1. Scheduler expiry without payment → CANCELLED + capacity release

## 14.6 Subscription delinquency

1. SUB scheduler identifies due unpaid charge
1. Day 1 → grace.entered
1. Day 8 → subscription.expired; COM/BKG deny new creation
1. Day 23 → converted-to-free + entitlement.changed
1. DOM stops custom domain and activates Free route
1. CAT hides paid-only data and selects/defaults <=6 showcase items

## 14.7 Commission overdue restriction

1. Weekly invoice created from RECEIVABLE records
1. 15-day due window
1. Overdue event emitted
1. CMP applies tenant/PAN restriction
1. COM/BKG deny new commerce but existing obligations remain accessible
1. Payment clears invoice; explicit restriction-lift rule executes if no other blocker

# 15. Idempotency, Ordering, Retry and DLQ Rules

| Concern | Contract |
| --- | --- |
| HTTP idempotency key | Persist scope_id + key + request_hash + response. Same key/same hash returns original result; same key/different hash => 409 IDEMPOTENCY_CONFLICT. |
| Webhook dedupe | Provider event ID preferred; fallback stable canonical hash. Duplicate accepted without duplicate business side effects. |
| Kafka inbox | UNIQUE(consumer_name,event_id); insert marker in same transaction as side effects. |
| Business uniqueness | Financial effects also use source business key, e.g. one commission trigger per source trigger version. |
| Retryable HTTP | Only idempotent requests or commands protected by Idempotency-Key. Exponential backoff + jitter for 429/selected 5xx. |
| Kafka processing retry | Bounded immediate retries for transient errors, then delayed retry/DLQ policy. Permanent schema/business errors are quarantined, not endlessly retried. |
| DLQ record | Original topic/partition/offset, event envelope, consumer, error code, stack/reference, first/last failure time, retry count. Sensitive payload redacted/encrypted. |
| Ordering | Partition by aggregate/store key. DB current state/version remains authority; stale event cannot regress aggregate. |
| Scheduler race | Jobs claimed with row lock/SKIP LOCKED or equivalent and idempotent business key. |
| Timeout | Synchronous internal calls use short explicit timeout; caller returns 503 if command cannot safely proceed. |

# 16. Security, Privacy and Audit Contract Rules

- No API or event payload carries raw passwords, refresh tokens, OTP values, provider secrets or permanent object-storage URLs.
- PAN, GSTIN and Guardian government identifiers are accepted only on authorized secure endpoints, encrypted at rest, masked in responses and excluded from Kafka except safe IDs/masked values when operationally necessary.
- Public storefront APIs read only approved/live projections; draft/rejected versions are never reachable through public IDs.
- Platform-admin APIs use distinct permission checks; “tenant_id is null” is never treated as admin authorization.
- Every material state-changing API logs actor/source, command, old/new state, resource, reason where applicable and correlation ID.
- Webhook raw bodies are retained according to configured audit/reconciliation retention with access restriction and redaction in logs.
- Customer privacy requests may anonymize deletable profile data but cannot erase statutory order/invoice/GST/commission/audit history.
- AI APIs return drafts/recommendations only and cannot directly mutate price, inventory, tax return, subscription charge or financial records.

# 17. OpenAPI / AsyncAPI Artifact Rules

## 17.1 Repository layout

contracts/
  openapi/
    iam-v1.yaml
    tenant-v1.yaml
    subscription-v1.yaml
    ...
  events/
    asyncapi-v1.yaml
    schemas/
      payment.confirmed.v1.json
      subscription.activated.v1.json
      ...

- FastAPI-generated OpenAPI is treated as a build artifact and compared against the committed contract.
- Each endpoint carries operationId equal to contract ID or a stable equivalent (for example SUB_ActivateSubscription).
- Request/response schemas use explicit additionalProperties policy; financial/business command models should default to rejecting unknown write fields unless forward-compatibility requires otherwise.
- Event JSON schemas default to allowing additive optional fields but require the envelope and event-specific required fields.
- AsyncAPI documents topics, producers, consumers, message schemas and bindings; it does not redefine business state rules.
- Breaking API path/request semantics use /api/v2 or a formally managed incompatible version; breaking event payload changes create .v2 event_type/schema.

# 18. Contract Testing and Compatibility Gates

| Gate | Mandatory test |
| --- | --- |
| OpenAPI schema | Generated OpenAPI diff must not contain unapproved breaking change. |
| API consumer contract | Frontend/service fixtures validate request/response examples and stable error codes. |
| Event schema compatibility | Producer schema must remain backward-compatible for same event_type version; breaking change requires v2. |
| Outbox/inbox | Mutation + outbox atomicity; duplicate event does not duplicate effect. |
| Webhook | Signature failure, duplicate callback, out-of-order callback and replay tests. |
| Authorization | Tenant isolation, store assignment, role, entitlement and restriction checks for each command class. |
| State transitions | Every state-changing endpoint mapped to allowed transition; invalid-from-state returns stable error. |
| Concurrency | Final stock, final slot capacity, duplicate payment/refund/reschedule, concurrent scheduler/invoice creation. |
| Acceptance criteria | AC-001..AC-090 remain release-blocking automated acceptance suite. |
| Examples | All examples in committed contract validated against actual Pydantic/JSON schemas in CI. |

# 19. Implementation Sequence

| Phase | Contract deliverables | Exit condition |
| --- | --- | --- |
| 1 — Foundation | Common errors, auth headers, idempotency, event envelope, outbox/inbox schemas, IAM/TEN/APR contracts | Service template can generate OpenAPI and publish/consume a test event idempotently. |
| 2 — Free Presence | TEN, DOM Free subdomain, CAT, APR, CUS public/claim endpoints + events | Registration → approved Free Store publication contract tests pass. |
| 3 — Subscription | SUB + FIN platform-payment contracts; entitlement.changed | AC-041..075 reachable only through explicit commands. |
| 4 — Product Commerce | CUS/INV/COM/PAY/refund contracts | Prepaid checkout/webhook/refund concurrency and idempotency tests pass. |
| 5 — Fulfilment | FUL/Shiprocket/COD/digital events | Authoritative delivery and download rules pass. |
| 6 — Booking | BKG + payment sequences/reschedule/no-show | Capacity/payment/commission orchestration tests pass. |
| 7 — Finance/Risk/GST | FIN commission invoice/dispute; CMP restriction/GST/grievance | PAN-wide restriction and exact GST approval version contracts pass. |
| 8 — Analytics/AI | ANL read/AI draft contracts | Entitlement/quota enforced; no autonomous financial mutation. |

# Appendix A — Endpoint Registry

| Service | ID | Method | Path | Actor | Idempotency | Purpose | Emits |
| --- | --- | --- | --- | --- | --- | --- | --- |
| IAM | IAM-001 | POST | /auth/login | PUBLIC | No | Authenticate principal | identity.security-event.recorded.v1 |
| IAM | IAM-002 | POST | /auth/refresh | Authenticated session | Yes | Rotate refresh session | identity.session.refreshed.v1 |
| IAM | IAM-003 | POST | /auth/logout | Authenticated | Yes | Revoke current session | identity.session.revoked.v1 |
| IAM | IAM-004 | POST | /auth/otp/challenges | PUBLIC/CUSTOMER | Yes | Create OTP challenge | identity.otp.challenge-created.v1 |
| IAM | IAM-005 | POST | /auth/otp/challenges/{challenge_id}/verify | PUBLIC/CUSTOMER | Yes | Verify OTP | identity.otp.verified.v1 |
| IAM | IAM-006 | GET | /me | Authenticated | N/A | Current principal + assignments | — |
| IAM | IAM-007 | POST | /admin/role-assignments | PLATFORM_OWNER/authorized admin | Yes | Grant scoped role | identity.role-assigned.v1 |
| IAM | IAM-008 | DELETE | /admin/role-assignments/{id} | PLATFORM_OWNER/authorized admin | Yes | Revoke role assignment | identity.role-revoked.v1 |
| TEN | TEN-001 | POST | /tenants/register | Authenticated principal | Yes | Register PAN tenant / start age flow | tenant.registration-started.v1 |
| TEN | TEN-002 | GET | /tenants/{tenant_id} | Tenant/Admin | N/A | Read tenant profile/state | — |
| TEN | TEN-003 | POST | /tenants/{tenant_id}/guardians | Tenant/Guardian workflow | Yes | Submit Guardian | guardian.verification-started.v1 |
| TEN | TEN-004 | POST | /tenants/{tenant_id}/guardians/{guardian_id}/consents | GUARDIAN | Yes | Accept required terms | guardian.consent.accepted.v1 |
| TEN | TEN-005 | POST | /tenants/{tenant_id}/adult-reverification | Tenant | Yes | Complete adult reverification | tenant.adult-reverified.v1 |
| TEN | TEN-006 | POST | /tenants/{tenant_id}/gstins | STORE_OWNER | Yes | Register/verify GSTIN | gstin.verification-requested.v1 |
| TEN | TEN-007 | GET | /tenants/{tenant_id}/gstins | Tenant/Admin | N/A | List GSTINs | — |
| TEN | TEN-008 | POST | /stores | STORE_OWNER | Yes | Create Free/direct-paid store shell | store.created.v1 |
| TEN | TEN-009 | GET | /stores/{store_id} | Assigned/Admin | N/A | Read store | — |
| TEN | TEN-010 | POST | /stores/{store_id}/staff | STORE_OWNER | Yes | Assign staff within entitlement | store.staff-assigned.v1 |
| TEN | TEN-011 | DELETE | /stores/{store_id}/staff/{assignment_id} | STORE_OWNER | Yes | Revoke store staff | store.staff-revoked.v1 |
| SUB | SUB-001 | GET | /plans | PUBLIC/Authenticated | N/A | List current plan offerings | — |
| SUB | SUB-002 | POST | /stores/{store_id}/subscriptions/activation-quote | STORE_OWNER | Yes | Calculate first activation | subscription.activation-quote-created.v1 |
| SUB | SUB-003 | POST | /stores/{store_id}/subscriptions/activate | STORE_OWNER | Yes | Activate paid subscription after payment | subscription.activated.v1 |
| SUB | SUB-004 | GET | /stores/{store_id}/entitlements | Assigned/internal | N/A | Resolve current capabilities | — |
| SUB | SUB-005 | GET | /subscriptions/{subscription_id} | Assigned/Admin | N/A | Read subscription lifecycle | — |
| SUB | SUB-006 | POST | /subscriptions/{id}/cancel | STORE_OWNER | Yes | Record initial cancellation notice | subscription.cancellation-notice-recorded.v1 |
| SUB | SUB-007 | POST | /subscriptions/{id}/upgrade-quote | STORE_OWNER | Yes | Calculate upgrade | subscription.upgrade-quote-created.v1 |
| SUB | SUB-008 | POST | /subscriptions/{id}/upgrade | STORE_OWNER | Yes | Apply approved/paid upgrade | subscription.upgraded.v1 |
| SUB | SUB-009 | POST | /subscriptions/{id}/downgrade | STORE_OWNER | Yes | Request future downgrade | subscription.downgrade-requested.v1 |
| SUB | SUB-010 | POST | /subscriptions/{id}/reactivate | STORE_OWNER | Yes | Reactivate after Free conversion | subscription.reactivated.v1 |
| SUB | SUB-011 | POST | /admin/upgrade-discounts/{request_id}/decision | PLATFORM_OWNER | Yes | Approve/reject setup-fee discount | subscription.upgrade-discount-decided.v1 |
| DOM | DOM-001 | POST | /stores/{store_id}/subdomain | STORE_OWNER/internal | Yes | Assign immutable Free subdomain | domain.subdomain-assigned.v1 |
| DOM | DOM-002 | POST | /stores/{store_id}/domains/options | STORE_OWNER | Yes | Submit preferred domains / check availability | domain.options-checked.v1 |
| DOM | DOM-003 | POST | /domain-requests/{id}/select | STORE_OWNER | Yes | Select available domain | domain.selected.v1 |
| DOM | DOM-004 | POST | /domain-requests/{id}/purchase | Platform workflow | Yes | Approve/purchase domain | domain.purchased.v1 |
| DOM | DOM-005 | GET | /stores/{store_id}/domain-status | Assigned/Admin | N/A | Read domain/DNS/publication status | — |
| DOM | DOM-006 | POST | /domain-requests/{id}/verify-dns | Platform/internal | Yes | Trigger DNS verification | domain.dns-verification-requested.v1 |
| DOM | DOM-007 | POST | /stores/{store_id}/publish | Platform/internal | Yes | Activate route if all gates pass | store.published.v1 |
| DOM | DOM-008 | POST | /domains/{id}/transfer-review | STORE_OWNER/Admin | Yes | Open post-closure transfer review | domain.transfer-review-opened.v1 |
| CAT | CAT-001 | POST | /stores/{store_id}/items | STORE_OWNER/STAFF | Yes | Create product/service item | catalog.item-created.v1 |
| CAT | CAT-002 | GET | /stores/{store_id}/items | Assigned/Public variant | N/A | List catalog | — |
| CAT | CAT-003 | GET | /items/{item_id} | Assigned/Public variant | N/A | Read item | — |
| CAT | CAT-004 | PATCH | /items/{item_id}/operational | STORE_OWNER/STAFF | Yes | Update price/active/service availability | catalog.item-operational-changed.v1 |
| CAT | CAT-005 | POST | /items/{item_id}/versions | STORE_OWNER/STAFF | Yes | Create controlled public version | catalog.version-created.v1 |
| CAT | CAT-006 | POST | /items/{item_id}/versions/{version_id}/submit | STORE_OWNER/STAFF | Yes | Submit for approval | content.submitted.v1 |
| CAT | CAT-007 | POST | /stores/{store_id}/pages/{page_type}/versions | STORE_OWNER/STAFF | Yes | Create page content version | catalog.page-version-created.v1 |
| CAT | CAT-008 | POST | /stores/{store_id}/media/upload-intents | STORE_OWNER/STAFF | Yes | Create private upload URL | catalog.media-upload-intent-created.v1 |
| CAT | CAT-009 | POST | /items/{item_id}/unpublish | STORE_OWNER/STAFF | Yes | Soft unpublish item | catalog.item-unpublished.v1 |
| CAT | CAT-010 | GET | /public/stores/{store_id}/snapshot | PUBLIC | N/A | Approved storefront read model | — |
| APR | APR-001 | POST | /approvals | Internal/domain service | Yes | Create review request | content.submitted.v1 |
| APR | APR-002 | GET | /approvals/queue | PLATFORM_STAFF | N/A | Review queue | — |
| APR | APR-003 | GET | /approvals/{id} | PLATFORM_STAFF/owner | N/A | Review detail | — |
| APR | APR-004 | POST | /approvals/{id}/approve | PLATFORM_STAFF | Yes | Approve immutable version | content.approved.v1 |
| APR | APR-005 | POST | /approvals/{id}/reject | PLATFORM_STAFF | Yes | Reject with reason | content.rejected.v1 |
| APR | APR-006 | POST | /approvals/{id}/emergency-takedown | PLATFORM_STAFF | Yes | Immediate takedown | content.emergency-takedown.v1 |
| CUS | CUS-001 | POST | /stores/{store_id}/customers/guest | PUBLIC checkout | Yes | Create/resolve UNCLAIMED customer | customer.unclaimed-created.v1 |
| CUS | CUS-002 | POST | /customers/{id}/claim/challenge | PUBLIC/CUSTOMER | Yes | Start Email OTP claim | customer.claim-challenge-created.v1 |
| CUS | CUS-003 | POST | /customers/{id}/claim/verify | PUBLIC/CUSTOMER | Yes | Verify OTP and claim | customer.claimed.v1 |
| CUS | CUS-004 | GET | /customers/{id} | CUSTOMER/assigned staff | N/A | Read customer | — |
| CUS | CUS-005 | PATCH | /customers/{id} | CUSTOMER/assigned staff | Yes | Update profile fields | customer.profile-updated.v1 |
| CUS | CUS-006 | POST | /customers/{id}/addresses | CUSTOMER | Yes | Create address | customer.address-created.v1 |
| CUS | CUS-007 | POST | /customers/{id}/privacy-requests | CUSTOMER | Yes | Open privacy request | customer.privacy-requested.v1 |
| INV | INV-001 | GET | /inventory/availability | Internal/STORE_STAFF | N/A | Read SKU availability | — |
| INV | INV-002 | POST | /inventory/reservations | Internal commerce | Yes | Atomic stock reservation | inventory.reserved.v1 |
| INV | INV-003 | POST | /inventory/reservations/{id}/consume | Internal commerce | Yes | Consume reservation | inventory.consumed.v1 |
| INV | INV-004 | POST | /inventory/reservations/{id}/release | Internal commerce/scheduler | Yes | Release reservation | inventory.released.v1 |
| INV | INV-005 | POST | /inventory/adjustments | STORE_OWNER/STAFF | Yes | Manual stock adjustment | inventory.adjusted.v1 |
| INV | INV-006 | GET | /stores/{store_id}/inventory | STORE_OWNER/STAFF | N/A | Inventory view | — |
| COM | COM-001 | POST | /stores/{store_id}/carts | PUBLIC/CUSTOMER | Yes | Create product cart | cart.created.v1 |
| COM | COM-002 | POST | /carts/{cart_id}/items | PUBLIC/CUSTOMER | Yes | Add/update product item | cart.changed.v1 |
| COM | COM-003 | POST | /carts/{cart_id}/checkout | PUBLIC/CUSTOMER | Yes | Create checkout/order + reserve stock | order.placed.v1 |
| COM | COM-004 | GET | /orders/{order_id} | CUSTOMER/STORE_STAFF | N/A | Read order | — |
| COM | COM-005 | GET | /stores/{store_id}/orders | STORE_STAFF | N/A | List orders | — |
| COM | COM-006 | POST | /orders/{order_id}/processing | STORE_STAFF | Yes | Start fulfilment processing | order.processing.v1 |
| COM | COM-007 | POST | /orders/{order_id}/cancel | CUSTOMER/STORE_STAFF | Yes | Request/execute eligible cancellation | order.cancelled.v1 |
| COM | COM-008 | POST | /orders/{order_id}/returns | CUSTOMER | Yes | Create return request | return.requested.v1 |
| COM | COM-009 | POST | /returns/{id}/decision | STORE_STAFF | Yes | Approve/reject return | return.decision-recorded.v1 |
| COM | COM-010 | POST | /orders/{order_id}/refunds | CUSTOMER/STORE_STAFF | Yes | Create refund request | refund.requested.v1 |
| BKG | BKG-001 | POST | /services/{service_id}/availability | PUBLIC/CUSTOMER | No | Compute available slots/capacity | — |
| BKG | BKG-002 | POST | /services/{service_id}/bookings | PUBLIC/CUSTOMER | Yes | Create service booking + capacity hold | booking.requested.v1 |
| BKG | BKG-003 | GET | /bookings/{booking_id} | CUSTOMER/STORE_STAFF | N/A | Read booking | — |
| BKG | BKG-004 | POST | /bookings/{id}/approve | STORE_STAFF | Yes | Seller approval | booking.approved.v1 |
| BKG | BKG-005 | POST | /bookings/{id}/reject | STORE_STAFF | Yes | Seller rejection | booking.rejected.v1 |
| BKG | BKG-006 | POST | /bookings/{id}/payment-intent | CUSTOMER/internal | Yes | Create required payment/deposit intent | booking.payment-required.v1 |
| BKG | BKG-007 | POST | /bookings/{id}/reschedule | CUSTOMER/STORE_STAFF | Yes | Atomic reschedule | booking.rescheduled.v1 |
| BKG | BKG-008 | POST | /bookings/{id}/cancel | CUSTOMER/STORE_STAFF | Yes | Cancel eligible booking | booking.cancelled.v1 |
| BKG | BKG-009 | POST | /bookings/{id}/complete | STORE_STAFF | Yes | Mark completed | booking.completed.v1 |
| BKG | BKG-010 | POST | /bookings/{id}/no-show | STORE_STAFF | Yes | Record no-show | booking.no-show.v1 |
| PAY | PAY-001 | POST | /stores/{store_id}/payment-connections/razorpay | STORE_OWNER | Yes | Connect/update tenant provider context | payment.provider-connected.v1 |
| PAY | PAY-002 | DELETE | /stores/{store_id}/payment-connections/{id} | STORE_OWNER | Yes | Disconnect provider | payment.provider-disconnected.v1 |
| PAY | PAY-003 | POST | /stores/{store_id}/payment-intents | Internal commerce/booking | Yes | Create provider payment intent | payment.intent-created.v1 |
| PAY | PAY-004 | GET | /payments/{payment_id} | Customer/Store/Internal | N/A | Read normalized payment | — |
| PAY | PAY-005 | POST | /payments/{payment_id}/refund | Internal approved refund | Yes | Initiate provider refund | refund.processing.v1 |
| PAY | PAY-006 | POST | /webhooks/razorpay | Razorpay webhook | Provider event ID | Verify/dedupe/normalize provider event | payment.* / refund.* |
| PAY | PAY-007 | POST | /admin/payments/{id}/reconcile | Platform staff | Yes | Manual/scheduled reconciliation | payment.reconciled.v1 |
| FUL | FUL-001 | POST | /shipping/quotes | Internal commerce | Yes | Get integrated logistics quote | — |
| FUL | FUL-002 | POST | /orders/{order_id}/shipments | STORE_STAFF/internal | Yes | Create Shiprocket shipment | shipment.created.v1 |
| FUL | FUL-003 | GET | /shipments/{shipment_id} | CUSTOMER/STORE_STAFF | N/A | Read shipment/tracking | — |
| FUL | FUL-004 | POST | /shipments/{shipment_id}/cancel | STORE_STAFF | Yes | Cancel eligible shipment | shipment.cancelled.v1 |
| FUL | FUL-005 | POST | /webhooks/shiprocket | Shiprocket webhook | Provider event ID | Normalize tracking/delivery/COD facts | shipment.* / cod.delivery-confirmed.v1 |
| FUL | FUL-006 | POST | /digital-entitlements/{id}/link | CUSTOMER/internal | Yes | Issue/reissue signed download link | digital.link-issued.v1 |
| FUL | FUL-007 | GET | /digital-download/{token} | CUSTOMER token | Token single policy | Validate and redirect/stream signed object | digital.downloaded.v1 |
| FIN | FIN-001 | GET | /tenants/{tenant_id}/commissions | Tenant/Admin | N/A | List commission records | — |
| FIN | FIN-002 | GET | /commission-invoices | Tenant/Admin | N/A | List weekly commission invoices | — |
| FIN | FIN-003 | GET | /commission-invoices/{id} | Tenant/Admin | N/A | Read invoice/lines | — |
| FIN | FIN-004 | POST | /commission-invoices/{id}/record-payment | Finance/Internal | Yes | Record platform dues payment | commission.invoice-paid.v1 |
| FIN | FIN-005 | POST | /commissions/{id}/dispute | STORE_OWNER | Yes | Open pay-first dispute | commission.dispute-opened.v1 |
| FIN | FIN-006 | POST | /commission-disputes/{id}/decision | Platform finance | Yes | Apply decision/credit | commission.credit-applied.v1 |
| FIN | FIN-007 | GET | /tenants/{tenant_id}/platform-invoices | Tenant/Admin | N/A | Subscriptions/setup/GST/domain invoices | — |
| FIN | FIN-008 | POST | /internal/platform-payments | Internal payment adapter | Yes | Record platform fee payment | finance.platform-payment-recorded.v1 |
| CMP | CMP-001 | POST | /compliance/documents | STORE_OWNER | Yes | Submit licence/brand/compliance evidence | compliance.document-submitted.v1 |
| CMP | CMP-002 | POST | /gst/cases | STORE_OWNER/GST_STAFF | Yes | Open GST service case | gst.requested.v1 |
| CMP | CMP-003 | GET | /gst/cases/{id} | Tenant/GST_STAFF | N/A | Read GST workflow | — |
| CMP | CMP-004 | POST | /gst/cases/{id}/drafts | GST_STAFF | Yes | Create immutable return draft | gst.draft-ready.v1 |
| CMP | CMP-005 | POST | /gst/cases/{id}/approve | STORE_OWNER authorized approver | Yes | Tenant approval of exact draft | gst.tenant-approved.v1 |
| CMP | CMP-006 | POST | /gst/cases/{id}/file | GST_STAFF | Yes | Record authorized filing | gst.filed.v1 |
| CMP | CMP-007 | POST | /complaints | PUBLIC/CUSTOMER | Yes | Open consumer grievance | compliance.complaint-opened.v1 |
| CMP | CMP-008 | GET | /stores/{store_id}/restrictions | Assigned/Internal | N/A | Resolve active restrictions | — |
| CMP | CMP-009 | POST | /risk/cases/{id}/restrict | Platform authorized | Yes | Apply store/tenant restriction | risk.restriction-applied.v1 |
| CMP | CMP-010 | POST | /restrictions/{id}/lift | Platform authorized | Yes | Lift restriction after guards | risk.restriction-lifted.v1 |
| CMP | CMP-011 | POST | /tenants/{tenant_id}/terminate | PLATFORM_OWNER | Yes | Permanent termination | risk.tenant-terminated.v1 |
| NTF | NTF-001 | POST | /internal/notifications | SERVICE | Yes | Queue transactional notification | notification.queued.v1 |
| NTF | NTF-002 | GET | /admin/notifications/{id} | Platform staff | N/A | Inspect delivery state | — |
| NTF | NTF-003 | POST | /admin/templates | Platform authorized | Yes | Create template version | notification.template-created.v1 |
| NTF | NTF-004 | POST | /webhooks/notifications/{provider} | Provider webhook | Provider event ID | Record delivery callback | notification.delivery-updated.v1 |
| ANL | ANL-001 | GET | /stores/{store_id}/analytics | Entitled store user | N/A | Basic/advanced analytics by entitlement | — |
| ANL | ANL-002 | POST | /ai/content | Scale AI user | Yes | Generate governed content draft | ai.output-created.v1 |
| ANL | ANL-003 | POST | /ai/seo | Scale AI user | Yes | Generate SEO suggestions | ai.output-created.v1 |
| ANL | ANL-004 | POST | /ai/recommendations | Scale AI user | Yes | Generate non-autonomous recommendations | ai.recommendation-created.v1 |
| ANL | ANL-005 | GET | /stores/{store_id}/ai/usage | Scale AI user/Admin | N/A | Usage/quota ledger | — |

# Appendix B — Event Registry

| Topic | Producer | Event type | Primary consumers |
| --- | --- | --- | --- |
| identity.lifecycle | IAM | identity.principal.created.v1 | TEN, NTF, security/analytics as applicable |
| identity.lifecycle | IAM | identity.session.revoked.v1 | TEN, NTF, security/analytics as applicable |
| identity.lifecycle | IAM | identity.role-assigned.v1 | TEN, NTF, security/analytics as applicable |
| identity.lifecycle | IAM | identity.role-revoked.v1 | TEN, NTF, security/analytics as applicable |
| identity.lifecycle | IAM | identity.otp.verified.v1 | TEN, NTF, security/analytics as applicable |
| identity.lifecycle | IAM | identity.security-event.recorded.v1 | TEN, NTF, security/analytics as applicable |
| tenant.lifecycle | TEN | tenant.registration-started.v1 | SUB, DOM, NTF, CMP, ANL |
| tenant.lifecycle | TEN | tenant.activated.v1 | SUB, DOM, NTF, CMP, ANL |
| tenant.lifecycle | TEN | tenant.guardian-required.v1 | SUB, DOM, NTF, CMP, ANL |
| tenant.lifecycle | TEN | guardian.verification-started.v1 | SUB, DOM, NTF, CMP, ANL |
| tenant.lifecycle | TEN | guardian.consent.accepted.v1 | SUB, DOM, NTF, CMP, ANL |
| tenant.lifecycle | TEN | tenant.adult-reverified.v1 | SUB, DOM, NTF, CMP, ANL |
| tenant.lifecycle | TEN | gstin.verified.v1 | SUB, DOM, NTF, CMP, ANL |
| tenant.lifecycle | TEN | store.created.v1 | SUB, DOM, NTF, CMP, ANL |
| tenant.lifecycle | TEN | store.free-entitlement-consumed.v1 | SUB, DOM, NTF, CMP, ANL |
| tenant.lifecycle | TEN | store.staff-assigned.v1 | SUB, DOM, NTF, CMP, ANL |
| subscription.lifecycle | SUB | subscription.activation-quote-created.v1 | DOM, COM, BKG, NTF, ANL, FIN |
| subscription.lifecycle | SUB | subscription.activated.v1 | DOM, COM, BKG, NTF, ANL, FIN |
| subscription.lifecycle | SUB | subscription.period-started.v1 | DOM, COM, BKG, NTF, ANL, FIN |
| subscription.lifecycle | SUB | subscription.payment-due.v1 | DOM, COM, BKG, NTF, ANL, FIN |
| subscription.lifecycle | SUB | subscription.grace-entered.v1 | DOM, COM, BKG, NTF, ANL, FIN |
| subscription.lifecycle | SUB | subscription.expired.v1 | DOM, COM, BKG, NTF, ANL, FIN |
| subscription.lifecycle | SUB | subscription.converted-to-free.v1 | DOM, COM, BKG, NTF, ANL, FIN |
| subscription.lifecycle | SUB | subscription.cancellation-notice-recorded.v1 | DOM, COM, BKG, NTF, ANL, FIN |
| subscription.lifecycle | SUB | subscription.upgrade-quote-created.v1 | DOM, COM, BKG, NTF, ANL, FIN |
| subscription.lifecycle | SUB | subscription.upgraded.v1 | DOM, COM, BKG, NTF, ANL, FIN |
| subscription.lifecycle | SUB | subscription.downgrade-requested.v1 | DOM, COM, BKG, NTF, ANL, FIN |
| subscription.lifecycle | SUB | subscription.downgraded.v1 | DOM, COM, BKG, NTF, ANL, FIN |
| subscription.lifecycle | SUB | subscription.reactivated.v1 | DOM, COM, BKG, NTF, ANL, FIN |
| entitlement.changed | SUB | entitlement.changed.v1 | CAT, COM, BKG, DOM, storefront projection |
| domain.lifecycle | DOM | domain.subdomain-assigned.v1 | NTF, ANL, storefront projection |
| domain.lifecycle | DOM | domain.options-checked.v1 | NTF, ANL, storefront projection |
| domain.lifecycle | DOM | domain.selected.v1 | NTF, ANL, storefront projection |
| domain.lifecycle | DOM | domain.purchased.v1 | NTF, ANL, storefront projection |
| domain.lifecycle | DOM | domain.dns-verified.v1 | NTF, ANL, storefront projection |
| domain.lifecycle | DOM | domain.activated.v1 | NTF, ANL, storefront projection |
| domain.lifecycle | DOM | domain.stopped.v1 | NTF, ANL, storefront projection |
| domain.lifecycle | DOM | domain.transfer-review-opened.v1 | NTF, ANL, storefront projection |
| domain.lifecycle | DOM | store.published.v1 | NTF, ANL, storefront projection |
| catalog.lifecycle | CAT | catalog.item-created.v1 | APR, INV, ANL, storefront projection |
| catalog.lifecycle | CAT | catalog.item-operational-changed.v1 | APR, INV, ANL, storefront projection |
| catalog.lifecycle | CAT | catalog.version-created.v1 | APR, INV, ANL, storefront projection |
| catalog.lifecycle | CAT | catalog.item-unpublished.v1 | APR, INV, ANL, storefront projection |
| catalog.lifecycle | CAT | catalog.media-uploaded.v1 | APR, INV, ANL, storefront projection |
| catalog.lifecycle | CAT | storefront.snapshot-invalidated.v1 | APR, INV, ANL, storefront projection |
| approval.lifecycle | APR | content.submitted.v1 | CAT, DOM, CMP, NTF, storefront projection |
| approval.lifecycle | APR | content.approved.v1 | CAT, DOM, CMP, NTF, storefront projection |
| approval.lifecycle | APR | content.rejected.v1 | CAT, DOM, CMP, NTF, storefront projection |
| approval.lifecycle | APR | content.resubmitted.v1 | CAT, DOM, CMP, NTF, storefront projection |
| approval.lifecycle | APR | content.emergency-takedown.v1 | CAT, DOM, CMP, NTF, storefront projection |
| approval.lifecycle | APR | content.unpublished.v1 | CAT, DOM, CMP, NTF, storefront projection |
| customer.lifecycle | CUS | customer.unclaimed-created.v1 | COM/BKG projections, NTF, ANL |
| customer.lifecycle | CUS | customer.claim-challenge-created.v1 | COM/BKG projections, NTF, ANL |
| customer.lifecycle | CUS | customer.claimed.v1 | COM/BKG projections, NTF, ANL |
| customer.lifecycle | CUS | customer.profile-updated.v1 | COM/BKG projections, NTF, ANL |
| customer.lifecycle | CUS | customer.address-created.v1 | COM/BKG projections, NTF, ANL |
| customer.lifecycle | CUS | customer.privacy-requested.v1 | COM/BKG projections, NTF, ANL |
| inventory.lifecycle | INV | inventory.reserved.v1 | COM, NTF/ANL where relevant |
| inventory.lifecycle | INV | inventory.consumed.v1 | COM, NTF/ANL where relevant |
| inventory.lifecycle | INV | inventory.released.v1 | COM, NTF/ANL where relevant |
| inventory.lifecycle | INV | inventory.expired.v1 | COM, NTF/ANL where relevant |
| inventory.lifecycle | INV | inventory.restored.v1 | COM, NTF/ANL where relevant |
| inventory.lifecycle | INV | inventory.adjusted.v1 | COM, NTF/ANL where relevant |
| inventory.lifecycle | INV | inventory.low-stock.v1 | COM, NTF/ANL where relevant |
| order.lifecycle | COM | order.placed.v1 | PAY, FUL, FIN, NTF, ANL, CMP |
| order.lifecycle | COM | order.payment-pending.v1 | PAY, FUL, FIN, NTF, ANL, CMP |
| order.lifecycle | COM | order.paid.v1 | PAY, FUL, FIN, NTF, ANL, CMP |
| order.lifecycle | COM | order.processing.v1 | PAY, FUL, FIN, NTF, ANL, CMP |
| order.lifecycle | COM | order.shipped.v1 | PAY, FUL, FIN, NTF, ANL, CMP |
| order.lifecycle | COM | order.delivered.v1 | PAY, FUL, FIN, NTF, ANL, CMP |
| order.lifecycle | COM | order.cancelled.v1 | PAY, FUL, FIN, NTF, ANL, CMP |
| order.lifecycle | COM | order.returned.v1 | PAY, FUL, FIN, NTF, ANL, CMP |
| order.lifecycle | COM | order.refunded.v1 | PAY, FUL, FIN, NTF, ANL, CMP |
| order.lifecycle | COM | order.failed.v1 | PAY, FUL, FIN, NTF, ANL, CMP |
| order.lifecycle | COM | order.disputed.v1 | PAY, FUL, FIN, NTF, ANL, CMP |
| refund.lifecycle | COM/PAY | refund.requested.v1 | COM/BKG, FIN, INV, NTF, ANL |
| refund.lifecycle | COM/PAY | refund.approved.v1 | COM/BKG, FIN, INV, NTF, ANL |
| refund.lifecycle | COM/PAY | refund.rejected.v1 | COM/BKG, FIN, INV, NTF, ANL |
| refund.lifecycle | COM/PAY | refund.processing.v1 | COM/BKG, FIN, INV, NTF, ANL |
| refund.lifecycle | COM/PAY | refund.completed.v1 | COM/BKG, FIN, INV, NTF, ANL |
| booking.lifecycle | BKG | booking.requested.v1 | PAY, FIN, NTF, ANL, CMP |
| booking.lifecycle | BKG | booking.approved.v1 | PAY, FIN, NTF, ANL, CMP |
| booking.lifecycle | BKG | booking.payment-required.v1 | PAY, FIN, NTF, ANL, CMP |
| booking.lifecycle | BKG | booking.confirmed.v1 | PAY, FIN, NTF, ANL, CMP |
| booking.lifecycle | BKG | booking.rescheduled.v1 | PAY, FIN, NTF, ANL, CMP |
| booking.lifecycle | BKG | booking.completed.v1 | PAY, FIN, NTF, ANL, CMP |
| booking.lifecycle | BKG | booking.cancelled.v1 | PAY, FIN, NTF, ANL, CMP |
| booking.lifecycle | BKG | booking.rejected.v1 | PAY, FIN, NTF, ANL, CMP |
| booking.lifecycle | BKG | booking.no-show.v1 | PAY, FIN, NTF, ANL, CMP |
| booking.lifecycle | BKG | booking.refunded.v1 | PAY, FIN, NTF, ANL, CMP |
| payment.lifecycle | PAY | payment.intent-created.v1 | COM, BKG, FIN, NTF, CMP |
| payment.lifecycle | PAY | payment.confirmed.v1 | COM, BKG, FIN, NTF, CMP |
| payment.lifecycle | PAY | payment.failed.v1 | COM, BKG, FIN, NTF, CMP |
| payment.lifecycle | PAY | payment.refund-initiated.v1 | COM, BKG, FIN, NTF, CMP |
| payment.lifecycle | PAY | payment.refund-confirmed.v1 | COM, BKG, FIN, NTF, CMP |
| payment.lifecycle | PAY | payment.provider-connected.v1 | COM, BKG, FIN, NTF, CMP |
| payment.lifecycle | PAY | payment.provider-disconnected.v1 | COM, BKG, FIN, NTF, CMP |
| payment.lifecycle | PAY | payment.reconciled.v1 | COM, BKG, FIN, NTF, CMP |
| shipment.lifecycle | FUL | shipment.created.v1 | COM, FIN, NTF, ANL |
| shipment.lifecycle | FUL | shipment.in-transit.v1 | COM, FIN, NTF, ANL |
| shipment.lifecycle | FUL | shipment.delivered.v1 | COM, FIN, NTF, ANL |
| shipment.lifecycle | FUL | shipment.returned.v1 | COM, FIN, NTF, ANL |
| shipment.lifecycle | FUL | shipment.cancelled.v1 | COM, FIN, NTF, ANL |
| shipment.lifecycle | FUL | cod.delivery-confirmed.v1 | COM, FIN, NTF, ANL |
| digital-fulfilment.lifecycle | FUL | digital.entitlement-issued.v1 | COM, NTF, ANL |
| digital-fulfilment.lifecycle | FUL | digital.link-issued.v1 | COM, NTF, ANL |
| digital-fulfilment.lifecycle | FUL | digital.downloaded.v1 | COM, NTF, ANL |
| digital-fulfilment.lifecycle | FUL | digital.link-expired.v1 | COM, NTF, ANL |
| digital-fulfilment.lifecycle | FUL | digital.entitlement-exhausted.v1 | COM, NTF, ANL |
| commission.lifecycle | FIN | commission.pending-trigger.v1 | CMP, NTF, ANL, SUB where dues affect state |
| commission.lifecycle | FIN | commission.receivable.v1 | CMP, NTF, ANL, SUB where dues affect state |
| commission.lifecycle | FIN | commission.invoiced.v1 | CMP, NTF, ANL, SUB where dues affect state |
| commission.lifecycle | FIN | commission.invoice-paid.v1 | CMP, NTF, ANL, SUB where dues affect state |
| commission.lifecycle | FIN | commission.invoice-overdue.v1 | CMP, NTF, ANL, SUB where dues affect state |
| commission.lifecycle | FIN | commission.dispute-opened.v1 | CMP, NTF, ANL, SUB where dues affect state |
| commission.lifecycle | FIN | commission.credit-created.v1 | CMP, NTF, ANL, SUB where dues affect state |
| commission.lifecycle | FIN | commission.credit-applied.v1 | CMP, NTF, ANL, SUB where dues affect state |
| commission.lifecycle | FIN | commission.cancelled-nonpayable.v1 | CMP, NTF, ANL, SUB where dues affect state |
| platform-finance.lifecycle | FIN | finance.platform-invoice-issued.v1 | SUB, DOM, CMP, NTF |
| platform-finance.lifecycle | FIN | finance.platform-payment-recorded.v1 | SUB, DOM, CMP, NTF |
| platform-finance.lifecycle | FIN | finance.due-cleared.v1 | SUB, DOM, CMP, NTF |
| platform-finance.lifecycle | FIN | finance.credit-note-issued.v1 | SUB, DOM, CMP, NTF |
| compliance.lifecycle | CMP | compliance.document-submitted.v1 | NTF, ANL, APR/CAT where gates apply |
| compliance.lifecycle | CMP | compliance.document-approved.v1 | NTF, ANL, APR/CAT where gates apply |
| compliance.lifecycle | CMP | gst.requested.v1 | NTF, ANL, APR/CAT where gates apply |
| compliance.lifecycle | CMP | gst.draft-ready.v1 | NTF, ANL, APR/CAT where gates apply |
| compliance.lifecycle | CMP | gst.tenant-approved.v1 | NTF, ANL, APR/CAT where gates apply |
| compliance.lifecycle | CMP | gst.filed.v1 | NTF, ANL, APR/CAT where gates apply |
| compliance.lifecycle | CMP | gst.acknowledged.v1 | NTF, ANL, APR/CAT where gates apply |
| compliance.lifecycle | CMP | compliance.complaint-opened.v1 | NTF, ANL, APR/CAT where gates apply |
| risk.lifecycle | CMP | risk.signal-created.v1 | COM, BKG, DOM, SUB, NTF, ANL |
| risk.lifecycle | CMP | risk.restriction-applied.v1 | COM, BKG, DOM, SUB, NTF, ANL |
| risk.lifecycle | CMP | risk.restriction-lifted.v1 | COM, BKG, DOM, SUB, NTF, ANL |
| risk.lifecycle | CMP | risk.tenant-terminated.v1 | COM, BKG, DOM, SUB, NTF, ANL |
| notification.delivery | NTF | notification.queued.v1 | Operations/ANL |
| notification.delivery | NTF | notification.sent.v1 | Operations/ANL |
| notification.delivery | NTF | notification.failed.v1 | Operations/ANL |
| notification.delivery | NTF | notification.delivery-updated.v1 | Operations/ANL |
| analytics.ingest | ANL/edge | analytics.page-view.v1 | ANL |
| analytics.ingest | ANL/edge | analytics.item-view.v1 | ANL |
| analytics.ingest | ANL/edge | analytics.form-submitted.v1 | ANL |

# Appendix C — Standard Error Code Registry

| Code | HTTP | Meaning |
| --- | --- | --- |
| INVALID_STATE_TRANSITION | 409 | Command not permitted from persisted state. |
| TENANT_PAN_ALREADY_REGISTERED | 409 | PAN already mapped to tenant. |
| FREE_STORE_ENTITLEMENT_CONSUMED | 409 | Lifetime Free Store already consumed. |
| GSTIN_REQUIRED | 422 | Paid activation lacks GSTIN. |
| GSTIN_NOT_OWNED | 409 | GSTIN does not belong to tenant PAN. |
| GSTIN_ALREADY_USED | 409 | GSTIN already bound to another paid store. |
| GUARDIAN_REQUIRED | 409 | Minor flow requires Guardian completion. |
| ENTITLEMENT_REQUIRED | 403 | Current plan/state lacks capability. |
| COMMERCE_SUSPENDED | 403 | Restriction blocks new commerce. |
| SUBSCRIPTION_EXPIRED | 403 | Expired/free state blocks new commerce. |
| CROSS_STORE_CHECKOUT_NOT_ALLOWED | 409 | Mixed store checkout attempted. |
| MIXED_CHECKOUT_NOT_ALLOWED | 409 | Disallowed product/service or service-type mixing. |
| INSUFFICIENT_INVENTORY | 409 | Atomic stock reservation failed. |
| CAPACITY_UNAVAILABLE | 409 | Slot capacity unavailable. |
| PAYMENT_NOT_CONFIRMED | 409 | No authoritative provider confirmation. |
| UPI_NOT_SUPPORTED | 422 | UPI requested through KarobarOne checkout. |
| CUSTOM_DOMAIN_REQUIRED | 409 | Paid publication without verified custom domain. |
| CONTENT_APPROVAL_REQUIRED | 409 | Controlled content not approved. |
| CANCELLATION_WINDOW_CLOSED | 409 | Initial cancellation notice at/after P3 start. |
| UPGRADE_APPROVAL_REQUIRED | 409 | Upgrade/discount approval or payment missing. |
| REFUND_NOT_ALLOWED | 409 | Refund disallowed by state/policy/rights evaluation. |
| IDEMPOTENCY_CONFLICT | 409 | Same idempotency key used with different request. |
| STALE_VERSION | 409 | Optimistic concurrency mismatch. |
| RATE_LIMITED | 429 | Rate/abuse threshold exceeded. |
| DEPENDENCY_UNAVAILABLE | 503 | Required provider/service unavailable. |

# Appendix D — State/API/Event Traceability

| Domain | API commands | Event topics | State-machine linkage |
| --- | --- | --- | --- |
| Tenant/Guardian | TEN-001/TEN-003/TEN-004/TEN-005 | tenant.lifecycle | REGISTRATION → AGE_CHECK → STANDARD_TENANT OR GUARDIAN flow |
| Store/Publication | TEN-008, DOM-001, DOM-007 | tenant.lifecycle, domain.lifecycle, entitlement.changed | FREE_PRESENCE / PAID_SETUP / PAID_READY / PUBLIC_LIVE |
| Content approval | CAT-006, APR-004/005/006 | approval.lifecycle | DRAFT → PENDING → APPROVED/LIVE or REJECTED; emergency takedown |
| Customer claim | CUS-001/002/003 | customer.lifecycle, identity.lifecycle | UNCLAIMED → CLAIM_CHALLENGE → CLAIMED |
| Inventory | INV-002/003/004 | inventory.lifecycle | ACTIVE → CONSUMED / RELEASED / EXPIRED |
| Order | COM-003/006/007/008/010 | order.lifecycle, refund.lifecycle | PLACED → PAYMENT_PENDING → PAID → PROCESSING → SHIPPED → DELIVERED etc. |
| Payment | PAY-003/005/006 | payment.lifecycle, refund.lifecycle | CREATED → PENDING → CONFIRMED/FAILED; refund flow |
| Fulfilment | FUL-002/004/005/006 | shipment.lifecycle, digital-fulfilment.lifecycle | Shipment and digital entitlement technical states |
| Booking | BKG-002/004/005/007/008/009/010 | booking.lifecycle | REQUESTED → APPROVED/PAYMENT_PENDING/CONFIRMED → COMPLETED etc. |
| Commission | FIN-004/005/006 | commission.lifecycle | PENDING_TRIGGER → RECEIVABLE → INVOICED → PAID; dispute/credit |
| Subscription | SUB-003/006/008/009/010 | subscription.lifecycle, entitlement.changed | Initial periods, cancellation, delinquency, Free conversion, reactivation |
| GST | CMP-002/004/005/006 | compliance.lifecycle | Requested → draft → tenant approved → filed → acknowledged |
| Risk | CMP-009/010/011 | risk.lifecycle | Signal/case → restriction applied/lifted or termination |

# Appendix E — Contract Checklist

- ☐ Every state-changing API maps to an explicit state-machine transition/command.
- ☐ Every retry-sensitive API declares Idempotency-Key behavior.
- ☐ Every endpoint declares actor/authorization scope.
- ☐ No API trusts client-supplied tenant/store scope without server validation.
- ☐ No endpoint marks payment successful from browser redirect alone.
- ☐ UPI is absent from KarobarOne checkout payment-method contracts.
- ☐ No product/service or cross-store checkout contract exists.
- ☐ No self-shipping/local-pickup API exists for V1.
- ☐ Every financially material fact snapshots inputs/rates/amounts and emits only after commit.
- ☐ Every transactionally significant event is produced through outbox.
- ☐ Every consumer is idempotent/inbox-protected.
- ☐ Event types are granular and versioned; topic names may remain coarse-grained.
- ☐ Kafka is never used as the authoritative timer.
- ☐ Public content APIs expose only approved/live data.
- ☐ Guardian role cannot silently acquire store-management capability.
- ☐ Existing obligations remain manageable during applicable suspension/expiry states.
- ☐ Historical order/booking/payment/commission/subscription/GST records are not destructively rewritten.
- ☐ OpenAPI and event schemas are committed and compatibility-tested in CI.
- ☐ Provider webhooks are signature/auth validated, raw-retained, deduplicated and replay-safe.
- ☐ AC-001..AC-090 remain mapped to automated acceptance tests.
**Engineering Baseline Statement**

This REST API & Kafka Event Contract Specification V1.0 is the proposed interface baseline for KarobarOne V1. It is intended to be converted directly into FastAPI/Pydantic request and response models, committed OpenAPI contracts, JSON event schemas and an AsyncAPI contract. Business behavior remains governed by BRD V2.1 and the deterministic State Machine & Business Rules Specification.
