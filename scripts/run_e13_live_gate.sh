#!/usr/bin/env bash
# E1.3 opt-in virtual effects lab. Run from a disposable clean Git checkout.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
GODOT_BIN="${GODOT_BIN:-${1:-}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -z "$GODOT_BIN" || ! -x "$GODOT_BIN" ]]; then
  echo 'E1_3_NOT_TESTED: provide GODOT_BIN' >&2
  exit 2
fi
OUT="${E13_REPORT_DIR:-$(mktemp -d -t anima-e13-evidence-XXXXXX)}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
export E12_REPORT_DIR="$OUT/e12"
export PYTHONNOUSERSITE=1
export PYTHONPATH="$ROOT"
export ANIMA_DATA_DIR="$(mktemp -d -t anima-e13-instance-XXXXXX)/instance"
# E1.2 performs clean-tree full regression BEFORE importing Godot assets.
bash scripts/run_e12_live_gate.sh > >(tee "$OUT/e12-gate.log") 2>&1
run() {
  local label="$1"
  shift
  echo "===== ${label} ====="
  "$@" 2>&1 | tee "$OUT/${label}.log"
}
run e13-unit "$PYTHON_BIN" -m pytest -q -p no:cacheprovider tests/test_lifecycle_world_verification.py
run e13-native "$GODOT_BIN" --headless --path labs/virtual_anima_lab/godot --script res://LifecycleWorldActionTest.gd
grep -q '^LIFECYCLE_E1_3_NATIVE_PASS' "$OUT/e13-native.log"
for seed in 7 8; do
  run "e13-live-${seed}" "$PYTHON_BIN" -m labs.virtual_anima_lab.python.lifecycle.world_action_smoke --godot "$GODOT_BIN" --seed "$seed"
  grep -q '"status": "E1_3_LIVE_PASS"' "$OUT/e13-live-${seed}.log"
done
printf 'E1_3_LIVE_GATE_PASS\n' | tee "$OUT/status.txt"
