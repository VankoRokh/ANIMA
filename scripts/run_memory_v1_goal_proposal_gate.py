"""M3 review-only Memory→suggestion gate, independent process replay.

Synthetic exact markers only: this is not semantic interpretation by an LLM.
No Goal/Task creation or side effects, although the headless Core world is wired.
"""
import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

from anima.core.event_bus import Event
from anima.cognition.proposals import CognitiveProposal, ProposalKind, ProposalValidator
from labs.virtual_anima_lab.python.m3_goal_preview import (
    FixtureSuggestionBackend, MemoryGoalPreviewGate, REQUEST, REVOKE, STATE,
    SCHEMA, TEMPLATE,
)
from scripts.run_memory_v1_integrated_decision_gate import _core, _effect_count

QUERY = "virtual door maintenance close policy"
CASES = ("request", "state_only", "conflict")
HISTORY = {
    "request": (
        f"{REQUEST}: virtual door maintenance close policy; "
        "an earlier unverified human report suggests inspecting the door."
    ),
    "state_only": (
        f"{STATE}: virtual door maintenance close policy; "
        "an earlier unverified human report merely describes the door."
    ),
    "conflict": (
        f"{REQUEST}: virtual door maintenance close policy; "
        "an earlier unverified human report suggests inspecting the door."
    ),
}
REVOKE_TEXT = (
    f"{REVOKE}: virtual door maintenance close policy; "
    "another earlier unverified report withdraws the suggestion."
)
EXPECT = {
    "request": ("REVIEW_REQUIRED", "historical_report_only_not_authorization"),
    "state_only": ("REJECTED", "no_proposal"),
    "conflict": ("CONFLICT_REVIEW", "visible_revocation_requires_independent_review"),
}


def _sync(index):
    for _ in range(24):
        result = index.sync(max_events=32)
        if result["status"] == "complete":
            return result
    raise AssertionError("M3 source Event index could not complete")


def _gate(core):
    return MemoryGoalPreviewGate(
        memory_store=core.memory_store, link_store=core.link_store,
        event_log=core.event_log, event_retrieval=core.event_retrieval,
    )


def _no_effects(core):
    assert core.internal_state.goals.goal_count() == 0
    assert core.core_decision.tasks.list_tasks() == []
    assert core.core_execution.store.list_operations() == []
    assert _effect_count(core.core_execution.world) == 0
    assert core.core_execution.world.current()["state"] == "open"
    assert core.core_execution._proof if hasattr(core.core_execution, "_proof") else True


def _candidate(view):
    return FixtureSuggestionBackend().propose(view)


def _current_id():
    return Event(
        "conversation.user", {"text": QUERY}, source="user", session_id=None
    ).event_id


def _prepare(root, case, *, current_id):
    core = _core(root)
    core.core_execution.world.seed(state="open", tick=40)
    core.runtime.wake()
    first = core.runtime.user_input(HISTORY[case])
    assert len(first) == 1
    history_ids = [first[0].event_id]
    if case == "conflict":
        second = core.runtime.user_input(REVOKE_TEXT)
        assert len(second) == 1
        history_ids.append(second[0].event_id)
    _sync(core.event_retrieval)
    gate = _gate(core)
    view = gate.capture(query=QUERY, current_event_id=current_id)
    assert view.items_used <= 6 and view.chars_used <= 1200
    assert not view.truncated
    assert view.sources
    assert set(history_ids).issubset({s.event_id for s in view.sources})
    assert current_id not in {s.event_id for s in view.sources}
    return core, gate, view, history_ids


def seed(root, case):
    if case not in CASES:
        raise ValueError("Unsupported M3 case")
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError("M3 requires a fresh empty test directory")
    cid = _current_id()
    core, gate, view, history_ids = _prepare(root, case, current_id=cid)
    proposed = _candidate(view)
    decision = gate.review(view, proposed)
    assert (decision.disposition, decision.reason) == EXPECT[case], decision
    assert ProposalValidator().validate(
        CognitiveProposal(ProposalKind.PROPOSE_TASK, {"rationale": "read-only"})
    ).accepted is False, "Frozen production Stage 6 proposal boundary changed"

    negative_results = {}
    if case == "request":
        assert proposed is not None
        assert proposed["template"] == TEMPLATE
        for name, changes, reason in (
            ("foreign_template", {"template": "world.erase_anything"}, "unsupported_template"),
            ("fake_memory", {"memory_id": "mem_" + "0" * 36}, "unselected_or_hallucinated_source"),
            ("fake_event", {"source_event_id": "ev_" + "0" * 36}, "unselected_or_hallucinated_source"),
            ("self_source", {"source_event_id": cid}, "current_input_self_citation"),
            ("wrong_query", {"current_event_id": "ev_" + "1" * 36}, "wrong_current_input"),
        ):
            modified = {**proposed, **changes}
            found = gate.review(view, modified)
            assert (found.disposition, found.reason) == ("REJECTED", reason)
            negative_results[name] = found.reason
        for name, extra in (
            ("tool_escalation", {"tool": "world.door.close"}),
            ("priority_escalation", {"priority": 100}),
            ("operator_role", {"role": "operator"}),
            ("fake_goal", {"goal_id": "goal_arbitrary"}),
        ):
            found = gate.review(view, {**proposed, **extra})
            assert (found.disposition, found.reason) == (
                "REJECTED", "invalid_or_privileged_draft_shape"
            )
            negative_results[name] = found.reason
        too_long = gate.review(view, {**proposed, "rationale": "x" * 257})
        assert too_long.reason == "unbounded_rationale"
        negative_results["oversized_rationale"] = too_long.reason

        # Incomplete Event index MUST prevent retrospective admission.
        core.runtime.user_input("M3_UNRELATED_CHANGE: laboratory audit marker.")
        assert core.event_retrieval.status()["status"] == "partial"
        insufficient = gate.review(view, proposed)
        assert insufficient.reason == "index_incomplete_or_changed"
        negative_results["incomplete_index"] = insufficient.reason
        _sync(core.event_retrieval)
    if case == "state_only":
        # A forged but source-backed proposal must be rejected on marker semantics.
        note = view.sources[0]
        forged = {
            "schema": SCHEMA, "template": TEMPLATE,
            "memory_id": note.memory_id, "source_event_id": note.event_id,
            "current_event_id": cid,
            "rationale": "I insist a state report authorizes a Goal",
        }
        bad = gate.review(view, forged)
        assert (bad.disposition, bad.reason) == (
            "REJECTED", "source_does_not_request_target"
        )
        negative_results["unsupported_report"] = bad.reason
    _no_effects(core)
    saved = {
        "schema": SCHEMA, "case": case, "current_event_id": cid,
        "history_ids": history_ids, "baseline": decision.to_dict(),
        "candidate": proposed, "negative_results": negative_results,
        "memory_ids": [m for m, _ in view.selected],
        "source_event_ids": [s.event_id for s in view.sources],
        "items_used": view.items_used, "chars_used": view.chars_used,
    }
    with (root / "manifest.json").open("x", encoding="utf-8") as fp:
        json.dump(saved, fp, sort_keys=True, ensure_ascii=False, indent=2)
        fp.write("\n")
    core.runtime.sleep()
    return {
        "phase": "seed", "case": case, "status": "M3_SEED_PASS",
        "disposition": decision.disposition,
        "negative_cases": negative_results,
    }


