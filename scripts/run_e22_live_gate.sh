#!/usr/bin/env bash
# E2.2 — only disposable world/Core raw storage; no production data.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
GODOT_BIN="${GODOT_BIN:-${1:-}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -z "$GODOT_BIN" || ! -x "$GODOT_BIN" ]]; then
  echo 'E2_2_NOT_TESTED: provide executable GODOT_BIN' >&2
  exit 2
fi
OUT="${E22_REPORT_DIR:-$(mktemp -d -t anima-e22-evidence-XXXXXX)}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
export PYTHONPATH="$ROOT"
export PYTHONNOUSERSITE=1
export E21_REPORT_DIR="$OUT/e21-prior-gates"
{
  printf 'sha=%s\n' "$(git rev-parse HEAD)"
  "$PYTHON_BIN" --version
  "$GODOT_BIN" --headless --version
} > "$OUT/environment.txt"

# Full E1.2–E2.1 P5/P6/M2 regression; performs pre-import clean-tree checks.
bash scripts/run_e21_live_gate.sh "$GODOT_BIN" 2>&1 | tee "$OUT/e21-regression.log"
grep -q '^E2_1_LIVE_GATE_PASS' "$OUT/e21-regression.log"
"$PYTHON_BIN" -m pytest -q -p no:cacheprovider tests/test_e22_raw_capture.py \
  2>&1 | tee "$OUT/e22-unit.log"
"$PYTHON_BIN" -m labs.virtual_anima_lab.python.lifecycle.e22_raw_live_gate \
  --godot "$GODOT_BIN" --evidence-dir "$OUT/e22-live" \
  2>&1 | tee "$OUT/e22-live.log"
grep -q '"status": "E2_2_LIVE_GATE_PASS"' "$OUT/e22-live.log"
printf 'E2_2_LIVE_GATE_PASS\n' | tee "$OUT/status.txt"
