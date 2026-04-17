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

lookup_user_id() {
  username="$1"
  /opt/keycloak/bin/kcadm.sh get users -r open-talon -q username="${username}" -q exact=true \
    | tr -d '\n' \
    | sed -n 's/.*"id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p'
}

ensure_realm_role() {
  role_name="$1"
  if ! /opt/keycloak/bin/kcadm.sh get "roles/${role_name}" -r open-talon >/dev/null 2>&1; then
    /opt/keycloak/bin/kcadm.sh create roles -r open-talon -s "name=${role_name}" >/dev/null
  fi
}

ensure_user() {
  username="$1"
  password="$2"
  email="$3"
  first_name="$4"
  last_name="$5"
  realm_role="$6"

  user_id="$(lookup_user_id "${username}")"
  if [ -z "${user_id}" ]; then
    /opt/keycloak/bin/kcadm.sh create users -r open-talon \
      -s "username=${username}" \
      -s "enabled=true" \
      -s "email=${email}" \
      -s "emailVerified=true" \
      -s "firstName=${first_name}" \
      -s "lastName=${last_name}" >/dev/null
    user_id="$(lookup_user_id "${username}")"
  else
    /opt/keycloak/bin/kcadm.sh update "users/${user_id}" -r open-talon \
      -s "email=${email}" \
      -s "emailVerified=true" \
      -s "firstName=${first_name}" \
      -s "lastName=${last_name}" \
      -s "enabled=true" >/dev/null
  fi

  /opt/keycloak/bin/kcadm.sh set-password -r open-talon \
    --username "${username}" \
    --new-password "${password}" >/dev/null
  /opt/keycloak/bin/kcadm.sh add-roles -r open-talon \
    --uusername "${username}" \
    --rolename "${realm_role}" >/dev/null 2>&1 || true
}

ensure_realm_role admin
ensure_realm_role supervisor
ensure_realm_role user

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
    -s 'redirectUris=["http://127.0.0.1:5173","http://127.0.0.1:*","http://127.0.0.1:*/*","http://localhost:5173","http://localhost:*","http://localhost:*/*"]' \
    -s 'webOrigins=["http://127.0.0.1:5173","http://127.0.0.1:*","http://localhost:5173","http://localhost:*"]' \
    -s 'attributes."pkce.code.challenge.method"=S256' >/dev/null
fi

ensure_user admin admin123 admin@local.dev OpenTalon Admin admin
ensure_user admin2 admin223 admin2@local.dev OpenTalon Admin2 admin
ensure_user supervisor supervisor123 supervisor@local.dev OpenTalon Supervisor supervisor
ensure_user supervisor2 supervisor223 supervisor2@local.dev OpenTalon Supervisor2 supervisor
ensure_user user1 user12345 user1@local.dev OpenTalon User1 user
ensure_user user2 user22345 user2@local.dev OpenTalon User2 user

echo "Keycloak local dev realms updated."
