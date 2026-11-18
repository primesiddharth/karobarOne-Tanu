**KAROBARONE**

**Infrastructure & Kubernetes
Deployment Specification**

Production infrastructure baseline for Kubernetes, data services, network security, observability, CI/CD, backup and operations

| Document Field | Value |
| --- | --- |
| Specification Version | 1.0 |
| Status | Infrastructure Implementation Baseline |
| Effective Date | 14 September 2026 |
| Business Authority | KarobarOne BRD V2.1 - Final Consolidated |
| Technical Inputs | Backend Technical Design V1.0; PostgreSQL Schema Specification V1.0; State Machine & Business Rules V1.0; REST API & Kafka Event Contract V1.0; Repository & Engineering Foundation V1.0; Backend Test & Acceptance V1.0 |
| Target Runtime | Docker + Kubernetes; Python/FastAPI services; PostgreSQL; Kafka; Redis; S3-compatible object storage |
| Initial Availability Target | 99.5% |
| Primary Audience | DevOps/SRE, Backend Engineering, Database, Security, QA, Architecture and Technical Leads |

| Authority — This document specifies infrastructure and deployment implementation. It does not alter business rules, state transitions, database ownership, API/event contracts or acceptance criteria. If a conflict exists, the BRD and higher-authority technical specifications prevail. |
| --- |

# **Document Contents**

1. Purpose, Scope and Normative Hierarchy

2. Approved Infrastructure Baseline and Design Decisions

3. Infrastructure Design Principles

4. Environment and Cluster Topology

5. Kubernetes Namespace and Resource Model

6. Workload Deployment Model

7. Service Discovery, Ingress and Public Routing

8. Tenant Website and Custom-Domain Routing

9. Network Security and NetworkPolicy

10. Service Accounts, RBAC and Workload Identity

11. Configuration, Secrets and Certificates

12. Container Image and Runtime Security

13. Health Probes, Graceful Shutdown and Availability

14. Resource Requests, Limits and Autoscaling

15. PostgreSQL / CloudNativePG Architecture

16. Kafka Platform Integration

17. Redis Platform Integration

18. Object Storage and Media Delivery

19. Scheduler, Workers and Asynchronous Jobs

20. Database Migration Deployment Pattern

21. Observability Platform

22. Alerting and Operational SLO Signals

23. CI/CD Deployment Pipeline

24. Release, Promotion and Rollback Strategy

25. Backup, Restore and Disaster Recovery

26. Capacity, Scaling and Performance Controls

27. Security and Supply-Chain Controls

28. Maintenance and Operational Runbooks

29. Environment Promotion and Change Management

30. Infrastructure Testing and Production Readiness

31. Implementation Phases

32. Open Decisions and Provider-Specific Extension Points

Appendix A - Kubernetes Naming and Labeling Standard

Appendix B - Illustrative Kubernetes Manifests

Appendix C - Network Flow Matrix

Appendix D - Production Readiness Checklist

# **1. Purpose, Scope and Normative Hierarchy**

## **1.1 Purpose**

This specification converts the approved KarobarOne backend and repository architecture into a deployable Kubernetes and infrastructure operating model. It defines how workloads are packaged, isolated, routed, scaled, observed, backed up, migrated and promoted through environments without changing the business semantics already captured in the BRD, state-machine, database and API/event specifications.

## **1.2 In Scope**

- Kubernetes environment/cluster and namespace structure.
- Deployment patterns for FastAPI APIs, Kafka consumers, outbox publishers, schedulers and administrative jobs.
- Ingress, Cloudflare/WAF, TLS, public/private service exposure and tenant host routing.
- CloudNativePG-based PostgreSQL operations, backup/restore and database migration gates.
- Kafka, Redis and S3-compatible storage integration boundaries.
- ServiceAccount/RBAC, NetworkPolicy, secrets, container security and supply-chain controls.
- Resource requests/limits, HPA/Kafka-lag scaling, PDBs, health probes and graceful shutdown.
- OpenTelemetry, Prometheus/Grafana, centralized logs, alerts and operational evidence.
- CI/CD deployment stages, environment promotion, rollback/roll-forward and release certification.
- Infrastructure testing, resilience checks, runbooks and production-readiness gates.

## **1.3 Out of Scope**

- Redefining pricing, subscriptions, commission, GST, domain commercial policy or other BRD business rules.
- Selecting a final cloud provider, managed Kafka vendor, DNS registrar, SMS/email vendor or PAN/GST verification provider.
- Providing legal, tax or regulatory certification.
- Final production sizing before staging/load-test evidence exists.
- Multi-region active-active architecture; V1 intentionally avoids premature multi-region complexity.

## **1.4 Normative Hierarchy**

| Priority | Artifact | Authority |
| --- | --- | --- |
| 1 | KarobarOne BRD V2.1 | Business/commercial/legal behavior and acceptance criteria. |
| 2 | State Machine & Business Rules V1.0 | Allowed lifecycle states, guards, timers and side effects. |
| 3 | PostgreSQL Schema Specification V1.0 | Persistence structures, ownership, constraints, RLS and migration invariants. |
| 4 | REST API & Kafka Event Contract V1.0 + machine-readable contracts | HTTP/event surfaces and compatibility. |
| 5 | Backend Technical Design V1.0 | Service boundaries, runtime topology and communication patterns. |
| 6 | Repository & Engineering Foundation V1.0 | Codebase, container, CI/CD and Kubernetes foundation. |
| 7 | Backend Test & Acceptance V1.0 | Verification, release gates and evidence. |
| 8 | This specification | Infrastructure/Kubernetes deployment implementation. |
| 9 | Provider-specific manifests/code | Must conform to all higher-authority artifacts. |

# **2. Approved Infrastructure Baseline and Design Decisions**

The following table distinguishes previously approved infrastructure requirements from implementation decisions introduced by this specification. “Approved baseline” must not be changed without revisiting the relevant higher-authority artifact. “Infrastructure design decision” may evolve through ADR/change control provided externally observable behavior and security guarantees remain intact.

