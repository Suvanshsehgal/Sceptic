#!/usr/bin/env bash
# Builds and starts Sceptic on the VM, then creates the database tables. Safe to run again for every update.
#   bash deploy/azure/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/../.."

# The compose file lives in deploy/azure but builds from the repository root. Newer Docker versions refuse that
# with their default "bake" builder, so use the classic builder.
export COMPOSE_BAKE=false
export BUILDX_BAKE_ENTITLEMENTS_FS=0

ENV_FILE=deploy/azure/.env
COMPOSE=(docker compose --env-file "$ENV_FILE" -f deploy/azure/docker-compose.azure.yml)

[ -f "$ENV_FILE" ] || { echo "Create $ENV_FILE first (copy deploy/azure/.env.azure.example and fill every value)."; exit 1; }
if grep -qE '=(change-me|)$' <(grep -E '^(POSTGRES_PASSWORD|JWT_SECRET_KEY|GITHUB_WEBHOOK_SECRET|GRAFANA_ADMIN_PASSWORD|SCEPTIC_DOMAIN)=' "$ENV_FILE"); then
  echo "$ENV_FILE still has a placeholder or empty required value. Fill POSTGRES_PASSWORD, JWT_SECRET_KEY, GITHUB_WEBHOOK_SECRET, GRAFANA_ADMIN_PASSWORD and SCEPTIC_DOMAIN."
  exit 1
fi

echo "== Building the Blind-Tester sandbox image"
docker build -t sceptic-sandbox:latest -f worker/sandbox/Dockerfile worker

echo "== Building and starting the stack"
"${COMPOSE[@]}" up -d --build

echo "== Waiting for the backend"
for i in $(seq 1 40); do
  if "${COMPOSE[@]}" exec -T backend curl -fs http://localhost:8000/health >/dev/null 2>&1; then break; fi
  sleep 5
done

echo "== Creating or updating the database tables"
"${COMPOSE[@]}" exec -T backend alembic upgrade head

echo
"${COMPOSE[@]}" ps
echo
echo "Done. Open: https://$(grep -E '^SCEPTIC_DOMAIN=' "$ENV_FILE" | cut -d= -f2)"
