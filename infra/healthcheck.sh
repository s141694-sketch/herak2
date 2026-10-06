#!/usr/bin/env sh
# Waits until every compose service reports healthy, then exits 0; exits 1 after the timeout (seconds, default 180).
# Usage, from anywhere: infra/healthcheck.sh [timeout]. The environment file is backend/.env, or HARAK_ENV_FILE.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
env_file="${HARAK_ENV_FILE:-$here/../backend/.env}"
timeout="${1:-180}"
elapsed=0
services="postgres redis backend worker beat collab frontend caddy"
while [ "$elapsed" -lt "$timeout" ]; do
  unhealthy=""
  states="$(docker compose --env-file "$env_file" -f "$here/docker-compose.yml" ps --format '{{.Service}} {{.Health}}')"
  for s in $services; do
    status="$(echo "$states" | awk -v s="$s" '$1==s {print $2}')"
    [ "$status" = "healthy" ] || unhealthy="$unhealthy $s(${status:-missing})"
  done
  if [ -z "$unhealthy" ]; then
    echo "all services healthy"
    exit 0
  fi
  echo "waiting:$unhealthy"
  sleep 5
  elapsed=$((elapsed + 5))
done
echo "timeout: services not healthy:$unhealthy" >&2
exit 1
