#!/usr/bin/env sh
# Waits until every service the compose file defines is running and, where it has a health check, healthy; exits 0,
# or 1 after the timeout (seconds, default 180). The services come from the compose file itself, so one removed from
# it (caddy behind an organization's own load balancer, postgres or redis for managed ones) is not waited for.
# Usage, from anywhere: infra/healthcheck.sh [timeout]. The environment file is backend/.env, or HARAK_ENV_FILE.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
env_file="${HARAK_ENV_FILE:-$here/../backend/.env}"
compose() { docker compose --env-file "$env_file" -f "$here/docker-compose.yml" "$@"; }
timeout="${1:-180}"
services="$(compose config --services)"
elapsed=0
while [ "$elapsed" -lt "$timeout" ]; do
  unready=""
  states="$(compose ps --format '{{.Service}} {{.State}} {{.Health}}')"
  for s in $services; do
    line="$(echo "$states" | awk -v s="$s" '$1==s')"
    state="$(echo "$line" | awk '{print $2}')"
    health="$(echo "$line" | awk '{print $3}')"
    if [ "$state" != "running" ] || { [ -n "$health" ] && [ "$health" != "healthy" ]; }; then
      unready="$unready $s(${health:-${state:-missing}})"
    fi
  done
  if [ -z "$unready" ]; then
    echo "all services running and healthy"
    exit 0
  fi
  echo "waiting:$unready"
  sleep 5
  elapsed=$((elapsed + 5))
done
echo "timeout: services not ready:$unready" >&2
exit 1
