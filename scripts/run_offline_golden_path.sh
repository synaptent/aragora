#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Resolve a working Python 3 interpreter.
# Prefer the project virtualenv, then fall back to system python3.
if [ -x "$ROOT_DIR/.venv/bin/python3" ]; then
  PYTHON="$ROOT_DIR/.venv/bin/python3"
elif command -v python3 &>/dev/null; then
  PYTHON="python3"
else
  echo "[offline-golden-path] ERROR: No python3 found" >&2
  exit 1
fi

echo "[offline-golden-path] Using Python: $PYTHON"

# Fail fast on leaked transports/file handles in offline smoke flows.
if [[ -n "${PYTHONWARNINGS:-}" ]]; then
  export PYTHONWARNINGS="error::ResourceWarning,${PYTHONWARNINGS}"
else
  export PYTHONWARNINGS="error::ResourceWarning"
fi
echo "[offline-golden-path] Enforcing PYTHONWARNINGS=${PYTHONWARNINGS}"

echo "[offline-golden-path] Installing dev/test dependencies"
"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -e ".[dev,test]"

echo "[offline-golden-path] Running offline behavior tests"
"$PYTHON" -m pytest tests/cli/test_offline_golden_path.py -v --timeout=120 --tb=short \
  -W error::ResourceWarning \
  -W error::pytest.PytestUnraisableExceptionWarning

echo "[offline-golden-path] Running offline demo CLI smoke"
ARAGORA_OFFLINE=1 "$PYTHON" -m aragora ask "Offline mode smoke" --demo --rounds 1

echo "[offline-golden-path] PASS"
