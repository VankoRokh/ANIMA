#!/usr/bin/env bash
# E2.1 read-only trusted-adapter lab gate, with complete E1.1-E1.4 regression.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
GODOT_BIN="${GODOT_BIN:-${1:-}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -z "$GODOT_BIN" || ! -x "$GODOT_BIN" ]]; then
  echo 'E2_1_NOT_TESTED: provide an executable GODOT_BIN' >&2
  exit 2
fi
OUT="${E21_REPORT_DIR:-$(mktemp -d -t anima-e21-report-XXXXXX)}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
export PYTHONPATH="$ROOT"
export PYTHONNOUSERSITE=1
export E14_REPORT_DIR="$OUT/e14-previous-gates"
{
  printf 'head=%s\n' "$(git rev-parse HEAD)"
  "$PYTHON_BIN" --version
  "$GODOT_BIN" --headless --version
} > "$OUT/environment.txt"
# E1.4 runner performs clean-tree pytest BEFORE Godot project import.
bash scripts/run_e14_live_gate.sh "$GODOT_BIN" 2>&1 | tee "$OUT/e14-baseline.log"
grep -q '^E1_4_LIVE_GATE_PASS' "$OUT/e14-baseline.log"
"$PYTHON_BIN" -m pytest -q -p no:cacheprovider tests/test_e21_core_gateway.py \
  2>&1 | tee "$OUT/e21-unit.log"
"$PYTHON_BIN" tests/e1_min_independent_live_audit.py \
  --godot "$GODOT_BIN" --evidence-dir "$OUT/e1min-independent" \
  2>&1 | tee "$OUT/e1min-independent.log"
grep -q '"status": "E1_MIN_INDEPENDENT_LIVE_PASS"' "$OUT/e1min-independent.log"
"$PYTHON_BIN" -m labs.virtual_anima_lab.python.lifecycle.e21_gateway_live_gate \
  --godot "$GODOT_BIN" --evidence-dir "$OUT/e21-live" \
  2>&1 | tee "$OUT/e21-gateway-live.log"
grep -q '"status": "E2_1_READ_ONLY_GATE_PASS"' "$OUT/e21-gateway-live.log"
printf 'E2_1_LIVE_GATE_PASS\n' | tee "$OUT/status.txt"
