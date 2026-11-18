# Tenant Service Database Migration Guide

## Schema: `tenant`
Owner: `tenant_svc`
Migrator: `tenant_migrator`

### Tables:
- `tenants`: Authoritative one-PAN-one-tenant record. Full PAN encrypted using Fernet (AES-128-CBC + HMAC-SHA256) with HMAC-SHA256 blind indexing on `pan_fingerprint`.
- `pan_verifications`: Provider result history.
- `guardians`: Guardian profile for Minor Tenants.
- `guardian_consents`: Immutable, append-only legal terms acceptance records bound to document code/version/hash.
- `gstins`: Verified GSTINs belonging to tenant PAN.
- `gstin_verifications`: GSTIN provider verification audit history.
- `stores`: Canonical stores. `store_mode` is `FREE_PRESENCE` or `PAID_COMMERCE`. Partial unique index on `gstin_id` where `archived_at IS NULL` ensures one GSTIN ↔ one active store.
- `free_store_entitlements`: Enforces one lifetime Free Store entitlement per tenant PAN.
- `store_memberships`: Staff assignments (`STORE_STAFF`).
- `seller_identity_snapshots`: Immutable historical identity snapshot captured at store creation.
- `outbox_events`, `processed_events`, `idempotency_keys`: Transactional messaging and exactly-once execution.

### Migration Commands:
```bash
# Run migrations using tenant_migrator role
alembic -c services/tenant/alembic.ini upgrade head

# Rollback
alembic -c services/tenant/alembic.ini downgrade -1

# Data migration from monolith
python tools/db/migrate_tenants.py --dry-run
python tools/db/migrate_tenants.py
```
