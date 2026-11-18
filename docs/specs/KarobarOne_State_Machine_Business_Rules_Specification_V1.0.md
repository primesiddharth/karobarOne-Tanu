**KAROBARONE**

**State Machine & Business Rules Specification**

Multi-Tenant SaaS Portfolio, Hybrid Commerce, Booking, GST Compliance & AI Platform

**Specification Version 1.0
13 September 2026**

Derived from:
KarobarOne BRD V2.1 • Backend Technical Design V1.0 • PostgreSQL Schema Specification V1.0

# Document Control

| Field | Value |
| --- | --- |
| Document Version | 1.0 — Initial State Machine & Business Rules Baseline |
| Status | Implementation Specification |
| Effective Date | 13 September 2026 |
| Product | KarobarOne |
| Business Authority | KarobarOne BRD V2.1 — Final Consolidated |
| Technical Inputs | Backend Technical Design V1.0; PostgreSQL Schema Specification V1.0 |
| Primary Users | Backend Engineering, Architecture, Database, QA, Product, Operations, Compliance |
| Purpose | Define deterministic states, transitions, guards, side effects, timers and cross-domain business rules so implementations cannot independently reinterpret lifecycle behavior. |

| Authority — The BRD remains authoritative for business behavior. This specification makes those rules executable. If a business-state transition here conflicts with an explicit BRD requirement, the BRD prevails and this document must be corrected. |
| --- |

| Technical-state rule — Retry, integration, scheduler and queue states that are not named in the BRD are labelled Technical State / Design Decision. They may change without changing externally observable business policy. |
| --- |

# Document Contents

- 1. Purpose, Scope and Normative Hierarchy
- 2. State-Machine Conventions
- 3. Global Business Invariants
- 4. Tenant Registration & Minor/Guardian State Machine
- 5. Store, Entitlement & Publication State Machine
- 6. Domain Lifecycle State Machine
- 7. Public Content Approval State Machine
- 8. Customer Account Claim State Machine
- 9. Inventory Reservation State Machine
- 10. Product Order State Machine
- 11. Payment State Machine
- 12. Refund State Machine
- 13. Shipment, COD & Digital Fulfilment State Machines
- 14. Booking State Machine
- 15. Commission State Machine
- 16. Commission Invoice & Commerce-Suspension State Machine
- 17. Subscription Lifecycle State Machine
- 18. Upgrade, Downgrade & Reactivation Rules
- 19. GST Compliance State Machine
- 20. Risk, Suspension & Termination State Machine
- 21. Notification, OTP & Scheduled-Job Technical States
- 22. Cross-Domain Orchestration Rules
- 23. Time, Scheduler and Expiry Rules
- 24. Transaction, Concurrency & Idempotency Rules
- 25. Event and Side-Effect Contract
- 26. Error / Transition-Rejection Taxonomy
- 27. Audit, Snapshot and Evidentiary Rules
- 28. Test and Acceptance Rules
- 29. Implementation Sequence
- Appendix A. State-to-Database Mapping
- Appendix B. BRD Rule Traceability
- Appendix C. Acceptance Criteria Ownership

# 1. Purpose, Scope and Normative Hierarchy

## 1.1 Purpose

This specification converts KarobarOne lifecycle requirements into deterministic backend behavior. Every state-changing command or integration event must be evaluated against an explicit current state, guard set and transition rule. Generic status mutation is prohibited for controlled business aggregates.

## 1.2 In Scope

- Tenant/PAN registration and Minor/Guardian progression.
- Store entitlement, publication and domain readiness.
- Content approval/version governance.
- Customer guest-account claiming.
- Inventory reservations and stock movement.
- Orders, payments, refunds, shipping, COD and digital fulfilment.
- Bookings and rescheduling.
- Subscription, advance, delinquency, upgrade, downgrade and reactivation.
- Commission, invoicing, disputes and commerce suspension.
- GST workflow, risk restrictions, notification/OTP technical state, timers and cross-domain side effects.

## 1.3 Normative Hierarchy

| Priority | Artifact | Authority |
| --- | --- | --- |
| 1 | KarobarOne BRD V2.1 | Business rules, commercial behavior, entitlements, acceptance criteria. |
| 2 | This State Machine & Business Rules Specification | Executable interpretation of BRD lifecycle behavior. |
| 3 | Backend Technical Design V1.0 | Service ownership, communication, architecture and runtime patterns. |
| 4 | PostgreSQL Schema Specification V1.0 | Persistence structures, constraints, indexes and RLS. |
| 5 | Code / API / event schemas | Must conform to all above artifacts. |

# 2. State-Machine Conventions

| Term | Meaning |
| --- | --- |
| State | Stable business or technical condition persisted against an aggregate. |
| Transition | Allowed change from one state to another. |
| Trigger | Command, verified external event, scheduler event or approved administrative action that attempts a transition. |
| Guard | Condition that must be true before transition. |
| Atomic action | Database mutation(s) committed in the same transaction as the transition. |
| Side effect | Downstream event/notification/projection/workflow started after commit via outbox. |
| Terminal state | No ordinary forward business transition except explicitly documented reopening/exception handling. |
| Technical State | Implementation-only state not intended as product policy; always labelled as such. |

| Transition command rule — Controlled aggregates expose explicit commands (activate, approve, cancel, reschedule, mark-delivered, etc.). A generic PATCH that accepts arbitrary status values must not be exposed to tenants or ordinary staff. |
| --- |

| Atomicity rule — Persist the new aggregate state, state-history record, audit event and outbox event in one PostgreSQL transaction. External calls occur before the transaction only when needed to obtain an authoritative decision, or after commit through a durable workflow. |
| --- |

# 3. Global Business Invariants

| Rule | Invariant | Source |
| --- | --- | --- |
| GBR-001 | One verified PAN maps to one tenant account. | BR-003, BR-010; AC-001 |
| GBR-002 | One PAN receives one lifetime Free Store entitlement. Upgrading that Free Store does not create a duplicate store. | BR-011..013; AC-002 |
| GBR-003 | A paid store requires one verified GSTIN belonging to the tenant PAN; one GSTIN cannot activate multiple paid stores. | BR-014..019; AC-008..010 |
| GBR-004 | All paid Billing Periods are exactly 30 consecutive calendar days, not calendar months. | BR-031..033; AC-041 |
| GBR-005 | Free Presence is non-transactional: no cart, checkout, commercial order, booking acceptance, online payment or COD. | BR-070; AC-003 |
| GBR-006 | Product and service checkout must remain separate; appointment and non-appointment service transactions remain separate; cross-store checkout is prohibited. | BR-100..104; AC-015..018 |
| GBR-007 | KarobarOne does not receive, hold, split or settle end-customer purchase consideration. | BR-140 principles; AC-090 |
| GBR-008 | UPI is not offered through KarobarOne checkout. | BR-141; AC-089 |
| GBR-009 | Provider webhooks/API events are authoritative for payment state where available; browser redirects alone do not confirm payment. | BR-143 |
| GBR-010 | Negative inventory / overselling is prohibited; stock mutation and reservation are transaction-safe. | BR-115..117 |
| GBR-011 | Controlled public-facing content cannot become LIVE without approval; emergency takedown remains available to Platform Staff. | BR-210..216; AC-079..081 |
| GBR-012 | Historical financial, tax, commercial, consent and audit records are not destructively rewritten because of later state changes. | BR-291..295; AC-082..083 |
| GBR-013 | Commission rate, price, tax and discount inputs used for a commercial transaction are snapshotted and not recalculated from current configuration. | BR-145, BR-163 |
| GBR-014 | Suspension must not prevent management of existing obligations such as existing orders/bookings, shipping, refunds, GST workflow, support and payment of dues where applicable. | BR-175, BR-254; AC-058 |
| GBR-015 | Every controlled transition is auditable with actor/source, previous state, new state, timestamp, correlation ID and reason where applicable. | BR-027, BR-216; Security NFRs |

# 4. Tenant Registration & Minor/Guardian State Machine

| Attribute | Specification |
| --- | --- |
| Owning service | Tenant & Store Service (TEN) |
| Aggregate | Tenant onboarding / Minor identity |
| Persistence | tenant.tenants; tenant.guardians; tenant.guardian_consents; iam.role_assignments |
| BRD / AC references | BR-020..029, BR-060..062, BR-050..053; AC-035..040 |

## States

| State | Type | Meaning |
| --- | --- | --- |
| REGISTRATION | Business | Registration record initiated; tenant not yet active. |
| AGE_CHECK | Business | Age is evaluated from verified identity inputs. |
| STANDARD_TENANT | Business | Adult tenant onboarding requirements satisfied. |
| GUARDIAN_REQUIRED | Business | Registrant is under 18; guardian workflow required. |
| GUARDIAN_VERIFICATION | Business | Minimum guardian identity/relationship evidence is being verified. |
| CONSENT_ACCEPTED | Business | Required guardian legal/privacy/commercial consent captured and bound to document versions. |
| MINOR_TENANT_ACTIVE | Business | Minor Tenant active with Guardian dependency. |
| ADULT_REVERIFICATION_REQUIRED | Business | Former minor has reached 18 and must reverify/accept current terms. |

## Lifecycle

| REGISTRATION → AGE_CHECK
AGE_CHECK ── 18+ ──> STANDARD_TENANT
AGE_CHECK ── under 18 ──> GUARDIAN_REQUIRED → GUARDIAN_VERIFICATION → CONSENT_ACCEPTED → MINOR_TENANT_ACTIVE
MINOR_TENANT_ACTIVE ── turns 18 ──> ADULT_REVERIFICATION_REQUIRED → STANDARD_TENANT |
| --- |

## Transition Matrix

| ID | From → To | Trigger & Guards | Atomic Actions | Side Effects / Rule |
| --- | --- | --- | --- | --- |
| TEN-01 | REGISTRATION → AGE_CHECK | PAN verification completed; date-of-birth/age information available. | Persist verified identity reference and age-check result. | Continue adult or guardian branch. |
| TEN-02 | AGE_CHECK → STANDARD_TENANT | Registrant age ≥ 18; required tenant acceptance captured. | Activate tenant; audit accepted terms/version. | Emit tenant.activated. |
| TEN-03 | AGE_CHECK → GUARDIAN_REQUIRED | Registrant age < 18. | Persist minor flag and guardian-required state. | Block completion of mandatory legal acceptance until guardian workflow. |
| TEN-04 | GUARDIAN_REQUIRED → GUARDIAN_VERIFICATION | Guardian minimum details and ID/relationship evidence submitted. | Create guardian record and verification case. | Guardian notification may be generated. |
| TEN-05 | GUARDIAN_VERIFICATION → CONSENT_ACCEPTED | Guardian verification passed; required declarations accepted. | Append immutable guardian consent records with exact document/version/hash. | Emit guardian.consent.accepted. |
| TEN-06 | CONSENT_ACCEPTED → MINOR_TENANT_ACTIVE | All mandatory minor onboarding requirements satisfied. | Activate minor tenant; retain guardian dependency. | Tenant may create Free Store and eligible Paid Store subject to GSTIN rules. |
| TEN-07 | MINOR_TENANT_ACTIVE → ADULT_REVERIFICATION_REQUIRED | Scheduler determines tenant has reached age 18. | Set reverification-required state; preserve guardian history. | Notify tenant; gate actions requiring fresh adult acceptance. |
| TEN-08 | ADULT_REVERIFICATION_REQUIRED → STANDARD_TENANT | Adult identity reverification passed; then-current terms freshly accepted. | Record new acceptance; remove mandatory Guardian dependency without deleting history. | Emit tenant.adult_reverified. |

## Business Rules

| Rule | Requirement | Source |
| --- | --- | --- |
| TEN-R01 | PAN must be verified before tenant registration completes; same PAN cannot create second tenant. | BR-060; BR-003/010; AC-001 |
| TEN-R02 | A Minor Tenant uses their own valid PAN; a paid GSTIN must belong to that PAN. | BR-020..022; AC-036..037 |
| TEN-R03 | Guardian data collection is limited to the minimum required identity, relationship and consent data. | BR-024..026; AC-038..039 |
| TEN-R04 | Guardian access does not automatically grant operational store-management permissions. | BR-052..053 |
| TEN-R05 | Historical Guardian consent remains retained after adult reverification. | BR-027..029 |

# 5. Store, Entitlement & Publication State Machine

| Attribute | Specification |
| --- | --- |
| Owning service | Tenant & Store Service + Domain & Publication Service |
| Aggregate | Store commerce/publication readiness |
| Persistence | tenant.stores; tenant.free_store_entitlements; subscription.entitlement_snapshots; domain.publication_routes |
| BRD / AC references | BR-011..019, BR-063..075, BR-080..094, BR-250..257; AC-002..014, AC-057..061, AC-083 |

## States

