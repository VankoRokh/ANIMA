#!/usr/bin/env bash
# ANIMA E1.4: isolated live ledger/readback gate on real Godot 4.7.2.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
GODOT_BIN="${GODOT_BIN:-${1:-}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -z "$GODOT_BIN" || ! -x "$GODOT_BIN" ]]; then
  echo 'E1_4_NOT_TESTED: provide executable GODOT_BIN' >&2
  exit 2
fi
OUT="${E14_REPORT_DIR:-$(mktemp -d -t anima-e14-evidence-XXXXXX)}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
export E13_REPORT_DIR="$OUT/e13"
export PYTHONNOUSERSITE=1
export PYTHONPATH="$ROOT"
printf 'sha=%s\npython=%s\ngodot=%s\n' \
  "$(git rev-parse HEAD)" "$("$PYTHON_BIN" --version)" "$("$GODOT_BIN" --headless --version)" > "$OUT/environment.txt"
# Keeps prior unmodified E1.2/E1.3 and P5/P6 regression evidence.
bash scripts/run_e13_live_gate.sh "$GODOT_BIN" 2>&1 | tee "$OUT/e13-baseline.log"
run() {
  local label="$1"
  shift
  echo "===== ${label} ====="
  "$@" 2>&1 | tee "$OUT/${label}.log"
}
run e14-unit "$PYTHON_BIN" -m pytest -q -p no:cacheprovider tests/test_lifecycle_world_recovery.py
run e14-native "$GODOT_BIN" --headless --path labs/virtual_anima_lab/godot --script res://LifecycleWorldLedgerTest.gd
grep -q '^LIFECYCLE_E1_4_NATIVE_PASS' "$OUT/e14-native.log"
for seed in 7 8; do
  run "e14-live-${seed}" "$PYTHON_BIN" -m labs.virtual_anima_lab.python.lifecycle.world_ledger_smoke --godot "$GODOT_BIN" --seed "$seed"
  grep -q '"status": "E1_4_LIVE_PASS"' "$OUT/e14-live-${seed}.log"
done
printf 'E1_4_LIVE_GATE_PASS\n' | tee "$OUT/status.txt"
