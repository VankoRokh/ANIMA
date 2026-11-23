#!/usr/bin/env bash
# ANIMA E1.2 lab-only live acceptance runner. No release or personal instance writes.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
BASE='a6f0021f0316b55fede8111bc5c2c4a549116ecf'
if ! git merge-base --is-ancestor "$BASE" HEAD; then
  echo 'E1_2_BLOCKED: checkout is not based on the reviewed E1.2 snapshot' >&2
  exit 2
fi
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  echo 'E1_2_BLOCKED: dirty working tree; use a clean, isolated checkout' >&2
  exit 2
fi
GODOT_BIN="${GODOT_BIN:-${1:-}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -z "$GODOT_BIN" || ! -x "$GODOT_BIN" ]]; then
  echo 'E1_2_NOT_TESTED: supply executable GODOT_BIN or first argument' >&2
  exit 2
fi
VERSION="$("$GODOT_BIN" --headless --version)"
if [[ "$VERSION" != *'4.7.2'* ]]; then
  echo "E1_2_BLOCKED: Godot 4.7.2 required; got $VERSION" >&2
  exit 2
fi
OUT="${E12_REPORT_DIR:-$(mktemp -d -t anima-e12-evidence-XXXXXX)}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
# No pre-existing ANIMA_DATA_DIR can be inherited by the test harness.
ISOLATED="$(mktemp -d -t anima-e12-instance-XXXXXX)"
trap 'rm -rf -- "$ISOLATED"' EXIT
export ANIMA_DATA_DIR="$ISOLATED/instance"
export PYTHONNOUSERSITE=1
export PYTHONPATH="$ROOT"
printf 'source_commit=%s\ngodot_version=%s\npython=%s\n' "$(git rev-parse HEAD)" "$VERSION" "$("$PYTHON_BIN" --version)" > "$OUT/environment.txt"
printf 'E1.2 report directory: %s\n' "$OUT"

run() {
  local label="$1"
  shift
  echo "===== ${label} ====="
  # pipefail propagates failures even though output is captured with tee.
  "$@" 2>&1 | tee "$OUT/${label}.log"
}

run e12-unit "$PYTHON_BIN" -m pytest -q -p no:cacheprovider tests/test_lifecycle_world_contracts.py tests/test_lifecycle_scenario.py
run project-check bash scripts/check.sh
run full-pytest "$PYTHON_BIN" -m pytest -q -p no:cacheprovider
run e12-native "$GODOT_BIN" --headless --path labs/virtual_anima_lab/godot --script res://LifecycleWorldTest.gd
grep -q 'LIFECYCLE_E1_2_NATIVE_PASS' "$OUT/e12-native.log"
for seed in 7 8; do
  run "e12-live-${seed}" "$PYTHON_BIN" -m labs.virtual_anima_lab.python.lifecycle.world_smoke --godot "$GODOT_BIN" --seed "$seed"
  grep -q 'E1_2_LIVE_PASS' "$OUT/e12-live-${seed}.log"
done
for spec in BridgeProtocolTest BridgeV2ContractTest BridgeP5CScenarioTest BridgeUiModeTest BridgeP6DoorTest; do
  run "legacy-${spec}" "$GODOT_BIN" --headless --path labs/virtual_anima_lab/godot --script "res://${spec}.gd"
done
run p5c-scenario-replay "$PYTHON_BIN" -m labs.virtual_anima_lab.python.scenario_runner --godot "$GODOT_BIN" --report-dir "$OUT/p5c-scenarios"
run m2-live "$PYTHON_BIN" -m labs.virtual_anima_lab.python.m2_integrated_gate --godot "$GODOT_BIN" --report "$OUT/m2-live.json"
printf 'E1_2_LIVE_GATE_PASS\n' | tee "$OUT/status.txt"
