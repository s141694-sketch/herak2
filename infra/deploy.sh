#!/usr/bin/env bash
# Harak on a server, step by step (the owner's request of 2026-10-08, D97). It follows the runbook
# (docs/2026-10-06-harak2-runbook.md) and does not replace it: backups off the server, monitoring and the emergency
# account are there. Run from the repository's root, on the server:
#
#   infra/deploy.sh setup                  asks for the address, the file store and the email, writes backend/.env
#                                          with fresh secrets (never over an existing one)
#   infra/deploy.sh start                  builds, starts, waits for every service, runs the smoke check
#   infra/deploy.sh organization           opens an organization and prints its manager's link to choose a password
#                                          (ORG_NAME, ORG_SLUG and ADMIN_EMAIL, or asked)
#   infra/deploy.sh link EMAIL [SLUG]      the link of a person invited without a password, when no email was sent
#   infra/deploy.sh update                 a backup, the branch's latest commits, build, start and checks
#   infra/deploy.sh status                 the services and their health
#
# Each value "setup" asks for may be given in the environment instead (HARAK_DOMAIN, FILES_BUCKET, ...).
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_FILE=backend/.env
# Tests only: an extra compose file (CI adds its in-memory store). Never set it on a server.
EXTRA=()
[ -n "${HARAK_COMPOSE_EXTRA:-}" ] && EXTRA=(-f "$HARAK_COMPOSE_EXTRA")
compose() { docker compose --env-file "$ENV_FILE" -f infra/docker-compose.yml "${EXTRA[@]}" "$@"; }
value() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -1; }
need_env() { [ -f "$ENV_FILE" ] || { echo "no $ENV_FILE yet: run infra/deploy.sh setup first" >&2; exit 1; }; }
ask() {
  # ask VAR "question" [default]: the environment's value, else the answer, else the default.
  local name="$1" question="$2" default="${3:-}" answer
  if [ -n "${!name:-}" ]; then return; fi
  if [ -t 0 ]; then
    read -r -p "$question${default:+ [$default]}: " answer
  else
    answer=""
  fi
  printf -v "$name" '%s' "${answer:-$default}"
}
secret() { openssl rand -hex 32; }

command -v docker >/dev/null || {
  echo "Docker is not installed. On Ubuntu: curl -fsSL https://get.docker.com | sh" >&2
  exit 1
}
docker compose version >/dev/null 2>&1 || { echo "docker compose (v2) is missing" >&2; exit 1; }

