"""Visible E4-L1.1 challenge runner. Inputs only, never reads gold.

Challenges are predeclared development probes NOT a blinded holdout.
Each case is processed in an isolated temporary Shadow MemoryStore.
"""
import argparse
import hashlib
import json
from pathlib import Path

from anima.core.event_bus import Event
from labs.exp009.e4_l11_association import run_case

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "docs" / "TESTING" / "Fixtures"
MANIFEST = "memory_e4_l11_challenge_manifest_v0.json"
INPUT = "memory_e4_l11_challenge_inputs_v0.json"
RAW_SCHEMA = "anima.e4.l11_challenge_raw/0.1"


def _blob_sha(content):
    return hashlib.sha1(
        b"blob " + str(len(content)).encode("ascii") + b"\0" + content
    ).hexdigest()


def load_challenge():
    manifest = json.loads((FIX / MANIFEST).read_text(encoding="utf-8"))
    if manifest["status"] != "PREDECLARED_VISIBLE_DEVELOPMENT_NOT_HOLDOUT":
        raise ValueError("Challenge manifest status mismatch")
    path = FIX / INPUT
    raw = path.read_bytes()
    pin = manifest["pinned_files"]["docs/TESTING/Fixtures/" + INPUT]
    if len(raw) != pin["bytes"] or _blob_sha(raw) != pin["git_blob_sha1"]:
        raise ValueError("Challenge input checksum changed")
    data = json.loads(raw)
    if (data["schema"] != "anima.e4.l11_challenge_inputs/0.1"
            or data["status"] != "OPEN_DEVELOPMENT_ADVERSARIAL_NOT_HOLDOUT"
            or len(data["cases"]) != manifest["case_count"]):
        raise ValueError("Challenge input schema or count changed")
    seen = set()
    for case in data["cases"]:
        for item in case["events"]:
            Event.validate_record(item["raw"])
            if item["raw"]["id"] in seen:
                raise ValueError("Duplicate raw Event ID across cases")
            seen.add(item["raw"]["id"])
    return data, pin


def run_suite(*, case_id=None):
    data, pin = load_challenge()
    selected = data["cases"]
    if case_id is not None:
        selected = [x for x in selected if x["id"] == case_id]
        if not selected:
            raise ValueError("Unknown challenge ID")
    return {
        "schema": RAW_SCHEMA,
        "status": "VISIBLE_DEVELOPMENT_RAW_NOT_CONFORMANCE",
        "gold_visible": False,
        "challenge_input_blob_sha1": pin["git_blob_sha1"],
        "cases": [
            run_case(dict(case, track=case["topic"]), entity_registry=data["entities"])
            for case in selected
        ],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--case", dest="case_id")
    p.add_argument("--output", type=Path)
    opts = p.parse_args(argv)
    text = json.dumps(run_suite(case_id=opts.case_id), ensure_ascii=False, indent=2) + "\n"
    if opts.output:
        opts.output.parent.mkdir(parents=True, exist_ok=True)
        with opts.output.open("x", encoding="utf-8") as target:
            target.write(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
