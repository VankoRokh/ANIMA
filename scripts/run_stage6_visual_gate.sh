#!/usr/bin/env bash
# E2.5c real Godot + Stage2/Stage6 Core action boundary, followed by old gates.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
GODOT_BIN="${GODOT_BIN:-${1:-}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -z "$GODOT_BIN" || ! -x "$GODOT_BIN" ]]; then
  echo "E2_5C_NOT_TESTED: provide Godot 4.7.2 binary" >&2
  exit 2
fi
OUT="${STAGE6_REPORT_DIR:-$(mktemp -d -t anima-stage6-evidence-XXXXXX)}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
export PYTHONPATH="$ROOT"
export PYTHONNOUSERSITE=1
export VISUAL_REPORT_DIR="$OUT/visual-prior-gates"
{
  printf 'sha=%s\n' "$(git rev-parse HEAD)"
  "$PYTHON_BIN" --version
  "$GODOT_BIN" --headless --version
} > "$OUT/environment.txt"
"$PYTHON_BIN" -m pytest -q -p no:cacheprovider tests/test_core_spatial_action_gate.py \
  2>&1 | tee "$OUT/spatial-core-unit.log"
"$PYTHON_BIN" -m labs.virtual_anima_lab.python.lifecycle.stage6_visual_live_gate \
  --godot "$GODOT_BIN" --evidence-dir "$OUT/spatial-live" \
  2>&1 | tee "$OUT/spatial-live.log"
grep -q '"status": "E2_5C_CORE_STAGE6_VISUAL_PASS"' "$OUT/spatial-live.log"

bash scripts/run_visual_decision_gate.sh "$GODOT_BIN" \
  2>&1 | tee "$OUT/visual-regression.log"
grep -q '^E2_5B_VISUAL_DECISION_GATE_PASS' "$OUT/visual-regression.log"
printf 'E2_5C_CORE_STAGE6_VISUAL_PASS\n' | tee "$OUT/status.txt"
