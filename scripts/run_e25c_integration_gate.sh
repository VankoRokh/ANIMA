#!/usr/bin/env bash
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
GODOT_BIN="${GODOT_BIN:-${1:-}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
[[ -n "$GODOT_BIN" && -x "$GODOT_BIN" ]] || { echo "Godot 4.7.2 required" >&2; exit 2; }
OUT="${E25CI_REPORT_DIR:-$(mktemp -d -t anima-e25ci-evidence-XXXXXX)}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
export PYTHONPATH="$ROOT" PYTHONNOUSERSITE=1 PYTHON_BIN GODOT_BIN
export STAGE6_REPORT_DIR="$OUT/stage6-regression"
echo "Evidence directory: $OUT"
git rev-parse HEAD | tee "$OUT/snapshot.txt"
"$PYTHON_BIN" -m pytest -q -p no:cacheprovider tests/test_visual_decision_policy.py tests/test_e24b_pose.py tests/test_core_spatial_action_gate.py
"$PYTHON_BIN" -m labs.virtual_anima_lab.python.lifecycle.e25c_memory_conflict_live_gate --godot "$GODOT_BIN" --evidence-dir "$OUT/lab-control" | tee "$OUT/lab-control.log"
grep -q '"status": "E2_5C_PAIRED_MEMORY_CONFLICT_PASS"' "$OUT/lab-control.log"
"$PYTHON_BIN" -m labs.virtual_anima_lab.python.lifecycle.e25c_memory_conflict_live_gate --godot "$GODOT_BIN" --core-stage6 --evidence-dir "$OUT/core-memory" | tee "$OUT/core-memory.log"
grep -q '"status": "E2_5C_INTEGRATED_MEMORY_STAGE6_PASS"' "$OUT/core-memory.log"
bash scripts/run_stage6_visual_gate.sh "$GODOT_BIN" | tee "$OUT/stage6-regression.log"
grep -q '^E2_5C_CORE_STAGE6_VISUAL_PASS' "$OUT/stage6-regression.log"
echo E2_5C_INTEGRATION_GATE_PASS | tee "$OUT/status.txt"
