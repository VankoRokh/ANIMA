"""Synthetic E4 derived-journal recovery demo; no production Memory writes."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile

from labs.exp009.e4_l0_observation import _load_frozen_inputs
from labs.exp009.e4_revision_journal_lab import (
    DerivedRevisionJournal, RevisionConflict, SimulatedCrash,
)


def run_probe():
    src = _load_frozen_inputs("positive")
    case = next(x for x in src["cases"] if x["id"] == "E4-D01")
    e1, e2, e3 = [deepcopy(x["raw"]) for x in case["events"]]
    with tempfile.TemporaryDirectory(prefix="e4-derived-journal-") as folder:
        journal_path = Path(folder) / "isolated_lab.db"
        journal = DerivedRevisionJournal(journal_path)
        before = {e["id"]: hashlib.sha256(json.dumps(
            e, sort_keys=True, ensure_ascii=False
        ).encode("utf-8")).hexdigest() for e in (e1, e2, e3)}
        journal.append_event("stream", e1)
        journal.append_event("stream", e2)
        journal.record_revision(
            projection_id="proj_d01_lab", stream_id="stream",
            expected_head=0, expected_source_version=2,
            source_event_ids=[e1["id"], e2["id"]],
            assignments={e1["id"]: "shadow_old", e2["id"]: "shadow_old"},
            operation_key="seed"
        )
        journal.append_event("stream", e3)
        request = dict(
            projection_id="proj_d01_lab", stream_id="stream",
            expected_head=1, expected_source_version=3,
            source_event_ids=[e1["id"], e2["id"], e3["id"]],
            assignments={e1["id"]: "shadow_old", e2["id"]: "derived_split"},
            operation_key="split",
            correction_event_id=e3["id"],
        )
        before_cut_seen = False
        try:
            journal.record_revision(**request, cut="before_commit")
        except SimulatedCrash:
            before_cut_seen = True
        reopened = DerivedRevisionJournal(journal_path)
        before_cut_head = reopened.read_revision("proj_d01_lab")["head_revision"]
        after_cut_seen = False
        try:
            reopened.record_revision(**request, cut="after_commit")
        except SimulatedCrash:
            after_cut_seen = True
        reopened = DerivedRevisionJournal(journal_path)
        replay = reopened.record_revision(**request)
        head = reopened.read_revision("proj_d01_lab")
        old = reopened.read_revision("proj_d01_lab", revision=1)
        late = deepcopy(e3)
        late["id"] = "ev_00000000-0000-4000-8000-000000088881"
        late["timestamp"] = "2026-11-01T12:09:00+00:00"
        late["payload"]["text"] = "Позднее уточнение источника"
        reopened.append_event("stream", late)
        stale = reopened.read_revision("proj_d01_lab")
        blocked = False
        try:
            reopened.publication_guard("proj_d01_lab", expected_revision=2)
        except RevisionConflict:
            blocked = True
        after = {e["id"]: hashlib.sha256(json.dumps(
            e, sort_keys=True, ensure_ascii=False
        ).encode("utf-8")).hexdigest() for e in (e1, e2, e3)}
        return {
            "schema": "anima.e4.derived_journal_recovery_lab/0.1",
            "status": "SIMULATED_TRANSACTION_RECOVERY_ONLY",
            "production_memory_modified": False,
            "core_authority_exercised": False,
            "before_commit_cut_injected": before_cut_seen,
            "head_after_precommit_cut": before_cut_head,
            "after_commit_cut_injected": after_cut_seen,
            "head_after_reopen": head["head_revision"],
            "idempotent_replay": replay["status"],
            "versions_preserved": reopened.versions("proj_d01_lab"),
            "historical_version1_assignment": old["record"]["assignments"][e2["id"]],
            "current_version2_assignment": head["record"]["assignments"][e2["id"]],
            "source_event_digests_preserved": before == after,
            "stale_after_late_event": not stale["eligible_for_lab_preflight"],
            "preflight_denied_on_stale": blocked,
            "staleness_scope": "ENTIRE_SOURCE_STREAM_CONSERVATIVE",
            "physical_power_loss_tested": False,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    opts = parser.parse_args(argv)
    payload = json.dumps(run_probe(), ensure_ascii=False, indent=2) + "\n"
    if opts.output:
        opts.output.parent.mkdir(parents=True, exist_ok=True)
        with opts.output.open("x", encoding="utf-8") as stream:
            stream.write(payload)
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
