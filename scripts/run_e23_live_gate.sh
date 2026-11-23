#!/usr/bin/env bash
# E2.3 controlled Godot sensory lab; no production Memory or FAST.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
GODOT_BIN="${GODOT_BIN:-${1:-}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -z "$GODOT_BIN" || ! -x "$GODOT_BIN" ]]; then
  echo 'E2_3_NOT_TESTED: provide executable GODOT_BIN' >&2
  exit 2
fi
OUT="${E23_REPORT_DIR:-$(mktemp -d -t anima-e23-evidence-XXXXXX)}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
export PYTHONPATH="$ROOT"
export PYTHONNOUSERSITE=1
export E22_REPORT_DIR="$OUT/e22-prior-gates"
{
  printf 'sha=%s\n' "$(git rev-parse HEAD)"
  "$PYTHON_BIN" --version
  "$GODOT_BIN" --headless --version
} > "$OUT/environment.txt"

bash scripts/run_e22_live_gate.sh "$GODOT_BIN" 2>&1 | tee "$OUT/e22-regression.log"
grep -q '^E2_2_LIVE_GATE_PASS' "$OUT/e22-regression.log"
"$PYTHON_BIN" -m pytest -q -p no:cacheprovider tests/test_e23_egocentric_contract.py \
  2>&1 | tee "$OUT/e23-unit.log"
"$PYTHON_BIN" -m labs.virtual_anima_lab.python.lifecycle.e23_view_live_gate \
  --godot "$GODOT_BIN" --evidence-dir "$OUT/e23-live" \
  2>&1 | tee "$OUT/e23-live.log"
grep -q '"status": "E2_3_VIEW_GATE_PASS"' "$OUT/e23-live.log"
printf 'E2_3_VIEW_GATE_PASS\n' | tee "$OUT/status.txt"
