#!/usr/bin/env bash
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
export PYTHONPATH="$ROOT" PYTHONNOUSERSITE=1
PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -m pytest -q -p no:cacheprovider tests/test_e26d_continuation.py tests/test_e26d_claim_verification.py tests/test_e26d_completion.py tests/test_e26b_cognitive_suite.py tests/test_e26a_native_tools.py tests/test_e26a_local_fast.py tests/test_e25a_cognition.py tests/test_e23_cognitive_proposal_contract.py
exec "$PYTHON_BIN" -m labs.virtual_anima_lab.python.lifecycle.e26b_cognitive_suite "$@"
