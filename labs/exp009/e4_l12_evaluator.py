"""Independent post-hoc E4 L1.2 evaluator.

This module does not import/call L1.2 or run its model. It reads closed
raw traces, validates provenance and exact frozen fixtures before opening
provisional gold. It assesses *laboratory* proposals only.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

from labs.exp009 import e4_evaluator as baseline
from labs.exp009 import e4_l11_evaluator as l11

TRACE_SCHEMA = "anima.e4.association_observation_l1_2/0.1"
RESULT_SCHEMA = "anima.e4.independent_evaluation_l1_2/0.1"
RAW_STATUS = "L1_2_CONSERVATIVE_SCOPED_LAB_NOT_E4_CONFORMANCE"
MAX_BYTES = 15_000_000

IDENTIFIER = re.compile(
    r"\b(?P<kind>тикет(?:а|е|у)?|ticket|случа(?:й|я|е|ю)|case|"
    r"авари(?:я|и|е|ю)|инцидент(?:а|е|у)?|событи(?:е|я|ю|и))"
    r"\s*(?:№\s*|#\s*)?(?P<token>[A-Za-zА-Я]?\d{1,6})\b", re.I
)
PROJECT = re.compile(r"\b(?:проект|проекте|project)\s+([A-Za-zА-Яа-я0-9_-]+)", re.I)


def _canonical(surface):
    words = " ".join(surface.strip(" «»\"'\t").split()).casefold().replace("ё", "е").split()
    if (2 <= len(words) <= 4
            and all(w.endswith("ой") and len(w) > 3 for w in words[:-1])
            and words[-1].endswith("кой") and len(words[-1]) > 5):
        return " ".join(
            [w[:-2] + "ая" for w in words[:-1]]
            + [words[-1][:-3] + "ка"]
        )
    return " ".join(words)


def _identifier_from_event(raw, setup):
    text = raw["payload"].get("text", "")
    found = IDENTIFIER.search(text) if isinstance(text, str) else None
    if not found:
        return None
    word = found["kind"].casefold()
    kind = ("ticket" if word.startswith(("тикет", "ticket"))
            else "case" if word.startswith(("случа", "case"))
            else "incident")
    project = PROJECT.search(text)
    if project:
        ns = {"kind": "reported_project", "name": project.group(1).casefold()}
    elif kind == "ticket" and setup.get("ticket_namespace"):
        ns = {"kind": "declared_speaker_scope", "name": str(setup["ticket_namespace"])}
    elif kind == "case" and setup.get("case_id_namespace"):
        ns = {"kind": "declared_speaker_scope", "name": str(setup["case_id_namespace"])}
    else:
        ns = {"kind": "speaker_session_local", "name": raw["source"]}
    return {
        "kind": kind, "token": found["token"].upper(), "namespace": ns,
        "source": raw["source"], "source_event_id": raw["id"],
        "authority": "source_report_only_not_verified_identity",
    }


def _validate(observed, source):
    if (observed.get("level") != "L1_2_SCOPED_RESEARCH_LAB"
            or "AutonomousCorrectionTargetVerification" not in
            observed.get("unsupported_capabilities", [])
            or observed.get("memory_store_unchanged") is not True):
        raise ValueError("Incorrect L1.2 level or authority declaration")
    previous = dict(observed, level="L1_1_CONSERVATIVE_REVISABLE_LAB")
    checked, proposals, changed = l11._validate_extensions(previous, source)
    events, _assignments, _pairs = checked
    ids = {row["raw"]["id"] for row in source["events"]}
    for pair in observed["story_pair_assessments"]:
        a = events[pair["left_event_key"]]
        b = events[pair["right_event_key"]]
        expected = {
            "left": _identifier_from_event(a, source["setup"]),
            "right": _identifier_from_event(b, source["setup"]),
        }
        if pair.get("typed_identifiers") != expected:
            raise ValueError("Forged or mismatched typed identifier provenance")
        left, right = expected["left"], expected["right"]
        if left and right:
            if ((left["kind"] != right["kind"]
                 or left["source"] != "user" or right["source"] != "user")
                    and pair["status"] != "insufficient"):
                raise ValueError("Cross-kind or untrusted Story improperly promoted")
            if (left["namespace"] != right["namespace"]
                    and pair["status"] == "same_case_reported"):
                raise ValueError("Cross-namespace Story improperly merged")
    for alias in observed["alias_records"]:
        if (alias.get("canonical_l12") != _canonical(alias["surface"])
                or alias.get("canonical_method_l12") !=
                "bounded_multi_adjective_instrumental_v0"):
            raise ValueError("False canonical alias normal form")
    by_key = {row["key"]: row["raw"] for row in source["events"]}
    order = {row["raw"]["id"]: i for i, row in enumerate(source["events"])}
    for mention in observed["alias_mentions"]:
        raw = by_key[mention["event_key"]]
        if mention.get("canonical_l12") != _canonical(mention["surface"]):
            raise ValueError("False alias mention normalization")
        candidate_sources = set(mention.get("candidate_source_event_ids", []))
        if not candidate_sources <= ids:
            raise ValueError("Unknown alias candidate source")
        records = [
            a for a in observed["alias_records"]
            if (a["surface"] == mention["surface"]
                and a["speaker"] == raw["source"]
                and order[a["source_event_id"]] < order[raw["id"]]
                and (a["session_id"] == raw["session_id"]
                     or bool(set(a["anchor_entity_ids"]) & {
                         r["id"] for r in raw["references"] if r["kind"] == "entity"
                     })))
        ]
        if "definition_not_reuse" in mention.get("reason_codes_l12", []):
            # The utterance defines the label rather than reusing it.
            # No candidate selection should be claimed for this position.
            if (mention["status"] != "insufficient"
                    or candidate_sources
                    or "я имел в виду" not in
                    raw["payload"].get("text", "").casefold()):
                raise ValueError("Source definition was misreported as alias reuse")
            continue
        if candidate_sources != {a["source_event_id"] for a in records}:
            raise ValueError("Alias candidate set was hidden or forged")
        if mention["status"] == "scoped_alias_reuse":
            if mention.get("expensive_method_calls") != 0:
                raise ValueError("Alias reuse claims expensive call")
            chosen = [
                a for a in records if a["source_event_id"] ==
                mention.get("source_event_id") and a["target_entity_id"] ==
                mention.get("target_entity_id")
            ]
            if not chosen:
                raise ValueError("Alias reuse without source-backed target")
            anchors = {x["id"] for x in raw["references"] if x["kind"] == "entity"}
            matched = [a for a in records if (
                a["target_entity_id"] in anchors
                or set(a["anchor_entity_ids"]) & anchors
            )] if anchors else []
            if matched:
                records = matched
            elif anchors and any(a["anchor_entity_ids"] for a in records):
                records = []
            if len({a["target_entity_id"] for a in records}) != 1:
                raise ValueError("Unresolved alias conflict was incorrectly promoted")
        elif mention["status"] == "insufficient":
            if "target_entity_id" in mention or "source_event_id" in mention:
                raise ValueError("Abstaining alias must not retain selected target")
    reports = observed.get("correction_target_assessments")
    if not isinstance(reports, list):
        raise ValueError("Missing CorrectionTarget decisions")
    if len(reports) < len(proposals):
        raise ValueError("Revision materialized without CorrectionTarget report")
    observed_proposals = {
        (p["source_projection_id"], p["trigger_event_id"]): p
        for p in proposals
    }
    for row in reports:
        trigger_id = row.get("correction_event_id")
        source_ids = row.get("target_source_event_ids", [])
        prior = source["setup"].get("prior_projection")
        if (not prior or not isinstance(prior, dict)
                or trigger_id not in ids or not isinstance(source_ids, list)
                or set(source_ids) != set(prior.get("source_event_ids", []))
                or row.get("target_projection_id") != prior.get("id")
                or row.get("target_revision") != prior.get("revision")
                or row.get("production_admission") is not False
                or row.get("raw_events_modified") is not False
                or row.get("authority") !=
                "SOURCE_SCOPED_LAB_CANDIDATE_NOT_CORE_ADMITTED"):
            raise ValueError("Forged CorrectionTarget or production authority")
        trigger = next(x["raw"] for x in source["events"]
                       if x["raw"]["id"] == trigger_id)
        originals = [next(x["raw"] for x in source["events"]
                          if x["raw"]["id"] == event_id) for event_id in source_ids]
        if (trigger["source"] != "user"
                or any(e["source"] != "user" for e in originals)):
            raise ValueError("CorrectionTarget user source is untrusted")
        revision = observed_proposals.get((row["target_projection_id"], trigger_id))
        if row["status"] == "lab_scoped_candidate":
            if revision is None:
                raise ValueError("Accepted CorrectionTarget not materialized in lab")
            if row["binding_method"] == "bounded_deictic_lab_only":
                if not re.match(r"^\s*(?:это|эти|они)\s+были\b",
                                trigger["payload"].get("text", ""), re.I):
                    raise ValueError("Deictic CorrectionTarget trigger not present")
            elif row["binding_method"] == "explicit_trial_labels_lab_only":
                trial_mentions = {
                    label for label in re.findall(
                        r"\b([A-ZА-Я])\b", trigger["payload"].get("text", "")
                    )
                }
                from_source = {
                    m.group(1) for s in originals
                    if (m := re.search(
                        r"\bтест(?:е|а|у)?\s+([A-ZА-Я])\b",
                        s["payload"].get("text", "")
                    ))
                }
                if not from_source <= trial_mentions or len(from_source) != 2:
                    raise ValueError("Trial labels do not bind CorrectionTarget")
            elif row["binding_method"] == "explicit_event_source_pointers_lab_only":
                event_ptrs = {x["id"] for x in trigger["references"] if x["kind"] == "event"}
                if event_ptrs != set(source_ids):
                    raise ValueError("CorrectionTarget source pointer mismatch")
            else:
                raise ValueError("Unknown correction-binding method")
        elif row["status"] == "rejected_unbound":
            if revision is not None:
                raise ValueError("Rejected correction materialized into a view")
        else:
            raise ValueError("Unknown CorrectionTarget status")
    return checked, proposals, changed


def _score_one(check, original, observed, checked, entities, proposals, changed):
    if check["kind"] == "alias" and check["expected"] in (
        "confirmed_in_scope", "known_reuse"
    ):
        surface = check.get("from") or check.get("surface")
        target = entities.get(check.get("to"))
        if not surface or target is None:
            return baseline._grade("NOT_SUPPORTED", "No target or source alias")
        canonical = _canonical(surface)
        if check["expected"] == "confirmed_in_scope":
            matched = any(
                a["canonical_l12"] == canonical and a["target_entity_id"] == target
                for a in observed["alias_records"]
            )
        else:
            matched = any(
                m.get("canonical_l12") == canonical
                and m["status"] == "scoped_alias_reuse"
                and m.get("target_entity_id") == target
                and m.get("expensive_method_calls") == 0
                for m in observed["alias_mentions"]
            )
        return baseline._grade(
            "PASS" if matched else "FAIL",
            "Scoped morphological source report; not global synonym or Entity identity",
            actual="source_backed" if matched else "not_found",
            level="L1_2_SCOPED_ALIAS",
        )
    return l11._score(check, original, observed, checked, entities, proposals, changed)


def evaluate_trace(trace_path, suite=None):
    path = Path(trace_path)
    if not path.is_file():
        raise ValueError("A closed L1.2 raw trace is required")
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError("Raw trace too large")
    payload = json.loads(raw)
    if (payload.get("schema") != TRACE_SCHEMA
            or payload.get("status") != RAW_STATUS
            or payload.get("gold_visible") is not False):
        raise ValueError("Wrong L1.2 raw trace or leaked oracle")
    selected = suite or payload.get("suite")
    if selected not in baseline.FILES or payload.get("suite") != selected:
        raise ValueError("Suite mismatch")
    # Original frozen input and provisional gold are hash-checked by the
    # predecessor's independent evaluator, not by the adapter.
    inputs, gold = baseline._fixtures(selected)
    input_by_id = {c["id"]: c for c in inputs["cases"]}
    gold_by_id = {c["id"]: c for c in gold["cases"]}
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Missing raw cases")
    ids = [c.get("case_id") for c in cases]
    if (len(ids) != len(set(ids)) or not set(ids) <= set(input_by_id)
            or ids != [c["id"] for c in inputs["cases"] if c["id"] in set(ids)]):
        raise ValueError("Case identity or sequence mismatch")
    all_checks, all_forbidden, tracks, rows = [], [], defaultdict(list), []
    for observed in cases:
        source = input_by_id[observed["case_id"]]
        checked, proposals, changed = _validate(observed, source)
        oracle = gold_by_id[source["id"]]
        outcomes = []
        for i, item in enumerate(oracle["checks"], 1):
            outcome = {
                "id": f"{source['id']}:check:{i}", "kind": item["kind"],
                "expected": item["expected"],
                "acceptable": item.get("acceptable", [item["expected"]]),
                **_score_one(item, source, observed, checked, inputs["entities"],
                             proposals, changed),
            }
            outcomes.append(outcome)
            all_checks.append(outcome)
            tracks[source["track"]].append(outcome)
        forbidden = []
        for i, label in enumerate(oracle["forbidden"], 1):
            row = {
                "id": f"{source['id']}:forbidden:{i}", "forbidden": label,
                **baseline._grade(
                    "NOT_SUPPORTED", "No independent Core effect/authority ledger"
                ),
            }
            forbidden.append(row)
            all_forbidden.append(row)
        rows.append({
            "case_id": source["id"], "track": source["track"],
            "checks": outcomes, "forbidden": forbidden,
            "check_metrics": baseline._metrics(outcomes),
        })
    return {
        "schema": RESULT_SCHEMA,
        "status": "L1_2_LIMITED_DIAGNOSTIC_NOT_E4_CONFORMANCE",
        "suite": selected,
        "trace_sha256": hashlib.sha256(raw).hexdigest(),
        "scope": {
            "cases": len(ids), "available_cases": len(inputs["cases"]),
            "complete_suite": len(ids) == len(inputs["cases"]),
            "level": "SOURCE_SCOPED_LAB_NO_PRODUCTION_ADMISSION",
        },
        "checks": baseline._metrics(all_checks),
        "forbidden": baseline._metrics(all_forbidden),
        "by_track": {k: baseline._metrics(v) for k, v in sorted(tracks.items())},
        "cases": rows,
        "limitations": [
            "CorrectionTarget deictic binding remains heuristic and lab-only",
            "Alias morphology, typed identifiers are bounded lexical heuristics",
            "Provisional visible gold only; no independent blind evaluation",
            "No production Memory write, Core Goal/Task authority, or L2",
            "All 99 forbidden obligations remain unsupported",
        ],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trace", type=Path, required=True)
    p.add_argument("--suite", choices=tuple(baseline.FILES))
    p.add_argument("--output", type=Path)
    p.add_argument("--print-summary", action="store_true")
    opts = p.parse_args(argv)
    result = evaluate_trace(opts.trace, suite=opts.suite)
    data = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if opts.output:
        if opts.output.resolve() == opts.trace.resolve():
            raise ValueError("Scorer cannot overwrite raw trace")
        opts.output.parent.mkdir(parents=True, exist_ok=True)
        with opts.output.open("x", encoding="utf-8") as target:
            target.write(data)
    elif not opts.print_summary:
        print(data, end="")
    if opts.print_summary:
        print(json.dumps(
            {"cases": result["scope"]["cases"], "checks": result["checks"],
             "forbidden": result["forbidden"]}, ensure_ascii=False
        ))


if __name__ == "__main__":
    main()
