from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REALM_IMPORT = ROOT / "infrastructure" / "keycloak" / "open-talon-realm.json"
INIT_SCRIPT = ROOT / "infrastructure" / "keycloak" / "init-dev-realms.sh"
COMPOSE_FILE = ROOT / "infrastructure" / "docker-compose.yaml"
LAUNCHER = ROOT / "open-talon"
LEGACY_PARTICIPANT_BACKFILL = (
    ROOT / "db" / "migrations" / "20260412000200_backfill_legacy_user_participants.sql"
)


def test_keycloak_realm_import_has_dev_ssl_and_default_users():
    payload = json.loads(REALM_IMPORT.read_text())

    assert payload["realm"] == "open-talon"
    assert payload["sslRequired"] == "none"
    assert payload["registrationEmailAsUsername"] is False

    users = {user["username"]: user for user in payload["users"]}
    assert set(users) >= {"admin", "supervisor", "user1", "user2"}
    assert users["admin"]["realmRoles"] == ["open-talon-admin"]
    assert users["admin"]["credentials"][0]["value"] == "admin123"
    assert users["supervisor"]["credentials"][0]["value"] == "supervisor123"
    assert users["user1"]["credentials"][0]["value"] == "user12345"
    assert users["user2"]["credentials"][0]["value"] == "user22345"


def test_keycloak_init_script_normalizes_local_dev_realms():
    script = INIT_SCRIPT.read_text()

    assert "update realms/master -s sslRequired=NONE" in script
    assert "update realms/open-talon -s sslRequired=NONE" in script
    assert 'lookup_client_id open-talon-tui' in script
    assert 'attributes."oauth2.device.authorization.grant.enabled"=true' in script
    assert 'lookup_client_id open-talon-web' in script
    assert 'attributes."pkce.code.challenge.method"=S256' in script


def test_local_startup_includes_keycloak_init_helper():
    compose = COMPOSE_FILE.read_text()
    launcher = LAUNCHER.read_text()

    assert "keycloak-init:" in compose
    assert 'entrypoint: ["/bin/sh", "/opt/keycloak/data/import/init-dev-realms.sh"]' in compose
    assert "KC_BOOTSTRAP_ADMIN_USERNAME" in compose
    assert "KC_BOOTSTRAP_ADMIN_PASSWORD" in compose
    assert "local services=(" in launcher
    assert "keycloak" in launcher
    assert "keycloak-init" in launcher
    assert 'AGENT_TASK_PID_FILE="${RUN_DIR}/agent-task-worker.pid"' in launcher
    assert '"agent-task-worker" \\' in launcher
    assert '"agent_runtime.agent_task_worker" \\' in launcher
    assert ': "${AUTH_MODE:=any}"' in launcher
    assert ': "${OIDC_ISSUER_URL:=${OPEN_TALON_OIDC_ISSUER_URL}}"' in launcher
    assert ': "${OIDC_CLIENT_ID_TUI:=${OPEN_TALON_OIDC_CLIENT_ID}}"' in launcher
    assert ': "${OIDC_AUDIENCE:=${OIDC_CLIENT_ID_TUI}}"' in launcher


def test_legacy_user_participant_backfill_migration_exists():
    sql = LEGACY_PARTICIPANT_BACKFILL.read_text()

    assert "UPDATE participants" in sql
    assert "SET user_id = participant_id" in sql
    assert "INSERT INTO users" in sql
    assert "LEFT JOIN users u ON COALESCE(p.user_id, p.participant_id) = u.user_id" in sql