| State | Type | Meaning |
| --- | --- | --- |
| FREE_PRESENCE | Business | Free non-transactional store entitlement. |
| PAID_SETUP | Technical State | Paid activation/setup not yet publicly launchable. |
| PAID_READY | Technical State | Paid subscription/GSTIN ready but publication gate may remain. |
| PUBLIC_LIVE | Technical State | Current approved publication route is serving publicly. |
| SUBSCRIPTION_EXPIRED | Business | Paid entitlement expired; no new orders/bookings. |
| COMMISSION_SUSPENDED | Business | New commerce blocked due to overdue commission. |
| RISK_SUSPENDED | Business | Risk restriction active. |
| ADMIN_SUSPENDED | Business | Administrative restriction active. |
| TERMINATED | Business | Tenant/store permanently terminated where applicable. |
| ARCHIVED | Technical State | Closed store with retained commercial history. |

## Lifecycle

| FREE_PRESENCE ── paid activation ──> PAID_SETUP → PAID_READY → PUBLIC_LIVE
PAID_* ── non-payment day 23 ──> FREE_PRESENCE
ACTIVE/PUBLIC_LIVE ── overdue commission / risk / admin ──> *_SUSPENDED
Historical commercial activity + closure → ARCHIVED; severe breach → TERMINATED |
| --- |

## Transition Matrix

| ID | From → To | Trigger & Guards | Atomic Actions | Side Effects / Rule |
| --- | --- | --- | --- | --- |
| STO-01 | new → FREE_PRESENCE | Lifetime Free Store entitlement available; required content later approved for publication. | Consume one lifetime free entitlement only once; create store + immutable subdomain. | Commerce features remain disabled. |
| STO-02 | FREE_PRESENCE → PAID_SETUP | Verified GSTIN belongs to tenant PAN; selected paid plan initiated. | Preserve same store ID; bind GSTIN and subscription process. | Do not create duplicate store. |
| STO-03 | PAID_SETUP → PAID_READY | Initial paid collection confirmed; subscription active; GSTIN valid. | Enable paid entitlements internally. | Custom domain still required before public paid launch. |
| STO-04 | PAID_READY → PUBLIC_LIVE | Custom domain DNS/config complete; content/policy approval gates satisfied. | Activate publication route. | Emit store.published / domain.route.activated. |
| STO-05 | PUBLIC_LIVE → FREE_PRESENCE | Subscription Day-23 conversion or valid end-after-P3 cancellation. | Disable paid entitlements; custom domain serving stops; activate Free subdomain; choose/derive up to 6 showcase items. | Retain higher-plan data hidden/disabled. |
| STO-06 | PUBLIC_LIVE → COMMISSION_SUSPENDED | Commission invoice overdue under finance policy. | Block creation of new commerce across tenant/PAN scope where applied. | Existing obligations remain manageable. |
| STO-07 | ACTIVE → RISK_SUSPENDED / ADMIN_SUSPENDED | Approved risk/admin action. | Create restriction record with scope/reason. | Do not destroy commercial history. |
| STO-08 | closed → ARCHIVED | Store has historical commercial activity and closure approved. | Archive store while retaining statutory/financial history. | No destructive deletion. |

## Business Rules

| Rule | Requirement | Source |
| --- | --- | --- |
| STO-R01 | Free Store publication is not automatic after PAN verification; required website content must pass approval. | BR-063 |
| STO-R02 | Paid public launch requires valid GSTIN and successful custom-domain configuration. | BR-064..065; AC-085 |
| STO-R03 | Free Store maximum showcase = 6 products/services combined; each item max 1 image and no video. | BR-070..075; AC-003..005 |
| STO-R04 | Paid stores may contain both products and services. | BR-080; AC-007 |
| STO-R05 | On downgrade/free conversion, unavailable higher-plan data is retained but disabled/hidden. | BR-094, BR-185; AC-061 |
| STO-R06 | Store with historical commercial activity is archived rather than destructively erased. | BR-294; AC-083 |

# 6. Domain Lifecycle State Machine

| Attribute | Specification |
| --- | --- |
| Owning service | Domain & Publication Service (DOM) |
| Aggregate | Free subdomain / paid custom domain |
| Persistence | domain.subdomains; domain.domains; domain.publication_routes |
| BRD / AC references | BR-040..049; AC-084..088 |

## States

| State | Type | Meaning |
| --- | --- | --- |
| FREE_SUBDOMAIN_ASSIGNED | Business | Immutable storename.karobarone.com assigned. |
| PREFERENCE_SUBMITTED | Technical State | Tenant domain options received. |
| AVAILABILITY_CHECKED | Technical State | Availability result stored. |
| SELECTED | Technical State | Available option selected. |
| PURCHASE_PENDING | Technical State | Commercial/Platform approval pending. |
| PURCHASED | Technical State | KarobarOne purchased/approved domain. |
| DNS_PENDING | Technical State | DNS/configuration in progress. |
| DNS_VERIFIED | Technical State | Required DNS records successfully verified. |
| ACTIVE | Technical State | Custom domain route serving paid store. |
| STOPPED_FREE_CONVERSION | Technical State | Custom-domain serving stopped after Free conversion. |
| TRANSFER_REVIEW | Technical State | Case-by-case transfer request under review. |

## Lifecycle

| Free: FREE_SUBDOMAIN_ASSIGNED (immutable)
Paid: PREFERENCE_SUBMITTED → AVAILABILITY_CHECKED → SELECTED → PURCHASE_PENDING → PURCHASED → DNS_PENDING → DNS_VERIFIED → ACTIVE
Paid → Free: ACTIVE → STOPPED_FREE_CONVERSION; Free subdomain serves store
Closure transfer request → TRANSFER_REVIEW (no automatic transfer) |
| --- |

## Transition Matrix

| ID | From → To | Trigger & Guards | Atomic Actions | Side Effects / Rule |
| --- | --- | --- | --- | --- |
| DOM-01 | new → FREE_SUBDOMAIN_ASSIGNED | Free Store created; requested slug available and not reserved. | Create immutable subdomain record. | Used for Free Presence and paid-to-free fallback. |
| DOM-02 | PREFERENCE_SUBMITTED → AVAILABILITY_CHECKED | Availability provider response received. | Store checked options and prices where needed. | No purchase yet. |
| DOM-03 | AVAILABILITY_CHECKED → SELECTED | Tenant selects available option. | Persist selection. | Premium/non-standard pricing may require quote/payment. |
| DOM-04 | SELECTED → PURCHASE_PENDING | Platform approval/premium handling required. | Create procurement request. | Standard qualifying domain cost may be included; premium requires separate payment. |
| DOM-05 | PURCHASE_PENDING → PURCHASED | Required approval/payment satisfied. | Persist registrar/provider identifiers. | KarobarOne remains registrant/owner while service active under model. |
| DOM-06 | PURCHASED → DNS_PENDING | Domain connected to platform. | Create DNS verification task. | Scheduler/provider polling. |
| DOM-07 | DNS_PENDING → DNS_VERIFIED | Required records resolve successfully. | Record verified timestamp/evidence. | Paid publication gate may proceed. |
| DOM-08 | DNS_VERIFIED → ACTIVE | Store other publication gates satisfied. | Activate route atomically. | Emit domain.activated. |
| DOM-09 | ACTIVE → STOPPED_FREE_CONVERSION | Store converts to Free Presence. | Deactivate custom-domain serving; keep domain/history record. | Free subdomain becomes active. |
| DOM-10 | closed → TRANSFER_REVIEW | Transfer requested after cancellation/closure. | Open manual case; do not auto-transfer. | Outcome requires mutual agreement. |

## Business Rules

| Rule | Requirement | Source |
| --- | --- | --- |
| DOM-R01 | Free subdomain is immutable once created. | BR-040..041; AC-084 |
| DOM-R02 | Every paid store requires custom domain before public launch. | BR-042..044; AC-085 |
| DOM-R03 | Premium/non-standard domain requires explicit approval and additional payment before purchase. | BR-047; AC-087 |
| DOM-R04 | Domain transfer after closure is case-by-case and not automatically guaranteed. | BR-048; AC-088 |
| DOM-R05 | Paid-to-Free conversion stops custom-domain serving and activates/generates immutable Free subdomain. | BR-049; AC-059 |

# 7. Public Content Approval State Machine

| Attribute | Specification |
| --- | --- |
| Owning service | Approval & Governance Service (APR) |
| Aggregate | Versioned public-facing content |
| Persistence | approval.approval_requests; approval.approval_decisions; approval.takedowns; catalog.*_versions; domain.publication_routes |
| BRD / AC references | BR-210..216, BR-271; AC-079..081 |

## States

| State | Type | Meaning |
| --- | --- | --- |
| DRAFT | Business | Editable version not submitted. |
| PENDING | Business | Submitted for Platform review. |
| APPROVED/LIVE | Business | Approved version may be publicly served. |
| REJECTED | Business | Rejected with mandatory reason/comment. |
| UNPUBLISHED | Business | Previously live version intentionally unpublished. |
| EMERGENCY_TAKEDOWN | Business | Immediate Platform Staff takedown for suspected prohibited/unsafe/illegal/fraudulent content. |

## Lifecycle

| DRAFT → PENDING → APPROVED/LIVE
PENDING → REJECTED → DRAFT → PENDING
APPROVED/LIVE → UNPUBLISHED
APPROVED/LIVE/PENDING → EMERGENCY_TAKEDOWN (Platform Staff) |
| --- |

## Transition Matrix

| ID | From → To | Trigger & Guards | Atomic Actions | Side Effects / Rule |
| --- | --- | --- | --- | --- |
| APR-01 | DRAFT → PENDING | Content type requires approval; version complete enough to review. | Freeze submitted version reference; create approval_request. | Current LIVE version remains unchanged. |
| APR-02 | PENDING → APPROVED/LIVE | Authorized reviewer approves. | Append approval_decision; switch live pointer to approved version. | Emit content.approved. |
| APR-03 | PENDING → REJECTED | Authorized reviewer rejects and supplies reason. | Persist rejection reason/comment. | Tenant may edit/resubmit as a new/revised draft. |
| APR-04 | REJECTED → DRAFT | Tenant edits rejected content. | Create/update draft version only. | No public change. |
| APR-05 | APPROVED/LIVE → UNPUBLISHED | Tenant/admin unpublishes; audit required. | Deactivate publication pointer. | No prior approval required for soft-delete/unpublish. |
| APR-06 | PENDING/APPROVED → EMERGENCY_TAKEDOWN | Authorized Platform Staff suspects illegal/counterfeit/unsafe/fraudulent/prohibited content. | Persist takedown record with actor/reason/evidence ref. | Immediately remove from public serving; may increase risk signal. |

## Business Rules

| Rule | Requirement | Source |
| --- | --- | --- |
| APR-R01 | Pending version never overwrites current LIVE version. | BR-210 |
| APR-R02 | Price, inventory quantity, active/inactive item and operational order/booking status do not require content approval. | BR-210 table |
| APR-R03 | Controlled content cannot go LIVE without approval. | AC-079 |
| APR-R04 | Rejected content must include reason/comment and may be resubmitted. | BR-211..212; AC-080 |
| APR-R05 | AI-generated public-facing content follows the same approval rules. | BR-271 |

# 8. Customer Account Claim State Machine

| Attribute | Specification |
| --- | --- |
| Owning service | Customer Service (CUS) + IAM |
| Aggregate | Store-scoped customer identity |
| Persistence | customer.customers; customer.account_claims; customer.privacy_requests; iam.otp_challenges |
| BRD / AC references | BR-130..136, BR-244..245; AC-076..078 |

## States

| State | Type | Meaning |
| --- | --- | --- |
| UNCLAIMED | Business | Guest checkout-created customer profile without claimed credentials. |
| CLAIM_CHALLENGE | Technical State | Email OTP claim challenge active. |
| CLAIMED | Business | Customer has successfully claimed account and may set permanent password. |
| PRIVACY_REQUEST_OPEN | Technical State | Data-principal request under processing; does not erase statutory records. |

## Lifecycle

| Guest checkout → UNCLAIMED
UNCLAIMED → CLAIM_CHALLENGE → CLAIMED
Customer privacy request → PRIVACY_REQUEST_OPEN → resolved while statutory history is retained |
| --- |

## Transition Matrix

| ID | From → To | Trigger & Guards | Atomic Actions | Side Effects / Rule |
| --- | --- | --- | --- | --- |
| CUS-01 | new → UNCLAIMED | Guest checkout supplies mandatory unique email and mobile within store. | Create store-scoped customer snapshot. | Order/booking references same customer aggregate. |
| CUS-02 | UNCLAIMED → CLAIM_CHALLENGE | Returning customer initiates claim. | Create hashed Email OTP challenge with expiry/attempt limits. | Send OTP notification. |
| CUS-03 | CLAIM_CHALLENGE → CLAIMED | Valid non-expired OTP; attempt/rate limits satisfied. | Mark customer claimed; bind IAM principal. | Allow permanent password creation. |
| CUS-04 | any → PRIVACY_REQUEST_OPEN | Valid privacy/access/deletion request. | Create privacy request workflow record. | Preserve statutory order/invoice/GST/commission/audit records. |

