#!/bin/sh
set -eu

VAULT_ADDR="${VAULT_ADDR:-http://openbao:8200}"
INIT_FILE="/openbao/file/init.json"
LOCAL_ROOT_TOKEN="${BAO_ROOT_TOKEN:-root}"

status_json() {
  VAULT_ADDR="$VAULT_ADDR" bao status -format=json 2>/dev/null || true
}

json_field() {
  field_name="$1"
  tr -d '\n' < "$INIT_FILE" | sed -n "s/.*\"${field_name}\":[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p"
}

json_first_array_item() {
  field_name="$1"
  tr -d '\n' < "$INIT_FILE" | sed -n "s/.*\"${field_name}\":[[:space:]]*\\[[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p"
}

until output="$(status_json)" && [ -n "$output" ]; do
  sleep 1
done

if printf '%s' "$output" | grep -q '"initialized":[[:space:]]*false'; then
  VAULT_ADDR="$VAULT_ADDR" bao operator init -key-shares=1 -key-threshold=1 -format=json > "$INIT_FILE"
fi

UNSEAL_KEY="$(json_first_array_item "unseal_keys_b64")"
INIT_ROOT_TOKEN="$(json_field "root_token")"

if [ -z "$UNSEAL_KEY" ] || [ -z "$INIT_ROOT_TOKEN" ]; then
  echo "Failed to load OpenBao init material from $INIT_FILE" >&2
  exit 1
fi

output="$(status_json)"
if printf '%s' "$output" | grep -q '"sealed":[[:space:]]*true'; then
  VAULT_ADDR="$VAULT_ADDR" bao operator unseal "$UNSEAL_KEY" >/dev/null
fi

if ! VAULT_ADDR="$VAULT_ADDR" VAULT_TOKEN="$INIT_ROOT_TOKEN" bao secrets list -format=json 2>/dev/null | grep -q '"secret/"'; then
  VAULT_ADDR="$VAULT_ADDR" VAULT_TOKEN="$INIT_ROOT_TOKEN" bao secrets enable -path=secret kv-v2 >/dev/null
fi

if [ "$LOCAL_ROOT_TOKEN" != "$INIT_ROOT_TOKEN" ] && ! VAULT_ADDR="$VAULT_ADDR" VAULT_TOKEN="$LOCAL_ROOT_TOKEN" bao token lookup >/dev/null 2>&1; then
  VAULT_ADDR="$VAULT_ADDR" VAULT_TOKEN="$INIT_ROOT_TOKEN" bao token create -id="$LOCAL_ROOT_TOKEN" -policy=root -orphan >/dev/null
fi

echo "OpenBao initialized, unsealed, and ready"
