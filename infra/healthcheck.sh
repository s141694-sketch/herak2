#!/usr/bin/env sh
# Waits until every compose service reports healthy, then exits 0; exits 1 after the timeout.
# Usage: cd infra && docker compose up -d --build && ./healthcheck.sh
set -eu
timeout="${1:-180}"
elapsed=0
services="postgres redis backend worker beat collab frontend"
while [ "$elapsed" -lt "$timeout" ]; do
  unhealthy=""
  for s in $services; do
    status="$(docker compose ps --format '{{.Service}} {{.Health}}' 2>/dev/null | awk -v s="$s" '$1==s {print $2}')"
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
