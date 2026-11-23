#!/usr/bin/env bash
# Local E2.5b visual experiment. Starts Core-backed Python runner + real GUI Godot.
# All memory stored in a new disposable temp directory unless --report-dir set.
# Only LAB action admission is implemented; Stage6/FAST are not connected.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export PYTHONNOUSERSITE=1
PYTHON_BIN="${PYTHON_BIN:-python3}"
GODOT_BIN="${GODOT_BIN:-$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64}"
if [[ ! -x "$GODOT_BIN" ]]; then
  echo "Godot 4.7.2 binary not found or not executable: $GODOT_BIN" >&2
  exit 2
fi
echo "ANIMA Visual Decision Lab / real Godot + Core-backed Raw / deterministic"
echo "Authority: LAB_ADMISSION, not native Stage6. FAST is NOT connected."
echo "Close other Godot Lifecycle Lab instances before launching."
exec "$PYTHON_BIN" -m labs.virtual_anima_lab.python.lifecycle.visual_runner \
  --godot "$GODOT_BIN" "$@"
