#!/usr/bin/env bash
# E2.5a read-only cognition: lab policy → Core-backed evidence, zero world act.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
GODOT_BIN="${GODOT_BIN:-${1:-}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -z "$GODOT_BIN" || ! -x "$GODOT_BIN" ]]; then
  echo 'E2_5A_NOT_TESTED: provide official Godot 4.7.2 binary' >&2
  exit 2
fi
OUT="${E25A_REPORT_DIR:-$(mktemp -d -t anima-e25a-evidence-XXXXXX)}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
export PYTHONPATH="$ROOT"
export PYTHONNOUSERSITE=1
export E24B_REPORT_DIR="$OUT/e24b-prior-gates"
{
  printf 'sha=%s\n' "$(git rev-parse HEAD)"
  "$PYTHON_BIN" --version
  "$GODOT_BIN" --headless --version
} > "$OUT/environment.txt"
"$PYTHON_BIN" -m pytest -q -p no:cacheprovider tests/test_e25a_cognition.py \
  2>&1 | tee "$OUT/e25a-unit.log"
"$PYTHON_BIN" -m labs.virtual_anima_lab.python.lifecycle.e25a_cognition_live_gate \
  --godot "$GODOT_BIN" --evidence-dir "$OUT/e25a-live" \
  2>&1 | tee "$OUT/e25a-live.log"
grep -q '"status": "E2_5A_READ_ONLY_COGNITION_PASS"' "$OUT/e25a-live.log"

bash scripts/run_e24b_pose_gate.sh "$GODOT_BIN" 2>&1 | tee "$OUT/e24b-regression.log"
grep -q '^E2_4B_POSE_GATE_PASS' "$OUT/e24b-regression.log"
printf 'E2_5A_READ_ONLY_COGNITION_PASS\n' | tee "$OUT/status.txt"