| ID | Classification | Baseline / Decision |
| --- | --- | --- |
| INF-001 | Approved baseline | Kubernetes orchestrates stateless APIs/workers; API and long-running workers are separate workloads. |
| INF-002 | Approved baseline | PostgreSQL is authoritative; initial deployment uses one PostgreSQL cluster with schema-per-service ownership. |
| INF-003 | Approved baseline | CloudNativePG is the preferred production PostgreSQL operator/control plane. |
| INF-004 | Approved baseline | Kafka carries asynchronous facts; application semantics assume at-least-once delivery with outbox/inbox idempotency. |
| INF-005 | Approved baseline | Redis is cache/rate-limit/read-acceleration only; correctness does not depend on Redis survival. |
| INF-006 | Approved baseline | Object storage is S3-compatible and private; signed URLs/control plane are used for protected media/digital products. |
| INF-007 | Approved baseline | Cloudflare/WAF sits in front of ingress; DB/Kafka/Redis are not publicly exposed. |
| INF-008 | Approved baseline | Internal application services use ClusterIP; NetworkPolicy restricts service/data access. |
| INF-009 | Approved baseline | OpenTelemetry + Prometheus/Grafana + centralized logs provide observability. |
| INF-010 | Approved baseline | Initial availability target is 99.5%; daily PostgreSQL backup with 15-day retention and periodic restore testing are required. |
| TDD-001 | Infrastructure design decision | Production is targeted as a dedicated cluster/account/project when feasible; dev/staging may share a non-production cluster with strict namespace/credential separation. |
| TDD-002 | Infrastructure design decision | Default-deny network policy is the namespace baseline; explicit egress/ingress allows only required flows. |
| TDD-003 | Infrastructure design decision | Pod Security Restricted-style controls are the target: non-root, no privilege escalation, dropped capabilities, read-only root where feasible. |
| TDD-004 | Infrastructure design decision | KEDA is recommended for Kafka-lag autoscaling where standard HPA metrics are insufficient; HPA remains valid for HTTP/API workloads. |
| TDD-005 | Infrastructure design decision | Continuous PostgreSQL WAL archiving to object storage is recommended in addition to required daily backups; formal RPO/RTO remain to be approved. |
| TDD-006 | Infrastructure design decision | Tenant websites use centralized host resolution/routing; Kubernetes resources are not created per tenant/domain. |
| TDD-007 | Infrastructure design decision | Rolling deployment is default; canary/blue-green may be used for high-risk releases without changing service contracts. |

# **3. Infrastructure Design Principles**

| ID | Principle | Infrastructure consequence |
| --- | --- | --- |
| K8S-PR-01 | Stateless application pods | API pods, consumers and workers keep durable business state in PostgreSQL/object storage, not local pod disks. |
| K8S-PR-02 | Business boundaries survive co-deployment | Logical service modules, DB schemas, migrations and contracts stay separate even when early deployments consolidate multiple services. |
| K8S-PR-03 | Data plane stays private | PostgreSQL, Kafka and Redis are reachable only from approved internal workloads. |
| K8S-PR-04 | Least privilege | Each workload has a dedicated ServiceAccount, minimum RBAC and minimum network permissions. |
| K8S-PR-05 | Declarative infrastructure | Cluster/application manifests are source-controlled; production changes are made through reviewed pipelines, not manual kubectl mutation except emergency break-glass procedures. |
| K8S-PR-06 | Migrations are explicit jobs | Database migrations are not performed as an implicit application startup side effect. |
| K8S-PR-07 | Asynchronous durability | Kafka outages do not invalidate committed DB state; outbox backlog recovers later. |
| K8S-PR-08 | Observable by default | Every production workload exposes health, metrics and trace/log context without leaking sensitive identifiers. |
| K8S-PR-09 | Fail closed for commercial creation | If critical entitlement/restriction dependencies cannot be safely verified, new commerce is denied while existing obligations remain manageable. |
| K8S-PR-10 | Measured scaling | Requests/limits and autoscaling thresholds are finalized using staging/load data, not arbitrary production guesses. |

# **4. Environment and Cluster Topology**

| Environment | Runtime | Data policy | Promotion role |
| --- | --- | --- | --- |
| local | Docker Compose/local containers | Synthetic/resettable data only | Developer feedback and contract/integration work. |
| dev | Kubernetes non-production namespace/cluster | Synthetic/test-provider data; no production PII | Continuous integration environment; migration and service integration. |
| staging | Kubernetes production-like namespace/cluster | Masked/synthetic data unless formally approved | Release candidate, load, resilience, security and restore validation. |
| prod | Kubernetes production cluster/namespace | Customer workload; strict secrets/audit/backups | Customer-facing production. |

| Design decision — Production should be isolated from developer workloads at cluster/account/project level when practical. At minimum, production and development must have separate namespaces, credentials, databases, secrets and network boundaries. Staging is strongly recommended as a production-like pre-release environment. |
| --- |

| Internet / Tenant Domains
        \|
        v
Cloudflare / WAF / TLS
        \|
        v
