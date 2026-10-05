#!/usr/bin/env bash
# Runs Keycloak for the SSO tests without Docker (D62): the Maven Central distribution on Java 21.
# KC_HOME points to an unpacked keycloak-quarkus-dist-26.8.0; it is fetched there when missing.
set -euo pipefail
VERSION=26.8.0
KC_HOME=${KC_HOME:-/var/tmp/keycloak/keycloak-$VERSION}
HERE=$(cd "$(dirname "$0")" && pwd)

if [ ! -x "$KC_HOME/bin/kc.sh" ]; then
  mkdir -p "$(dirname "$KC_HOME")"
  base=https://repo1.maven.org/maven2/org/keycloak/keycloak-quarkus-dist/$VERSION/keycloak-quarkus-dist-$VERSION.tar.gz
  curl -sSfo "$KC_HOME.tar.gz" "$base"
  echo "$(curl -sSf "$base.sha1")  $KC_HOME.tar.gz" | sha1sum -c -
  tar xzf "$KC_HOME.tar.gz" -C "$(dirname "$KC_HOME")"
  rm "$KC_HOME.tar.gz"
fi

mkdir -p "$KC_HOME/data/import"
cp "$HERE"/realms/*.json "$KC_HOME/data/import/"
export KC_BOOTSTRAP_ADMIN_USERNAME=${KC_BOOTSTRAP_ADMIN_USERNAME:-admin}
export KC_BOOTSTRAP_ADMIN_PASSWORD=${KC_BOOTSTRAP_ADMIN_PASSWORD:-harak-sso-test-admin}
exec "$KC_HOME/bin/kc.sh" start-dev --import-realm --http-port 8180 --hostname http://localhost:8180
