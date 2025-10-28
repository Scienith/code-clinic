#!/usr/bin/env bash
set -euo pipefail

# CodeClinic installer (project-root edition)
# - Creates/uses a project-local Python 3.11 virtualenv at <DEST>/.venv
# - Installs CodeClinic from GitHub main branch into that venv
# - Creates <DEST>/codeclinic/ with:
#     - codeclinic.sh (wrapper to run QA with local venv/config)
#     - codeclinic.yaml (strict template, patched to output under codeclinic/results)
# - Ensures QA outputs are written under <DEST>/codeclinic/results/

DEST="$(pwd)"
PY_BIN="python3.11"

usage() {
  cat <<EOF
Install CodeClinic into a target project directory.

Options:
  --dest <path>   Target project root (default: current directory)
  --python <bin>  Python interpreter to use (default: python3.11)
  -h, --help      Show this help

Examples:
  bash install.sh
  bash install.sh --dest /path/to/project
  bash install.sh --python python3
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest) DEST="$2"; shift 2;;
    --python) PY_BIN="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown option: $1" >&2; usage; exit 1;;
  esac
done

echo "[INFO] Installing CodeClinic to: $DEST"
mkdir -p "$DEST"

# 1) Ensure requested Python is available
if ! command -v "$PY_BIN" >/dev/null 2>&1; then
  echo "[ERROR] $PY_BIN not found on PATH. Please install it or pass --python <bin>." >&2
  exit 1
fi

# 2) Create venv if missing
if [[ ! -d "$DEST/.venv" ]]; then
  echo "[INFO] Creating virtualenv at $DEST/.venv (using $PY_BIN)"
  (cd "$DEST" && "$PY_BIN" -m venv .venv)
else
  echo "[INFO] Reusing existing virtualenv at $DEST/.venv"
fi

# shellcheck disable=SC1090
source "$DEST/.venv/bin/activate"
python -V || true

# 3) Always install CodeClinic (GitHub main) and required tools into this venv
echo "[INFO] Installing CodeClinic (main) and quality tools into .venv"
pip install -q --upgrade pip
pip install -q "git+https://github.com/Scienith/code-clinic@main" \
  black ruff mypy pytest coverage radon pyyaml

# 4) Create codeclinic/ directory and wrapper
CC_DIR="$DEST/codeclinic"
mkdir -p "$CC_DIR"

WRAP="$CC_DIR/codeclinic.sh"
cat > "$WRAP" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_ACTIVATE="$PROJECT_ROOT/.venv/bin/activate"

if [[ -f "$VENV_ACTIVATE" ]]; then
  # shellcheck disable=SC1090
  source "$VENV_ACTIVATE"
else
  echo "[ERROR] Virtualenv not found at $VENV_ACTIVATE" >&2
  exit 1
fi

# Run from project root so that tool.paths resolves consistently
cd "$PROJECT_ROOT"

CMD="${1:-qa}"; shift || true
case "$CMD" in
  qa)
    ACTION="${1:-run}"; shift || true
    if [[ "$ACTION" == "run" ]]; then
      exec codeclinic qa run --config "$SCRIPT_DIR/codeclinic.yaml" --output "$SCRIPT_DIR/results" "$@"
    elif [[ "$ACTION" == "fix" ]]; then
      exec codeclinic qa fix --config "$SCRIPT_DIR/codeclinic.yaml" "$@"
    else
      echo "Usage: codeclinic.sh qa [run|fix] [extra-args...]" >&2
      exit 2
    fi
    ;;
  *)
    # Pass-through to CodeClinic CLI
    exec codeclinic "$CMD" "$@"
    ;;
esac
SH
chmod +x "$WRAP"

timestamp() { date +%Y%m%d-%H%M%S; }

# 5) Generate codeclinic.yaml from packaged strict template (backup existing)
CFG_ROOT="$DEST/codeclinic.yaml"
CFG_CC="$CC_DIR/codeclinic.yaml"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$SCRIPT_DIR/src/codeclinic/templates/codeclinic.yaml"

if [[ -f "$CFG_CC" ]]; then
  bak="$CFG_CC.bak.$(timestamp)"; mv "$CFG_CC" "$bak" && echo "[BACKUP] $CFG_CC -> $bak"
fi
if [[ -f "$CFG_ROOT" ]]; then
  bak="$CFG_ROOT.bak.$(timestamp)"; mv "$CFG_ROOT" "$bak" && echo "[BACKUP] $CFG_ROOT -> $bak"
fi

if [[ -f "$TEMPLATE" ]]; then
  cp "$TEMPLATE" "$CFG_CC"
  echo "[INFO] Wrote template config: $CFG_CC"
else
  echo "[WARN] Template not found at $TEMPLATE; falling back to 'codeclinic qa init'"
  (cd "$DEST" && codeclinic qa init)
  mv "$CFG_ROOT" "$CFG_CC"
fi

# 6) Rewrite codeclinic.yaml to place outputs under codeclinic/results/
python3 - <<PY || true
import sys, yaml, pathlib
p = pathlib.Path(r"$CFG_CC")
data = yaml.safe_load(p.read_text(encoding='utf-8')) or {}
tool = data.setdefault('tool', {})
tool['output'] = 'codeclinic/results'
# Make paths relative to project root (wrapper runs from project root)
from pathlib import Path as _P
root = _P(r"$DEST")
src = root / 'src'
tool['paths'] = ['src'] if src.exists() else ['.']
# Ensure default excludes are present (avoid scanning tests/.venv/migrations)
ex = tool.get('exclude')
defaults = ["**/.venv/**", "**/migrations/**", "**/tests/**"]
if not isinstance(ex, list):
    tool['exclude'] = defaults
else:
    for pat in defaults:
        if pat not in ex:
            ex.append(pat)
# Force JUnit under codeclinic/results/artifacts
tools = data.setdefault('tools', {})
tests = tools.setdefault('tests', {})
junit = tests.setdefault('junit', {})
junit['enabled'] = True
junit['output'] = 'codeclinic/results/artifacts/junit.xml'
p.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding='utf-8')
print('[INFO] Updated codeclinic.yaml: tool.output=results, tool.paths=%s' % tool['paths'])
PY

echo "[DONE] CodeClinic installed. Next steps:"
cat <<EOF
  1) Run checks:  $CC_DIR/codeclinic.sh qa run
  2) Fix issues:  $CC_DIR/codeclinic.sh qa fix
  3) Outputs under: $CC_DIR/results/
     - $CC_DIR/results/summary.json
     - $CC_DIR/results/artifacts/
     - $CC_DIR/results/logs/
EOF
