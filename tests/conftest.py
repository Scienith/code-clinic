import sys
from pathlib import Path

# Ensure repo_root/src is available on sys.path before any tests import project modules
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