## Business Rules

| Rule | Requirement | Source |
| --- | --- | --- |
| CUS-R01 | Customer identity is unique by email and by mobile within one store; same values may exist independently in another store. | BR-130..132; AC-076 |
| CUS-R02 | Guest checkout creates UNCLAIMED customer. | BR-133; AC-077 |
| CUS-R03 | Email OTP is used to claim UNCLAIMED account. | BR-134, BR-244; AC-078 |
| CUS-R04 | Customer deletion requests cannot destroy legally required commercial/tax history. | BR-136; BR-291 |

# 9. Inventory Reservation State Machine

| Attribute | Specification |
| --- | --- |
| Owning service | Inventory Service (INV) |
| Aggregate | Tracked SKU reservation |
| Persistence | inventory.stock_balances; inventory.reservations; inventory.stock_movements |
| BRD / AC references | BR-112..118 |

## States

| State | Type | Meaning |
| --- | --- | --- |
| ACTIVE | Technical State | Quantity reserved for checkout until expires_at. |
| CONSUMED | Technical State | Reservation converted into committed stock reduction. |
| RELEASED | Technical State | Reservation explicitly released after cancellation/failure. |
| EXPIRED | Technical State | Reservation timed out without conversion. |

## Lifecycle

| AVAILABLE STOCK → ACTIVE reservation (default target 10 min configurable)
ACTIVE → CONSUMED on qualifying order/payment rule
ACTIVE → RELEASED on checkout/order cancellation/failure
ACTIVE → EXPIRED on scheduler timeout |
| --- |

## Transition Matrix

| ID | From → To | Trigger & Guards | Atomic Actions | Side Effects / Rule |
| --- | --- | --- | --- | --- |
| INV-01 | none → ACTIVE | SKU tracks inventory; available_qty ≥ requested_qty; store/cart valid. | Lock/atomic conditional update; increase reserved qty; insert reservation with expires_at. | Return reservation IDs to checkout. |
| INV-02 | ACTIVE → CONSUMED | Order reaches configured qualifying commitment point. | Decrease on-hand/available and reserved consistently; append stock movement. | Emit inventory.consumed. |
| INV-03 | ACTIVE → RELEASED | Checkout/order cancelled or payment fails before consumption. | Decrease reserved qty; append release movement. | Emit inventory.released. |
| INV-04 | ACTIVE → EXPIRED | expires_at reached and reservation still active. | Release reserved quantity atomically. | Emit inventory.expired. |
| INV-05 | CONSUMED → restoration movement | Qualifying cancellation/refund requires stock restoration. | Append compensating stock movement; increase quantity where policy applies. | Never edit historical movement. |

## Business Rules

| Rule | Requirement | Source |
| --- | --- | --- |
| INV-R01 | Inventory tracking is optional per physical SKU; non-tracked products do not require finite stock. | BR-112..114 |
| INV-R02 | Negative inventory/overselling is prohibited. | BR-115 |
| INV-R03 | Inventory changes must be transaction-safe; reservation default target is 10 minutes and configurable. | BR-116..117 |
| INV-R04 | Stock supports reduction after qualifying order and restoration after qualifying cancellation/refund. | BR-116 |

# 10. Product Order State Machine

| Attribute | Specification |
| --- | --- |
| Owning service | Commerce Service (COM) |
| Aggregate | Product order |
| Persistence | commerce.orders; commerce.order_items; commerce.order_status_history; inventory.*; payment.payment_intents; fulfilment.shipments |
| BRD / AC references | BR-100..118, BR-140..158, BR-220..228; AC-015..022, AC-082 |

## States

| State | Type | Meaning |
| --- | --- | --- |
| PLACED | Business | Order created. |
| PAYMENT_PENDING | Business | Payment confirmation required. |
| PAID | Business | Authoritative payment receipt confirmed/verified. |
| PROCESSING | Business | Seller processing order. |
| SHIPPED | Business | Approved logistics confirms shipment/in-transit handoff. |
| DELIVERED | Business | Approved logistics confirms delivery. |
| CANCELLED | Business | Order cancelled under applicable rules. |
| RETURNED | Business | Return received/recognized. |
| REFUNDED | Business | Refund completed/recorded. |
| FAILED | Business | Order/checkout could not complete. |
| DISPUTED | Business | Operational dispute open. |

## Lifecycle

| PLACED → PAYMENT_PENDING → PAID → PROCESSING → SHIPPED → DELIVERED
PLACED/PAYMENT_PENDING/PAID/PROCESSING → CANCELLED where policy allows
DELIVERED → RETURNED → REFUNDED where returnable and approved
Any relevant commercial state → DISPUTED (controlled case), failed checkout/payment → FAILED |
| --- |

## Transition Matrix

| ID | From → To | Trigger & Guards | Atomic Actions | Side Effects / Rule |
| --- | --- | --- | --- | --- |
| ORD-01 | new → PLACED | Paid store; commerce allowed; cart contains products only; one store; inventory reservation succeeds; totals snapshotted. | Create order + items + snapshots + state history in transaction. | Emit order.placed. |
| ORD-02 | PLACED → PAYMENT_PENDING | Online payment required and not yet authoritatively confirmed. | Persist payment_intent reference. | Customer directed to tenant-connected provider. |
| ORD-03 | PAYMENT_PENDING → PAID | Verified provider webhook/API confirmation or permitted verified receipt. | Set paid_at; append state history; consume applicable reservation. | Emit order.paid; commission trigger for prepaid order. |
| ORD-04 | PAID → PROCESSING | Seller accepts/starts fulfillment. | Append state transition. | Shipment creation may start. |
| ORD-05 | PROCESSING → SHIPPED | Approved logistics provider confirms shipment. | Bind shipment reference; append state. | Customer shipping notification. |
| ORD-06 | SHIPPED → DELIVERED | Approved logistics confirms delivery. | Set delivered_at. | COD delivery triggers commission receivable. |
| ORD-07 | pre-shipment eligible → CANCELLED | Customer/seller cancellation request valid under policy and payment/shipping state. | Append cancellation; release stock or create compensating movement; initiate refund if prepaid. | Commission adjustment as applicable. |
| ORD-08 | DELIVERED → RETURNED | Returnable physical product; request approved; seller confirms receipt. | Record returned quantity/condition/evidence; restore stock where applicable. | Refund workflow may proceed. |
| ORD-09 | refund completed → REFUNDED | Provider/manual refund completion recorded. | Snapshot refund amount/method/reference. | Emit refund.completed; proportional commission credit where applicable. |
| ORD-10 | checkout/order → FAILED | Irrecoverable creation/payment failure before valid commercial completion. | Release reservations; persist failure reason. | No commission trigger unless separate valid event already occurred. |

## Business Rules

| Rule | Requirement | Source |
| --- | --- | --- |
| ORD-R01 | Product checkout may combine physical and digital products but never services. | BR-100..102; AC-015..017 |
| ORD-R02 | One cart/order/payment belongs to exactly one store; cross-store checkout prohibited. | BR-103..104; AC-018 |
| ORD-R03 | Before shipment customer may request cancellation. | BR-223 |
| ORD-R04 | Physical return workflow is request → seller review → approved return shipment → seller confirms receipt → refund. | BR-224 |
| ORD-R05 | Digital products are ordinarily non-returnable after successful access/download, subject to mandatory exceptions. | BR-225 |
| ORD-R06 | Partial refunds are supported where operationally applicable and commission adjusts proportionally. | BR-226 |
| ORD-R07 | Commercial order records are not destructively deleted. | BR-257; AC-082 |

# 11. Payment State Machine

| Attribute | Specification |
| --- | --- |
| Owning service | Payment Integration Service (PAY) |
| Aggregate | Payment intent / provider payment |
| Persistence | payment.provider_connections; payment.payment_intents; payment.payment_attempts; payment.webhook_events; payment.provider_refunds |
| BRD / AC references | BR-140..145; AC-022, AC-089..090 |

## States

| State | Type | Meaning |
| --- | --- | --- |
| CREATED | Technical State | Payment intent recorded. |
| PENDING | Technical State | Awaiting authoritative provider outcome. |
| CONFIRMED | Technical State | Successful tenant-receipt signal verified. |
| FAILED | Technical State | Provider reports failure/terminal error. |
| CANCELLED | Technical State | Intent abandoned/cancelled before confirmation. |
| REFUND_PENDING | Technical State | Provider refund initiated. |
| REFUNDED | Technical State | Refund completion verified. |

## Lifecycle

| CREATED → PENDING → CONFIRMED
PENDING → FAILED / CANCELLED
CONFIRMED → REFUND_PENDING → REFUNDED |
| --- |

## Transition Matrix

| ID | From → To | Trigger & Guards | Atomic Actions | Side Effects / Rule |
| --- | --- | --- | --- | --- |
| PAY-01 | new → CREATED | Paid commerce allowed; payment method permitted; tenant provider connection active. | Create intent with order/booking snapshot and idempotency key. | Initiate provider request. |
| PAY-02 | CREATED → PENDING | Provider order/payment reference created. | Persist provider IDs; never store prohibited secrets. | Await webhook/API confirmation. |
| PAY-03 | PENDING → CONFIRMED | Webhook signature valid; event not replayed; provider success matches intent/amount/store context. | Persist raw event + normalized payment state in one transaction. | Emit payment.confirmed; downstream order/booking/commission react. |
| PAY-04 | PENDING → FAILED | Authoritative provider failure. | Persist failure code/detail. | Release reservations/capacity where appropriate. |
| PAY-05 | CONFIRMED → REFUND_PENDING | Approved refund submitted to provider or COD/manual refund workflow recorded. | Create refund record; preserve original payment. | Emit refund.initiated. |
| PAY-06 | REFUND_PENDING → REFUNDED | Authoritative provider completion or manual evidence recorded for supported offline/COD refund. | Append refund completion; do not rewrite original receipt. | Emit refund.completed. |

## Business Rules

| Rule | Requirement | Source |
| --- | --- | --- |
| PAY-R01 | Customer funds are received directly by tenant; KarobarOne does not hold/split/settle purchase consideration. | BR-140 principle; AC-090 |
| PAY-R02 | Tenant-connected Razorpay or approved provider adapter is used; UPI excluded from KarobarOne checkout. | BR-140..141; AC-089 |
| PAY-R03 | Provider webhook/API events are authoritative; browser redirect alone is insufficient. | BR-143 |
| PAY-R04 | If tenant Razorpay is disconnected/suspended, online payment stops; COD may continue only through approved logistics. | BR-144 |
| PAY-R05 | Payment/price/tax/discount/commission-rate snapshots are stored with relevant transaction. | BR-145 |

# 12. Refund State Machine

| Attribute | Specification |
| --- | --- |
| Owning service | Commerce + Payment Services |
| Aggregate | Refund request / completion |
| Persistence | commerce.refund_requests; payment.provider_refunds; finance.commission_adjustments |
| BRD / AC references | BR-222..228, BR-284 |

## States

| State | Type | Meaning |
| --- | --- | --- |
| REQUESTED | Business | Customer/seller refund request recorded. |
| APPROVED | Business | Refund approved under policy/mandatory rights. |
| PROCESSING | Business | Provider/manual refund execution in progress. |
| REFUNDED | Business | Refund completed and evidence recorded. |
| REJECTED | Business | Refund rejected with reason. |

## Lifecycle

| REQUESTED → APPROVED → PROCESSING → REFUNDED
REQUESTED → REJECTED |
| --- |

## Transition Matrix

| ID | From → To | Trigger & Guards | Atomic Actions | Side Effects / Rule |
| --- | --- | --- | --- | --- |
| REF-01 | new → REQUESTED | Order/booking and refund reason valid enough to open case. | Create refund_request with requested amount/lines. | Notify seller/platform as appropriate. |
| REF-02 | REQUESTED → APPROVED | Policy/consumer-right checks pass; authorized approver acts. | Record approved amount/reason. | Create provider/manual refund instruction. |
| REF-03 | REQUESTED → REJECTED | Request invalid under applicable policy/rights; reason mandatory. | Persist rejection reason/evidence. | Notify customer. |
| REF-04 | APPROVED → PROCESSING | Refund execution initiated. | Bind provider_refund/manual evidence record. | Await completion. |
| REF-05 | PROCESSING → REFUNDED | Authoritative completion/evidence available. | Set refund completed; create proportional commission credit where applicable. | Emit refund.completed. |

## Business Rules

