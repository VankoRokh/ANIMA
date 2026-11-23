#!/usr/bin/env bash
# Human/operator-only GUI diagnostics for the E1.2 Lifecycle World.
# This does NOT connect Core, Memory, CognitiveCoordinator or FAST.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

GODOT_BIN="${GODOT_BIN:-$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64}"
PORT="${ANIMA_LAB_PORT:-46029}"
SEED="${ANIMA_LAB_SEED:-7}"

if [[ ! -x "$GODOT_BIN" ]]; then
  printf 'Godot binary missing or not executable: %s\n' "$GODOT_BIN" >&2
  printf 'Set GODOT_BIN to your official Godot 4.7.2 executable.\n' >&2
  exit 2
fi
if [[ ! "$PORT" =~ ^[0-9]+$ ]] || (( 10#$PORT < 1024 || 10#$PORT > 65535 )); then
  echo "ANIMA_LAB_PORT must be between 1024 and 65535" >&2
  exit 2
fi
if [[ ! "$SEED" =~ ^[0-9]+$ ]]; then
  echo "ANIMA_LAB_SEED must be an unsigned integer" >&2
  exit 2
fi

echo "ANIMA Visual Diagnostics / Godot only / observe-only"
echo "Operator truth and cyan coverage preview are NOT supplied to ANIMA."
echo "Core/Memory/FAST telemetry: not connected (requires future integration)."
echo "Close other LifecycleWorld instances to avoid port $PORT conflict."
exec "$GODOT_BIN" \
  --path "$ROOT/labs/virtual_anima_lab/godot" \
  res://LifecycleWorld.tscn -- \
  --lifecycle-port "$PORT" \
  --lifecycle-seed "$SEED" \
  --lifecycle-debug-ui
