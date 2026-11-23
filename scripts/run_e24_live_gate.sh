#!/usr/bin/env bash
# E2.4 read-only agent sensor -> Core provenance -> derived working memory.
# All world and Core data are disposable, no production profile or FAST.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
GODOT_BIN="${GODOT_BIN:-${1:-}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -z "$GODOT_BIN" || ! -x "$GODOT_BIN" ]]; then
  echo 'E2_4_NOT_TESTED: provide official Godot 4.7.2 binary' >&2
  exit 2
fi
OUT="${E24_REPORT_DIR:-$(mktemp -d -t anima-e24-evidence-XXXXXX)}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
export PYTHONPATH="$ROOT"
export PYTHONNOUSERSITE=1
export E23_REPORT_DIR="$OUT/e23-prior-gates"
{
  printf 'sha=%s\n' "$(git rev-parse HEAD)"
  "$PYTHON_BIN" --version
  "$GODOT_BIN" --headless --version
} > "$OUT/environment.txt"

"$PYTHON_BIN" -m pytest -q -p no:cacheprovider tests/test_e24_working_memory.py \
  2>&1 | tee "$OUT/e24-unit.log"
"$PYTHON_BIN" -m labs.virtual_anima_lab.python.lifecycle.e24_memory_live_gate \
  --godot "$GODOT_BIN" --evidence-dir "$OUT/e24-live" \
  2>&1 | tee "$OUT/e24-live.log"
grep -q '"status": "E2_4_MEMORY_GATE_PASS"' "$OUT/e24-live.log"

# E1.2–E2.3 frozen regression after new E2.4 gate.
bash scripts/run_e23_live_gate.sh "$GODOT_BIN" 2>&1 | tee "$OUT/e23-regression.log"
grep -q '^E2_3_VIEW_GATE_PASS' "$OUT/e23-regression.log"
printf 'E2_4_MEMORY_GATE_PASS\n' | tee "$OUT/status.txt"