| Rule | Requirement | Source |
| --- | --- | --- |
| REF-R01 | Partial refunds supported where operationally applicable. | BR-226 |
| REF-R02 | COD refunds are executed outside KarobarOne by tenant; platform records method/reference/amount/date/evidence. | BR-227 |
| REF-R03 | Commission is proportionally adjusted where relevant. | BR-226; BR-175 note |
| REF-R04 | Tenant-configured policy cannot remove mandatory consumer rights. | BR-284 |

# 13. Shipment, COD & Digital Fulfilment State Machines

| Attribute | Specification |
| --- | --- |
| Owning service | Fulfilment Service (FUL) |
| Aggregate | Shipment + digital entitlement |
| Persistence | fulfilment.shipments; fulfilment.shipment_events; fulfilment.digital_entitlements; fulfilment.download_tokens |
| BRD / AC references | BR-150..158; AC-019..021 |

## States

| State | Type | Meaning |
| --- | --- | --- |
| SHIPMENT_PENDING | Technical State | Shipment required but not yet created with approved provider. |
| SHIPMENT_CREATED | Technical State | Approved logistics shipment/AWB exists. |
| IN_TRANSIT | Technical State | Provider reports shipment in transit. |
| DELIVERED | Technical State | Provider confirms delivery. |
| SHIPMENT_CANCELLED | Technical State | Shipment cancelled before delivery. |
| RETURNED/RTO | Technical State | Provider reports return-to-origin/return state. |
| DIGITAL_ACTIVE | Technical State | Digital download entitlement valid. |
| DIGITAL_EXPIRED | Technical State | 24-hour issued URL/token expired. |
| DIGITAL_EXHAUSTED | Technical State | Maximum downloads reached for issued entitlement/token. |

## Lifecycle

| Physical: SHIPMENT_PENDING → SHIPMENT_CREATED → IN_TRANSIT → DELIVERED
                              └→ SHIPMENT_CANCELLED / RETURNED-RTO
Digital: order eligible → DIGITAL_ACTIVE → DIGITAL_EXPIRED / DIGITAL_EXHAUSTED; replacement secure link may be issued from order history |
| --- |

## Transition Matrix

| ID | From → To | Trigger & Guards | Atomic Actions | Side Effects / Rule |
| --- | --- | --- | --- | --- |
| FUL-01 | pending → SHIPMENT_CREATED | Approved Shiprocket/integrated provider connection; required e-way information satisfied when legally required. | Persist provider shipment/AWB; shipping charge snapshot. | Emit shipment.created. |
| FUL-02 | SHIPMENT_CREATED → IN_TRANSIT | Authoritative provider tracking event. | Append shipment event. | Order may transition to SHIPPED. |
| FUL-03 | IN_TRANSIT → DELIVERED | Authoritative provider delivery event. | Append event + delivered_at. | Order → DELIVERED; COD commission becomes receivable. |
| FUL-04 | eligible order → DIGITAL_ACTIVE | Digital product payment/order conditions satisfied. | Issue signed download token/URL; never expose permanent object URL. | Audit entitlement and downloads. |
| FUL-05 | DIGITAL_ACTIVE → DIGITAL_EXPIRED | Issued URL/token reaches 24-hour validity. | Mark token expired; entitlement history retained. | Customer may request/reissue replacement secure link via order history. |
| FUL-06 | DIGITAL_ACTIVE → DIGITAL_EXHAUSTED | 3 downloads consumed for issued entitlement/token under initial policy. | Increment audited download count; block further use of token. | Replacement may be generated through order history. |

## Business Rules

| Rule | Requirement | Source |
| --- | --- | --- |
| FUL-R01 | Self-shipping and local/store pickup are not supported in V1. | BR-150, BR-153; AC-019 |
| FUL-R02 | Physical shipment and COD require approved integrated logistics provider; initial provider Shiprocket. | BR-151, BR-154; AC-020 |
| FUL-R03 | COD commission recognition occurs upon confirmed delivery from logistics provider. | BR-155; AC-021 |
| FUL-R04 | Digital download URL initial validity = 24 hours; max 3 downloads per issued entitlement; permanent object URLs prohibited. | BR-156..157 |
| FUL-R05 | E-way bill information must be satisfied before shipment where legally required. | BR-158 |

# 14. Booking State Machine

| Attribute | Specification |
| --- | --- |
| Owning service | Booking Service (BKG) |
| Aggregate | Service booking |
| Persistence | booking.bookings; booking.booking_status_history; booking.capacity_reservations; booking.booking_reschedules; payment.payment_intents; finance.commission_records |
| BRD / AC references | BR-120..129, BR-166..171, BR-221; AC-023..027 |

## States

| State | Type | Meaning |
| --- | --- | --- |
| REQUESTED | Business | Booking request created. |
| APPROVED | Business | Seller approves where approval mode applies. |
| PAYMENT_PENDING | Business | Payment/deposit required and awaiting receipt. |
| CONFIRMED | Business | Booking confirmed. |
| RESCHEDULED | Business | Prior booking occurrence rescheduled; history retained. |
| COMPLETED | Business | Service completed. |
| CANCELLED | Business | Booking cancelled under applicable rules. |
| REJECTED | Business | Seller rejects request. |
| NO_SHOW | Business | Customer did not attend. |
| REFUNDED | Business | Applicable refund completed. |

## Lifecycle

| REQUESTED → APPROVED → PAYMENT_PENDING → CONFIRMED → COMPLETED
REQUESTED → REJECTED
REQUESTED/APPROVED/PAYMENT_PENDING/CONFIRMED → CANCELLED
CONFIRMED → RESCHEDULED → new booking occurrence / CONFIRMED
CONFIRMED → NO_SHOW
eligible cancellation/refund → REFUNDED |
| --- |

## Transition Matrix

| ID | From → To | Trigger & Guards | Atomic Actions | Side Effects / Rule |
| --- | --- | --- | --- | --- |
| BKG-01 | new → REQUESTED | Paid store; service transaction type valid; slot/capacity reservation succeeds; price/tax/discount/commission snapshots captured. | Create booking + capacity reservation + state history. | Emit booking.requested. |
| BKG-02 | REQUESTED → APPROVED | Seller-approval mode and authorized seller approves. | Record approval. | If approve-before-pay → PAYMENT_PENDING; otherwise confirmation follows configured sequence. |
| BKG-03 | REQUESTED → CONFIRMED | Instant confirmation mode and payment rules already satisfied / pay-after-service configured. | Consume/hold capacity as confirmed. | Emit booking.confirmed; pay-after-service commission trigger follows BR-166 timing. |
| BKG-04 | APPROVED → PAYMENT_PENDING | Approve-before-pay flow requires payment/deposit. | Set payment deadline; retain capacity reservation. | Scheduler will expire unpaid reservation. |
| BKG-05 | PAYMENT_PENDING → CONFIRMED | Verified payment/deposit received before deadline. | Mark confirmed; payment snapshot stored. | Emit booking.confirmed / payment.confirmed. |
| BKG-06 | PAYMENT_PENDING → CANCELLED | Payment deadline expires unpaid. | Release capacity. | Emit booking.expired/cancelled. |
| BKG-07 | CONFIRMED → RESCHEDULED | Reschedule permitted; new slot capacity reserved atomically. | Persist reschedule linking old/new occurrence; release old capacity only after new reservation succeeds. | Reverse old commission record and create new so only one final commission remains. |
| BKG-08 | CONFIRMED → COMPLETED | Service occurrence completed. | Persist completion. | Operational analytics; pay-after-service commission already triggered on booking date per BRD. |
| BKG-09 | CONFIRMED → CANCELLED | Eligible cancellation under policy/mandatory rights. | Release capacity; initiate refund/commission adjustment as applicable. | Eligible pay-after-service cancellation makes commission non-payable/credited. |
| BKG-10 | REQUESTED/APPROVED → REJECTED | Seller rejects request. | Persist rejection reason. | Valid seller rejection does not automatically remove pay-after-service commission when that trigger applies; verified invalid/fraud/system-error case may credit after dispute. |
| BKG-11 | CONFIRMED → NO_SHOW | Occurrence passed and seller/platform records no-show. | Persist no-show evidence/time. | NO_SHOW does not remove applicable pay-after-service commission. |

## Business Rules

| Rule | Requirement | Source |
| --- | --- | --- |
| BKG-R01 | Appointment and non-appointment services use separate service transactions in V1. | BR-102; AC-017 |
| BKG-R02 | Booking confirmation may be instant or seller approval required; payment sequence supports documented modes including deposits and pay-after-service. | BR-122..125 |
| BKG-R03 | Expired unpaid approve-before-pay reservations release capacity. | BR-125 |
| BKG-R04 | Bookings support rescheduling and NO_SHOW. | BR-126..127 |
| BKG-R05 | Cancellation/refund/no-show policy is subject to mandatory consumer rights. | BR-128 |
| BKG-R06 | Capacity may exceed one customer where configured and must be transaction-safe. | BR-129 |

# 15. Commission State Machine

| Attribute | Specification |
| --- | --- |
| Owning service | Commission & Finance Service (FIN) |
| Aggregate | Commission record |
| Persistence | finance.commission_records; finance.commission_adjustments; finance.commission_invoice_lines; finance.commission_disputes |
| BRD / AC references | BR-160..175; AC-021..030 |

## States

| State | Type | Meaning |
| --- | --- | --- |
| PENDING_TRIGGER | Business | Commercial transaction exists but commission trigger has not yet occurred. |
| RECEIVABLE | Business | Commission obligation has triggered. |
| INVOICED | Business | Included in issued weekly commission invoice/demand. |
| PAID | Business | Tenant paid invoiced commission. |
| DISPUTED_AFTER_PAYMENT | Business | Pay-first dispute is under review after payment. |
| CREDIT_PENDING | Business | Approved reversal/adjustment awaiting application. |
| CREDIT_APPLIED | Business | Credit applied to later balance/invoice. |
| CANCELLED/NON_PAYABLE | Business | Commission determined non-payable under qualifying rule. |

## Lifecycle

| PENDING_TRIGGER → RECEIVABLE → INVOICED → PAID
PAID → DISPUTED_AFTER_PAYMENT → CREDIT_PENDING → CREDIT_APPLIED
PENDING_TRIGGER/RECEIVABLE → CANCELLED/NON_PAYABLE for qualifying cancellation
RECEIVABLE/INVOICED → CREDIT_PENDING for eligible refund/reversal adjustments |
| --- |

## Transition Matrix

| ID | From → To | Trigger & Guards | Atomic Actions | Side Effects / Rule |
| --- | --- | --- | --- | --- |
| FIN-01 | new → PENDING_TRIGGER | Order/booking created; commission rate/base snapshot captured. | Create commission record with source transaction and trigger type. | No receivable yet unless trigger is immediate. |
| FIN-02 | PENDING_TRIGGER → RECEIVABLE | Prepaid payment verified OR COD delivered OR pay-after-service booking date trigger reached. | Set receivable_at; compute base excluding GST/shipping using snapshots. | Eligible for weekly invoice. |
| FIN-03 | RECEIVABLE → INVOICED | Weekly invoice generation picks uninvoiced receivables. | Create immutable invoice line linking commission record. | Issue consolidated tenant invoice/demand. |
| FIN-04 | INVOICED → PAID | Platform verifies commission invoice payment. | Apply receipt to invoice/records. | Lift commission suspension when all applicable overdue conditions resolved. |
| FIN-05 | PAID → DISPUTED_AFTER_PAYMENT | Tenant submits dispute after payment. | Create dispute case; preserve payment. | Pay-first model: no immediate reversal. |
| FIN-06 | DISPUTED_AFTER_PAYMENT → CREDIT_PENDING | Dispute approved. | Create commission_adjustment credit. | Apply to future/current eligible balance. |
| FIN-07 | CREDIT_PENDING → CREDIT_APPLIED | Credit allocated to invoice/balance. | Append credit application. | Do not mutate original commission record/value. |
| FIN-08 | PENDING_TRIGGER/RECEIVABLE → CANCELLED/NON_PAYABLE | Eligible customer cancellation makes commission non-payable under BRD rule. | Persist cancellation/credit reason. | Repeated cancellation may add risk signal. |
| FIN-09 | rescheduled booking → replacement record | Booking rescheduled. | Reverse old commission record and create new record for new booking occurrence. | Guarantee only one final payable commission. |

## Business Rules

