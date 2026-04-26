#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
INFRA_ENV_FILE="${ROOT_DIR}/infrastructure/.env"

usage() {
  cat <<EOF
Usage:
  ./scripts/system-init.sh [--memgraph] [--wait-seconds seconds]

Initialize the local Open Talon system with the checked-in defaults.

This starts the normal local stack, applies pending migrations through gateway
startup, runs the local Keycloak/OpenBao init helpers, and waits until the
seeded default records and managed operational-agent identities are present.

Options:
  --memgraph              Start the optional Memgraph service through ./open-talon start.
  --wait-seconds seconds  Seconds to wait for seeded defaults after startup.
                          Default: OPEN_TALON_SYSTEM_INIT_WAIT_SECONDS or 120.
  -h, --help              Show this help.
EOF
}

ensure_python() {
  if [[ ! -x "${PYTHON_BIN}" ]]; then
    echo "Missing ${PYTHON_BIN}. Run ./scripts/bootstrap-python.sh first." >&2
    exit 1
  fi
}

load_local_env() {
  if [[ -f "${INFRA_ENV_FILE}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${INFRA_ENV_FILE}"
    set +a
  fi
}

wait_for_default_records() {
  local wait_seconds="$1"
  OPEN_TALON_SYSTEM_INIT_WAIT_SECONDS="${wait_seconds}" "${PYTHON_BIN}" - <<'PY'
import asyncio
import os
import sys
import time

import asyncpg


def _truthy_env(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _postgres_dsn() -> str:
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit
    user = os.getenv("POSTGRES_USER", "admin")
    password = os.getenv("POSTGRES_PASSWORD", "password")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "app_db")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


BASE_CHECKS = [
    (
        "default organization",
        "SELECT EXISTS (SELECT 1 FROM organizations WHERE slug = 'default')",
    ),
    (
        "system base organization",
        "SELECT EXISTS (SELECT 1 FROM organizations WHERE slug = 'system-base')",
    ),
    (
        "default project",
        """
        SELECT EXISTS (
            SELECT 1
            FROM projects AS p
            JOIN organizations AS o ON o.organization_id = p.organization_id
            WHERE o.slug = 'default' AND p.slug = 'default'
        )
        """,
    ),
    (
        "administration project",
        """
        SELECT EXISTS (
            SELECT 1
            FROM projects AS p
            JOIN organizations AS o ON o.organization_id = p.organization_id
            WHERE o.slug = 'default' AND p.slug = 'administration'
        )
        """,
    ),
    (
        "system operations workspace",
        """
        SELECT EXISTS (
            SELECT 1
            FROM workspaces AS w
            JOIN organizations AS o ON o.organization_id = w.organization_id
            WHERE o.slug = 'system-base'
              AND w.metadata @> '{"operations_workspace": true}'::jsonb
        )
        """,
    ),
    (
        "organization operations workspace",
        """
        SELECT EXISTS (
            SELECT 1
            FROM workspaces AS w
            JOIN organizations AS o ON o.organization_id = w.organization_id
            WHERE o.slug = 'default'
              AND w.metadata @> '{"operations_workspace": true}'::jsonb
        )
        """,
    ),
    (
        "local Ollama provider",
        "SELECT EXISTS (SELECT 1 FROM llm_providers WHERE engine_id = 'local-ollama')",
    ),
    (
        "OpenAI Responses provider",
        "SELECT EXISTS (SELECT 1 FROM llm_providers WHERE engine_id = 'openai-responses')",
    ),
    (
        "Postgres memory provider",
        "SELECT EXISTS (SELECT 1 FROM memory_providers WHERE provider_key = 'postgres')",
    ),
    (
        "Reasoning Planner agent",
        "SELECT EXISTS (SELECT 1 FROM system_agents WHERE display_name = 'Reasoning Planner')",
    ),
    (
        "Tinker agent",
        "SELECT EXISTS (SELECT 1 FROM system_agents WHERE agent_key = 'tinker')",
    ),
    (
        "Steward agent",
        "SELECT EXISTS (SELECT 1 FROM system_agents WHERE agent_key = 'steward')",
    ),
    (
        "Curator agent",
        """
        SELECT EXISTS (
            SELECT 1
            FROM system_agents
            WHERE agent_key = 'curator' AND scope = 'organization'
        )
        """,
    ),
    (
        "Anchor agent",
        "SELECT EXISTS (SELECT 1 FROM system_agents WHERE agent_key = 'anchor')",
    ),
    (
        "control-plane MCP server",
        "SELECT EXISTS (SELECT 1 FROM mcp_servers WHERE server_key = 'open_talon_control_plane')",
    ),
]

OPERATIONAL_IDENTITY_CHECKS = [
    (
        "Steward machine identity",
        """
        SELECT EXISTS (
            SELECT 1
            FROM agent_identities AS identity
            JOIN system_agents AS agent ON agent.agent_id = identity.system_agent_id
            WHERE agent.agent_key = 'steward'
              AND identity.status = 'active'
        )
        """,
    ),
    (
        "Curator machine identity",
        """
        SELECT EXISTS (
            SELECT 1
            FROM agent_identities AS identity
            JOIN system_agents AS agent ON agent.agent_id = identity.system_agent_id
            WHERE agent.agent_key = 'curator'
              AND agent.scope = 'organization'
              AND identity.status = 'active'
        )
        """,
    ),
]


async def _missing_defaults(conn: asyncpg.Connection, checks: list[tuple[str, str]]) -> list[str]:
    missing: list[str] = []
    for label, sql in checks:
        if not await conn.fetchval(sql):
            missing.append(label)
    return missing


async def _main() -> None:
    dsn = _postgres_dsn()
    wait_seconds = float(os.getenv("OPEN_TALON_SYSTEM_INIT_WAIT_SECONDS", "120"))
    deadline = time.monotonic() + wait_seconds
    checks = list(BASE_CHECKS)
    if _truthy_env("OPERATIONAL_AGENTS_BOOTSTRAP_ENABLED", True):
        checks.extend(OPERATIONAL_IDENTITY_CHECKS)

    last_error: str | None = None
    while True:
        try:
            conn = await asyncpg.connect(dsn)
            try:
                missing = await _missing_defaults(conn, checks)
            finally:
                await conn.close()
            if not missing:
                print("System defaults are initialized.")
                return
            last_error = "missing: " + ", ".join(missing)
        except Exception as exc:  # noqa: BLE001 - this is a readiness loop.
            last_error = str(exc)

        if time.monotonic() >= deadline:
            print(
                f"Timed out waiting for system defaults after {wait_seconds:.0f}s: {last_error}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        await asyncio.sleep(2)


asyncio.run(_main())
PY
}

enable_memgraph=0
wait_seconds="${OPEN_TALON_SYSTEM_INIT_WAIT_SECONDS:-120}"

while (($# > 0)); do
  case "$1" in
    --memgraph)
      enable_memgraph=1
      ;;
    --wait-seconds)
      if (($# < 2)); then
        echo "--wait-seconds requires a value." >&2
        exit 1
      fi
      wait_seconds="$2"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown system-init option: $1" >&2
      usage
      exit 1
      ;;
  esac
  shift
done

ensure_python
load_local_env

start_args=(start)
if ((enable_memgraph)); then
  start_args+=(--memgraph)
fi

echo "Starting Open Talon local system..."
"${ROOT_DIR}/open-talon" "${start_args[@]}"

echo "Waiting for seeded defaults and managed identities..."
wait_for_default_records "${wait_seconds}"