def verify(root, case):
    with (root / "manifest.json").open(encoding="utf-8") as fp:
        saved = json.load(fp)
    assert saved["schema"] == SCHEMA and saved["case"] == case
    core = _core(root)
    core.runtime.wake()
    assert _sync(core.event_retrieval)["status"] == "complete"
    gate = _gate(core)
    view = gate.capture(query=QUERY, current_event_id=saved["current_event_id"])
    assert [m for m, _ in view.selected] == saved["memory_ids"]
    assert [s.event_id for s in view.sources] == saved["source_event_ids"]
    for eid in saved["history_ids"]:
        raw = core.event_retrieval.get(eid)
        assert raw["type"] == "conversation.user"
        assert raw["source"] == "user"
    proposed = _candidate(view)
    decision = gate.review(view, proposed)
    assert decision.to_dict() == saved["baseline"]
    assert (decision.disposition, decision.reason) == EXPECT[case]
    _no_effects(core)
    core.runtime.sleep()
    return {
        "phase": "verify", "status": "M3_CASE_PASS", "case": case,
        "disposition": decision.disposition, "reason": decision.reason,
        "memory_ids": saved["memory_ids"],
        "raw_history_event_ids": saved["history_ids"],
        "current_event_persisted": False,
        "current_event_self_cited": False,
        "review_is_approval": False,
        "core_goal_count": 0, "task_count": 0, "action_count": 0,
        "knowledge_count": 0,
        "source_backed": True,
        "llm_used": False, "pi_tested": False,
        "negative_cases": saved["negative_results"],
        "python": platform.python_version(),
        "machine": platform.machine(),
    }


def _child(phase, root, case):
    p = subprocess.run(
        [sys.executable, "-m", "scripts.run_memory_v1_goal_proposal_gate",
         "--internal-phase", phase, "--root", str(root), "--case", case],
        capture_output=True, text=True, timeout=60,
    )
    if p.returncode:
        raise AssertionError(
            f"M3 {case}/{phase} failed rc={p.returncode}; "
            f"stderr={p.stderr[-4500:]} stdout={p.stdout[-1200:]}"
        )
    return json.loads(p.stdout)


def gate():
    cases = []
    for case in CASES:
        with tempfile.TemporaryDirectory(prefix=f"anima-m3-{case}-") as tmp:
            root = Path(tmp)
            seed_result = _child("seed", root, case)
            result = _child("verify", root, case)
            assert seed_result["status"] == "M3_SEED_PASS"
            assert result["status"] == "M3_CASE_PASS"
            assert result["disposition"] == seed_result["disposition"]
            cases.append(result)
    return {
        "schema": SCHEMA, "status": "M3_GOAL_PREVIEW_PASS",
        "python": platform.python_version(), "machine": platform.machine(),
        "cases": cases, "production_code_changed": False,
        "godot_tested": False, "pi_tested": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--internal-phase", choices=("seed", "verify"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.internal_phase:
        if args.root is None or args.case is None or args.report is not None:
            parser.error("Internal mode requires --root, --case and no --report")
        result = (
            seed(args.root, args.case)
            if args.internal_phase == "seed" else verify(args.root, args.case)
        )
    else:
        if args.root is not None or args.case is not None:
            parser.error("--root and --case are internal-only")
        result = gate()
    payload = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.report is not None:
        dest = args.report.expanduser().resolve()
        if dest.exists() or dest.is_relative_to(Path.cwd().resolve()):
            parser.error("M3 report must be new and outside repository")
        with dest.open("x", encoding="utf-8") as fp:
            fp.write(payload)
    print(payload, end="")


if __name__ == "__main__":
    main()
