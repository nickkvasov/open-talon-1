#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
VENV_DIR="${ROOT_DIR}/.venv"

"${PYTHON_BIN}" -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/python" -m pip install -r "${ROOT_DIR}/requirements-dev.txt"

cat <<EOF
Python environment is ready at ${VENV_DIR}

Next steps:
  source .venv/bin/activate
  pytest tests/gateway-edge -q
  pytest test/infrastructure/test_infrastructure.py -q
EOF
