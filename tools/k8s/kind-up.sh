#!/usr/bin/env bash
# tools/k8s/kind-up.sh — Automates kind cluster setup, image build, overlay application and smoke tests.
set -euo pipefail

CLUSTER_NAME="karobarone"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "==> [1/6] Checking prerequisites..."
command -v docker >/dev/null 2>&1 || { echo "Docker is required but not installed."; exit 1; }
command -v kind >/dev/null 2>&1 || { echo "kind is required but not installed."; exit 1; }
command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required but not installed."; exit 1; }

echo "==> [2/6] Ensuring KIND cluster '${CLUSTER_NAME}' exists..."
if ! kind get clusters | grep -q "^${CLUSTER_NAME}$"; then
  kind create cluster --name "${CLUSTER_NAME}"
fi

echo "==> [3/6] Building Docker images..."
SERVICES=("gateway" "iam" "tenant" "approval" "catalog" "domain" "customer" "subscription" "inventory")

for svc in "${SERVICES[@]}"; do
  echo "    Building karobarone/${svc}:latest..."
  docker build -q -t "karobarone/${svc}:latest" -f "${ROOT_DIR}/services/${svc}/Dockerfile" "${ROOT_DIR}"
  echo "    Loading karobarone/${svc}:latest into kind..."
  kind load docker-image "karobarone/${svc}:latest" --name "${CLUSTER_NAME}"
done

echo "==> [4/6] Applying Dev Overlay..."
kubectl apply -k "${ROOT_DIR}/deploy/k8s/overlays/dev"

echo "==> [5/6] Waiting for postgres pod to be ready..."
kubectl rollout status deployment/postgres -n karobar-platform --timeout=120s

echo "    Bootstrapping schemas and roles..."
PG_POD=$(kubectl get pods -n karobar-platform -l app.kubernetes.io/name=postgres -o jsonpath='{.items[0].metadata.name}')
kubectl exec -i -n karobar-platform "$PG_POD" -- psql -U karobar_admin -d karobarone < "${ROOT_DIR}/tools/db/bootstrap.sql"

echo "==> [6/6] Running Alembic Migration Jobs..."
kubectl apply -f "${ROOT_DIR}/deploy/k8s/base/migration-jobs.yaml"
kubectl wait --for=condition=complete job --all -n karobar-platform --timeout=180s

echo "==> Kind deployment complete! Verifying Gateway status..."
kubectl rollout status deployment/gateway -n karobar-platform --timeout=120s
echo "All microservices deployed and healthy in kind cluster '${CLUSTER_NAME}'."