| Rule | Requirement | Source |
| --- | --- | --- |
| FIN-R01 | Commission base = taxable product/service value after discounts and eligible refunds, excluding GST and shipping. | BR-161; AC-028 |
| FIN-R02 | Commission rate is snapshotted at order/booking creation; later plan changes do not retrospectively alter it. | BR-163 |
| FIN-R03 | Prepaid commission triggers on verified payment; COD on confirmed delivery; pay-after-service on booking date. | BR-164..166; AC-021..023 |
| FIN-R04 | Eligible cancellation may reverse pay-after-service commission; seller rejection and NO_SHOW do not automatically remove it. | BR-167..170; AC-024..026 |
| FIN-R05 | Rescheduling reverses old and creates new commission; only one final commission payable. | BR-171; AC-027 |
| FIN-R06 | Weekly consolidated invoice; 15-calendar-day payment window; disputes are pay-first/credit-later. | BR-172..174; AC-029..030 |

# 16. Commission Invoice & Commerce-Suspension State Machine

| Attribute | Specification |
| --- | --- |
| Owning service | Commission & Finance + Compliance/Risk |
| Aggregate | Tenant commission invoice and PAN-wide commerce gate |
| Persistence | finance.commission_invoices; finance.commission_invoice_lines; compliance.restrictions |
| BRD / AC references | BR-172..175, BR-253..254; AC-029..030, AC-058 |

## States

| State | Type | Meaning |
| --- | --- | --- |
| DRAFT | Technical State | Weekly invoice aggregation in progress. |
| ISSUED | Technical State | Invoice/demand issued with due date = issue + 15 calendar days. |
| PAID | Technical State | Invoice settled. |
| OVERDUE | Technical State | Due date passed with outstanding amount. |
| COMMISSION_SUSPENDED | Business | New commerce blocked across applicable tenant/PAN stores. |
| CLEARED | Technical State | Overdue condition resolved; restriction may be lifted after reconciliation. |

## Lifecycle

| DRAFT → ISSUED → PAID
ISSUED ── due+outstanding ──> OVERDUE → COMMISSION_SUSPENDED
OVERDUE/COMMISSION_SUSPENDED ── payment/credit resolution ──> CLEARED → active commerce |
| --- |

## Transition Matrix

| ID | From → To | Trigger & Guards | Atomic Actions | Side Effects / Rule |
| --- | --- | --- | --- | --- |
| CINV-01 | DRAFT → ISSUED | Weekly billing run complete; eligible commission lines frozen. | Create invoice number/issue/due dates + immutable lines. | Notify tenant. |
| CINV-02 | ISSUED → PAID | Outstanding reaches zero through verified payment/credits. | Mark paid. | No suspension trigger. |
| CINV-03 | ISSUED → OVERDUE | 15 calendar days elapsed and outstanding > 0. | Mark overdue; audit scheduler action. | Emit commission.invoice.overdue. |
| CINV-04 | OVERDUE → COMMISSION_SUSPENDED | Finance/risk policy applies suspension. | Create tenant/PAN-scoped restriction. | Block new commerce across stores; preserve management of existing obligations. |
| CINV-05 | OVERDUE/SUSPENDED → CLEARED | Outstanding resolved and no blocking issue remains. | Close restriction/reconcile invoice. | Emit commerce.reinstated. |

## Business Rules

| Rule | Requirement | Source |
| --- | --- | --- |
| CINV-R01 | Commission invoice payment period = 15 calendar days. | BR-173 |
| CINV-R02 | Overdue commission may block new commerce across all stores belonging to same PAN. | BR-175; BR-253 |
| CINV-R03 | Existing orders/bookings/refunds/shipping/support/GST/payment-of-dues remain manageable during suspension. | BR-175, BR-254; AC-058 |
| CINV-R04 | Dispute does not defer payment; successful dispute creates later credit. | BR-174; AC-030 |

# 17. Subscription Lifecycle State Machine

| Attribute | Specification |
| --- | --- |
| Owning service | Subscription & Entitlement Service (SUB) |
| Aggregate | Store subscription |
| Persistence | subscription.subscriptions; subscription.subscription_periods; subscription.subscription_charges; subscription.advance_movements; subscription.entitlement_snapshots |
| BRD / AC references | BR-030..039, BR-180..192; AC-041..075 |

## States

| State | Type | Meaning |
| --- | --- | --- |
| INITIAL_PAID_ACTIVATION | Business | First paid activation workflow. |
| ACTIVE_PERIOD_1 | Business | First 30-day paid period. |
| ACTIVE_PERIOD_2 | Business | Second 30-day paid period. |
| P3_FULLY_PREPAID | Business | Cancellation notice before P3; advance fully covers P3. |
| P3_50_PERCENT_DUE | Business | Continuation; 50% of plan price due for P3. |
| P4_50_PERCENT_DUE | Business | Continuation; remaining 50% due for P4. |
| STANDARD_RENEWAL | Business | Period 5 onward full plan price per 30-day period. |
| PAYMENT_GRACE | Business | Days 1–7 after unpaid required due date. |
| SUBSCRIPTION_EXPIRED | Business | Days 8–22 unpaid; site visible but no new orders/bookings. |
| FREE_PRESENCE | Business | Day 23 unpaid or approved end-of-P3 cancellation outcome. |

## Lifecycle

| INITIAL_PAID_ACTIVATION → ACTIVE_PERIOD_1 → ACTIVE_PERIOD_2
  ├─ cancellation before P3 → P3_FULLY_PREPAID → FREE_PRESENCE after P3
  └─ no cancellation → P3_50_PERCENT_DUE → P4_50_PERCENT_DUE → STANDARD_RENEWAL
Any unpaid required due: PAYMENT_GRACE (days 1–7) → SUBSCRIPTION_EXPIRED (days 8–22) → FREE_PRESENCE (day 23) |
| --- |

## Transition Matrix

| ID | From → To | Trigger & Guards | Atomic Actions | Side Effects / Rule |
| --- | --- | --- | --- | --- |
| SUB-01 | INITIAL_PAID_ACTIVATION → ACTIVE_PERIOD_1 | Verified GSTIN; activation collection = Period 1 fee S + Third-Period Advance A3=S; first-ever setup fee = 0. | Create subscription, P1 period, charge lines and advance movement separately identifiable. | Emit subscription.activated + entitlement.changed. |
| SUB-02 | ACTIVE_PERIOD_1 → ACTIVE_PERIOD_2 | P1 ends; required Period 2 full payment S received for next period. | Create exact next 30-day period; do not consume advance. | Continue full paid entitlements. |
| SUB-03 | ACTIVE_PERIOD_2 → P3_FULLY_PREPAID | Cancellation notice successfully recorded before P3 start. | Mark cancellation effective after P3; apply Third-Period Advance fully to P3; additional P3 due = 0. | Paid functionality remains active throughout P3. |
| SUB-04 | P3_FULLY_PREPAID → FREE_PRESENCE | P3 completes. | End paid subscription; convert entitlements/store routing to Free. | Stop custom domain; retain paid data hidden. |
| SUB-05 | ACTIVE_PERIOD_2 → P3_50_PERCENT_DUE | No cancellation notice before P3 start. | Create P3 charge = 0.5S and consume 0.5S advance credit economically. | Continuation path. |
| SUB-06 | P3_50_PERCENT_DUE → P4_50_PERCENT_DUE | P3 required 50% payment received and P3 ends. | Create P4 charge = 0.5S; consume remaining 0.5S advance credit. | Advance economically fully reimbursed across P3/P4. |
| SUB-07 | P4_50_PERCENT_DUE → STANDARD_RENEWAL | P4 required payment received and P4 ends. | Create next exact 30-day full-price period. | Period 5 onward ordinary renewal. |
| SUB-08 | STANDARD_RENEWAL → STANDARD_RENEWAL | Full S received by each subsequent period boundary. | Create next 30-day period. | Continue entitlement. |
| SUB-09 | required payment due → PAYMENT_GRACE | Due date reached and required amount unpaid. | Record delinquency start and reminders. | Paid functionality may continue days 1–7. |
| SUB-10 | PAYMENT_GRACE → SUBSCRIPTION_EXPIRED | Start of Day 8 and still unpaid. | Set expired state; preserve website visibility. | Block new orders/bookings; existing obligations manageable. |
| SUB-11 | SUBSCRIPTION_EXPIRED → FREE_PRESENCE | Start of Day 23 and still unpaid. | Apply unused Third-Period Advance set-off where applicable; convert to Free; disable paid entitlements/custom domain. | Set-off does not reverse delinquency or restore paid status. |
| SUB-12 | PAYMENT_GRACE/EXPIRED → active paid state | Required payment is received before Day 23 and reconciliation succeeds. | Record payment; clear delinquency; resume correct period state. | Emit subscription.recovered. |

## Business Rules

| Rule | Requirement | Source |
| --- | --- | --- |
| SUB-R01 | Billing Period is exactly 30 consecutive calendar days; calculate programmatically. | BR-031..033; AC-041 |
| SUB-R02 | Initial activation = S + Third-Period Advance S; Initial Setup = 0 for first-ever paid activation of each store. | BR-180; BR-036..037; AC-042..043 |
| SUB-R03 | Period 2 requires full S and advance is not normally consumed. | BR-181; AC-044 |
| SUB-R04 | Cancellation notice is valid any time before P3 starts; P3 has ₹0 additional payment and stays fully paid; paid service ends after P3. | BR-182; AC-045..048 |
| SUB-R05 | No cancellation = continuation; P3=0.5S; P4=0.5S; P5+=S. | BR-183; AC-049..053 |
| SUB-R06 | Unpaid due lifecycle = PAYMENT_GRACE days 1–7; SUBSCRIPTION_EXPIRED days 8–22; FREE on Day 23. | BR-184..185; AC-054..061 |
| SUB-R07 | Third-Period Advance does not automatically settle scheduled P2 during normal grace; unused advance may be set off at Free conversion without restoring paid status. | BR-186; AC-062..064 |

# 18. Upgrade, Downgrade & Reactivation Rules

| Attribute | Specification |
| --- | --- |
| Owning service | Subscription & Entitlement Service (SUB) |
| Aggregate | Plan-change request / reactivation |
| Persistence | subscription.plan_change_requests; subscription.upgrade_quotes; subscription.subscription_charges; subscription.entitlement_snapshots |
| BRD / AC references | BR-187..192; AC-065..075 |

## States

| State | Type | Meaning |
| --- | --- | --- |
| UPGRADE_REQUESTED | Technical State | Tenant requested higher paid plan. |
| UPGRADE_QUOTED | Technical State | Prorated/advance/setup calculation frozen. |
| DISCOUNT_REVIEW | Technical State | Optional Upgrade Setup Fee discount awaiting Platform Owner decision. |
| UPGRADE_READY | Technical State | Required amount finalized and ready for collection. |
| UPGRADED | Technical State | Higher plan effective. |
| DOWNGRADE_REQUESTED | Technical State | Lower-plan request recorded. |
| DOWNGRADE_APPROVED | Technical State | Platform Owner due diligence approves future-boundary downgrade. |
| REACTIVATION_REQUESTED | Technical State | Former paid store in Free Presence requests paid reactivation. |
| REACTIVATED | Technical State | New 30-day paid period started after required collection. |

## Lifecycle

| Upgrade: REQUESTED → QUOTED → [DISCOUNT_REVIEW] → READY → UPGRADED
Downgrade: REQUESTED → APPROVED → effective at future Billing Period boundary
Reactivation: FREE_PRESENCE → REACTIVATION_REQUESTED → payment (S + 0.5S setup) → REACTIVATED |
| --- |

## Transition Matrix

| ID | From → To | Trigger & Guards | Atomic Actions | Side Effects / Rule |
| --- | --- | --- | --- | --- |
| PLAN-01 | UPGRADE_REQUESTED → UPGRADE_QUOTED | Target plan higher than current; R days remaining computed from authoritative period. | Freeze quote: prorated difference=(H-L)*R/30; if before P3, advance top-up=max(0,H-existing eligible advance); gross setup=0.5*(H-L). | Quote immutable/auditable. |
| PLAN-02 | UPGRADE_QUOTED → DISCOUNT_REVIEW | Tenant requests Upgrade Setup Fee discount. | Persist requested discount; no automatic waiver. | Platform Owner decision required. |
| PLAN-03 | DISCOUNT_REVIEW → UPGRADE_READY | Platform Owner approves/rejects setup-fee discount with reason. | Persist gross setup, discount amount/rate, net setup and approver/timestamp/reason. | Discount affects setup-fee component only unless explicitly approved otherwise. |
| PLAN-04 | UPGRADE_READY → UPGRADED | Required additional collection confirmed. | Activate higher-plan entitlements immediately if approved; preserve snapshot history. | Emit entitlement.changed. |
| PLAN-05 | DOWNGRADE_REQUESTED → DOWNGRADE_APPROVED | Due diligence confirms lower-plan entitlement compliance and no avoidance of outstanding obligations. | Schedule change for future Billing Period boundary unless otherwise approved. | Retain incompatible higher-plan data hidden/disabled. |
| PLAN-06 | FREE_PRESENCE → REACTIVATION_REQUESTED | Free conversion was caused by non-payment and tenant requests paid plan. | Create reactivation quote: S + Reactivation Setup Fee 0.5S. | First-ever setup waiver cannot be reused. |
| PLAN-07 | REACTIVATION_REQUESTED → REACTIVATED | Full required reactivation collection confirmed. | Start fresh exact 30-day Billing Period at reactivation timestamp/date. | Emit subscription.reactivated / entitlement.changed. |

