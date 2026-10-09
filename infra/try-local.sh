#!/usr/bin/env bash
# Harak on one's own computer, to try it (the owner's request of 2026-10-08, D96): the pilot's compose stack at
# https://localhost, with files kept on this computer (D98) and emails printed in the worker's log instead of sent.
#
#   infra/try-local.sh            start, and open an organization whose manager is ADMIN_EMAIL (default
#                                 manager@example.com): prints the link to choose the manager's password
#   infra/try-local.sh --demo     start, with ready accounts of every role (the browser tests' data)
#   infra/try-local.sh --emails   the emails Harak would have sent (invitations, reminders), from the worker's log
#   infra/try-local.sh --stop     stop; the data stays for the next start
#   infra/try-local.sh --reset    stop and erase everything, the trial's backend/.env included
#
# Needs Docker with compose v2, openssl and bash (on Windows: inside WSL). Ports 80 and 443 must be free.
# Not for a server: infra/deploy.sh and the runbook (docs/2026-10-06-harak2-runbook.md) deploy Harak there.
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_FILE=backend/.env
MARK="# Harak local trial (infra/try-local.sh): fresh secrets, https://localhost, nothing is sent."
compose() { docker compose --env-file "$ENV_FILE" -f infra/docker-compose.yml "$@"; }

command -v docker >/dev/null || { echo "Docker is not installed: https://docs.docker.com/get-docker/" >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "docker compose (v2) is missing" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker is not running: start Docker Desktop (or the docker service)" >&2; exit 1; }

trial_env() { [ -f "$ENV_FILE" ] && head -1 "$ENV_FILE" | grep -qF "$MARK"; }

case "${1:-}" in
  --stop)
    compose down
    exit 0
    ;;
  --emails)
    # Decoded: the console backend writes the Arabic bodies in base64.
    compose logs --no-log-prefix worker 2>/dev/null | compose exec -T backend python -c "$(cat infra/print-emails.py)"
    exit 0
    ;;
  --reset)
    trial_env || { echo "$ENV_FILE is not the trial's: nothing erased" >&2; exit 1; }
    compose down -v
    rm -f "$ENV_FILE"
    echo "erased: the trial's data and $ENV_FILE"
    exit 0
    ;;
  "" | --demo) ;;
  *)
    sed -n '2,14p' "$0"
    exit 1
    ;;
esac

if [ ! -f "$ENV_FILE" ]; then
  command -v openssl >/dev/null || { echo "openssl is missing" >&2; exit 1; }
  secret() { openssl rand -hex 32; }
  {
    echo "$MARK"
    grep -v -E '^(HARAK_DOMAIN|ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS|APP_URL|SECRET_KEY|COLLAB_TOKEN_SECRET|COLLAB_SERVICE_SECRET|POSTGRES_PASSWORD|FIELD_ENCRYPTION_KEYS|EMAIL_URL|FILES_BACKEND)=' infra/pilot.env.example
    echo "HARAK_DOMAIN=localhost"
    echo "ALLOWED_HOSTS=localhost,backend"
    echo "CSRF_TRUSTED_ORIGINS=https://localhost"
    echo "APP_URL=https://localhost"
    echo "SECRET_KEY=$(secret)"
    echo "COLLAB_TOKEN_SECRET=$(secret)"
    echo "COLLAB_SERVICE_SECRET=$(secret)"
    echo "POSTGRES_PASSWORD=$(secret)"
    echo "FIELD_ENCRYPTION_KEYS=$(openssl rand 32 | base64 | tr '+/' '-_')"
    # Emails go to the worker's log; this script reads the invitation's link from there.
    echo "EMAIL_URL=consolemail://"
    # Files in the files-data volume on this computer (D98).
    echo "FILES_BACKEND=local"
  } > "$ENV_FILE"
  echo "made $ENV_FILE for the trial"
elif ! trial_env; then
  echo "$ENV_FILE exists and is not the trial's: left as it is. Move it aside to try Harak here." >&2
  exit 1
fi

echo "building and starting (the first time takes several minutes)..."
compose up -d --build
infra/healthcheck.sh 600

if [ "${1:-}" = "--demo" ]; then
  compose exec -T -e HARAK_ALLOW_SEED=1 -e E2E_PASSWORD=harak-demo-password backend python manage.py seed_e2e
  cat <<'EOF'

Harak is at https://localhost (accept the browser's warning: the certificate is this computer's own).
Accounts, all with the password  harak-demo-password :
  multi@example.com      training manager of "مركز التدريب المهني" (and a reviewer elsewhere)
  author@example.com     author
  reviewer@example.com   reviewer
  approver@example.com   approver
The emails Harak would have sent:  infra/try-local.sh --emails
EOF
  exit 0
fi

name="${ORG_NAME:-مركز التجربة}"
slug="${ORG_SLUG:-trial}"
email="${ADMIN_EMAIL:-manager@example.com}"
if compose exec -T backend python manage.py create_organization --name "$name" --slug "$slug" --admin-email "$email"
then
  # The same link the invitation carries, made here rather than read back from the logged email.
  link="$(compose exec -T -e TRIAL_EMAIL="$email" -e TRIAL_SLUG="$slug" backend python manage.py shell -c "
import os
from apps.accounts.members import _link
from apps.accounts.models import Organization, User
user = User.objects.get(email=os.environ['TRIAL_EMAIL'].strip().lower())
print(_link(user, Organization.objects.get(slug=os.environ['TRIAL_SLUG'])))" | tail -1)"
  echo
  echo "Harak is at https://localhost (accept the browser's warning: the certificate is this computer's own)."
  echo "Open this link to choose the password of $email, then sign in as the manager of $name:"
  echo "  $link"
else
  echo "Harak is at https://localhost. The organization $slug exists already: sign in as its manager."
fi
