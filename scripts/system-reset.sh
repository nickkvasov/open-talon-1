#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${ROOT_DIR}/infrastructure/data"
RUN_DIR="${ROOT_DIR}/.run"

usage() {
  cat <<EOF
Usage:
  ./scripts/system-reset.sh --yes [--init] [--memgraph] [--include-models]

Stop the local Open Talon stack and remove persisted local runtime state.

By default this wipes bind-mounted service data under infrastructure/data while
preserving infrastructure/data/ollama so local model downloads are not discarded.
Use --include-models to wipe the Ollama model cache too.

Options:
  --yes, -y        Skip the interactive confirmation prompt.
  --init           Run ./scripts/system-init.sh after the reset finishes.
  --memgraph       Pass --memgraph to system-init. Requires --init.
  --include-models Also remove infrastructure/data/ollama.
  -h, --help       Show this help.
EOF
}

confirm_reset() {
  local target_description="$1"

  cat <<EOF
This will stop the local Open Talon stack and delete ${target_description}.

It removes local Postgres, Keycloak container state, OpenBao secrets, Kafka,
Valkey, ClickHouse, MinIO, Forgejo, pgAdmin, communication logs, and managed
worktrees from this repository's local infrastructure/data directory.

Type "reset local open talon" to continue:
EOF

  local answer
  read -r answer
  if [[ "${answer}" != "reset local open talon" ]]; then
    echo "Reset cancelled."
    exit 1
  fi
}

wipe_data_dir() {
  mkdir -p "${DATA_DIR}"
  if ((include_models)); then
    echo "Removing all local runtime data under ${DATA_DIR}..."
    rm -rf "${DATA_DIR}"
    mkdir -p "${DATA_DIR}"
    return
  fi

  echo "Removing local runtime data under ${DATA_DIR}, preserving Ollama models..."
  find "${DATA_DIR}" -mindepth 1 -maxdepth 1 ! -name ollama -exec rm -rf {} +
}

clean_run_dir() {
  if [[ ! -d "${RUN_DIR}" ]]; then
    return
  fi
  find "${RUN_DIR}" -maxdepth 1 \( -name '*.pid' -o -name '*.log' \) -exec rm -f {} +
}

assume_yes=0
run_init=0
include_models=0
enable_memgraph=0

while (($# > 0)); do
  case "$1" in
    --yes|-y)
      assume_yes=1
      ;;
    --init)
      run_init=1
      ;;
    --include-models)
      include_models=1
      ;;
    --memgraph)
      enable_memgraph=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown system-reset option: $1" >&2
      usage
      exit 1
      ;;
  esac
  shift
done

if ((enable_memgraph)) && ! ((run_init)); then
  echo "--memgraph only has an effect with --init." >&2
  exit 1
fi

if ! ((assume_yes)); then
  if ((include_models)); then
    confirm_reset "all contents of ${DATA_DIR}, including the Ollama model cache"
  else
    confirm_reset "all contents of ${DATA_DIR} except infrastructure/data/ollama"
  fi
fi

echo "Stopping Open Talon local system..."
"${ROOT_DIR}/open-talon" stop

wipe_data_dir
clean_run_dir

echo "Local Open Talon runtime state has been reset."

if ((run_init)); then
  init_args=()
  if ((enable_memgraph)); then
    init_args+=(--memgraph)
  fi
  exec "${ROOT_DIR}/scripts/system-init.sh" "${init_args[@]}"
fi
