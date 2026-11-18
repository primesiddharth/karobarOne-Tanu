# IAM Migration Documentation (`docs/migrations/iam.md`)

## 1. Target Schema Overview
The `iam` schema encapsulates all identity, authentication, session lifecycle, and scoped authorization primitives.

### Tables Created (Revision `002`)
- `iam.principals`: Canonical human and service principal identities.
- `iam.credentials`: Passwords hashed via Argon2id (and legacy bcrypt for transparent migration re-hashing).
- `iam.sessions`: Active login sessions tracking issue, expiry, and revocation.
- `iam.refresh_tokens`: Rotation history and reuse revocation tracking (`token_hash`, `replaced_by`, `used_at`).
- `iam.role_assignments`: Role grants strictly checking platform vs tenant vs store scopes.
- `iam.otp_challenges`: One-time password verification challenges (`destination_fingerprint`, `attempt_count`).
- `iam.security_events`: Append-only audit trail of authentication events and security actions.

---

## 2. Monolith Field Mapping & Transformations

| Monolith Table / Column | IAM Target Table / Column | Transformation & Migration Note |
|---|---|---|
| `users.id` (`VARCHAR(36)`) | `iam.principals.id` (`UUID`) | Native PostgreSQL UUID type conversion. |
| `users.email` (`VARCHAR`) | `iam.principals.email` (`VARCHAR(255)`) | Lowercased & trimmed per `OQ-017`. Unique index on `lower(email)`. |
| `users.phone_number` | `iam.principals.mobile_e164` | Normalized to E.164. |
| `users.password_hash` | `iam.credentials.password_hash` | Monolith bcrypt hash preserved with `algorithm = 'bcrypt'`. Rehashed to Argon2id on first login. |
| `users.is_active` | `iam.principals.status` | Mapped `true` -> `'ACTIVE'`, `false` -> `'DISABLED'`. |
| `users.is_superuser` | `iam.role_assignments` | Mapped to `role_code = 'PLATFORM_OWNER'`, `tenant_id = NULL`, `store_id = NULL`. |
| `password_reset_tokens` | `iam.otp_challenges` | Subsumed under unified challenge table with rate limits and attempt caps. |
| `login_history` | `iam.security_events` | Standardized audit log. |

### Dropped / Unmapped Monolith Fields
- `users.first_name`, `users.last_name`: Personal profile fields moved to domain service profile tables (`customer.customers`, `tenant.seller_identity_snapshots`).
- `users.avatar_url`: Handled by Catalog/Asset domain.
- `users.created_at`, `users.updated_at`: Retained as standard UTC timestamps.
