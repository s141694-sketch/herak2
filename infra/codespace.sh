#!/usr/bin/env bash
# Harak in a GitHub Codespace, for trial sessions with colleagues (the owner's choice of 2026-10-09, D99). The same
# compose stack as a server; GitHub's port forwarding gives it a public https address, and infra/compose.codespaces.yml
# puts a small proxy ("front", port 8000) where Caddy would be. Guide: docs/2026-10-09-harak2-codespaces.md.
#
#   infra/codespace.sh start          builds and starts, makes port 8000 public, prints the address to share
#   infra/codespace.sh demo           an account for each role, with a password made for this Codespace
#   infra/codespace.sh organization   an empty organization and its manager's link (ORG_NAME, ORG_SLUG, ADMIN_EMAIL)
#   infra/codespace.sh link EMAIL [SLUG]   the link of someone invited (no email is sent from a Codespace)
#   infra/codespace.sh emails         the emails Harak would have sent
#   infra/codespace.sh status         the services and their health
#   infra/codespace.sh stop           stops Harak; the data stays for the next start
#
# Runs only inside a Codespace (it reads CODESPACE_NAME and GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN); CI sets
# HARAK_PUBLIC_HOST instead. Emails are not sent, and the AI agents are off, as in the pilot (D94).
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_FILE=backend/.env
OVERLAY=infra/compose.codespaces.yml
PORT=8000
MARK="# Harak in a GitHub Codespace (infra/codespace.sh): fresh secrets, GitHub's https address, nothing is sent."
export HARAK_COMPOSE_EXTRA="$OVERLAY"
compose() { docker compose --env-file "$ENV_FILE" -f infra/docker-compose.yml -f "$OVERLAY" "$@"; }
value() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -1; }

if [ -n "${HARAK_PUBLIC_HOST:-}" ]; then
  HOST="$HARAK_PUBLIC_HOST"
elif [ -n "${CODESPACE_NAME:-}" ] && [ -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]; then
  HOST="$CODESPACE_NAME-$PORT.$GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN"
else
  echo "This runs inside a GitHub Codespace (see docs/2026-10-09-harak2-codespaces.md)." >&2
  exit 1
fi
command -v docker >/dev/null && docker info >/dev/null 2>&1 || {
  echo "Docker is not running in this Codespace yet: wait a minute after it opens, then try again." >&2
  exit 1
}

ours() { [ -f "$ENV_FILE" ] && head -1 "$ENV_FILE" | grep -qF "$MARK"; }

configure() {
  if [ -f "$ENV_FILE" ] && ! ours; then
    echo "$ENV_FILE exists and is not this script's: left as it is." >&2
    exit 1
  fi
  if ours; then
    # Only the address lines follow a changed address; the secrets, and the database password its volume holds, stay.
    if [ "$(value HARAK_DOMAIN)" != "$HOST" ]; then
      sed -i -e "s|^HARAK_DOMAIN=.*|HARAK_DOMAIN=$HOST|" -e "s|^ALLOWED_HOSTS=.*|ALLOWED_HOSTS=$HOST,backend|" \
        -e "s|^CSRF_TRUSTED_ORIGINS=.*|CSRF_TRUSTED_ORIGINS=https://$HOST|" -e "s|^APP_URL=.*|APP_URL=https://$HOST|" \
        "$ENV_FILE"
      echo "the address changed to https://$HOST"
    fi
    return
  fi
  secret() { openssl rand -hex 32; }
  umask 077
  {
    echo "$MARK"
    grep -v -E '^(HARAK_DOMAIN|ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS|APP_URL|SECRET_KEY|COLLAB_TOKEN_SECRET|COLLAB_SERVICE_SECRET|POSTGRES_PASSWORD|FIELD_ENCRYPTION_KEYS|EMAIL_URL|FILES_BACKEND)=' infra/pilot.env.example
    echo "HARAK_DOMAIN=$HOST"
    echo "ALLOWED_HOSTS=$HOST,backend"
    echo "CSRF_TRUSTED_ORIGINS=https://$HOST"
    echo "APP_URL=https://$HOST"
    echo "SECRET_KEY=$(secret)"
    echo "COLLAB_TOKEN_SECRET=$(secret)"
    echo "COLLAB_SERVICE_SECRET=$(secret)"
    echo "POSTGRES_PASSWORD=$(secret)"
    echo "FIELD_ENCRYPTION_KEYS=$(openssl rand 32 | base64 | tr '+/' '-_')"
    echo "EMAIL_URL=consolemail://"
    echo "FILES_BACKEND=local"
  } > "$ENV_FILE"
}

make_public() {
  if command -v gh >/dev/null && [ -n "${CODESPACE_NAME:-}" ] \
    && gh codespace ports visibility "$PORT:public" -c "$CODESPACE_NAME" >/dev/null 2>&1; then
    echo "port $PORT is public: anyone with the address reaches Harak's sign-in page"
  else
    cat <<EOF
Make the address reachable by your colleagues: in the PORTS tab (next to TERMINAL), right-click port $PORT ("Harak"),
then Port Visibility > Public.
EOF
  fi
}

start() {
  configure
  echo "building and starting (the first time takes 10 to 20 minutes)..."
  compose up -d --build
  infra/healthcheck.sh 900
  make_public
  echo
  echo "Harak is at:  https://$HOST"
  echo "Next: infra/codespace.sh demo (ready accounts), or infra/codespace.sh organization (an empty one)."
}

demo() {
  local password
  password="$(value HARAK_DEMO_PASSWORD)"
  if [ -z "$password" ]; then
    password="$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-16)"
    echo "HARAK_DEMO_PASSWORD=$password" >> "$ENV_FILE"
  fi
  compose exec -T -e HARAK_ALLOW_SEED=1 -e E2E_PASSWORD="$password" backend python manage.py seed_e2e
  cat <<EOF

Harak is at https://$HOST
Accounts, all with the password  $password  (made for this Codespace; share it only with your colleagues):
  multi@example.com      training manager of "مركز التدريب المهني"
  author@example.com     author
  reviewer@example.com   reviewer
  approver@example.com   approver
EOF
}

[ -f "$ENV_FILE" ] || [ "${1:-}" = start ] || { echo "start Harak first: infra/codespace.sh start" >&2; exit 1; }
case "${1:-}" in
  start) start ;;
  demo) demo ;;
  organization) infra/deploy.sh organization ;;
  link) shift; infra/deploy.sh link "$@" ;;
  emails) compose logs worker ;;
  status) compose ps ;;
  stop) compose stop ;;
  *) sed -n '2,17p' "$0"; exit 1 ;;
esac
