#!/usr/bin/env bash
set -euo pipefail

# CodeClinic QA wrapper (project-local)
# - Activates .venv under project root
# - Runs QA via 'codeclinic qa ...' with config/output under codeclinic/

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_ACTIVATE="$PROJECT_ROOT/.venv/bin/activate"

if [[ -f "$VENV_ACTIVATE" ]]; then
  # shellcheck disable=SC1090
  source "$VENV_ACTIVATE"
else
  echo "[ERROR] Virtualenv not found at $VENV_ACTIVATE" >&2
  exit 1
fi

cd "$PROJECT_ROOT"

CMD="${1:-qa}"; shift || true
case "$CMD" in
  qa)
    ACTION="${1:-run}"; shift || true
    if [[ "$ACTION" == "run" ]]; then
      exec codeclinic qa run --config "$PROJECT_ROOT/codeclinic/codeclinic.yaml" --output "$PROJECT_ROOT/codeclinic/results" "$@"
    elif [[ "$ACTION" == "fix" ]]; then
      exec codeclinic qa fix --config "$PROJECT_ROOT/codeclinic/codeclinic.yaml" --output "$PROJECT_ROOT/codeclinic/results" "$@"
    else
      echo "Usage: codeclinic.sh qa [run|fix] [extra-args...]" >&2
      exit 2
    fi
    ;;
  *)
    exec codeclinic "$CMD" "$@"
    ;;
esac
