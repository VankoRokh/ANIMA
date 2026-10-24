#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$task_root"
task_python="${ANIMA_PYTHON:-python3}"
"$task_python" -c 'import sys; assert sys.version_info >= (3, 12), "Use Python 3.12 or newer; validated baseline: 3.12.14"'
if [[ ! -d .venv ]]; then
    "$task_python" -m venv .venv
fi
if [[ ! -x .venv/bin/python ]]; then
    echo 'Existing .venv is unusable. Preserve it and choose a working environment.' >&2
    exit 1
fi
.venv/bin/python -c 'import sys; assert sys.version_info >= (3, 12), "Existing .venv requires Python 3.12 or newer"; print("ANIMA environment:", sys.version.split()[0])'
.venv/bin/python -m pip install -r requirements-dev.txt
echo 'Runtime uses the standard library; development dependencies are installed.'
echo 'Next: bash scripts/check.sh'