## Business Rules

| Rule | Requirement | Source |
| --- | --- | --- |
| PLAN-R01 | Upgrade may be effective immediately when approved. | BR-188 |
| PLAN-R02 | Mid-period prorated subscription difference uses remaining days R of current 30-day period. | BR-188; AC-069 |
| PLAN-R03 | Upgrade before P3 recalculates Third-Period Advance to higher plan level. | BR-188 section 20.11; AC-070..071 |
| PLAN-R04 | Gross Upgrade Setup Fee = 50% of higher-lower plan price difference; discount requires Platform Owner approval and is auditable. | BR-189; AC-072..075 |
| PLAN-R05 | Voluntary downgrade normally takes effect at future Billing Period boundary and requires Platform Owner due diligence/approval. | BR-190..192 |
| PLAN-R06 | Reactivation collection = selected plan S + 50% Reactivation Setup Fee; reactivation starts fresh 30-day period. | BR-187; AC-065..068 |

# 19. GST Compliance State Machine

| Attribute | Specification |
| --- | --- |
| Owning service | Compliance & Risk Service (CMP) |
| Aggregate | GST service request / return version |
| Persistence | compliance.gst_service_requests; compliance.gst_return_versions; compliance.gst_approvals; finance.platform_invoices |
| BRD / AC references | BR-200..209; AC-031..034 |

## States

| State | Type | Meaning |
| --- | --- | --- |
| REQUESTED | Technical State | GST assistance requested/identified for store/GSTIN/tax period. |
| QUOTATION_REQUIRED | Technical State | Work is separately chargeable under plan/return conditions. |
| AWAITING_PAYMENT | Technical State | Approved chargeable quotation awaits payment. |
| DATA_COLLECTION | Business workflow step | Required platform/external data being collected. |
| VALIDATION | Business workflow step | Data validation/reconciliation. |
| DRAFT_PREPARED | Business workflow step | Draft GSTR-1/GSTR-3B prepared. |
| COMPLIANCE_REVIEW | Business workflow step | Authorized compliance review. |
| TENANT_APPROVAL_PENDING | Business workflow step | Immutable draft awaiting tenant approval. |
| APPROVED_FOR_FILING | Technical State | Tenant approved exact draft/version. |
| FILED | Business workflow step | Authorized filing completed. |
| ACKNOWLEDGED | Business workflow step | ARN/acknowledgement stored. |

## Lifecycle

| Chargeable: REQUESTED → QUOTATION_REQUIRED → AWAITING_PAYMENT → DATA_COLLECTION
Included NIL workflow: REQUESTED → DATA_COLLECTION
DATA_COLLECTION → VALIDATION → DRAFT_PREPARED → COMPLIANCE_REVIEW → TENANT_APPROVAL_PENDING → APPROVED_FOR_FILING → FILED → ACKNOWLEDGED |
| --- |

## Transition Matrix

| ID | From → To | Trigger & Guards | Atomic Actions | Side Effects / Rule |
| --- | --- | --- | --- | --- |
| GST-01 | REQUESTED → QUOTATION_REQUIRED | Commerce non-NIL OR Growth/Scale filing OR separately chargeable work. | Create quotation scope based on platform/external transactions and reconciliation complexity. | No preparation until quotation accepted/payment where required. |
| GST-02 | REQUESTED → DATA_COLLECTION | Commerce plan + eligible NIL GSTR-1/GSTR-3B bundled service. | Create scoped store/GSTIN/tax-period request. | Collect required data. |
| GST-03 | QUOTATION_REQUIRED → AWAITING_PAYMENT | Tenant approves quotation. | Persist approval/quote version. | Await required payment. |
| GST-04 | AWAITING_PAYMENT → DATA_COLLECTION | Payment confirmed. | Open preparation workflow. | Notify compliance staff. |
| GST-05 | DATA_COLLECTION → VALIDATION | Required data submitted for period. | Freeze/import source files/references. | Run validation/reconciliation. |
| GST-06 | VALIDATION → DRAFT_PREPARED | Validation passes or exceptions resolved. | Create immutable return draft/version. | No filing yet. |
| GST-07 | DRAFT_PREPARED → COMPLIANCE_REVIEW | Draft complete. | Assign/review by authorized compliance staff. | May return to data/draft for corrections. |
| GST-08 | COMPLIANCE_REVIEW → TENANT_APPROVAL_PENDING | Compliance review complete. | Freeze exact draft/version/hash presented to tenant. | Send approval request. |
| GST-09 | TENANT_APPROVAL_PENDING → APPROVED_FOR_FILING | Tenant approves exact immutable draft. | Record approver, timestamp, tax period and version reference. | Mandatory gate before final filing. |
| GST-10 | APPROVED_FOR_FILING → FILED | Authorized filing action succeeds. | Persist filing reference/status. | Await ARN/acknowledgement. |
| GST-11 | FILED → ACKNOWLEDGED | ARN/acknowledgement received. | Store acknowledgement immutably. | Workflow complete. |

## Business Rules

| Rule | Requirement | Source |
| --- | --- | --- |
| GST-R01 | Commerce includes NIL GSTR-1 and NIL GSTR-3B only; non-NIL separately chargeable. | BR-200..201; AC-031..032 |
| GST-R02 | Growth and Scale AI GST filing is separately chargeable. | BR-202; AC-033 |
| GST-R03 | GST service is scoped separately per store/GSTIN and may include external/off-platform data supplied by tenant. | BR-203..205 |
| GST-R04 | Chargeable work follows quotation → tenant approval/payment → preparation. | BR-206 |
| GST-R05 | Final filing requires recorded tenant approval of immutable draft/version. | BR-207..208; AC-034 |
| GST-R06 | QRMP not supported in standard V1 workflow. | BR-209 note / Out of Scope |

# 20. Risk, Suspension & Termination State Machine

| Attribute | Specification |
| --- | --- |
| Owning service | Compliance & Risk Service (CMP) |
| Aggregate | Restriction / platform state |
| Persistence | compliance.risk_signals; compliance.restrictions; tenant.stores; finance.commission_invoices |
| BRD / AC references | BR-250..257; BR-291..295; AC-058, AC-082..083 |

## States

| State | Type | Meaning |
| --- | --- | --- |
| ACTIVE | Technical baseline | No active blocking restriction. |
| COMMISSION_SUSPENDED | Business | New commerce restricted due to overdue commission. |
| RISK_SUSPENDED | Business | Risk-based restriction. |
| ADMIN_SUSPENDED | Business | Administrative restriction. |
| TERMINATED | Business | Permanent tenant/PAN termination for severe qualifying conduct. |

## Lifecycle

| ACTIVE → COMMISSION_SUSPENDED (overdue commission)
ACTIVE → RISK_SUSPENDED (risk review)
ACTIVE/RISK_SUSPENDED → ADMIN_SUSPENDED (authorized admin action)
Any severe case → TERMINATED
Restrictions may start at store scope and escalate to tenant/PAN scope |
| --- |

## Transition Matrix

| ID | From → To | Trigger & Guards | Atomic Actions | Side Effects / Rule |
| --- | --- | --- | --- | --- |
| RSK-01 | ACTIVE → COMMISSION_SUSPENDED | Overdue commission condition and approved enforcement rule. | Create restriction with tenant/PAN scope; preserve source invoice/reason. | Block new commerce; existing obligations remain manageable. |
| RSK-02 | ACTIVE → RISK_SUSPENDED | Risk signals reach review/enforcement outcome. | Create store-level or tenant/PAN-level restriction. | Emit risk.restricted; notify affected tenant as policy permits. |
| RSK-03 | ACTIVE/RISK → ADMIN_SUSPENDED | Authorized administrative action with reason. | Persist actor/reason/scope/evidence. | Apply configured operational blocks. |
| RSK-04 | suspended → ACTIVE | Authorized review determines restriction resolved. | Close restriction with reason/actor. | Restore capabilities subject to subscription/finance state. |
| RSK-05 | any → TERMINATED | Severe fraud, illegal activity, repeated material compliance violations or serious contractual breach. | Persist termination decision; archive required commercial records. | Disable new activity; preserve statutory/financial obligations/history. |

## Business Rules

| Rule | Requirement | Source |
| --- | --- | --- |
| RSK-R01 | Risk may begin at store level and escalate to tenant/PAN level depending on severity/review. | BR-251..252 |
| RSK-R02 | Risk indicators include repeated cancellations/rejections, suspicious payment states, unverified/offline payment patterns, approval violations and suspected commission avoidance. | BR-255 |
| RSK-R03 | During suspension, existing obligations remain manageable where appropriate. | BR-254 |
| RSK-R04 | Termination does not authorize deletion of required commercial history or unpaid obligations. | BR-256..257; BR-291..295 |

# 21. Notification, OTP & Scheduled-Job Technical States

| Attribute | Specification |
| --- | --- |
| Owning service | Notification Service + IAM + Scheduler workers |
| Aggregate | Notification job / OTP challenge / durable scheduled command |
| Persistence | notification.notification_jobs; notification.delivery_attempts; notification.rate_limit_counters; iam.otp_challenges |
| BRD / AC references | BR-240..246; Security NFRs |

## States

| State | Type | Meaning |
| --- | --- | --- |
| QUEUED | Technical State | Notification/scheduled job accepted durably. |
| PROCESSING | Technical State | Worker owns execution attempt. |
| SENT | Technical State | Provider accepted message. |
| DELIVERED | Technical State | Delivery confirmation available where provider supports it. |
| FAILED_RETRYABLE | Technical State | Temporary failure; retry scheduled. |
| FAILED_FINAL | Technical State | Retry policy exhausted/permanent provider error. |
| OTP_ACTIVE | Technical State | Hashed OTP valid until expiry/attempt limit. |
| OTP_VERIFIED | Technical State | OTP successfully verified once. |
| OTP_EXPIRED | Technical State | OTP expired or invalidated. |

## Lifecycle

| Notification: QUEUED → PROCESSING → SENT → [DELIVERED]
                      └→ FAILED_RETRYABLE → QUEUED / FAILED_FINAL
OTP: OTP_ACTIVE → OTP_VERIFIED / OTP_EXPIRED
Scheduled command: durable job due → PROCESSING → completed or retried idempotently |
| --- |

## Transition Matrix

| ID | From → To | Trigger & Guards | Atomic Actions | Side Effects / Rule |
| --- | --- | --- | --- | --- |
| NTF-01 | new → QUEUED | Transactional event requires email/SMS under configured policy/fair-use. | Insert notification_job with template/version and idempotency key. | Worker processes asynchronously. |
| NTF-02 | QUEUED → PROCESSING | Worker claims job using safe concurrency mechanism. | Increment attempt; lock/lease job. | Call provider. |
| NTF-03 | PROCESSING → SENT | Provider accepts message. | Persist provider message ID. | Delivery webhook may later mark delivered. |
| NTF-04 | PROCESSING → FAILED_RETRYABLE | Transient error. | Persist error + next_retry_at. | Retry with bounded backoff. |
| NTF-05 | PROCESSING → FAILED_FINAL | Permanent failure or attempts exhausted. | Persist final reason. | Operational alert for critical notifications. |
| NTF-06 | OTP_ACTIVE → OTP_VERIFIED | Submitted OTP hash matches; challenge unexpired; attempts/rate limits valid. | Set verified_at; invalidate further use. | Continue claim/security flow. |
| NTF-07 | OTP_ACTIVE → OTP_EXPIRED | Expiry reached or abuse/attempt limit exhausted. | Invalidate challenge. | Require new challenge subject to rate limit. |

## Business Rules

| Rule | Requirement | Source |
| --- | --- | --- |
| NTF-R01 | V1 transactional channels are Email and SMS. | BR-240 |
| NTF-R02 | OTP and transactional SMS are subject to configurable limits and abuse protection. | BR-242..245 |
| NTF-R03 | Guardian receives legally necessary Minor Tenant notifications where applicable. | BR-246 |
| NTF-R04 | Notification failure must not roll back an already committed financial/order/payment state transition; delivery is retried asynchronously. | Technical design decision preserving transactional integrity. |

## Technical / Design Decisions

| Design Decision — Kafka is an event transport, not the authoritative timer store. Expiries such as subscription Day 8/23, booking payment deadline, inventory reservation expiry and OTP expiry must be driven by durable due-time data plus an idempotent scheduler/worker. |
| --- |

# 22. Cross-Domain Orchestration Rules

