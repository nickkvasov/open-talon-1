#!/bin/sh
set -eu

KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak:8080}"
KEYCLOAK_ADMIN_USER="${KEYCLOAK_ADMIN_USER:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"

echo "Waiting for Keycloak at ${KEYCLOAK_URL}..."
until /opt/keycloak/bin/kcadm.sh config credentials \
  --server "${KEYCLOAK_URL}" \
  --realm master \
  --user "${KEYCLOAK_ADMIN_USER}" \
  --password "${KEYCLOAK_ADMIN_PASSWORD}" >/dev/null 2>&1; do
  sleep 2
done

echo "Configuring local dev realms..."
/opt/keycloak/bin/kcadm.sh update realms/master -s sslRequired=NONE >/dev/null
/opt/keycloak/bin/kcadm.sh update realms/open-talon -s sslRequired=NONE >/dev/null

lookup_client_id() {
  client_name="$1"
  /opt/keycloak/bin/kcadm.sh get clients -r open-talon -q clientId="${client_name}" \
    | tr -d '\n' \
    | sed -n 's/.*"id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p'
}

OPEN_TALON_TUI_ID="$(lookup_client_id open-talon-tui)"
if [ -n "${OPEN_TALON_TUI_ID}" ]; then
  /opt/keycloak/bin/kcadm.sh update "clients/${OPEN_TALON_TUI_ID}" -r open-talon \
    -s publicClient=true \
    -s standardFlowEnabled=false \
    -s directAccessGrantsEnabled=false \
    -s serviceAccountsEnabled=false \
    -s 'attributes."oauth2.device.authorization.grant.enabled"=true' \
    -s 'attributes."oauth2.device.polling.interval"=5' >/dev/null
fi

OPEN_TALON_WEB_ID="$(lookup_client_id open-talon-web)"
if [ -n "${OPEN_TALON_WEB_ID}" ]; then
  /opt/keycloak/bin/kcadm.sh update "clients/${OPEN_TALON_WEB_ID}" -r open-talon \
    -s publicClient=true \
    -s standardFlowEnabled=true \
    -s directAccessGrantsEnabled=false \
    -s serviceAccountsEnabled=false \
    -s 'attributes."pkce.code.challenge.method"=S256' >/dev/null
fi

echo "Keycloak local dev realms updated."
