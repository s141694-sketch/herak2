#!/usr/bin/env bash
# Harak in a GitHub Codespace, for trial sessions with colleagues (the owner's choice of 2026-10-09, D99). The same
# compose stack as a server; GitHub's port forwarding gives it a public https address, and infra/compose.codespaces.yml
# puts a small proxy ("front", port 8000) where Caddy would be. Guide: docs/2026-10-09-harak2-codespaces.md.
#
#   infra/codespace.sh start          builds and starts, makes port 8000 public, prints the address to share
#   infra/codespace.sh watch          during a session: one line per visit, which keeps the Codespace from stopping
#   infra/codespace.sh demo           an account for each role, each with its own password (made once)
#   infra/codespace.sh organization   an empty organization and its manager's link (ORG_NAME, ORG_SLUG, ADMIN_EMAIL)
#   infra/codespace.sh link EMAIL [SLUG]   the link of someone invited (no email is sent from a Codespace)
#   infra/codespace.sh emails         the emails Harak would have sent, readable
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
    grep -v -E '^(HARAK_DOMAIN|ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS|APP_URL|SECRET_KEY|COLLAB_TOKEN_SECRET|COLLAB_SERVICE_SECRET|POSTGRES_PASSWORD|FIELD_ENCRYPTION_KEYS|EMAIL_URL|FILES_BACKEND|LOGIN_THROTTLE_RATE)=' infra/pilot.env.example
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
    # Colleagues may share one address as Harak sees it, if GitHub's forwarding does not say who they are; the
    # per-account pause after wrong passwords (D84) still guards each account.
    echo "LOGIN_THROTTLE_RATE=60/minute"
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

watch() {
  cat <<EOF
Leave this running during the session: each visit to Harak prints a line here, and GitHub counts that as activity,
so the Codespace does not stop for lack of it. Ctrl+C ends the watch; Harak keeps running.
EOF
  compose logs -f --tail 0 front
}

demo() {
  # Made once: running it again only prints the accounts, so it never resets what the trial changed.
  if [ -z "$(value HARAK_DEMO_ACCOUNTS)" ]; then
    compose exec -T -e HARAK_ALLOW_SEED=1 -e E2E_PASSWORD="$(openssl rand -hex 24)" backend \
      python manage.py seed_e2e >/dev/null
    local accounts
    accounts="$(compose exec -T backend python manage.py shell -c "
import secrets
from apps.accounts.models import User
listed = ['multi@example.com', 'author@example.com', 'reviewer@example.com', 'approver@example.com']
pairs = []
for user in User.objects.filter(email__endswith='example.com') | User.objects.filter(email__endswith='vtc.test'):
    if user.email in listed:
        password = secrets.token_urlsafe(9)
        user.set_password(password)
        pairs.append(user.email + ':' + password)
    else:
        user.set_unusable_password()  # the browser tests' other accounts cannot be signed in to here
    user.save(update_fields=['password'])
print(','.join(sorted(pairs, key=lambda p: listed.index(p.split(':')[0]))))" | tail -1)"
    echo "HARAK_DEMO_ACCOUNTS=$accounts" >> "$ENV_FILE"
  fi
  echo
  echo "Harak is at https://$HOST"
  echo "Accounts, each with its own password (give each colleague theirs only):"
  local role
  for pair in $(value HARAK_DEMO_ACCOUNTS | tr ',' ' '); do
    case "${pair%%:*}" in
      multi@*) role="training manager of مركز التدريب المهني" ;;
      author@*) role="author" ;;
      reviewer@*) role="reviewer" ;;
      *) role="approver" ;;
    esac
    printf '  %-22s %-14s %s\n' "${pair%%:*}" "${pair#*:}" "$role"
  done
}

emails() {
  compose logs --no-log-prefix worker 2>/dev/null | compose exec -T backend python -c "$(cat infra/print-emails.py)"
}

[ -f "$ENV_FILE" ] || [ "${1:-}" = start ] || { echo "start Harak first: infra/codespace.sh start" >&2; exit 1; }
case "${1:-}" in
  start) start ;;
  demo) demo ;;
  organization) infra/deploy.sh organization ;;
  link) shift; infra/deploy.sh link "$@" ;;
  watch) watch ;;
  emails) emails ;;
  status) compose ps ;;
  stop) compose stop ;;
  *) sed -n '2,18p' "$0"; exit 1 ;;
esac
