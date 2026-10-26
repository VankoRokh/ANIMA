#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$task_root"
task_python="${ANIMA_PYTHON:-$task_root/.venv/bin/python}"
if [[ ! -x "$task_python" ]] && [[ -z "${ANIMA_PYTHON:-}" ]]; then
    task_python=python3
fi
exec "$task_python" -B scripts/check_project.py
