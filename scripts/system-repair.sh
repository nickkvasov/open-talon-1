#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
INFRA_ENV_FILE="${ROOT_DIR}/infrastructure/.env"

usage() {
  cat <<EOF
Usage:
  ./scripts/system-repair.sh [--no-start] [--memgraph] [--skip-identities]

Repair missing managed defaults in an existing local Open Talon system.

By default this starts the normal local stack first, then repairs migration-seeded
defaults through the managed defaults repairer and repairs managed
operational-agent machine identities through the gateway bootstrap service.

Options:
  --no-start        Do not call ./open-talon start before repairing.
  --memgraph        Start optional Memgraph through ./open-talon start.
  --skip-identities Skip Keycloak/OpenBao-backed machine identity repair.
  -h, --help        Show this help.
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

repo_pythonpath() {
  local entries=(
    "${ROOT_DIR}/packages/contracts"
    "${ROOT_DIR}/services/core-collab"
    "${ROOT_DIR}/services/gateway-edge"
    "${ROOT_DIR}/services/agent-runtime"
    "${ROOT_DIR}/services/generated-tools-builder"
    "${ROOT_DIR}/services/workspace-memory"
    "${ROOT_DIR}/apps/tui"
  )
  local joined
  joined="$(IFS=:; echo "${entries[*]}")"
  if [[ -n "${PYTHONPATH:-}" ]]; then
    printf '%s:%s\n' "${joined}" "${PYTHONPATH}"
  else
    printf '%s\n' "${joined}"
  fi
}

start_stack=1
enable_memgraph=0
repair_args=()

while (($# > 0)); do
  case "$1" in
    --no-start)
      start_stack=0
      ;;
    --memgraph)
      enable_memgraph=1
      ;;
    --skip-identities)
      repair_args+=(--skip-identities)
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown system-repair option: $1" >&2
      usage
      exit 1
      ;;
  esac
  shift
done

if ((enable_memgraph)) && ! ((start_stack)); then
  echo "--memgraph only has an effect when the script starts the stack." >&2
  exit 1
fi

ensure_python
load_local_env

if ((start_stack)); then
  start_args=(start)
  if ((enable_memgraph)); then
    start_args+=(--memgraph)
  fi
  echo "Starting Open Talon local system before repair..."
  "${ROOT_DIR}/open-talon" "${start_args[@]}"
fi

echo "Repairing Open Talon managed defaults..."
PYTHONPATH="$(repo_pythonpath)" "${PYTHON_BIN}" "${ROOT_DIR}/scripts/system_repair.py" "${repair_args[@]}"
