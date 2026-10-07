#!/usr/bin/env sh
# After each deployment: checks that Harak answers through its TLS front as a browser would reach it (task 8.6, D88).
# It signs nobody in and changes nothing: the one sign-in it tries is for an address no account can have.
#
#   infra/smoke.sh https://harak.example.com
#   SMOKE_CACERT=root.crt infra/smoke.sh https://localhost    # a certificate from a local authority (tests)
#
# Exits 1 if any check fails, naming each.
set -u
base="${1:?usage: smoke.sh https://<domain>}"
base="${base%/}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
tls=""
[ -n "${SMOKE_CACERT:-}" ] && tls="--cacert $SMOKE_CACERT"
failed=0

ok() { echo "ok    $1"; }
fail() {
  echo "FAIL  $1: $2"
  failed=1
}
# fetch <path> [curl options]: the status in $work/status, headers in $work/headers, body in $work/body.
fetch() {
  path="$1"
  shift
  # shellcheck disable=SC2086 # $tls is empty or two words
  curl -sS -m 20 $tls -o "$work/body" -D "$work/headers" -w '%{http_code}' -c "$work/cookies" -b "$work/cookies" \
    "$@" "$base$path" >"$work/status" 2>"$work/error" || true
  cat "$work/status"
}
header() { tr -d '\r' <"$work/headers" | grep -i "^$1:" | tail -1 | cut -d' ' -f2-; }

# Right after services restart, nginx may take a few seconds to find a recreated one (D88): wait up to 30 s until the
# API and the collaboration service answer, then check everything once.
tries=0
while [ "$tries" -lt 15 ]; do
  [ "$(fetch /api/health/ -m 3)" = 200 ] && [ "$(fetch /collab/health -m 3)" = 200 ] && break
  sleep 2
  tries=$((tries + 1))
done

# 1. The interface and its script.
if [ "$(fetch /)" = 200 ] && grep -q 'id="root"' "$work/body"; then
  ok "the interface loads"
  script="$(grep -o '/assets/[^"]*\.js' "$work/body" | head -1)"
  if [ -n "$script" ] && [ "$(fetch "$script")" = 200 ]; then
    ok "its script loads"
  else
    fail "its script loads" "${script:-no script in the page}"
  fi
else
  fail "the interface loads" "status $(cat "$work/status") $(cat "$work/error")"
fi

# 2. The API, its database and Redis, reached over HTTPS. A redirect here means the front's scheme was lost on the
# way, and every API call would loop.
status="$(fetch /api/health/)"
if [ "$status" = 200 ] && grep -q '"status":"ok"' "$work/body"; then
  ok "the API, its database and Redis"
else
  fail "the API, its database and Redis" "status $status $(head -c 200 "$work/body") $(header location)"
fi
case "$base" in
  https://*)
    if [ -n "$(header strict-transport-security)" ]; then
      ok "HSTS"
    else
      fail "HSTS" "no Strict-Transport-Security header"
    fi
    host="${base#https://}"
    # Caddy answers plain HTTP with a redirect, and needs port 80 for its certificates. An organization's own
    # load balancer may close it instead: then this is a note, not a failure.
    plain="$(curl -sS -m 10 -o /dev/null -w '%{http_code} %{redirect_url}' "http://$host/" 2>/dev/null || true)"
    case "$plain" in
      30[178]\ https://*) ok "plain HTTP is sent to HTTPS" ;;
      000*) echo "note  plain HTTP does not answer on port 80: right behind a load balancer that closes it; with caddy, port 80 must reach this host" ;;
      *) fail "plain HTTP is sent to HTTPS" "$plain" ;;
    esac
    ;;
  *) fail "HTTPS" "the address is not https; production settings require it" ;;
esac

# 3. The collaboration service, and a live connection to it through both proxies.
if [ "$(fetch /collab/health)" = 200 ] && grep -q '"service":"collab"' "$work/body"; then
  ok "the collaboration service"
else
  fail "the collaboration service" "status $(cat "$work/status")"
fi
# The address the editor itself opens, /collab without a slash (frontend/src/live/useLiveDocument.ts): a WebSocket
# handshake does not follow redirects, so anything but 101 here means live editing cannot connect.
# shellcheck disable=SC2086
upgrade="$(curl -sS -m 5 $tls --http1.1 -o /dev/null -w '%{http_code} %{redirect_url}' -H 'Connection: Upgrade' \
  -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: c21va2UtY2hlY2stMDAwMA==' \
  "$base/collab" 2>/dev/null || true)"
case "$upgrade" in
  101*) ok "live editing connects" ;;
  *) fail "live editing connects" "status $upgrade, not 101" ;;
esac

# 4. Signing in: the CSRF cookie, the trusted origin and the session. Refused credentials prove the whole path.
fetch /api/auth/csrf/ >/dev/null
token="$(awk '$6 == "csrftoken" {print $7}' "$work/cookies" | tail -1)"
email="smoke-$(date +%s)@example.invalid"
status="$(fetch /api/auth/login/ -X POST -H 'Content-Type: application/json' -H "X-CSRFToken: $token" \
  -H "Origin: $base" -H "Referer: $base/" --data "{\"email\":\"$email\",\"password\":\"not-a-password\"}")"
if [ "$status" = 400 ] && grep -q invalid_credentials "$work/body"; then
  ok "sign-in answers (CSRF, origin, session)"
else
  fail "sign-in answers (CSRF, origin, session)" "status $status $(head -c 200 "$work/body")"
fi

# 5. What only the services call each other on stays closed from outside.
# Open, each would answer 403 without the services' secret; closed at nginx, 404.
for call in "GET /api/internal/collab/documents/1/" "POST /collab/internal/documents/x/freeze"; do
  path="${call#* }"
  status="$(fetch "$path" -X "${call%% *}")"
  if [ "$status" = 404 ]; then
    ok "closed from outside: $path"
  else
    fail "closed from outside: $path" "status $status"
  fi
done

[ "$failed" = 0 ] && echo "smoke check passed" || echo "smoke check FAILED" >&2
exit "$failed"
