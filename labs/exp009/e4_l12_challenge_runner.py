"""Run the predeclared visible challenge with L1.2. Never opens gold."""
import argparse
import json
from pathlib import Path

from labs.exp009.e4_l11_challenge_runner import load_challenge
from labs.exp009.e4_l12_association import run_case

SCHEMA = "anima.e4.l12_challenge_raw/0.1"


def run_suite(*, case_id=None):
    fixture, pinned = load_challenge()
    cases = fixture["cases"]
    if case_id:
        cases = [c for c in cases if c["id"] == case_id]
        if not cases:
            raise ValueError("Unknown challenge case")
    return {
        "schema": SCHEMA,
        "status": "VISIBLE_L12_DEVELOPMENT_RAW_NOT_CONFORMANCE",
        "gold_visible": False,
        "challenge_input_blob_sha1": pinned["git_blob_sha1"],
        "cases": [
            run_case(dict(c, track=c["topic"]), entity_registry=fixture["entities"])
            for c in cases
        ],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--case", dest="case_id")
    p.add_argument("--output", type=Path)
    args = p.parse_args(argv)
    content = json.dumps(run_suite(case_id=args.case_id),
                         ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        print(content, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(content)


if __name__ == "__main__":
    main()
