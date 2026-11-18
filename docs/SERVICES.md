# SERVICES.md — Service cards (first 8 + gateway)

Each card = what to build, nothing more. Paths/IDs/events are verbatim from the API/Event Contract. "Gap" events (SOURCE_GAPS.json) are **not published**.
Schema table names: DB Schema spec if present, else State Machine Appendix A, else BTDD (RULES §1 C4). Common to all: `outbox_events`, `processed_events`, `idempotency_keys`, state history tables.

Build order: **1 IAM · 2 TEN · 3 APR · 4 CAT · 5 DOM(free) · 6 CUS · 7 SUB · 8 DOM(paid) · 9 INV** (+ gateway after TEN).

---
## 1. IAM — Identity & Access  (schema `iam`, BTDD §9.1)
**Tables:** principals, credentials, sessions, refresh_tokens, otp_challenges, role_assignments, service_principals, security_events.

| ID | Method | Path | Actor | Idem |
|---|---|---|---|---|
| IAM-001 | POST | /auth/login | PUBLIC | no |
| IAM-002 | POST | /auth/refresh | session | yes |
| IAM-003 | POST | /auth/logout | auth | yes |
| IAM-004 | POST | /auth/otp/challenges | PUBLIC/CUSTOMER | yes |
| IAM-005 | POST | /auth/otp/challenges/{challenge_id}/verify | PUBLIC/CUSTOMER | yes |
| IAM-006 | GET | /me | auth | – |
| IAM-007 | POST | /admin/role-assignments | PLATFORM_OWNER/admin | yes |
| IAM-008 | DELETE | /admin/role-assignments/{id} | PLATFORM_OWNER/admin | yes |

