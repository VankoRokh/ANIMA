#!/usr/bin/env bash
# E2.4b: readback-only relative viewpoints, no action grants to Memory or LLM.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
GODOT_BIN="${GODOT_BIN:-${1:-}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -z "$GODOT_BIN" || ! -x "$GODOT_BIN" ]]; then
  echo 'E2_4B_NOT_TESTED: provide official Godot 4.7.2 binary' >&2
  exit 2
fi
OUT="${E24B_REPORT_DIR:-$(mktemp -d -t anima-e24b-evidence-XXXXXX)}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
export PYTHONPATH="$ROOT"
export PYTHONNOUSERSITE=1
export E24_REPORT_DIR="$OUT/e24a-prior-gates"
{
  printf 'sha=%s\n' "$(git rev-parse HEAD)"
  "$PYTHON_BIN" --version
  "$GODOT_BIN" --headless --version
} > "$OUT/environment.txt"
"$PYTHON_BIN" -m pytest -q -p no:cacheprovider tests/test_e24b_pose.py \
  2>&1 | tee "$OUT/e24b-unit.log"
"$PYTHON_BIN" -m labs.virtual_anima_lab.python.lifecycle.e24b_pose_live_gate \
  --godot "$GODOT_BIN" --evidence-dir "$OUT/e24b-live" \
  2>&1 | tee "$OUT/e24b-live.log"
grep -q '"status": "E2_4B_POSE_GATE_PASS"' "$OUT/e24b-live.log"

bash scripts/run_e24_live_gate.sh "$GODOT_BIN" 2>&1 | tee "$OUT/e24a-regression.log"
grep -q '^E2_4_MEMORY_GATE_PASS' "$OUT/e24a-regression.log"
printf 'E2_4B_POSE_GATE_PASS\n' | tee "$OUT/status.txt"
