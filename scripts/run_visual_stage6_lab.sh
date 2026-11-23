#!/usr/bin/env bash
# E2.5c native Stage2 Goal/Task + Stage6 SandboxExecutor visual experiment.
# Existing E2.5b LAB_ADMISSION remains available as a comparison.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export PYTHONNOUSERSITE=1
PYTHON_BIN="${PYTHON_BIN:-python3}"
GODOT_BIN="${GODOT_BIN:-$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64}"
if [[ ! -x "$GODOT_BIN" ]]; then
  echo "Godot 4.7.2 not found: $GODOT_BIN" >&2
  exit 2
fi
echo "ANIMA E2.5c: Core Goal/Task + Stage6 World Effect, visual UI"
echo "FAST/DEEP not connected. This is an experimental bounded capability."
echo "Close previous Godot LifecycleWorld before starting."
exec "$PYTHON_BIN" -m labs.virtual_anima_lab.python.lifecycle.visual_runner \
  --godot "$GODOT_BIN" --core-stage6 "$@"
