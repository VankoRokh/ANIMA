"""Explicit no-LLM, no-GUI P1 bootstrap smoke runner.

Run: python -m anima.core --once --data-dir /tmp/anima-p1-smoke
This is intentionally a lifecycle smoke, NOT an autonomous agent loop.
"""

import argparse
import json
from pathlib import Path

from anima.core.assembly import build_core


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="ANIMA P1 headless bootstrap (lifecycle only; no autonomy)"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="perform one wake/sleep lifecycle and output a JSON snapshot",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="isolated data directory (default: ANIMA_DATA_DIR / project data)",
    )
    args = parser.parse_args(argv)
    if not args.once:
        parser.error("--once is required: bootstrap changes persistent state")

    assembly = build_core(args.data_dir)
    assembly.runtime.wake()
    assembly.runtime.sleep()
    snapshot = assembly.runtime.snapshot()

    # Emit only the machine-readable smoke summary. Do not expose the full
    # in-memory DiagnosticTrace or infer autonomous behavior from this result.
    result = {
        "phase": "P1_BOOTSTRAP_ONLY",
        "autonomous_loop": False,
        "instance_id": snapshot["identity"]["instance_id"],
        "status": snapshot["state"]["status"],
        "session": snapshot["state"]["session"],
        "events_processed": snapshot["state"]["events_processed"],
        "memories": snapshot["memory"]["count"],
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
