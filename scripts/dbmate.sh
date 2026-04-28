#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

usage() {
  cat <<EOF
Usage:
  ./scripts/dbmate.sh new <migration_name>
  ./scripts/dbmate.sh up
  ./scripts/dbmate.sh status

Open Talon keeps the historic dbmate.sh entrypoint for developer muscle memory,
but applies migrations through the same Python runner used by app startup and tests.
EOF
}

repo_pythonpath() {
  local entries=(
    "${ROOT_DIR}/packages/contracts"
    "${ROOT_DIR}/services/core-collab"
  )
  local joined
  joined="$(IFS=:; echo "${entries[*]}")"
  if [[ -n "${PYTHONPATH:-}" ]]; then
    printf '%s:%s\n' "${joined}" "${PYTHONPATH}"
  else
    printf '%s\n' "${joined}"
  fi
}

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Missing ${PYTHON_BIN}. Run ./scripts/bootstrap-python.sh first." >&2
  exit 1
fi

case "${1:-}" in
  new|up|status)
    exec env \
      PYTHONPATH="$(repo_pythonpath)" \
      "${PYTHON_BIN}" \
      "${ROOT_DIR}/scripts/migrations.py" \
      "$@"
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    echo "Unsupported migration command: $1" >&2
    usage >&2
    exit 1
    ;;
esac
