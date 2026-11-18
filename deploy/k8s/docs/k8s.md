# Kubernetes Deployment Runbook — KarobarOne Microservices

This runbook documents local validation (using [kind](https://kind.sigs.k8s.io/) or minikube) and production Kustomize manifest operations.

> [!NOTE]
> Production and staging runtime is **Render (Docker)** with Neon Postgres (see `DEPLOY.md §4`).
> Kubernetes manifests are maintained for local offline validation and future cloud cluster migrations. Render does not execute Kubernetes manifests.

---

## 1. Directory Structure

```
deploy/k8s/
├── base/
│   ├── namespace.yaml           # Enforces Pod Security Standard 'restricted'
│   ├── network-policy.yaml      # Default deny + Gateway/Mesh/Neon ingress/egress
│   ├── gateway.yaml             # API Gateway Reverse Proxy (Deployment, Service, Ingress, PDB, HPA)
│   ├── migration-jobs.yaml      # Pre-deployment one-off Alembic DB migration Jobs
│   ├── kustomization.yaml       # Base composition
│   └── services/
│       ├── iam.yaml             # IAM Service + Outbox Worker
│       ├── tenant.yaml          # Tenant Service + Outbox Worker
│       ├── approval.yaml        # Approval Service + Outbox Worker
│       ├── catalog.yaml         # Catalog Service + Outbox Worker
│       ├── domain.yaml          # Domain Service + Outbox Worker
│       ├── customer.yaml        # Customer Service + Outbox Worker
│       ├── subscription.yaml    # Subscription Service + Outbox/Scheduler Worker
│       └── inventory.yaml       # Inventory Service + Outbox/Reservation Worker
└── overlays/
    ├── dev/                     # Local KIND cluster overlay (PostgreSQL container, mock secrets)
    ├── staging/                 # Render / Staging branch overlay
    └── prod/                    # Production overlay (HPA, strict PDB, pinned release digests)
```

---

## 2. Local Kind Cluster Setup

### Prerequisites
- Docker Engine
- `kind` CLI (`brew install kind` / `choco install kind`)
- `kubectl` CLI

### Quickstart Script
Run the automated script in `tools/k8s/kind-up.sh`:
```bash
bash microservice/tools/k8s/kind-up.sh
```

### Manual Step-by-Step

#### Step 1: Create Kind Cluster
```bash
kind create cluster --name karobarone --config - <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 80
    hostPort: 8080
    protocol: TCP
EOF
```

#### Step 2: Build & Load Local Container Images
From the `microservice/` root directory:
```bash
# Build all service images
docker build -t karobarone/gateway:latest -f services/gateway/Dockerfile .
docker build -t karobarone/iam:latest -f services/iam/Dockerfile .
docker build -t karobarone/tenant:latest -f services/tenant/Dockerfile .
docker build -t karobarone/approval:latest -f services/approval/Dockerfile .
docker build -t karobarone/catalog:latest -f services/catalog/Dockerfile .
docker build -t karobarone/domain:latest -f services/domain/Dockerfile .
docker build -t karobarone/customer:latest -f services/customer/Dockerfile .
docker build -t karobarone/subscription:latest -f services/subscription/Dockerfile .
docker build -t karobarone/inventory:latest -f services/inventory/Dockerfile .

# Load images into kind cluster node
kind load docker-image karobarone/gateway:latest --name karobarone
kind load docker-image karobarone/iam:latest --name karobarone
kind load docker-image karobarone/tenant:latest --name karobarone
kind load docker-image karobarone/approval:latest --name karobarone
kind load docker-image karobarone/catalog:latest --name karobarone
kind load docker-image karobarone/domain:latest --name karobarone
kind load docker-image karobarone/customer:latest --name karobarone
kind load docker-image karobarone/subscription:latest --name karobarone
kind load docker-image karobarone/inventory:latest --name karobarone
```

#### Step 3: Apply Dev Kustomize Overlay
```bash
kubectl apply -k microservice/deploy/k8s/overlays/dev
```

#### Step 4: Bootstrap Database Schema (Dev Only)
Once the `postgres` pod in `karobar-platform` is running:
```bash
PG_POD=$(kubectl get pods -n karobar-platform -l app.kubernetes.io/name=postgres -o jsonpath='{.items[0].metadata.name}')
kubectl exec -i -n karobar-platform "$PG_POD" -- psql -U karobar_admin -d karobarone < microservice/tools/db/bootstrap.sql
```

#### Step 5: Run Database Migrations
Trigger migration jobs:
```bash
kubectl create job --from=cronjob/migrate-iam migrate-iam-manual -n karobar-platform || kubectl apply -f microservice/deploy/k8s/base/migration-jobs.yaml
kubectl wait --for=condition=complete job --all -n karobar-platform --timeout=120s
```

---

## 3. Verifying Deployment & Probes

Check pod status:
```bash
kubectl get pods -n karobar-platform
```

Verify service endpoints:
```bash
# Port forward gateway service
kubectl port-forward -n karobar-platform svc/gateway 8000:8000

# Health checks
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
```

---

## 4. Security Hardening Invariants Enforced

1. **Restricted Pod Security Standard**: Namespaces enforce `pod-security.kubernetes.io/enforce: restricted`.
2. **Non-Root & Read-Only**: All containers run with `runAsNonRoot: true`, `readOnlyRootFilesystem: true`, and drop `ALL` Linux capabilities.
3. **Automount Tokens Disabled**: `automountServiceAccountToken: false` on all ServiceAccounts.
4. **Default-Deny Network Policies**: Ingress/Egress locked down to explicitly allowed peer ports and external Postgres (5432) / TLS (443).
5. **No Migration at Startup**: Migrations are strictly separated into one-off Jobs using dedicated migrator roles.