| Rule | Orchestration | Required Behavior |
| --- | --- | --- |
| XDOM-01 | Product checkout | COM validates paid entitlement/store restrictions → INV reserves tracked stock → COM creates order → PAY creates intent → authoritative payment event updates order → FIN commission trigger → NTF notifications. Product/service and cross-store mixing rejected before reservation. |
| XDOM-02 | Booking creation | BKG validates paid entitlement/transaction type → reserves capacity → applies approval/payment sequence → PAY verification where required → FIN commission trigger according to payment mode/date → NTF. |
| XDOM-03 | Paid activation | TEN validates GSTIN ownership/uniqueness → SUB creates initial activation charges/advance → payment/reconciliation confirms collection → SUB activates entitlements → DOM custom-domain workflow → APR/publication gates → route ACTIVE. |
| XDOM-04 | Free conversion | SUB reaches valid conversion transition → entitlement snapshot changes → DOM stops custom domain/activates Free subdomain → CAT publication projection enforces ≤6 showcase items → COM/BKG reject new transactions; history retained. |
| XDOM-05 | COD delivery | FUL receives authoritative delivery → COM order DELIVERED → FIN commission RECEIVABLE → NTF customer/seller event. |
| XDOM-06 | Refund | COM refund approved → PAY/provider/manual execution → REFUNDED → FIN proportional credit/adjustment → INV restoration where policy/condition applies → NTF. |
| XDOM-07 | Reschedule | BKG reserves new capacity first → persists linkage → releases old capacity → FIN reverses old commission/creates new → NTF. No double commission. |
| XDOM-08 | Emergency takedown | APR creates emergency takedown → public route/read model removes content immediately → CMP may add risk signal → audit immutable; current commercial history unaffected. |
| XDOM-09 | Commission suspension | FIN overdue → CMP restriction at tenant/PAN scope → SUB entitlements may remain historically paid but COM/BKG new-transaction guard denies; existing obligation endpoints remain allowed. |
| XDOM-10 | AI public content | ANL/AI output is draft only → CAT version → APR ordinary approval → LIVE. AI must not silently modify price, inventory, tax return, subscription charge or financial records. |

# 23. Time, Scheduler and Expiry Rules

| Timer | Authoritative due data | Scheduler action | Idempotency / Late execution rule |
| --- | --- | --- | --- |
| Inventory reservation | inventory.reservations.expires_at | ACTIVE → EXPIRED; release qty. | Transition guarded by current_state=ACTIVE; repeated execution no-op. |
| Booking payment deadline | booking booking/payment_deadline_at | PAYMENT_PENDING → CANCELLED; release capacity. | If payment already confirmed, expiry command rejected. |
| Subscription Day 1/8/23 | subscription due_date / delinquency_started_at | Enter PAYMENT_GRACE, SUBSCRIPTION_EXPIRED, then FREE_PRESENCE. | Derive from absolute timestamps/dates; missed scheduler run catches up deterministically to correct state. |
| Billing Period boundary | subscription_periods.end_at | Open next exact 30-day period/charge according to current lifecycle. | Unique next-period constraint prevents duplicate periods. |
| Commission invoice due | commission_invoices.due_date | ISSUED → OVERDUE; evaluate restriction. | If outstanding=0, no overdue transition. |
| OTP expiry | iam.otp_challenges.expires_at | OTP_ACTIVE → OTP_EXPIRED. | Verification and expiry compete atomically on current state. |
| Digital token expiry | fulfilment.download_tokens.expires_at | DIGITAL_ACTIVE token → expired. | Downloaded count and expiry checked atomically at download request. |
| Minor reaches 18 | tenant DOB-derived due date | MINOR_TENANT_ACTIVE → ADULT_REVERIFICATION_REQUIRED. | Once transition exists, repeat task no-op. |

| Calendar rule — All subscription periods are exactly 30 consecutive calendar days. Do not use “+1 month” date arithmetic. Store authoritative UTC instants and explicit period_start / period_end values. |
| --- |

# 24. Transaction, Concurrency & Idempotency Rules

| ID | Rule |
| --- | --- |
| TX-01 | State transition, state-history row, audit event and outbox event must commit atomically. |
| TX-02 | Every external webhook is stored raw, signature-validated, deduplicated by provider event ID/hash and normalized idempotently. |
| TX-03 | Every Kafka consumer assumes at-least-once delivery and records processed event IDs/inbox state in the same transaction as side effects. |
| TX-04 | Create/payment/refund/reschedule commands that can be retried require Idempotency-Key scoped to appropriate tenant/store/resource context. |
| TX-05 | Inventory reservation/consume/release and booking-capacity reservation use row-level locking or atomic conditional updates; application-level read-then-write without lock is prohibited. |
| TX-06 | Financial history is append-only. Corrections are compensating journal/commission/advance movements, not UPDATE of historical amount. |
| TX-07 | Order/booking state transitions use optimistic version check or row lock so two concurrent commands cannot both advance from the same state. |
| TX-08 | Cross-service workflows do not use distributed database transactions. Use local transaction + outbox + idempotent consumers/compensating transitions. |
| TX-09 | Cross-service UUID references are validated at command boundary; do not create cross-service hard foreign keys by default. |
| TX-10 | A stale browser/API client cannot force an earlier state by sending a status field; current persisted state controls transition eligibility. |

# 25. Event and Side-Effect Contract

| Topic | Representative facts | Primary consumers |
| --- | --- | --- |
| tenant.lifecycle | tenant.activated, guardian.consent.accepted, adult_reverified, gstin.verified, store.created | SUB, DOM, NTF, CMP, analytics |
| subscription.lifecycle | subscription.activated, grace.entered, expired, converted_to_free, reactivated, upgraded, downgraded | DOM, COM, BKG, NTF, analytics |
| entitlement.changed | resolved capability snapshot changed | COM, BKG, CAT, DOM, storefront projection |
| domain.lifecycle | subdomain.assigned, dns.verified, domain.activated/stopped | DOM projections, NTF, analytics |
| approval.lifecycle | content.submitted, approved, rejected, emergency_takedown | CAT/storefront, CMP, NTF |
| inventory.lifecycle | reserved, consumed, released, expired, restored | COM, analytics |
| order.lifecycle | placed, paid, processing, shipped, delivered, cancelled, returned, refunded | PAY, FUL, FIN, NTF, analytics |
| booking.lifecycle | requested, approved, confirmed, rescheduled, cancelled, completed, no_show | PAY, FIN, NTF, analytics |
| payment.lifecycle | payment.confirmed, payment.failed, refund.completed, provider.disconnected | COM/BKG, FIN, NTF, CMP |
| shipment.lifecycle | created, in_transit, delivered, returned | COM, FIN, NTF, analytics |
| commission.lifecycle | receivable, invoiced, paid, credit_applied, invoice.overdue | CMP, NTF, analytics |
| compliance.lifecycle | gst.requested, draft_ready, tenant_approved, filed, acknowledged | NTF, analytics |
| risk.lifecycle | signal.created, restriction.applied/lifted, terminated | COM, BKG, DOM, NTF |

| Event naming — Topic names may remain coarse-grained as defined in the BTDD; event_type inside the envelope should be specific and versioned (for example subscription.converted_to_free.v1). |
| --- |

# 26. Error / Transition-Rejection Taxonomy

| Code | When to reject |
| --- | --- |
| INVALID_STATE_TRANSITION | Requested transition is not permitted from current persisted state. |
| TENANT_PAN_ALREADY_REGISTERED | Verified PAN already has a tenant. |
| FREE_STORE_ENTITLEMENT_CONSUMED | Lifetime Free Store entitlement already consumed. |
| GSTIN_REQUIRED / GSTIN_NOT_OWNED / GSTIN_ALREADY_USED | Paid activation GSTIN guards fail. |
| GUARDIAN_REQUIRED | Minor flow attempts to bypass mandatory Guardian verification/consent. |
| ENTITLEMENT_REQUIRED | Feature unavailable under current plan/state. |
| COMMERCE_SUSPENDED | New order/booking attempted while commission/risk/admin restriction blocks commerce. |
| SUBSCRIPTION_EXPIRED | New order/booking attempted during SUBSCRIPTION_EXPIRED/Free state. |
| CROSS_STORE_CHECKOUT_NOT_ALLOWED | Cart/checkout references more than one store. |
| MIXED_CHECKOUT_NOT_ALLOWED | Product and service or disallowed service types mixed in one transaction. |
| INSUFFICIENT_INVENTORY | Atomic reservation cannot satisfy requested tracked quantity. |
| CAPACITY_UNAVAILABLE | Requested service slot/capacity cannot be reserved. |
| PAYMENT_NOT_CONFIRMED | Client/browser attempts paid transition without authoritative provider confirmation. |
| UPI_NOT_SUPPORTED | UPI requested through KarobarOne checkout. |
| CUSTOM_DOMAIN_REQUIRED | Paid public launch attempted without verified custom domain. |
| CONTENT_APPROVAL_REQUIRED | Controlled version requested LIVE without approval. |
| CANCELLATION_WINDOW_CLOSED | Initial cancellation notice submitted on/after Period 3 start. |
| UPGRADE_APPROVAL_REQUIRED | Discount/upgrade workflow lacks required approval/payment. |
| REFUND_NOT_ALLOWED | Requested refund is not permitted under current state/policy/mandatory-right evaluation. |
| IDEMPOTENCY_CONFLICT | Same idempotency key reused with materially different request payload. |
| STALE_VERSION | Optimistic concurrency version mismatch. |

# 27. Audit, Snapshot and Evidentiary Rules

| Area | Minimum evidence |
| --- | --- |
| State transition | aggregate_id, old_state, new_state, trigger/command, actor or source, timestamp, correlation_id, reason where applicable. |
| Guardian consent | guardian identity reference, relationship, exact terms/privacy/commercial document version/hash, accepted_at, evidence/signature method. |
| Content approval | submitted version ID, reviewer, decision, timestamp, rejection/takedown reason, prior/live version pointer. |
| Payment webhook | provider event ID, signature-validation result, raw payload retention policy, normalized intent/payment ID, received_at, replay/dedupe status. |
| Subscription calculation | plan_version, S/L/H/R inputs, period dates, charge components, Third-Period Advance movements, setup fee, discounts and approver. |
| Commission | source order/booking, snapshotted rate/base components, trigger fact, invoice line, credits/disputes. |
| GST filing | store/GSTIN/tax period, immutable draft/version, tenant approval actor/timestamp, filing reference, ARN/acknowledgement. |
| Restriction/termination | scope, reason, source signals/invoices, approver, applied/lifted timestamps, evidence references. |

| No retroactive rewrite — Historical PAN/GSTIN/seller identity/order/booking/invoice/commission/subscription snapshots are not rewritten merely because current master data later changes. |
| --- |

# 28. Test and Acceptance Rules

| Test class | Required coverage |
| --- | --- |
| Transition unit tests | Every documented transition has positive guard tests and at least one invalid-from-state test. |
| State-machine property tests | No terminal state can escape except explicitly documented; no arbitrary status assignment; duplicate command remains idempotent. |
| Concurrency tests | Inventory reservation, booking capacity, payment webhook duplicates, refund duplicate, reschedule races and subscription scheduler race. |
| Time-bound tests | 30-day periods, cancellation just-before/at P3 boundary, Day 7/8/22/23 delinquency boundaries, 15-day commission due, 10-minute reservation, OTP/download expiry. |
| Financial tests | Advance movements balance; P3/P4 credits total original advance; upgrade formula; reactivation 1.5S; commission excludes GST/shipping; proportional refund credits. |
| Integration tests | Razorpay webhook signature/dedupe; Shiprocket delivery → COD commission; outbox publish/retry; consumer inbox dedupe. |
| Acceptance tests | All AC-001..AC-090 mapped to automated tests; business-critical ACs block release. |

# 29. Implementation Sequence

| Phase | State machines implemented first | Exit condition |
| --- | --- | --- |
| 1 — Foundation | Transition framework, audit/outbox/idempotency; Tenant/Guardian; Content Approval | No generic status mutation; lifecycle test harness established. |
| 2 — Free Presence | Store/Publications, Domain Free Subdomain, Customer claim | Registration → approved Free Store publication works end-to-end. |
| 3 — Subscription | Subscription lifecycle, upgrade/downgrade/reactivation, timers | AC-041..075 automated and passing. |
| 4 — Commerce | Inventory, Order, Payment, Refund | Product checkout/payment/refund race-safe and idempotent. |
| 5 — Fulfilment | Shipment/COD, Digital fulfilment | Provider delivery drives order/commission correctly. |
| 6 — Booking | Booking/capacity/reschedule/no-show | All payment modes and commission triggers deterministic. |
| 7 — Finance/Risk/GST | Commission invoice/suspension, GST workflow, Risk | PAN-wide restriction and compliance workflows auditable. |
| 8 — Analytics/AI | Event-derived analytics; AI content routes through approval | AI cannot mutate financially material fields silently. |