Kubernetes Ingress / Gateway
        \|
        +--> Public API routes ------> FastAPI Deployments
        \|                               \|--> PostgreSQL (private)
        \|                               \|--> Redis (private)
        \|                               `--> Kafka (private)
        \|
        +--> Storefront host router --> Public storefront/read projection

Workers / consumers / schedulers run as separate Deployments.
Object storage/CDN is private-by-default with controlled signed/public delivery. |
| --- |

# **5. Kubernetes Namespace and Resource Model**

## **5.1 Namespace Baseline**

| Namespace pattern | Purpose | Notes |
| --- | --- | --- |
| karobarone-dev | Shared development workloads | Non-production only; synthetic/test data. |
| karobarone-staging | Release candidate workloads | Production-like controls; deployment/promotion gate. |
| karobarone-prod | Production application workloads | No developer credentials; GitOps/CI-controlled changes. |
| karobarone-observability-<env> | OTel/Prometheus/Grafana/log components where separated | May be central/shared depending platform design. |
| karobarone-data-<env> | Optional data-operator namespace | Use only if platform team separates CNPG/Redis/Kafka operator resources. |

## **5.2 Canonical Labels**

| app.kubernetes.io/name: commerce-api
app.kubernetes.io/part-of: karobarone
app.kubernetes.io/component: api \| worker \| consumer \| scheduler
app.kubernetes.io/managed-by: ci-cd
karobarone.io/service: commerce
karobarone.io/environment: prod
karobarone.io/revision: <git-sha> |
| --- |

Labels must use logical service names and stable route templates. Tenant IDs, PAN/GSTIN values, customer IDs and other high-cardinality/sensitive identifiers must never be Kubernetes labels or Prometheus metric labels.

# **6. Workload Deployment Model**

| Workload type | Kubernetes primitive | Scaling / availability | Rule |
| --- | --- | --- | --- |
| HTTP API | Deployment + ClusterIP Service | HPA; >=2 replicas in production where service criticality/traffic justify | Stateless; readiness removes pod before traffic. |
| Kafka consumer | Deployment | Replicas bounded by partitions; CPU + lag/KEDA where used | Consumer group controls partition ownership; inbox dedupe protects replay. |
| Outbox publisher | Deployment | Multiple replicas allowed with safe claiming | DB outbox is durability source; event_id stable across retries. |
| Scheduler | Deployment | Multiple replicas allowed | SELECT ... FOR UPDATE SKIP LOCKED + business idempotency prevents duplicate transitions. |
| Background worker | Deployment | Queue/backlog/resource-driven | No durable workflow state stored only in process memory. |
| Database migration | Job | Single-writer per deployment stage | Runs before incompatible app rollout; never auto-run in API startup. |
| Reconciliation | CronJob or durable scheduler job | Cadence by domain/provider | Must be idempotent and audit corrections rather than rewrite history. |
| One-off admin repair | Job under break-glass/change control | Manual approval | Must invoke supported domain correction paths or auditable scripts; never ad-hoc SQL destructive edits. |

## **6.1 Deployment Consolidation**

The logical architecture contains 16 services. Early implementation may co-deploy related service modules to reduce operational overhead, but consolidation does not permit cross-service schema writes or imported foreign domain models. Every logical service remains independently testable, owns its schema/migrations and preserves its OpenAPI/event contracts so extraction later does not require data redesign.

# **7. Service Discovery, Ingress and Public Routing**

| Route class | Exposure | Routing rule |
| --- | --- | --- |
| Public platform/API | Cloudflare/WAF -> Ingress/Gateway | Only explicitly approved public endpoints; TLS required. |
| Provider webhooks | Cloudflare/WAF -> dedicated webhook routes | Signature/auth validation, raw retention, dedupe and fast durable acceptance. |
| Internal service API | ClusterIP only | Resolved through Kubernetes DNS; authenticated workload identity/service contract. |
| Metrics | Internal only | Prometheus scrape/service monitor; never internet-facing. |
| PostgreSQL/Kafka/Redis | Private data network only | No public LoadBalancer/NodePort. |
| Admin endpoints | Ingress with stronger policy | Platform role checks; optional VPN/identity-aware gateway may be added without changing API semantics. |

## **7.1 TLS and Edge**

- Cloudflare/WAF is the approved edge layer in front of Kubernetes ingress.
- All customer-facing traffic uses HTTPS.
- Origin TLS certificates are managed by cert-manager or the selected platform certificate mechanism; certificate automation is an infrastructure choice, not a business rule.
- Rate limiting may occur at Cloudflare/gateway and per service; OTP/auth abuse limits remain enforced at application level even if edge rate limiting exists.

# **8. Tenant Website and Custom-Domain Routing**

KarobarOne must support many tenant hosts without creating a Kubernetes Deployment/Service/Ingress per tenant. Tenant identity is resolved from the HTTP Host value against the Domain/Publication service read model. The same storefront runtime can serve many Free subdomains and paid custom domains while all commercial data remains tenant/store scoped in the application/database.

| Free store:  storename.karobarone.com ----                                           +--> edge/ingress --> storefront-router --> store snapshot
Paid domain: www.tenant-domain.com --------/

Host resolution result:
  host -> store_id -> publication_state -> active content/read projection

Do NOT create per-tenant pods, services, databases or ingress resources. |
| --- |

| Rule | Requirement |
| --- | --- |
| Free host | Wildcard/subdomain routing supports immutable storename.karobarone.com. |
| Paid host | Custom domain is served only after domain/DNS/publication gates pass. |
| Free conversion | Custom-domain serving stops; Free subdomain route becomes authoritative. |
| Unknown host | Return controlled not-found/unconfigured response; never infer tenant by untrusted path parameter. |
| Host cache | Redis/CDN cache may accelerate lookup, but publication database/projection remains authoritative. |
| DNS changes | Domain service owns lifecycle; Kubernetes application routing stays generic and host-driven. |

# **9. Network Security and NetworkPolicy**

## **9.1 Default-Deny Model**

Each production namespace should adopt default-deny ingress and egress. Workloads receive explicit allowances based on their dependency graph. NetworkPolicy supplements application authorization; it does not replace JWT/service identity or PostgreSQL RLS.

| Source | Destination | Port/protocol class | Policy |
| --- | --- | --- | --- |
| Ingress controller | Public API/storefront Services | HTTP/TCP | Allow only required public Service selectors. |
| API/worker pods | PostgreSQL/CNPG Service | PostgreSQL/TCP | Allow only service workloads; DB roles still schema-scoped. |
| Consumers/workers | Kafka brokers | Kafka/TCP | Allow required producer/consumer workloads only. |
| API/worker pods | Redis | Redis/TCP | Allow only workloads using cache/rate-limit functions. |
| Application pods | OTel collector | OTLP | Allow telemetry egress. |
| Application pods | DNS | UDP/TCP DNS | Allow cluster DNS. |
| Provider adapter workloads | Internet provider APIs | HTTPS | Allow controlled egress; preferably via egress policy/proxy where platform supports. |
| Unknown workload | DB/Kafka/Redis/internal services | Any | Deny. |

## **9.2 NetworkPolicy Review Rules**

- A new service cannot gain broad namespace-wide egress merely because development is easier.
- A new provider integration requires an explicit outbound dependency and secret review.
- Data stores never use public internet endpoints unless a managed provider requires one and access is protected by private networking/IP/TLS controls documented in an ADR.
- NetworkPolicy changes are reviewed with the service manifest and tested in staging.

# **10. Service Accounts, RBAC and Workload Identity**

| Control | Standard |
| --- | --- |
| ServiceAccount | Dedicated per deployable workload or service family; no default ServiceAccount for production application pods. |
| Kubernetes API RBAC | Application pods receive no Kubernetes write permission unless explicitly required. |
| Cloud/provider identity | Use workload identity/service-account federation where supported instead of long-lived static cloud keys. |
| Migration identity | Dedicated migration Job identity with DB migration permission; application runtime role does not acquire schema-owner privileges. |
| Operator identities | CloudNativePG/ingress/observability operators run in platform-controlled service accounts. |
| Break-glass | Human emergency access is time-bound/audited and distinct from normal CI/CD identity. |

# **11. Configuration, Secrets and Certificates**

| Configuration class | Examples | Kubernetes handling |
| --- | --- | --- |
| Non-secret runtime | SERVICE_NAME, ENVIRONMENT, LOG_LEVEL, endpoints | ConfigMap/environment variables; source-controlled defaults where safe. |
| Secrets | DB password, provider tokens, JWT private keys | External secret manager -> Secret reference where available; never Git/image. |
| Business configuration | Plan limits, policy gates, timeouts defined as business config | Versioned PostgreSQL tables owned by the domain service; not ConfigMaps. |
| Operational tuning | worker concurrency, pool size, batch size | ConfigMap/env with documented defaults/ranges. |
| TLS certificates | Ingress origin/public certificates | Automated certificate manager/provider integration; renew before expiry. |
| Webhook secrets | Razorpay/Shiprocket/notification provider signing keys | Environment-scoped secret, rotation runbook required. |

- Secrets must not appear in pod specs committed to Git, logs, crash dumps or test fixtures.
- Provider credentials are scoped per environment and, where applicable, per tenant/provider connection.
- Secret rotation should support overlapping old/new credentials when provider semantics permit to avoid downtime.
- Changing a Secret/ConfigMap must cause controlled workload reload/rollout; applications should not assume pod-local mutable configuration.

# **12. Container Image and Runtime Security**

| Requirement | Baseline |
| --- | --- |
| Build | Multi-stage build from committed lockfile; production image contains runtime dependencies only. |
| Base image | Minimal supported Python runtime; production pipeline pins approved image digest/release. |
| User | Non-root UID/GID. |
| Privilege | allowPrivilegeEscalation=false; drop Linux capabilities by default. |
| Filesystem | Read-only root where feasible; explicit /tmp or writable volume only when required. |
| Secrets | Never baked into image layers. |
| Image identity | Immutable tag by Git SHA; deployment records image digest and migration revision. |
| Scanning | Dependency, secret and container image scan before promotion. |
| SBOM/provenance | Recommended baseline; mandatory when organizational/compliance policy requires. |
| Entrypoint | Explicit API/worker/consumer role; migrations are separate Jobs. |

# **13. Health Probes, Graceful Shutdown and Availability**

| Endpoint / behavior | Rule |
| --- | --- |
| /health/live | Process liveness only; must not fail merely because a downstream dependency is temporarily unavailable. |
| /health/ready | Indicates workload can perform intended function. Database is required for transactional services; optional dependencies are assessed by service criticality. |
| startupProbe | Recommended for workloads with slower initialization to avoid premature liveness restarts. |
| SIGTERM handling | Stop accepting new requests/records, allow bounded in-flight completion, flush telemetry, close DB/Kafka connections. |
| Consumer shutdown | Stop polling before termination; commit/ack only after local transaction succeeds. |
| Readiness before rollout | New pod becomes ready only after configuration, DB connectivity and required contract/bootstrap checks pass. |

| Technical tuning — Probe periods/timeouts/failure thresholds are deployment values and must be tuned from staging behavior. They are not business requirements. |
| --- |

# **14. Resource Requests, Limits and Autoscaling**

## **14.1 Resource Policy**

- Every production pod has CPU and memory requests/limits established from measured staging/load tests.
- No production workload uses “unlimited” resources by omission.
- Memory limits should avoid predictable OOMKill under normal p95 load; CPU limits should not create unacceptable throttling.
- Resource changes are version-controlled deployment changes and should reference load/observability evidence.

## **14.2 Autoscaling**

| Workload | Primary signal | Secondary signal | Notes |
| --- | --- | --- | --- |
| HTTP API | CPU / request concurrency | p95 latency / request rate where supported | HPA; keep at least enough replicas to preserve maintenance/rollout availability. |
| Kafka consumer | Kafka lag | CPU / processing latency | KEDA recommended when lag metrics are available; replicas cannot usefully exceed partition count. |
| Outbox publisher | Outbox backlog age/count | CPU / publish latency | Scale cautiously to avoid DB hot-row contention. |
| Scheduler | Due-job backlog / lateness | CPU | Correctness comes from DB claiming/idempotency, not single-replica assumption. |
| Storefront read API | Request rate / CPU | cache hit ratio / p95 latency | Designed for horizontal scale and CDN/cache acceleration. |

## **14.3 PodDisruptionBudget**

Production APIs with multiple replicas should use a PDB so voluntary maintenance does not remove all replicas simultaneously. PDB values depend on replica count; a common initial pattern is maxUnavailable: 1 for workloads with at least two replicas. Single-replica dev/staging workloads do not gain availability from a PDB.

# **15. PostgreSQL / CloudNativePG Architecture**

V1 uses one authoritative PostgreSQL cluster with one schema per logical service. Service runtime roles write only their own schema. Cross-service UUID references are validated through service/API/event boundaries rather than hard cross-schema foreign keys by default.

| Area | Production baseline |
| --- | --- |
| Operator/control plane | CloudNativePG preferred. Application pods never manage database lifecycle. |
| Topology | HA-capable PostgreSQL cluster; production replica count determined by availability/cost test. Three instances are the target pattern where budget permits. |
| Storage | Persistent volumes with provider-backed durable block storage; storage class selected for database IOPS/latency. |
| Schemas | iam, tenant, subscription, domain, catalog, approval, customer, inventory, commerce, booking, payment, fulfilment, finance, compliance, notification, analytics. |
| Roles | Separate runtime/migration roles. Runtime write privileges limited to owned schema; RLS/session context applied where specified. |
| Connections | Connection pool per service; maximum pools sized against DB max connections. Add pooler only when measured need warrants. |
| Backups | Daily backup minimum, 15-day retention; periodic restore test mandatory. |
| WAL | Continuous WAL archiving recommended to reduce data-loss window beyond daily-backup baseline. |
| Monitoring | Replication status, storage usage, connections, lock waits, slow queries, backup status and restore test evidence. |
| Maintenance | Vacuum/analyze/autovacuum monitored; index growth and due-job queue indexes reviewed as scale increases. |

## **15.1 Database Availability and Failover**

- Applications connect through the CloudNativePG read-write Service rather than a specific pod.
- Failover must not require changing application configuration.
- Connection pools must tolerate transient failover and recreate connections.
- Database HA does not replace application idempotency; retried transactions/requests must remain safe.
- Production failover behavior is tested in staging before release certification.

## **15.2 RPO/RTO Status**

| Open decision — The approved baseline specifies daily backup and 15-day retention but does not define contractual RPO/RTO. Without WAL/PITR, worst-case data loss can approach the backup interval. Production launch should approve RPO/RTO and select backup/WAL/restore controls accordingly. |
| --- |

# **16. Kafka Platform Integration**

The production Kafka hosting model is intentionally provider-neutral. Kafka may be managed externally or Kubernetes-hosted using an approved operator; application contracts must not depend on that choice. The infrastructure specification therefore governs access, topic provisioning, security, observability and consumer scaling rather than mandating a broker vendor.

| Concern | Rule |
| --- | --- |
| Bootstrap/config | Injected per environment through ConfigMap/Secret references. |
| Security | TLS/authentication according to selected Kafka platform; credentials scoped per environment/workload where feasible. |
| Topics | Provision the approved topic families and DLQs declaratively before dependent consumers are promoted. |
| Partitioning | Partition by aggregate/store key where ordering matters; do not rely on total topic ordering. |
| Consumers | Consumer groups per logical reaction; idempotent inbox marker committed with side effects. |
| Scaling | Scale by lag/processing latency; consumer replica count constrained by partitions. |
| Outbox | DB transaction writes outbox; publisher retries until broker acknowledgement. |
| DLQ | Poison events move after bounded retries with original metadata and alert. |
| Monitoring | Broker/client errors, publish latency, consumer lag, processing latency, retry rate, DLQ count. |
| Timer rule | Kafka is not a timer; due-time workflows use durable scheduler jobs. |

# **17. Redis Platform Integration**

| Use | Allowed | Not allowed |
| --- | --- | --- |
| Rate limiting | Yes | Cannot be sole source for legally/commercially significant counters. |
| Ephemeral cache | Yes | Cannot determine payment/commission/subscription truth if DB unavailable. |
| Read acceleration | Yes | Must be invalidatable/reconstructable from authoritative state. |
| Distributed lock | Only with careful bounded use | Must not replace DB transaction/unique constraint for financial correctness. |
| Session/auth hints | Possible according to IAM design | Authoritative session revocation/records remain controlled by IAM persistence. |
| Queue | Not primary platform queue | Kafka/durable DB jobs remain async foundations. |

Redis failure must degrade performance or optional functions, not corrupt commercial state. Applications require explicit timeouts and circuit/fallback behavior rather than indefinite blocking on Redis.

# **18. Object Storage and Media Delivery**

| Area | Rule |
| --- | --- |
| Storage | S3-compatible private object storage. |
| Uploads | Application issues pre-signed upload intent; large binaries are not proxied through API pods unless required for scanning. |
| Public images | Delivered through controlled CDN/proxy/public object policy only after content/publication rules permit. |
| Digital products | Private; time-limited signed links; initial policy 24 hours/max 3 downloads as defined by business specification. |
| Keys | Non-guessable object keys; never expose permanent digital-product object URL. |
| Metadata | MIME, size, checksum, dimensions/duration, owner tenant/store, scan/approval reference stored in DB. |
| Scanning | Malware/content scanning recommended before availability where appropriate. |
| Lifecycle | Temporary uploads, failed uploads and expired derived objects use lifecycle cleanup policies; statutory/business records remain in DB. |
| Backup | Object-storage durability/lifecycle policy is separate from PostgreSQL backup and must be documented for production. |

# **19. Scheduler, Workers and Asynchronous Jobs**

| Job family | Infrastructure execution | Correctness guard |
| --- | --- | --- |
| Subscription lifecycle | Scheduler Deployment + DB scheduled_jobs | Unique business key per subscription/period/transition; row claim with SKIP LOCKED. |
| Inventory expiry | Scheduler/worker | Active reservation + expires_at state guard; atomic release. |
| Booking deadline | Scheduler/worker | Lock booking/capacity reservation before release/transition. |
| Commission invoice/due | Scheduler/worker | Only uninvoiced eligible rows; unique invoice-line key; deterministic cutoff. |
| Minor adulthood | Scheduled date-driven job | Transition once with audit evidence. |
| Payment/shipment reconciliation | CronJob/durable scheduled job | Compare provider authoritative state; use correction commands/idempotency; never destructive rewrite. |
| Digital link expiry | Scheduler / token TTL checks | Expire token/entitlement state idempotently. |

Worker pods are horizontally scalable. Correctness must not depend on a singleton scheduler leader; database claiming and unique business keys are the safety mechanism.

# **20. Database Migration Deployment Pattern**

Each service owns its Alembic migration history. Production migrations are executed as dedicated Kubernetes Jobs in a canonical service order under a single migration gate. Applications do not run migrations automatically on pod startup.

1. Build and test migration on clean database and upgrade from previous supported revision.

2. Create immutable application images and deployment manifests referencing the same Git SHA.

3. Run pre-deploy migration Job with dedicated migration credentials.

4. Verify migration completion, expected schema revision and key health queries.

5. Roll out backward-compatible application version.

6. Run smoke/contract/workflow checks.

7. Perform later destructive/contract migration only after old application/data path is no longer used and recovery plan is approved.

| Migration rule — Prefer expand -> backfill -> switch -> contract. Application rollback is allowed only while database changes remain backward-compatible; otherwise roll forward. |
| --- |

# **21. Observability Platform**

| Signal | Platform | Minimum coverage |
| --- | --- | --- |
| Logs | Centralized JSON log pipeline | service, env, request/correlation/trace IDs, safe principal/tenant/store UUID context, event_id, stable error code; redact PAN/GSTIN/OTP/provider secrets. |
| Metrics | Prometheus | request rate/latency/errors/429; DB pool/locks; Kafka lag/retries/DLQ; outbox backlog; scheduler lateness; business-safe counters. |
| Traces | OpenTelemetry collector/backend | HTTP -> internal HTTP -> Kafka publish/consume -> worker spans using correlation/trace context. |
| Dashboards | Grafana | API health, Kafka/outbox, DB, scheduler, provider integration, business workflow signals. |
| Audit | Domain-owned append-only DB records | Material admin/commercial/legal decisions; operational logs are not a substitute for audit evidence. |

## **21.1 Metric Cardinality Rules**

- Use route templates, service name, status class, event type and consumer group as bounded labels.
- Do not label Prometheus metrics by tenant_id, store_id, customer_id, PAN/GSTIN, order_id or other unbounded identifiers.
- High-cardinality investigation belongs in logs/traces with access controls, not metric labels.

# **22. Alerting and Operational SLO Signals**

The BRD establishes an initial 99.5% availability target but does not define a complete SLO/error-budget policy. Infrastructure alerts therefore focus on user-impact and correctness risks while formal SLO thresholds can be finalized through production-readiness review.

| Alert area | Trigger class | Operational response |
| --- | --- | --- |
| Public API availability | Sustained readiness failure / 5xx rate / latency degradation | Check ingress, service replicas, DB dependencies; rollback if release-related. |
| PostgreSQL | Primary unavailable, replication unhealthy, storage high, backup failure | CNPG/DB runbook; protect writes; failover/restore decision. |
| Kafka | Publish failures, large consumer lag, DLQ growth | Inspect broker/client, outbox backlog and consumer errors; reconcile affected workflows. |
| Outbox | Oldest unpublished age / backlog above threshold | Restore publisher/Kafka; verify no duplicate business mutation. |
| Scheduler | Due-job lateness/backlog | Catch-up with duplicate guards; assess subscription/commission/customer impact. |
| Webhook integrations | Signature failures spike / provider callbacks absent / reconciliation mismatch | Provider outage/reconciliation runbook. |
| Security | Secret leak, denied cross-tenant attempt anomalies, WAF attack spike | Security escalation and credential/session containment. |
| Storage | PVC/object-store quota or filesystem pressure | Capacity action before write failure. |

# **23. CI/CD Deployment Pipeline**

| Stage | Infrastructure/deployment action | Gate |
| --- | --- | --- |
| 1. Change detection | Determine services/contracts/migrations/deploy overlays affected | Invalid metadata/path blocks. |
| 2. Static quality | Lint/type/import-boundary/manifests | PR blocked. |
| 3. Unit + contract | Unit/state policies; OpenAPI/AsyncAPI/JSON Schema compatibility | PR blocked. |
| 4. Migration validation | Fresh DB + previous revision upgrade; schema ownership | PR blocked. |
| 5. Integration | PostgreSQL/Kafka/Redis; outbox/inbox/RLS; provider fakes | PR blocked. |
| 6. Security | Dependency/secret/SAST/container scan | Severity policy gate. |
| 7. Build | Immutable images by Git SHA; SBOM/provenance where enabled | No deploy if build fails. |
| 8. Dev deploy | Apply migrations + deploy selected workloads + smoke | Integration feedback. |
| 9. Staging deploy | Production-like manifests + workflow/resilience/load/security/restore checks | Promotion blocked on failure. |
| 10. Release certification | Full AC-001..AC-090 + required engineering invariant suite | Production blocked on failure. |
| 11. Prod migration | Single-writer migration Job; verify revision | Application rollout halted on failure. |
| 12. Prod rollout | Approved image digest/manifests; rolling/canary; health/reconciliation | Rollback/roll-forward if health gate fails. |

# **24. Release, Promotion and Rollback Strategy**

## **24.1 Default Rolling Release**

- Deploy immutable image digest/Git SHA.
- Readiness protects traffic from unready pods.
- maxUnavailable/maxSurge configured to preserve capacity for critical APIs.
- Monitor service, DB, Kafka and business workflow signals during rollout.
- Stop/rollback if failure thresholds are reached.

## **24.2 Canary / Blue-Green**

High-risk changes such as payment, subscription, migration or routing changes may use canary or blue-green deployment. This is an infrastructure technique only; API/event versions and state-machine rules remain unchanged. A canary must not consume a Kafka partition subset in a way that creates mixed incompatible event semantics.

## **24.3 Rollback Rules**

| Change type | Rollback policy |
| --- | --- |
| Application-only, DB backward-compatible | Rollback to prior image digest after health check. |
| Additive DB change | Application rollback allowed if old version tolerates new schema. |
| Destructive/incompatible DB change | Prefer roll-forward; restore only through approved DB incident procedure. |
| Event schema additive compatible | Old/new consumers may coexist if contract tests prove compatibility. |
| Event breaking change | Use new .v2 event type; do not mutate .v1 meaning. |
| Configuration/secret | Revert source-controlled config or rotate credential; verify dependent provider state. |

# **25. Backup, Restore and Disaster Recovery**

| Data/service | Minimum baseline | Recommended enhancement |
| --- | --- | --- |
| PostgreSQL | Daily backup; 15-day retention; periodic restore test | Continuous WAL/PITR; separate backup bucket/account; backup integrity monitoring. |
| Object storage | Provider durability + lifecycle policy | Versioning/replication according to approved retention/RPO. |
| Kafka | Events are integration transport, not sole business truth | Platform replication/retention sized for recovery/replay; critical truth remains DB. |
| Redis | No correctness dependency | Rebuild cache; persistence optional by use case. |
| Kubernetes manifests | Git/source control | Git mirror/repository backup; immutable release artifacts. |
| Secrets | Secret-manager backup/recovery according to provider | Document key rotation/recovery and access audit. |

## **25.1 Restore Drill**

1. Restore PostgreSQL backup into isolated staging/recovery environment.

2. Verify expected backup timestamp and migration revision.

3. Run schema checks plus representative tenant/order/subscription/commission integrity queries.

4. Deploy compatible application image and run smoke + selected workflow/acceptance tests.

5. Verify outbox/inbox/scheduler state to prevent duplicate replay or missed due jobs.

6. Record actual restore duration, data-loss window and remediation actions.

## **25.2 Disaster-Recovery Limitation**

| Important — The current product baseline defines 99.5% initial availability and backup retention, but not contractual multi-region DR, RPO or RTO. This document therefore does not promise those values. They must be explicitly approved before production SLA commitments are made. |
| --- |

# **26. Capacity, Scaling and Performance Controls**

| Risk / bottleneck | Infrastructure control |
| --- | --- |
| Hot inventory SKU row contention | Atomic DB reservation, short transactions, indexes, load test final-unit races; scale app pods only after DB contention understood. |
| Appointment slot contention | Atomic capacity reservation; isolate hot rows; monitor lock waits. |
| Kafka partition imbalance | Partition by aggregate/store as appropriate; monitor per-partition lag; increase partitions with compatibility/ordering review. |
| Large tenant/admin queries | tenant/store/date indexes, cursor pagination, read projections; protect DB from unbounded exports. |
| Approval/analytics read load | Use projections/analytics service; avoid heavy cross-domain joins on OLTP schemas. |
| Scheduler scans | due_at/state partial indexes; batch claims with SKIP LOCKED; monitor oldest due age. |
| Webhook bursts | Fast validate/persist/dedupe response; async normalization/consumption; HPA and queue/backlog monitoring. |
| Storefront reads | CDN/cache/read projection; horizontal API scale; avoid transactional multi-service joins per request. |

# **27. Security and Supply-Chain Controls**

| Control plane | Required control |
| --- | --- |
| Source control | Protected main, CODEOWNERS, PR review, secret scanning. |
| Dependencies | Lockfile, vulnerability scan, controlled update PRs. |
| Containers | Non-root/minimal image, image scan, immutable digest, optional signature/SBOM. |
| Kubernetes | Least RBAC, dedicated ServiceAccounts, NetworkPolicy, restricted pod security, no public data services. |
| Secrets | External secret manager where available; environment-scoped; rotation runbook. |
| Ingress | HTTPS + Cloudflare/WAF; controlled routes; application authorization still mandatory. |
| Database | Schema-scoped roles, RLS where specified, encrypted/fingerprinted sensitive identifiers. |
| Provider callbacks | Signature/auth validation, raw retention, dedupe/replay safety. |
| Logging | Redaction; no PAN/GSTIN/OTP/provider secrets in ordinary logs. |
| Human access | Least privilege, audited admin/break-glass paths; production credentials separated from development. |

# **28. Maintenance and Operational Runbooks**

| Runbook | Minimum infrastructure content |
| --- | --- |
| Database migration failure | Stop rollout; identify applied revisions; DB health; roll-forward/restore decision; owner/escalation. |
| PostgreSQL failover/restore | CNPG state, primary/replica health, backup choice, restore/failover steps, app reconnect validation. |
| Kafka lag/DLQ | Consumer group/topic/partition; failing event; replay/skip criteria; reconciliation. |
| Outbox backlog | DB backlog query; publisher/Kafka health; safe replay; duplicate-risk verification. |
| Razorpay webhook outage | Provider health; raw event/reconciliation; replay path; payment correction command. |
| Shiprocket webhook outage | Provider polling/reconciliation; shipment/COD commission impact. |
| Subscription scheduler delay | Due-job backlog; catch-up; duplicate guard; affected stores/timers. |
| Commission invoice failure | Cutoff; duplicate-line guard; rerun; tenant restriction impact. |
| Secret compromise | Revoke/rotate; redeploy; access audit; session invalidation where relevant. |
| Production rollback | Image vs schema compatibility; Kafka consumer/version interaction; post-rollback reconciliation. |
| Certificate/DNS incident | Edge/origin cert status, DNS records, custom-domain impact, safe fallback for Free domain where applicable. |

# **29. Environment Promotion and Change Management**

| Change | Dev | Staging | Prod |
| --- | --- | --- | --- |
| Application image | Auto/developer integration | Release candidate digest | Same approved digest promoted; no rebuild. |
| DB migration | Ephemeral + upgrade test | Production-like migration rehearsal | Gated single-writer Job. |
| Contract change | Generate/diff | Compatibility + consumer tests | Only approved version. |
| Infrastructure manifest | Schema/lint/render | Apply + smoke + policy tests | Approved rendered diff/change record. |
| Secrets | Non-prod credentials | Staging credentials | Separate production credentials. |
| Provider integrations | Fake/sandbox | Sandbox/test where available | Production account/tenant context. |
| Acceptance tests | Impacted subset | Cross-service release pack | Full release certification required before promotion. |

- Production uses artifact promotion rather than rebuilding from source after staging approval.
- Manual production changes outside source control are prohibited except documented emergency break-glass actions, which must be reconciled back into source control.
- Infrastructure changes that affect network/data/security boundaries require architecture/security review and an ADR when material.

# **30. Infrastructure Testing and Production Readiness**

| Test area | Required validation |
| --- | --- |
| Kubernetes manifests | Schema/render/lint; namespace, ServiceAccount, probes, resources, securityContext, NetworkPolicy present. |
| Network isolation | Unauthorized pod cannot reach DB/Kafka/Redis/internal API; approved flows work. |
| RLS/tenant isolation | Cross-tenant read/write denied even with repository predicate omission where RLS applies. |
| Failover | API reconnects after DB failover; duplicate transaction effects do not occur. |
| Kafka outage | Committed DB mutation/outbox survives; later publish produces one downstream effect. |
| Consumer replay | Duplicate event is harmless; DLQ/replay runbook verified. |
| Scheduler concurrency | Multiple replicas create one lifecycle effect/charge. |
| Webhook burst/replay | Fast durable acceptance; duplicate/out-of-order events do not regress state. |
| Autoscaling | Scale-out/scale-in preserves readiness and does not exceed Kafka partition usefulness. |
| Backup/restore | Restore drill completes with application/schema/business integrity checks. |
| Rolling release | At least one production-like rollout/rollback rehearsal in staging. |
| Security | Image/secret/dependency scan, pod security, RBAC, NetworkPolicy, ingress exposure review. |
| Acceptance | Full AC-001..AC-090 + mandatory engineering suite passes before production release. |

Production cannot be declared ready while unresolved S0/S1 defects exist. Cross-tenant access, duplicate financial side effects, ledger corruption, payment/webhook authority flaws, inventory oversell and subscription misbilling are release blockers.

# **31. Implementation Phases**

| Phase | Infrastructure deliverable | Exit condition |
| --- | --- | --- |
| I0 - Local foundation | Docker Compose PostgreSQL/Kafka/Redis/object storage/mail + service images | One service runs migrations, publishes outbox event and consumes idempotently. |
| I1 - Dev Kubernetes | Namespace, ingress, ServiceAccounts, ConfigMaps/Secrets, probes, NetworkPolicy, dev CNPG | Free Presence slice deploys and smoke tests pass. |
| I2 - Observability/CI | OTel/Prometheus/Grafana/log pipeline + contract/migration/security gates | Dashboards/alerts visible; PR quality gates enforced. |
| I3 - Staging | Production-like routing, provider sandboxes, HPA/PDB, backup/restore rehearsal | Release candidate workflow and resilience tests pass. |
| I4 - Production data plane | Production CNPG, Kafka/Redis integrations, private storage, secret manager | Backup/failover/security verification complete. |
| I5 - Production release | Cloudflare/WAF/ingress, migration gate, immutable images, rollout/rollback | Full acceptance certification and operational approval. |
| I6 - Scale hardening | Lag-based autoscaling, tuned resources/partitions/indexes, DR improvement | Measured performance and incident/runbook maturity. |

# **32. Open Decisions and Provider-Specific Extension Points**

| Decision | Status | Infrastructure constraint |
| --- | --- | --- |
| Production cloud / Kubernetes provider | Open | Must support private networking, persistent storage, load balancing and IAM/secret integration. |
| Kafka managed vs self-hosted/operator | Open | Keep application contracts provider-neutral; ensure TLS/auth, topic provisioning, lag metrics and DLQ operations. |
| Redis managed vs Kubernetes-hosted | Open | Failure cannot affect correctness; private access only. |
| Object storage/CDN provider | Open | S3-compatible private storage, signed URLs, lifecycle rules and auditability. |
| External secret manager | Open | Prefer workload identity and automated sync/rotation; never Git secrets. |
| Ingress controller/API gateway | Open | Must support HTTPS, host routing, Webhook routes, rate limits, observability and Cloudflare origin. |
| Certificate automation | Open | Must renew origin/custom-domain certs before expiry and expose failure alerts. |
| RPO/RTO | Open - business/ops approval required | Backup/WAL/DR design must be validated against approved targets. |
| Admin access gateway/VPN | Open | Must not weaken application RBAC; production admin paths require stronger access controls. |
| KEDA / custom metrics stack | Recommended option | Use when Kafka-lag/request metrics are needed for autoscaling; not required for initial correctness. |

# **Appendix A - Kubernetes Naming and Labeling Standard**

| Object | Pattern | Example |
| --- | --- | --- |
| Namespace | karobarone-<env> | karobarone-prod |
| Deployment | <service>-<role> | commerce-api / payment-consumer |
| Service | <service>-api | commerce-api |
| ServiceAccount | <service>-<role> | commerce-api |
| ConfigMap | <service>-config | commerce-config |
| Secret reference | <service>-secrets | payment-secrets |
| HPA | <deployment> | commerce-api |
| PDB | <deployment> | commerce-api |
| NetworkPolicy | <source>-to-<destination> | commerce-to-postgres |
| Migration Job | migrate-<service>-<revision> | migrate-commerce-a1b2c3 |
| Image | registry/karobarone/<service>:<git-sha> | registry/karobarone/commerce:9f12... |

# **Appendix B - Illustrative Kubernetes Manifests**

| Important — These snippets are infrastructure templates, not provider-ready production manifests. Exact API versions, annotations, storage classes, ingress classes, secret integrations and CNPG options must be validated against the selected platform/version before deployment. |
| --- |

## **B.1 FastAPI Deployment + Service**

| apiVersion: apps/v1
kind: Deployment
metadata:
  name: commerce-api
  labels:
    app.kubernetes.io/name: commerce-api
    app.kubernetes.io/part-of: karobarone
spec:
  replicas: 2
  strategy:
    type: RollingUpdate
  selector:
    matchLabels:
      app.kubernetes.io/name: commerce-api
  template:
    metadata:
      labels:
        app.kubernetes.io/name: commerce-api
        karobarone.io/service: commerce
    spec:
      serviceAccountName: commerce-api
      containers:
      - name: api
        image: registry/karobarone/commerce:<git-sha>
        ports:
        - containerPort: 8080
        securityContext:
          runAsNonRoot: true
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities: { drop: ["ALL"] }
        readinessProbe:
          httpGet: { path: /health/ready, port: 8080 }
        livenessProbe:
          httpGet: { path: /health/live, port: 8080 }
        resources:
          requests: { cpu: "100m", memory: "256Mi" }
          limits:   { cpu: "500m", memory: "512Mi" }
---
apiVersion: v1
kind: Service
metadata: { name: commerce-api }
spec:
  type: ClusterIP
  selector: { app.kubernetes.io/name: commerce-api }
  ports:
  - port: 80
    targetPort: 8080 |
| --- |

## **B.2 HPA**

| apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: { name: commerce-api }
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: commerce-api
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 65
# Values are illustrative; production thresholds come from staging/load evidence. |
| --- |

## **B.3 PodDisruptionBudget**

| apiVersion: policy/v1
kind: PodDisruptionBudget
metadata: { name: commerce-api }
spec:
  maxUnavailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: commerce-api |
| --- |

## **B.4 Default-Deny NetworkPolicy**

| apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: default-deny }
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress] |
| --- |

## **B.5 Allow Commerce -> PostgreSQL**

| apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: commerce-to-postgres }
spec:
  podSelector:
    matchLabels: { karobarone.io/service: commerce }
  policyTypes: [Egress]
  egress:
  - to:
    - namespaceSelector:
        matchLabels: { karobarone.io/data-plane: "true" }
      podSelector:
        matchLabels: { cnpg.io/cluster: karobarone-postgres }
    ports:
    - { protocol: TCP, port: 5432 }
# Adapt selectors to actual CNPG/platform labels. |
| --- |

## **B.6 Migration Job**

| apiVersion: batch/v1
kind: Job
metadata: { name: migrate-commerce-<revision> }
spec:
  backoffLimit: 1
  template:
    spec:
      restartPolicy: Never
      serviceAccountName: commerce-migration
      containers:
      - name: migrate
        image: registry/karobarone/commerce:<git-sha>
        command: ["alembic", "upgrade", "head"]
        envFrom:
        - configMapRef: { name: commerce-config }
        - secretRef: { name: commerce-migration-secrets } |
| --- |

## **B.7 CloudNativePG Cluster - Illustrative**

| apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata: { name: karobarone-postgres }
spec:
  instances: 3
  storage:
    size: 100Gi
  # Configure provider storageClass, resources and backup/WAL settings.
  # Runtime/migration roles and schema ownership are managed separately.
# Validate fields against the installed CloudNativePG release. |
| --- |

## **B.8 Kafka Consumer Deployment**

| apiVersion: apps/v1
kind: Deployment
metadata: { name: finance-consumer }
spec:
  replicas: 2
  selector:
    matchLabels: { app.kubernetes.io/name: finance-consumer }
  template:
    metadata:
      labels:
        app.kubernetes.io/name: finance-consumer
        karobarone.io/service: finance
    spec:
      serviceAccountName: finance-consumer
      containers:
      - name: consumer
        image: registry/karobarone/finance:<git-sha>
        args: ["python", "-m", "karobarone_finance.workers.kafka_consumer"]
        # Scale using Kafka lag when metrics/KEDA are available. |
| --- |

# **Appendix C - Network Flow Matrix**

| Source | Destination | Protocol | Rule |
| --- | --- | --- | --- |
| Internet | Cloudflare/WAF | HTTPS | Public traffic only. |
| Cloudflare/WAF | Ingress/Gateway | HTTPS | Origin restricted to trusted edge/network where possible. |
| Ingress/Gateway | Public API/storefront Services | HTTP/TLS internal | Only approved public routes. |
| API services | PostgreSQL | 5432/TCP | Only owned-schema DB role; private. |
| API/worker/consumer | Kafka | Kafka/TCP/TLS | Approved producers/consumers only. |
| API/worker | Redis | Redis/TCP/TLS where supported | Cache/rate limit only. |
| API/worker | OTel collector | OTLP | Telemetry. |
| Prometheus | Application /metrics | HTTP internal | Metrics scrape only. |
| Provider webhooks | Ingress webhook endpoints | HTTPS | Validated callbacks. |
| Provider adapters | External provider APIs | HTTPS egress | Explicit provider domains/endpoints. |
| App workloads | Object storage | HTTPS | Signed/private object operations. |
| DB operator | Object backup storage | HTTPS | Backup/WAL archive if configured. |
| Developer workstation | Prod DB/Kafka/Redis | None by default | No direct routine access; break-glass only. |

# **Appendix D - Production Readiness Checklist**

☐ Production cluster/namespace and credentials are isolated from development.

☐ All public routes terminate through Cloudflare/WAF and HTTPS; internal services are ClusterIP-only.

☐ Default-deny NetworkPolicy exists and required data/service flows are explicitly allowed.

☐ Every workload has dedicated ServiceAccount and least Kubernetes RBAC.

☐ Production images run non-root and pass dependency/secret/container scan policy.

☐ CPU/memory requests and limits are defined from staging/load evidence.

☐ Readiness/liveness/startup behavior and graceful shutdown are tested.

☐ Critical APIs have appropriate replica/PDB/HPA policy.

☐ Kafka consumers use idempotent inbox/business-key protection and monitored DLQ/retry.

☐ Outbox publisher recovers from broker outage without duplicate business mutation.

☐ CloudNativePG cluster, schema roles, backups and failover path are verified.

☐ Daily PostgreSQL backup and 15-day retention are active; restore drill evidence exists.

☐ RPO/RTO decision is explicitly approved or documented as open risk before SLA commitment.

☐ Object storage is private by default; digital-product permanent public URLs are impossible.

☐ Secrets are externalized and environment-scoped; rotation runbooks exist.

☐ OpenTelemetry traces, Prometheus metrics, centralized logs and core dashboards are live.

☐ Alerts cover API, DB, Kafka, outbox, scheduler, provider webhooks, storage and security conditions.

☐ Migrations run as gated Jobs and expand/backfill/switch/contract rules are followed.

☐ Staging rehearsal includes migration, rollout, rollback/roll-forward, DB failover/recovery and webhook/Kafka resilience.

☐ Full AC-001..AC-090 and mandatory engineering invariant suite pass.

☐ No unresolved S0/S1 defects remain.

☐ Operational runbooks and escalation ownership exist for critical data/async/provider failures.

☐ Deployed image digests, manifest revision and DB migration revisions are recorded for the release.

# **Engineering Baseline Statement**

This Infrastructure & Kubernetes Deployment Specification V1.0 is the proposed deployment baseline for KarobarOne V1. It operationalizes the approved backend architecture without redefining business policy. Provider-specific choices may evolve through controlled infrastructure decisions, but tenant isolation, private data services, schema ownership, idempotent asynchronous processing, migration gates, observability, backup/restore, acceptance testing and security controls remain mandatory.

Derived from KarobarOne BRD V2.1 and the approved Backend Technical Design, Database Design, State Machine, API/Event Contract, Repository/Foundation and Backend Test & Acceptance specifications.
