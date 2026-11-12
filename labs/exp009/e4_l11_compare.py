"""Compare two independent E4 evaluation artifacts, never load gold/algorithms."""
import argparse
import json
from pathlib import Path


def compare(old, new):
    if old.get("suite") != new.get("suite"):
        raise ValueError("Mismatch in compared suites")
    a = {check["id"]: check for row in old["cases"] for check in row["checks"]}
    b = {check["id"]: check for row in new["cases"] for check in row["checks"]}
    if a.keys() != b.keys():
        raise ValueError("Not the same set of frozen gold checks")
    if any((a[k]["expected"], a[k]["acceptable"]) !=
           (b[k]["expected"], b[k]["acceptable"]) for k in a):
        raise ValueError("Gold contract drift")
    changes = [{
        "id": key, "from": a[key]["status"], "to": b[key]["status"],
        "old_actual": a[key].get("actual"),
        "new_actual": b[key].get("actual"),
    } for key in sorted(a) if a[key]["status"] != b[key]["status"]]
    regressions = [
        row for row in changes
        if row["from"] == "PASS" and row["to"] != "PASS"
    ]
    return {
        "schema": "anima.e4.l1_l11_differential/0.1",
        "suite": old["suite"],
        "legacy_trace_sha256": old["trace_sha256"],
        "improved_trace_sha256": new["trace_sha256"],
        "gold_checks": len(a),
        "legacy": old["checks"],
        "l1_1": new["checks"],
        "changed_checks": changes,
        "regressions": regressions,
        "no_regressions": not regressions,
        "full_e4_conformance": False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--old", type=Path, required=True)
    p.add_argument("--new", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(argv)
    old = json.loads(a.old.read_text(encoding="utf-8"))
    new = json.loads(a.new.read_text(encoding="utf-8"))
    result = compare(old, new)
    if a.output.resolve() in (a.old.resolve(), a.new.resolve()):
        raise ValueError("Refuse to overwrite evaluation input")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({
        "suite": result["suite"],
        "changed_checks": result["changed_checks"],
        "regressions": result["regressions"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
