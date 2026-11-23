#!/usr/bin/env bash
# E2.5b: live Godot + real Core + decision-step API, plus old E1.2–E2.5a gates.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
GODOT_BIN="${GODOT_BIN:-${1:-}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -z "$GODOT_BIN" || ! -x "$GODOT_BIN" ]]; then
  echo "E2_5B_NOT_TESTED: provide official Godot 4.7.2 binary" >&2
  exit 2
fi
OUT="${VISUAL_REPORT_DIR:-$(mktemp -d -t anima-visual-evidence-XXXXXX)}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
export PYTHONPATH="$ROOT"
export PYTHONNOUSERSITE=1
export E25A_REPORT_DIR="$OUT/e25a-prior-gates"
{
  printf 'sha=%s\n' "$(git rev-parse HEAD)"
  "$PYTHON_BIN" --version
  "$GODOT_BIN" --headless --version
} > "$OUT/environment.txt"
"$PYTHON_BIN" -m pytest -q -p no:cacheprovider tests/test_visual_decision_policy.py \
  2>&1 | tee "$OUT/visual-unit.log"
"$PYTHON_BIN" -m labs.virtual_anima_lab.python.lifecycle.visual_runner_live_gate \
  --godot "$GODOT_BIN" --evidence-dir "$OUT/visual-live" \
  2>&1 | tee "$OUT/visual-live.log"
grep -q '"status": "E2_5B_VISUAL_DECISION_GATE_PASS"' "$OUT/visual-live.log"

bash scripts/run_e25a_cognition_gate.sh "$GODOT_BIN" \
  2>&1 | tee "$OUT/e25a-regression.log"
grep -q '^E2_5A_READ_ONLY_COGNITION_PASS' "$OUT/e25a-regression.log"
printf 'E2_5B_VISUAL_DECISION_GATE_PASS\n' | tee "$OUT/status.txt"
