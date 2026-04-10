#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v dbmate >/dev/null 2>&1; then
  echo "dbmate is not installed. Install it first: https://github.com/amacneil/dbmate" >&2
  exit 1
fi

export DATABASE_URL="${DATABASE_URL:-postgresql://admin:password@localhost:5432/app_db?sslmode=disable}"
export DBMATE_MIGRATIONS_DIR="${ROOT_DIR}/db/migrations"

exec dbmate "$@"
