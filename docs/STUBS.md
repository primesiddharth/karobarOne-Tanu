# STUBS.md — Every stub, what it replaces, when it dies

Each stub is marked in code as `# STUB(<service>, OQ-xxx)`. Dev-only endpoints return 404 when `ENVIRONMENT=prod`.

| Stub | Lives in | Replaces | Dies when |
|---|---|---|---|
| PAN/GST verifier (mock, deterministic synthetic ids) | tenant `clients.py` | PAN/GST provider (OQ-023) | provider chosen + sandbox certified |
| Registrar/DNS mock | domain `clients.py` | registrar + DNS provider | provider chosen |
| OTP/email sender → log + Mailpit | iam `clients.py` | NTF email/SMS | NTF service built |
| Restriction check → "none" | each service `clients.py` | CMP restrictions | CMP built |
| Free entitlements (static) | catalog `clients.py` | SUB entitlements | Retired in Phase 8a (Catalog now calls SUB `GET /stores/{id}/entitlements`) |
| `POST /internal/dev/platform-payments` | subscription | `finance.platform-payment-recorded` from FIN | FIN built |
| MinIO object storage (presigned upload intents + object check) | catalog `clients.py` | S3-compatible vendor (OQ-013) | cloud vendor chosen (R2/S3/B2) |
| Gateway upstream default = monolith | gateway | new services | per-service cutover |
| Customer IAM principal provision stub | customer `clients.py` | IAM customer principal provisioning (OQ-040) | IAM customer registration endpoint specified |
| Customer store tenant resolver fallback | customer `clients.py` | Sync Tenant store resolve (OQ-035) | Multi-service orchestration container networking |
| HTTP outbox relay + `/internal/events` | every service `worker.py` | Kafka | Kafka-compatible service chosen (OQ-002) |
