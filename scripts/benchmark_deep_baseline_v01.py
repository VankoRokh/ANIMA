#!/usr/bin/env python3
"""Run the scoped DEEP baseline audit v0.1 without mutating v0 evidence."""

from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.benchmark_deep_baseline as base
from anima.experiments.deep_audit_v01 import AUDIT_VERSION, default_audit_corpus


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    base.AUDIT_VERSION = AUDIT_VERSION
    base.default_audit_corpus = default_audit_corpus

    if "--output-dir" not in args:
        output = (
            ROOT
            / ".benchmarks"
            / "deep-baseline-v01"
            / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        )
        args.extend(["--output-dir", str(output)])
    return base.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