setup() {
  if [ -f "$ENV_FILE" ]; then
    echo "$ENV_FILE exists already: left as it is. Edit it by hand, or move it aside to start over." >&2
    exit 1
  fi
  command -v openssl >/dev/null || { echo "openssl is missing" >&2; exit 1; }
  echo "The address people will open, such as harak.example.com. Its DNS record must point at this server."
  ask HARAK_DOMAIN "Domain"
  [ -n "$HARAK_DOMAIN" ] || { echo "a domain is required" >&2; exit 1; }
  echo
  echo "The file store: an S3-compatible bucket at your provider (imports, logos, Word and PDF files)."
  ask FILES_BUCKET "Bucket name"
  ask FILES_ENDPOINT_URL "Endpoint URL (empty for AWS itself)" ""
  ask FILES_REGION "Region" "us-east-1"
  ask FILES_ACCESS_KEY_ID "Access key id"
  ask FILES_SECRET_ACCESS_KEY "Secret access key"
  [ -n "$FILES_BUCKET" ] || { echo "a bucket is required: files are kept there, and backed up from there" >&2; exit 1; }
  echo
  echo "Email for invitations and notifications, as smtp+tls://user:password@host:587 (characters @ : / in the"
  echo "user or password written %40 %3A %2F). Empty: nothing is sent, and you give people their links yourself"
  echo "with: infra/deploy.sh link <email>"
  ask EMAIL_URL "SMTP URL" ""
  ask DEFAULT_FROM_EMAIL "Sender" "Harak <no-reply@$HARAK_DOMAIN>"
  umask 077
  {
    grep -v -E '^(HARAK_DOMAIN|ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS|APP_URL|SECRET_KEY|COLLAB_TOKEN_SECRET|COLLAB_SERVICE_SECRET|POSTGRES_PASSWORD|FIELD_ENCRYPTION_KEYS|EMAIL_URL|DEFAULT_FROM_EMAIL|FILES_BUCKET|FILES_ENDPOINT_URL|FILES_REGION|FILES_ACCESS_KEY_ID|FILES_SECRET_ACCESS_KEY|FILES_CREATE_BUCKET)=' infra/pilot.env.example
    echo
    echo "# --- Written by infra/deploy.sh setup ---"
    echo "HARAK_DOMAIN=$HARAK_DOMAIN"
    echo "ALLOWED_HOSTS=$HARAK_DOMAIN,backend"
    echo "CSRF_TRUSTED_ORIGINS=https://$HARAK_DOMAIN"
    echo "APP_URL=https://$HARAK_DOMAIN"
    echo "SECRET_KEY=$(secret)"
    echo "COLLAB_TOKEN_SECRET=$(secret)"
    echo "COLLAB_SERVICE_SECRET=$(secret)"
    echo "POSTGRES_PASSWORD=$(secret)"
    echo "FIELD_ENCRYPTION_KEYS=$(openssl rand 32 | base64 | tr '+/' '-_')"
    echo "EMAIL_URL=${EMAIL_URL:-consolemail://}"
    echo "DEFAULT_FROM_EMAIL=$DEFAULT_FROM_EMAIL"
    echo "FILES_BUCKET=$FILES_BUCKET"
    echo "FILES_ENDPOINT_URL=$FILES_ENDPOINT_URL"
    echo "FILES_REGION=$FILES_REGION"
    echo "FILES_ACCESS_KEY_ID=$FILES_ACCESS_KEY_ID"
    echo "FILES_SECRET_ACCESS_KEY=$FILES_SECRET_ACCESS_KEY"
    echo "FILES_CREATE_BUCKET=${FILES_CREATE_BUCKET:-False}"
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo
  echo "Wrote $ENV_FILE (readable by you alone). Keep a copy of this line somewhere safe, apart from the backups:"
  echo "  $(grep '^FIELD_ENCRYPTION_KEYS=' "$ENV_FILE")"
  echo "Without it no backup can bring back the two-factor secrets. Next: infra/deploy.sh start"
}

smoke() {
  local domain cacert=""
  domain="$(value HARAK_DOMAIN)"
  if [ "$domain" = "localhost" ]; then  # tests: Caddy's local authority signed the certificate
    for _ in $(seq 1 30); do
      compose cp caddy:/data/caddy/pki/authorities/local/root.crt /tmp/harak-root.crt 2>/dev/null && break
      sleep 2
    done
    cacert=/tmp/harak-root.crt
  fi
  SMOKE_CACERT="$cacert" infra/smoke.sh "https://$domain"
}

start() {
  need_env
  echo "building and starting (the first time takes several minutes)..."
  compose build
  compose up -d
  infra/healthcheck.sh 600
  smoke
  echo
  echo "Harak is up at https://$(value HARAK_DOMAIN). Next, if not done yet: infra/deploy.sh organization"
}

link_for() {
  # link_for EMAIL SLUG: the invitation's password link, made by the code that makes the email's.
  compose exec -T -e LINK_EMAIL="$1" -e LINK_SLUG="$2" backend python manage.py shell -c "
import os
from apps.accounts.members import _link
from apps.accounts.models import Membership, Organization, User
user = User.objects.get(email=os.environ['LINK_EMAIL'].strip().lower())
organization = Organization.objects.get(slug=os.environ['LINK_SLUG'])
invited = Membership.including_invitations.filter(user=user, organization=organization, accepted_at__isnull=True)
if user.has_usable_password() or not invited.exists():
    print('no link: this person has a password, or no invitation of ' + organization.slug + ' waits for them')
else:
    print(_link(user, organization))" | tail -1
}

organization() {
  need_env
  ask ORG_NAME "The organization's name" "مركز التدريب"
  ask ORG_SLUG "A short identifier (letters, digits, -)" "center"
  ask ADMIN_EMAIL "Its training manager's email"
  [ -n "$ADMIN_EMAIL" ] || { echo "the manager's email is required" >&2; exit 1; }
  compose exec -T backend python manage.py create_organization --name "$ORG_NAME" --slug "$ORG_SLUG" \
    --admin-email "$ADMIN_EMAIL"
  echo
  echo "The manager chooses a password from this link, then signs in at https://$(value HARAK_DOMAIN):"
  echo "  $(link_for "$ADMIN_EMAIL" "$ORG_SLUG")"
  echo "They invite colleagues from the Members page. Without email, give each their link:"
  echo "  infra/deploy.sh link <email> $ORG_SLUG"
}

update() {
  need_env
  echo "a backup first (runbook, section 5)..."
  compose exec -T backup python manage.py backup --dest /backups
  git pull --ff-only
  echo "Check the new version's dependencies now if you can (runbook, section 5, step 3)."
  start
}

case "${1:-}" in
  setup) setup ;;
  start) start ;;
  organization) organization ;;
  link)
    need_env
    [ -n "${2:-}" ] || { echo "usage: infra/deploy.sh link EMAIL [SLUG]" >&2; exit 1; }
    link_for "$2" "${3:-${ORG_SLUG:-center}}"
    ;;
  update) update ;;
  status) need_env; compose ps ;;
  *) sed -n '2,17p' "$0"; exit 1 ;;
esac
