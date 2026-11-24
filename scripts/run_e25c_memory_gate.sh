#!/usr/bin/env bash
# E2.5c paired memory on/off + contradiction, real Godot.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
GODOT_BIN="${GODOT_BIN:-${1:-}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -z "$GODOT_BIN" || ! -x "$GODOT_BIN" ]]; then
  echo 'E2_5C_NOT_TESTED: official Godot 4.7.2 required' >&2
  exit 2
fi
OUT="${E25C_REPORT_DIR:-$(mktemp -d -t anima-e25c-evidence-XXXXXX)}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
export PYTHONPATH="$ROOT"
export PYTHONNOUSERSITE=1
export VISUAL_REPORT_DIR="$OUT/e25b-prior-gates"
{
  printf 'sha=%s\n' "$(git rev-parse HEAD)"
  "$PYTHON_BIN" --version
  "$GODOT_BIN" --headless --version
} > "$OUT/environment.txt"
"$PYTHON_BIN" -m pytest -q -p no:cacheprovider \
  tests/test_visual_decision_policy.py tests/test_e24b_pose.py \
  2>&1 | tee "$OUT/e25c-unit.log"
"$PYTHON_BIN" -m labs.virtual_anima_lab.python.lifecycle.e25c_memory_conflict_live_gate \
  --godot "$GODOT_BIN" --evidence-dir "$OUT/e25c-live" \
  2>&1 | tee "$OUT/e25c-live.log"
grep -q '"status": "E2_5C_PAIRED_MEMORY_CONFLICT_PASS"' "$OUT/e25c-live.log"
bash scripts/run_visual_decision_gate.sh "$GODOT_BIN" \
  2>&1 | tee "$OUT/e25b-regression.log"
grep -q '^E2_5B_VISUAL_DECISION_GATE_PASS' "$OUT/e25b-regression.log"
printf 'E2_5C_PAIRED_MEMORY_CONFLICT_PASS\n' | tee "$OUT/status.txt"