# Appendix A. State-to-Database Mapping

| State Machine | Authoritative Tables | Event Topic(s) |
| --- | --- | --- |
| Tenant/Guardian | tenant.tenants; tenant.guardians; tenant.guardian_consents | tenant.lifecycle |
| Store/Publication | tenant.stores; subscription.entitlement_snapshots; domain.publication_routes | tenant.lifecycle; entitlement.changed; domain.lifecycle |
| Domain | domain.subdomains; domain.domains; domain.publication_routes | domain.lifecycle |
| Approval | approval.approval_requests; approval.approval_decisions; approval.takedowns | approval.lifecycle |
| Customer claim | customer.customers; customer.account_claims; iam.otp_challenges | customer.lifecycle; identity.lifecycle |
| Inventory | inventory.reservations; inventory.stock_balances; inventory.stock_movements | inventory.lifecycle |
| Order | commerce.orders; commerce.order_status_history; commerce.order_items | order.lifecycle |
| Payment | payment.payment_intents; payment.payment_attempts; payment.webhook_events; provider_refunds | payment.lifecycle; refund.lifecycle |
| Refund | commerce.refund_requests; payment.provider_refunds; finance.commission_adjustments | refund.lifecycle; commission.lifecycle |
| Fulfilment | fulfilment.shipments; fulfilment.shipment_events; digital_entitlements; download_tokens | shipment.lifecycle; digital-fulfilment.lifecycle |
| Booking | booking.bookings; booking.booking_status_history; capacity_reservations; booking_reschedules | booking.lifecycle |
| Commission | finance.commission_records; commission_adjustments; commission_disputes | commission.lifecycle |
| Commission invoice | finance.commission_invoices; commission_invoice_lines; compliance.restrictions | commission.lifecycle; risk.lifecycle |
| Subscription | subscription.subscriptions; subscription_periods; subscription_charges; advance_movements | subscription.lifecycle; entitlement.changed |
| Plan change | subscription.plan_change_requests; upgrade_quotes; entitlement_snapshots | subscription.lifecycle; entitlement.changed |
| GST | compliance.gst_service_requests; gst_return_versions; gst_approvals | compliance.lifecycle |
| Risk | compliance.risk_signals; compliance.restrictions | risk.lifecycle |
| Notification/OTP | notification.notification_jobs; delivery_attempts; iam.otp_challenges | identity.lifecycle / event-driven notifications |

# Appendix B. BRD Rule Traceability

| Machine / Rule Area | BRD Source |
| --- | --- |
| Tenant/Minor/Guardian | BR-002..004, BR-010..029, BR-050..053, BR-060..069 |
| Store/Entitlements | BR-030..039, BR-063..094 |
| Domain | BR-040..049 |
| Checkout/Inventory | BR-100..118 |
| Booking | BR-120..129, BR-166..171, BR-221 |
| Customer | BR-130..136, BR-244..245 |
| Payment | BR-140..145 |
| Fulfilment | BR-150..158 |
| Commission | BR-160..175 |
| Subscription/Plan changes | BR-180..192 |
| GST | BR-200..209 |
| Approval | BR-210..216, BR-271 |
| Orders/Refunds | BR-220..228 |
| Notification | BR-240..246 |
| Risk | BR-250..257 |
| Retention/Closure | BR-290..295 |

# Appendix C. Acceptance Criteria Ownership

| AC | Primary machine / rule area | Acceptance criterion |
| --- | --- | --- |
| AC-001 | Tenant / Store | One PAN cannot create a second tenant account |
| AC-002 | Tenant / Store | One PAN cannot create a second lifetime Free Store after entitlement is consumed |
| AC-003 | Store / Entitlement / Catalog | Free Store cannot create carts, orders, bookings or checkout transactions |
| AC-004 | Store / Entitlement / Catalog | Free Store cannot showcase more than 6 products/services combined |
| AC-005 | Store / Entitlement / Catalog | Each Free showcase item supports max 1 image and no video |
| AC-006 | Store / Entitlement / Catalog | Paid catalog is not blocked by the Free six-item limit |
| AC-007 | Store / Entitlement / Catalog | Paid store may contain products and services |
| AC-008 | Store / Entitlement / Catalog | Paid commerce cannot activate until GSTIN is verified against tenant PAN |
| AC-009 | Store / Entitlement / Catalog | Same GSTIN cannot activate two paid stores |
| AC-010 | Store / Entitlement / Catalog | Different GSTIN-based stores under same PAN may use different paid plans |
| AC-011 | Store / Entitlement / Catalog | No turnover-based mandatory upgrade exists |
| AC-012 | Store / Entitlement / Catalog | Commerce item media allows max 5 images and no video |
| AC-013 | Store / Entitlement / Catalog | Growth item media allows max 10 images + 1 video |
| AC-014 | Store / Entitlement / Catalog | Scale AI has no commercial media-count ceiling, subject to technical limits |
| AC-015 | Checkout / Inventory / Fulfilment | Product/service checkout cannot be combined |
| AC-016 | Checkout / Inventory / Fulfilment | Physical and digital products may share Product Checkout |
| AC-017 | Checkout / Inventory / Fulfilment | Appointment and non-appointment services use separate transactions |
| AC-018 | Checkout / Inventory / Fulfilment | Cross-store cart/checkout is impossible |
| AC-019 | Checkout / Inventory / Fulfilment | Self-shipping/local pickup unavailable |
| AC-020 | Checkout / Inventory / Fulfilment | COD requires approved logistics |
| AC-021 | Commission / Finance | COD commission becomes receivable on confirmed delivery |
| AC-022 | Commission / Finance | Prepaid commission trigger uses confirmed/verified payment receipt |
| AC-023 | Commission / Finance | Pay-after-service commission becomes receivable on booking date |
| AC-024 | Commission / Finance | Eligible customer cancellation may reverse pay-after-service commission |
| AC-025 | Commission / Finance | Seller rejection of valid booking does not automatically remove commission |
| AC-026 | Commission / Finance | NO_SHOW does not remove applicable commission |
| AC-027 | Commission / Finance | Rescheduling prevents double commission |
| AC-028 | Commission / Finance | Commission calculation excludes GST and shipping |
| AC-029 | Commission / Finance | Weekly commission demand has 15-calendar-day payment window |
| AC-030 | Commission / Finance | Commission disputes use pay-first/credit-later model |
| AC-031 | GST Compliance | Commerce includes NIL GSTR-1/GSTR-3B only |
| AC-032 | GST Compliance | Commerce non-NIL GST work requires separate quotation |
| AC-033 | GST Compliance | Growth/Scale GST filing is separately chargeable |
| AC-034 | GST Compliance | GST filing requires recorded tenant approval |
| AC-035 | Tenant / Guardian | Registrant below 18 cannot complete required onboarding without Guardian workflow |
| AC-036 | Tenant / Guardian | Minor Tenant uses own verified PAN |
| AC-037 | Tenant / Guardian | Minor Paid Store GSTIN must belong to Minor Tenant PAN |
| AC-038 | Tenant / Guardian | Guardian government ID and signed consent must be recorded |
| AC-039 | Tenant / Guardian | Guardian data collection is limited to required minimum |
| AC-040 | Tenant / Guardian | Minor reaching 18 triggers adult reverification |
| AC-041 | Subscription / Plan Change | Subscription Billing Period is exactly 30 calendar days |
| AC-042 | Subscription / Plan Change | First paid activation collects Period 1 fee plus 100% Third-Period Advance |
| AC-043 | Subscription / Plan Change | First-ever setup of each individual store is complimentary |
| AC-044 | Subscription / Plan Change | Period 2 requires full applicable subscription payment |
| AC-045 | Subscription / Plan Change | Cancellation notice can be submitted any time before Period 3 starts |
| AC-046 | Subscription / Plan Change | Valid cancellation before Period 3 produces ₹0 additional Period-3 payment |
| AC-047 | Subscription / Plan Change | Valid cancellation allows full paid functionality during Period 3 |
| AC-048 | Subscription / Plan Change | Valid cancellation causes paid subscription to end after Period 3 |
| AC-049 | Subscription / Plan Change | No cancellation notice means subscription continuation |
| AC-050 | Subscription / Plan Change | Continuing Period 3 charge equals 50% of applicable plan price |
| AC-051 | Subscription / Plan Change | Continuing Period 4 charge equals 50% of applicable plan price |
| AC-052 | Subscription / Plan Change | Advance credits across Period 3 and 4 total 100% of original advance |
| AC-053 | Subscription / Plan Change | Period 5 onward returns to full normal subscription |
| AC-054 | Subscription / Plan Change | Missing required payment triggers 7-day PAYMENT_GRACE |
| AC-055 | Subscription / Plan Change | Days 8–22 become SUBSCRIPTION_EXPIRED |
| AC-056 | Subscription / Plan Change | Day 23 unpaid converts store to Free Presence |
| AC-057 | Subscription / Plan Change | During SUBSCRIPTION_EXPIRED, no new orders/bookings may be created |
| AC-058 | Subscription / Plan Change | Existing obligations remain manageable during delinquency |
| AC-059 | Subscription / Plan Change | Free conversion stops custom-domain serving |
| AC-060 | Subscription / Plan Change | Free conversion leaves no more than 6 showcase items |
| AC-061 | Subscription / Plan Change | Higher-plan data is retained but disabled after Free conversion |
| AC-062 | Subscription / Plan Change | Third-Period Advance does not automatically settle Period 2 while Period 2 payment is still within its normal payment/grace lifecycle |
| AC-063 | Subscription / Plan Change | Unused advance may be set off against outstanding subscription at Free conversion |
| AC-064 | Subscription / Plan Change | Such set-off does not automatically restore paid status |
| AC-065 | Subscription / Plan Change | Reactivation requires full new 30-day subscription fee |
| AC-066 | Subscription / Plan Change | Reactivation Setup Fee equals 50% of selected plan fee |
| AC-067 | Subscription / Plan Change | Reactivation date starts a new 30-day Billing Period |
| AC-068 | Subscription / Plan Change | Complimentary Initial Setup cannot be reused for reactivation |
| AC-069 | Subscription / Plan Change | Mid-period upgrade subscription difference is prorated by remaining days |
| AC-070 | Subscription / Plan Change | Upgrade before Period 3 recalculates Third-Period Advance |
| AC-071 | Subscription / Plan Change | Advance Top-Up equals required advance minus existing eligible advance |
| AC-072 | Subscription / Plan Change | Gross Upgrade Setup Fee equals 50% of plan-price difference |
| AC-073 | Subscription / Plan Change | Upgrade Setup Fee discount requires Platform Owner approval |
| AC-074 | Subscription / Plan Change | Setup discount approval is auditable |
| AC-075 | Subscription / Plan Change | Upgrade setup discount does not automatically waive subscription-price difference |
| AC-076 | Customer Claim | Customer email/mobile are mandatory and unique within store |
| AC-077 | Customer Claim | Guest checkout creates UNCLAIMED customer |
| AC-078 | Customer Claim | Email OTP is used to claim UNCLAIMED account |
| AC-079 | Content Approval | Controlled content cannot go LIVE without approval |
| AC-080 | Content Approval | Rejected content records reason |
| AC-081 | Content Approval | Platform Staff can emergency-unpublish suspicious/prohibited content |
| AC-082 | Retention / Closure | Sellers cannot delete historical commercial transactions |
| AC-083 | Retention / Closure | Store with commercial history is archived rather than destructively erased |
| AC-084 | Domain | Free subdomain is immutable |
| AC-085 | Domain | Paid public launch requires custom domain |
| AC-086 | Domain | Standard qualifying domain cost is included according to commercial policy |
| AC-087 | Domain | Premium domain requires additional approval/payment |
| AC-088 | Domain | Domain transfer after closure is not automatic |
| AC-089 | Payment / Platform Funds | UPI through KarobarOne checkout is unavailable |
| AC-090 | Payment / Platform Funds | Platform does not hold customer purchase funds |

# Final Implementation Baseline

This State Machine & Business Rules Specification V1.0 is the implementation baseline for KarobarOne backend lifecycle behavior. Backend APIs, database transition handlers, Kafka consumers, schedulers, workers and QA automation should implement these rules without introducing undocumented business-state transitions. Any material change to pricing, subscription periods, advances, setup fees, commission, PAN/GSTIN identity, Minor Tenant rules, domains, payments, GST, store lifecycle or legal seller model requires BRD change control before this specification is revised.

| Next engineering artifact — The next specification should define the REST API and Kafka/Event Contracts from these transitions: command endpoints, request/response schemas, authorization, error codes, idempotency keys, event envelopes, producer/consumer ownership, retry and DLQ behavior. |
| --- |