**Publishes** (`identity.lifecycle`): `identity.principal.created.v1`, `identity.session.revoked.v1`, `identity.role-assigned.v1`, `identity.role-revoked.v1`, `identity.otp.verified.v1`, `identity.security-event.recorded.v1`. *Gap (don't emit):* `identity.session.refreshed`, `identity.otp.challenge-created`. **Consumes:** none.

**Rules:** Argon2id; JWT claims per RULES §8; refresh rotation + reuse→revoke session; OTP hash-only + TTL + attempt cap + rate limit (HTTP 429 `RATE_LIMITED`) + single use; platform roles separate from tenant/store roles; GUARDIAN ≠ store manager; no account-existence leak; security events recorded for login/OTP/session. Also expose what other services need: public key (env/JWKS) for verification; an internal "issue/verify OTP for a purpose" use by CUS (CUS calls IAM-004/005 with a service key).
**Gaps to ask (OQ):** no endpoint creates a principal (sign-up) — propose `POST /auth/register` only after approval; OTP TTL/attempt/rate values; hash algorithm of monolith passwords (if bcrypt → verify-then-rehash, bcrypt dep only in IAM).
**Stubs:** email/SMS OTP delivery → log + Mailpit (NTF later).
**ACs:** AC-078 (OTP claim, with CUS), AC-035/036/076/077 support; tests SEC-TST-005..008, FND-TST-001/002/010/011/028.
**Must-have tests:** expired/revoked token denied; refresh replay denied + session revoked; OTP wrong/expired/replayed/attempt-limit; admin role separate; password hash is Argon2id; no plaintext secrets in DB/logs.

---
## 2. TEN — Tenant & Store  (schema `tenant`, BTDD §9.2, SM §4–5)
**Tables:** tenants, pan_verifications, guardians(guardian_profiles, guardian_links), guardian_consents, gstins, gstin_verifications, stores, free_store_entitlements, store_memberships, seller_identity_snapshots, scheduled_jobs.

| ID | Method | Path | Actor |
|---|---|---|---|
| TEN-001 | POST | /tenants/register | auth principal (idem) |
| TEN-002 | GET | /tenants/{tenant_id} | tenant/admin |
| TEN-003 | POST | /tenants/{tenant_id}/guardians | tenant/guardian |
| TEN-004 | POST | /tenants/{tenant_id}/guardians/{guardian_id}/consents | GUARDIAN |
| TEN-005 | POST | /tenants/{tenant_id}/adult-reverification | tenant |
| TEN-006 | POST | /tenants/{tenant_id}/gstins | STORE_OWNER |
| TEN-007 | GET | /tenants/{tenant_id}/gstins | tenant/admin |
| TEN-008 | POST | /stores | STORE_OWNER |
| TEN-009 | GET | /stores/{store_id} | assigned/admin |
| TEN-010 | POST | /stores/{store_id}/staff | STORE_OWNER |
| TEN-011 | DELETE | /stores/{store_id}/staff/{assignment_id} | STORE_OWNER |

**Publishes** (`tenant.lifecycle`): `tenant.registration-started.v1`, `tenant.activated.v1`, `tenant.guardian-required.v1`, `guardian.verification-started.v1`, `guardian.consent.accepted.v1`, `tenant.adult-reverified.v1`, `gstin.verified.v1`, `store.created.v1` (payload `store_mode: FREE|DIRECT_PAID_SETUP`), `store.free-entitlement-consumed.v1`, `store.staff-assigned.v1`. *Gap:* `gstin.verification-requested`, `store.staff-revoked`. **Consumes:** `identity.principal.created.v1`.

**TEN-001 contract:** request `{pan, legal_name, tenant_type: INDIVIDUAL|BUSINESS|OTHER, date_of_birth|null, acceptance_refs:[{document_code, version}]}` → `{tenant_id, registration_state: AGE_CHECK|GUARDIAN_REQUIRED|STANDARD_TENANT, pan_masked}`.

**Rules:**
1. PAN verified (mock adapter) → fingerprint unique → else `409 TENANT_PAN_ALREADY_REGISTERED` (AC-001). One tenant per PAN.
2. Tenant onboarding machine TEN-01..08 (REGISTRATION → AGE_CHECK → STANDARD_TENANT | GUARDIAN_REQUIRED → GUARDIAN_VERIFICATION → CONSENT_ACCEPTED → MINOR_TENANT_ACTIVE → ADULT_REVERIFICATION_REQUIRED → STANDARD_TENANT). Minor cannot finish mandatory acceptance without guardian + consent: `GUARDIAN_REQUIRED` (AC-035).
3. Minor uses own PAN; paid GSTIN must belong to minor's PAN (`GSTIN_NOT_OWNED`) (AC-036/037).
4. Guardian: store only minimum (identity, relationship, contact, encrypted ID evidence, consent). Consent rows insert-only with document code/version/hash, accepted_at (AC-038/039). Guardian role gives no store rights. History kept after adult reverification.
5. Turns-18 scheduled job → `ADULT_REVERIFICATION_REQUIRED` exactly once (AC-040); TEN-005 completes it with fresh acceptance.
6. One lifetime Free Store entitlement per PAN, consumed atomically in TEN-008 → `409 FREE_STORE_ENTITLEMENT_CONSUMED` (AC-002). Upgrading a Free store never creates a duplicate.
7. GSTIN: encrypt + fingerprint + mask; verified against tenant PAN (mock adapter); `GSTIN_NOT_OWNED`; one GSTIN ↔ one paid store (`GSTIN_ALREADY_USED`) (AC-008/009); different GSTIN stores under same PAN may differ in plan (AC-010).
8. Seller identity snapshotted, never rewritten. Stores with commercial history are archived, never hard-deleted (AC-082/083; archive command only, no delete endpoint).
9. Store lifecycle states (FREE_PRESENCE, PAID_*, SUSPENDED…) are **derived** from SUB/DOM/CMP, not stored here (OQ).

**Internal endpoint needed (not in contract → OQ):** `POST /internal/gstins/{id}/bind` for SUB at paid activation (atomic "GSTIN unused" check).
**Stubs:** PAN/GST verifier adapter (mock: deterministic synthetic PANs).
**ACs:** AC-001, 002, 008, 009, 010, 035–040, 082(partial), 083(partial). Tests: FND-TST-001/002/008/009/010/013, SEC-TST-005.
**Must-have tests:** duplicate PAN race (two concurrent registrations → one wins); concurrent Free-store creation → one wins; minor flow end to end; turns-18 job boundary (day before / exact / repeated run); PAN never in logs/events/responses.

---
## 3. APR — Approval & Governance  (schema `approval`, BTDD §9.6, SM §7)
**Tables:** approval_requests (approval_submissions), approval_decisions, review_assignments, takedowns (emergency_takedowns), governance_audit.

| ID | Method | Path | Actor |
|---|---|---|---|
| APR-001 | POST | /approvals | SERVICE (CAT) idem |
| APR-002 | GET | /approvals/queue | PLATFORM_STAFF |
| APR-003 | GET | /approvals/{id} | PLATFORM_STAFF/owner |
| APR-004 | POST | /approvals/{id}/approve | PLATFORM_STAFF idem |
| APR-005 | POST | /approvals/{id}/reject | PLATFORM_STAFF idem |
| APR-006 | POST | /approvals/{id}/emergency-takedown | PLATFORM_STAFF idem |

**Publishes** (`approval.lifecycle`): `content.submitted.v1`, `content.approved.v1` (payload: tenant_id, store_id, approval_id, content_type, content_id, content_version_id, reviewer_id, decided_at), `content.rejected.v1`, `content.resubmitted.v1`, `content.emergency-takedown.v1`, `content.unpublished.v1`. **Consumes:** none (CAT calls APR-001 synchronously).
**State machine (APR-01..06):** DRAFT → PENDING → APPROVED/LIVE | REJECTED → DRAFT; APPROVED/LIVE → UNPUBLISHED; PENDING/APPROVED → EMERGENCY_TAKEDOWN.
**Rules:** APR owns the *request* state; CAT owns the content versions. A decision row stores actor, reason, timestamp, immutable content-version ref. Reject requires non-empty reason (AC-080). Approve takes `{expected_version, comment}`; the LIVE pointer only changes when CAT consumes `content.approved` (AC-079). Emergency takedown: authorized staff, reason + evidence ref, works on PENDING or LIVE, audit row (AC-081). Only PENDING can be approved/rejected.
**OQ:** who emits `content.unpublished` (APR-05 says tenant/admin unpublish; CAT-009 emits `catalog.item-unpublished`).
**ACs:** AC-079, 080, 081 (with CAT). **Tests:** invalid-from-state for each command; reject without reason → 422; double approve race → one wins; non-staff role denied.

---
## 4. CAT — Catalog & CMS  (schema `catalog`, BTDD §9.5, §14)
**Tables:** catalog_items (item_type), product_details, service_details, item_public_versions, categories, variant_types, variants, variant_values, item_media, store_pages, page_versions, blog_posts, blog_versions, seo_metadata, store_content_config, entitlement_projection (local copy of SUB events).

| ID | Method | Path | Actor |
|---|---|---|---|
| CAT-001 | POST | /stores/{store_id}/items | OWNER/STAFF idem |
| CAT-002 | GET | /stores/{store_id}/items | assigned/public variant |
| CAT-003 | GET | /items/{item_id} | assigned/public variant |
| CAT-004 | PATCH | /items/{item_id}/operational | OWNER/STAFF idem |
| CAT-005 | POST | /items/{item_id}/versions | OWNER/STAFF idem |
| CAT-006 | POST | /items/{item_id}/versions/{version_id}/submit | OWNER/STAFF idem |
| CAT-007 | POST | /stores/{store_id}/pages/{page_type}/versions | OWNER/STAFF idem |
| CAT-008 | POST | /stores/{store_id}/media/upload-intents | OWNER/STAFF idem |
| CAT-009 | POST | /items/{item_id}/unpublish | OWNER/STAFF idem |
| CAT-010 | GET | /public/stores/{store_id}/snapshot | PUBLIC |

**Publishes** (`catalog.lifecycle`): `catalog.item-created.v1`, `catalog.item-operational-changed.v1`, `catalog.version-created.v1`, `catalog.item-unpublished.v1`, `catalog.media-uploaded.v1`, `storefront.snapshot-invalidated.v1`. *Gap:* `catalog.page-version-created`, `catalog.media-upload-intent-created`. **Consumes:** `entitlement.changed.v1`, `content.approved.v1`, `content.rejected.v1`, `content.emergency-takedown.v1`, `content.unpublished.v1`.
**CAT-001 request:** `{item_type: PHYSICAL_PRODUCT|DIGITAL_PRODUCT|APPOINTMENT_SERVICE|NON_APPOINTMENT_SERVICE, operational:{price,currency_code,active}, draft:{title,description,category_id}}` → `{item_id, draft_version_id, approval_state:"DRAFT"}`.
**Rules:**
1. One `catalog_items` table with `item_type`. Operational fields (price, active, service availability) change **without** approval; controlled fields (title, description, media, category, custom variants, SEO) are versioned and need approval (APR-R02).
2. A pending version never overwrites LIVE; promotion on `content.approved` is atomic; previous LIVE retained historically; reject keeps LIVE and the version is editable/resubmittable.
3. Entitlement limits come from the local `entitlement_projection` (fallback: sync `GET /stores/{id}/entitlements`; fail closed if unknown): Free ≤ **6 combined** showcase items (AC-004), ≤1 image/item, no video (AC-005); Commerce ≤5 images/no video (AC-012); Growth ≤10 images + 1 video (AC-013); Scale AI no commercial ceiling, only technical limits (AC-014); paid ignores the Free six cap (AC-006); products and services coexist in paid (AC-007).
4. On downgrade / Free conversion: data retained but hidden/disabled, never deleted (AC-061); Free keeps ≤ 6 showcase items (AC-060) — **selection rule missing → OQ** (propose: keep the 6 currently-LIVE items with earliest `created_at`).
5. Blog only if entitlement allows; no comments in V1.
6. CAT-006 calls APR-001 (sync, service key) and records the approval id; CAT emits no submit event itself (RULES C7).
7. Media: pre-signed upload URL (S3-compatible adapter; MinIO locally); object keys non-guessable and private; metadata (mime, size, checksum, dimensions/duration, owner tenant/store, scan_status, approval-version ref). Server finalizes by checking the object, never trusting the client. Public images only for LIVE versions.
8. CAT-010 reads a LIVE-only projection; draft/rejected ids unreachable.
**Stubs:** entitlements before SUB exists (static Free capabilities); object storage → MinIO; restriction check.
**ACs:** AC-003(catalog side), 004, 005, 006, 007, 012, 013, 014, 060, 061, 079. **Tests:** seventh-item rejection; media limits at boundary per plan; LIVE v3 stays served while v4 pending/rejected; promotion atomic; snapshot never contains draft; IDOR across stores.

---
## 5. DOM — Domain & Publication  (schema `domain`, BTDD §9.4, SM §6)
**Tables:** subdomains(free_subdomains), domain_requests, domains, domain_cost_classifications, dns_checks, store_domain_mappings, publication_routes, scheduled_jobs.

| ID | Method | Path | Actor |
|---|---|---|---|
| DOM-001 | POST | /stores/{store_id}/subdomain | OWNER/internal idem |
| DOM-002 | POST | /stores/{store_id}/domains/options | OWNER idem |
| DOM-003 | POST | /domain-requests/{id}/select | OWNER idem |
| DOM-004 | POST | /domain-requests/{id}/purchase | platform idem |
| DOM-005 | GET | /stores/{store_id}/domain-status | assigned/admin |
| DOM-006 | POST | /domain-requests/{id}/verify-dns | platform/internal idem |
| DOM-007 | POST | /stores/{store_id}/publish | platform/internal idem (`{expected_version}`) |
| DOM-008 | POST | /domains/{id}/transfer-review | OWNER/admin idem |

**Publishes** (`domain.lifecycle`): `domain.subdomain-assigned.v1`, `domain.options-checked.v1`, `domain.selected.v1`, `domain.purchased.v1`, `domain.dns-verified.v1`, `domain.activated.v1`, `domain.stopped.v1`, `domain.transfer-review-opened.v1`, `store.published.v1`. *Gap:* `domain.dns-verification-requested`, `domain.route.activated`. **Consumes:** `store.created.v1`, `subscription.activated.v1`, `subscription.converted-to-free.v1`, `content.approved.v1`, `entitlement.changed.v1`.
**State machine (DOM-01..10):** FREE_SUBDOMAIN_ASSIGNED; PREFERENCE_SUBMITTED → AVAILABILITY_CHECKED → SELECTED → PURCHASE_PENDING → PURCHASED → DNS_PENDING → DNS_VERIFIED → ACTIVE → STOPPED_FREE_CONVERSION; closure → TRANSFER_REVIEW.
**Rules:** Free subdomain `storename.karobarone.com`, immutable once created, unique (AC-084). Free publish: required content approved + Free subdomain. Paid public launch: active subscription + verified GSTIN + DNS-verified custom domain + approvals + no restriction, else `409 CUSTOM_DOMAIN_REQUIRED` (AC-085). Standard domain cost "included" vs premium requiring extra approval + payment: configurable classification, audited (AC-086/087). Free conversion: stop custom-domain serving, keep history, activate Free subdomain (AC-059). Transfer after closure opens a manual case, never automatic (AC-088). Host → store resolution for the storefront comes from `publication_routes` (central routing; no per-tenant resources). Unknown host → controlled 404. Registrar/DNS never decides publication; DOM applies the guards. Purchase must not blind-retry after a timeout; look up by request reference first.
**Stubs:** registrar/DNS mock adapter; subscription/entitlement/GSTIN/restriction checks via clients (Free-only until SUB/TEN-bind exist).
**OQ:** reserved/blocked subdomain names; who calls DOM-001 (tenant gives the slug).
**ACs:** AC-059, 084, 085, 086, 087, 088. **Tests:** rename attempt rejected; duplicate slug race; publish gates each missing → distinct failure; premium purchase blocked until approval+payment recorded; route switches on conversion event; duplicate event is a no-op.

---
## 6. CUS — Customer  (schema `customer`, BTDD §9.7, SM §8)
**Tables:** customers, customer_credentials_link, customer_addresses, account_claims (customer_claim_challenges), privacy_requests (customer_privacy_requests).

| ID | Method | Path | Actor |
|---|---|---|---|
| CUS-001 | POST | /stores/{store_id}/customers/guest | PUBLIC (idem) |
| CUS-002 | POST | /customers/{id}/claim/challenge | PUBLIC/CUSTOMER idem |
| CUS-003 | POST | /customers/{id}/claim/verify | PUBLIC/CUSTOMER idem |
| CUS-004 | GET | /customers/{id} | customer/assigned staff |
| CUS-005 | PATCH | /customers/{id} | customer/staff idem (profile fields only) |
| CUS-006 | POST | /customers/{id}/addresses | CUSTOMER idem |
| CUS-007 | POST | /customers/{id}/privacy-requests | CUSTOMER idem |

**Publishes** (`customer.lifecycle`): `customer.unclaimed-created.v1`, `customer.claim-challenge-created.v1`, `customer.claimed.v1`, `customer.profile-updated.v1`, `customer.address-created.v1`, `customer.privacy-requested.v1`. **Consumes:** none.
**Rules:** email and mobile mandatory and unique **per store** (`UNIQUE(store_id,email)`, `UNIQUE(store_id,mobile)`), same values allowed in another store (AC-076). Guest create-or-resolve → `UNCLAIMED` (AC-077). Claim: CUS-002 asks IAM (IAM-004, service key) for an Email OTP; CUS-003 verifies via IAM-005 then sets `CLAIMED`, binds the IAM principal, allows setting a password (AC-078). Invalid/expired OTP never claims. Privacy request: anonymize deletable profile fields; never touch statutory order/invoice/GST/commission/audit data (none exist yet — guard by design, write the rule + test with a placeholder). Customer sees only own store-scoped data.
**OQ:** email/mobile normalization (lowercase email; mobile format).
**Stubs:** email delivery via IAM stub.
**ACs:** AC-076, 077, 078. **Tests:** duplicate within store → conflict; same value in other store OK; concurrent guest creation → one row; claim with wrong/expired/replayed OTP; IDOR across customers/stores.

---
## 7. SUB — Subscription & Entitlement  (schema `subscription`, BTDD §9.3 §13, SM §17–18)
**Tables:** plans, plan_versions, plan_entitlements, subscriptions, subscription_periods, subscription_charges, subscription_payments, advance_movements (advances, advance_allocations), cancellation_notices, plan_change_requests, upgrade_quotes, upgrade_discount_requests, lifecycle_events, entitlement_snapshots (store_entitlement_projection), scheduled_jobs.

| ID | Method | Path | Actor |
|---|---|---|---|
| SUB-001 | GET | /plans | public/auth |
| SUB-002 | POST | /stores/{store_id}/subscriptions/activation-quote | OWNER idem |
| SUB-003 | POST | /stores/{store_id}/subscriptions/activate | OWNER idem |
| SUB-004 | GET | /stores/{store_id}/entitlements | assigned/internal |
| SUB-005 | GET | /subscriptions/{subscription_id} | assigned/admin |
| SUB-006 | POST | /subscriptions/{id}/cancel | OWNER idem (`{reason?, expected_version}`) |
| SUB-007 | POST | /subscriptions/{id}/upgrade-quote | OWNER idem |
| SUB-008 | POST | /subscriptions/{id}/upgrade | OWNER idem |
| SUB-009 | POST | /subscriptions/{id}/downgrade | OWNER idem |
| SUB-010 | POST | /subscriptions/{id}/reactivate | OWNER idem |
| SUB-011 | POST | /admin/upgrade-discounts/{request_id}/decision | PLATFORM_OWNER idem |

**Publishes** (`subscription.lifecycle` + `entitlement.changed`): `subscription.activation-quote-created.v1`, `subscription.activated.v1`, `subscription.period-started.v1`, `subscription.payment-due.v1`, `subscription.grace-entered.v1`, `subscription.expired.v1`, `subscription.converted-to-free.v1`, `subscription.cancellation-notice-recorded.v1`, `subscription.upgrade-quote-created.v1`, `subscription.upgraded.v1`, `subscription.downgrade-requested.v1`, `subscription.downgraded.v1`, `subscription.reactivated.v1`, `entitlement.changed.v1`. *Gap:* `subscription.upgrade-discount-decided`. **Consumes:** `store.created.v1` (create Free entitlement snapshot), `finance.platform-payment-recorded.v1` (**stubbed**: dev-only `POST /internal/dev/platform-payments`, disabled in prod).
**Calculation module** (`domain.py`, pure, versioned by `calc_policy_version`; stores inputs + result + rounding policy). S = plan price per 30 days, A3 = advance:
- Activation: Period1 = S, A3 = S, collect 2S before GST, first-ever setup fee 0 per store (AC-042/043).
- Period 2 due = S; advance is **not** auto-applied to P2 (AC-044/062).
- Cancel notice strictly **before P3 start** else `CANCELLATION_WINDOW_CLOSED` (AC-045); then P3 additional due = 0, full paid features in P3, paid ends after P3 → Free (AC-046..048). No notice → continuation (AC-049): P3 = 0.5S, P4 = 0.5S, advance credited 0.5S + 0.5S = 100% (AC-050..052), P5+ = S (AC-053).
- Period = exactly 30 consecutive days, half-open `[start, start+30d)`, never calendar months (AC-041).
- Unpaid required charge: Days 1–7 `PAYMENT_GRACE`; Days 8–22 `SUBSCRIPTION_EXPIRED` (site visible, **no new orders/bookings**, existing obligations manageable); Day 23 → `FREE_PRESENCE` (AC-054..058). On conversion: stop custom domain (DOM), ≤6 showcase (CAT), retain higher-plan data hidden, unused advance may be set off — **set-off does not restore paid status** (AC-059..064). Payment before Day 23 → recovery.
- Reactivation after non-payment conversion: new 30-day period at S + setup fee 0.5S; period starts at reactivation; complimentary setup not reusable (AC-065..068).
- Upgrade L→H with R days left: `prorated = (H−L)·R/30`; `top_up = max(0, required_advance − eligible_advance)` (before P3, AC-070/071); `gross_setup = 0.5·(H−L)`; discount only on setup, requires PLATFORM_OWNER decision with audit (approver, amount, reason, time), never waives the proration (AC-069, 072..075). Quote immutable.
- Downgrade: future period boundary, Platform Owner due diligence; higher-plan data hidden not deleted.
- No turnover-based forced upgrade (AC-011).
**Entitlement snapshot** (`GET /stores/{id}/entitlements`, `entitlement.changed.v1.capabilities`): minimum fields needed by CAT/DOM now — `plan_code, state, commerce_enabled, showcase_limit, max_images_per_item, max_videos_per_item, custom_domain_allowed, blog_allowed` (OQ: schema not specified; extend only when a consumer needs it). Resolved from plan version + lifecycle state; fail closed.
**Scheduler:** `scheduled_jobs` for period charge, grace, expiry, Day-23 conversion, scheduled downgrade; unique `business_key = subscription+period+transition`.
**Plan data:** plan prices/limits are **not in the specs** — seed from the BRD into `plan_versions` (OQ-005). Commission rates 4/2/1% belong to FIN, not here. GST per charge component and rounding = OQ until tax review.
**Activation guard:** needs TEN bind GSTIN (OQ internal endpoint) before collecting.
**ACs:** AC-041..075 (entitlement side of 057/058 only; the order/booking denial is proven later in COM/BKG), AC-011, 059/060/061 with DOM/CAT. **Tests:** deterministic clock boundaries (before/at/after P3; Day 7/8/22/23); two scheduler replicas → one transition; advance ledger balances; quote reproducible from stored inputs; discount without owner approval rejected; duplicate payment event; every AC row has a test.

---
## 8. INV — Inventory  (schema `inventory`, BTDD §9.8, SM §9)
**Tables:** skus, stock_balances, reservations (stock_reservations), stock_movements (append-only), inventory_adjustments, scheduled_jobs.

| ID | Method | Path | Actor |
|---|---|---|---|
| INV-001 | GET | /inventory/availability | internal/STAFF |
| INV-002 | POST | /inventory/reservations | SERVICE idem |
| INV-003 | POST | /inventory/reservations/{id}/consume | SERVICE idem |
| INV-004 | POST | /inventory/reservations/{id}/release | SERVICE/scheduler idem |
| INV-005 | POST | /inventory/adjustments | OWNER/STAFF idem |
| INV-006 | GET | /stores/{store_id}/inventory | OWNER/STAFF |

**Publishes** (`inventory.lifecycle`): `inventory.reserved.v1` (reservation_group_id, checkout_id, reservations[{id,sku_id,quantity,expires_at}]), `inventory.consumed.v1`, `inventory.released.v1`, `inventory.expired.v1`, `inventory.restored.v1`, `inventory.adjusted.v1`, `inventory.low-stock.v1`. **Consumes:** none now (order.cancelled / refund.completed handlers are written when COM/PAY exist).
**INV-002 request:** `{store_id, checkout_id, lines:[{sku_id, quantity}], ttl_seconds:600}` → `{reservation_group_id, reservations:[…]}`; all-or-nothing per checkout.
**Rules:** tracking optional per physical SKU; digital effectively unlimited (INV-R01); **no negative stock** — reserve with one conditional update:
`UPDATE stock_balances SET reserved = reserved + :q WHERE sku_id = :id AND on_hand - reserved >= :q` (0 rows → `INSUFFICIENT_INVENTORY`); consume/release likewise atomic; TTL default 600 s from config, expiry by scheduler (ACTIVE→EXPIRED, release qty, guarded by state); every change appends a `stock_movements` row; restoration is a compensating movement, never an edit (INV-05).
**State machine:** ACTIVE → CONSUMED | RELEASED | EXPIRED.
**OQ:** no endpoint creates SKUs (INV-005 only adjusts) — propose consuming `catalog.item-created.v1` for PHYSICAL_PRODUCT or an internal `POST /internal/skus` (needs approval); cross-store reservation must be rejected.
**Tests:** FND-TST-014 final-unit race on real Postgres (N concurrent, exactly one wins, never negative); duplicate expiry worker no-op; reserve→consume→restore ledger sums; idempotent reserve replay; group all-or-nothing; IDOR.

---
## 9. Gateway (not a domain service)
`services/gateway`: FastAPI reverse proxy. Routes `/api/v1/*` by path prefix to upstream URLs from env (default: monolith); YAML route table, flip one line per extracted service. Adds/propagates `X-Request-Id`, basic rate limit (Redis later), CORS. **Does not authenticate or inject tenant headers** — services verify JWTs themselves. Health at `/health/live|ready`. Public webhook routes for later services pass through untouched.

---
## 10. AC ownership summary (first 8)
| ACs | Owner(s) | Status when first 8 done |
|---|---|---|
| 001, 002, 008, 009, 010, 035–040 | TEN (+IAM) | complete |
| 011, 041–056, 059–075 | SUB (+DOM/CAT for 059–061) | complete |
| 057, 058, 003 | SUB entitlement side | **partial** (full needs COM/BKG) |
| 004–007, 012–014 | CAT (+SUB) | complete |
| 076–078 | CUS (+IAM) | complete |
| 079–081 | APR (+CAT) | complete |
| 082, 083 | TEN (+COM) | **partial** (archive rule + no delete endpoint) |
| 084–088 | DOM | complete (premium payment recording partial) |
| INV concurrency (FND-TST-014) | INV | complete |
| 015–034, 089, 090 | COM/BKG/PAY/FUL/FIN/CMP | out of scope now |
