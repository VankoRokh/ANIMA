"""Raw L1.2 source-binding probe; open development observations, not an oracle."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from labs.exp009.e4_l0_observation import _load_frozen_inputs
from labs.exp009.e4_l12_association import run_case as l12_case
from labs.exp009.e4_l11_challenge_runner import load_challenge
from labs.exp009.e4_l12_target_proof import assess, source_fingerprint


def run_probe():
    corpus = _load_frozen_inputs("positive")
    case = deepcopy(next(c for c in corpus["cases"] if c["id"] == "E4-D01"))
    baseline = l12_case(case, entity_registry=corpus["entities"])
    assignments = baseline["episode_baseline"]["event_assignments"]
    prior = case["setup"]["prior_projection"]
    sources = [case["events"][0]["raw"], case["events"][1]["raw"]]
    snapshot = {
        "projection_id": prior["id"], "revision": prior["revision"],
        "source_event_ids": [x["id"] for x in sources],
        "source_sha256": {x["id"]: source_fingerprint(x) for x in sources},
    }
    original = assess(case, assignments, expected_snapshot=snapshot)
    trigger = case["events"][2]["raw"]
    trigger["references"].extend(
        [{"kind": "event", "id": x["id"]} for x in sources]
    )
    explicit = assess(case, assignments, expected_snapshot=snapshot)
    wrong = deepcopy(case)
    wrong["events"][2]["raw"]["references"].pop()
    wrong_ref = assess(wrong, assignments, expected_snapshot=snapshot)
    changed = deepcopy(case)
    changed["events"][0]["raw"]["payload"]["text"] = "Changed original Event"
    stale = assess(changed, assignments, expected_snapshot=snapshot)

    challenge, _ = load_challenge()
    alias = deepcopy(next(c for c in challenge["cases"] if c["id"] == "E4-X07"))
    later = alias["events"][2]["raw"]
    later["session_id"] = "new_session"
    later["references"] = [
        x for x in later["references"]
        if x["id"] != challenge["entities"]["pi_psu_secondary"]
    ]
    ambient = l12_case(dict(alias, track=alias["topic"]),
                       entity_registry=challenge["entities"])
    mention = next(x for x in ambient["alias_mentions"] if x["event_key"] == "e3")
    return {
        "schema": "anima.e4.l12_source_binding_open_probe/0.1",
        "status": "VISIBLE_LAB_ONLY_NOT_E4_CONFORMANCE",
        "cases": {
            "without_explicit_pointers": original["assessments"][0],
            "two_exact_pointers_and_snapshot": explicit["assessments"][0],
            "one_pointer": wrong_ref["assessments"][0],
            "altered_original_event": stale["assessments"][0],
            "cross_session_ambient_alias": {
                "status": mention["status"],
                "reason_codes": mention["reason_codes_l12"],
                "candidate_source_event_ids": mention["candidate_source_event_ids"],
            },
        },
        "core_authority_verified": False,
        "production_admission": False,
        "memory_store_unchanged": True,
        "no_hidden_gold_or_independent_holdout": True,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path)
    args = p.parse_args(argv)
    result = json.dumps(run_probe(), ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        print(result, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(result)


if __name__ == "__main__":
    main()
