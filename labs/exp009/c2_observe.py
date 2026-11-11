"""EXP-009 / C2-A,B: external, read-only observation of real Core processing.

The fixture feeds synthetic inputs through registered Core APIs. It neither
creates episodic Memory for world observations nor supplies world ground truth.
JSONL includes raw inputs, admission results, Belief snapshots and source events.
"""

import argparse
import json
import tempfile
from pathlib import Path

from anima.core.assembly import build_core
from anima.core.belief import PropertyRule
from anima.core.ingress import CONTRACT, SourceRegistration


SUBJECT = "entity.rig@exp009"
TEMP = "system.temperature@1"
COOLING = "system.cooling@1"
A = "sensor.temperature_a"
B = "sensor.temperature_b"
FAN = "sensor.cooling"
CLOCK = "lab_tick"


def _build(root):
    sources = {
        source: SourceRegistration(
            source_ref=source,
            producer_ref="adapter.exp009/0.1",
            allowed_kinds=("state.property", "sensor.unavailable"),
        )
        for source in (A, B, FAN)
    }
    properties = {
        (SUBJECT, TEMP): PropertyRule(
            subject_ref=SUBJECT,
            predicate_ref=TEMP,
            value_type="integer",
            clock_domain=CLOCK,
            allowed_sources=(A, B),
            freshness_ticks=2,
        ),
        (SUBJECT, COOLING): PropertyRule(
            subject_ref=SUBJECT,
            predicate_ref=COOLING,
            value_type="symbol",
            clock_domain=CLOCK,
            allowed_sources=(FAN,),
            freshness_ticks=2,
            allowed_symbols=("on", "off"),
        ),
    }
    return build_core(root, sources=sources, properties=properties)


def _input(name, predicate, tick, revision, value=None, *, unavailable=False):
    at = {"domain": CLOCK, "value": tick}
    payload = {
        "subject_ref": SUBJECT,
        "predicate_ref": predicate,
        "observed_at": at,
        "temporal_scope": {"kind": "instant", "at": dict(at)},
        "source_revision": revision,
    }
    if unavailable:
        payload["reason"] = "sensor_offline"
    else:
        payload["value"] = {
            "type": "integer" if predicate == TEMP else "symbol",
            "value": value,
        }
    return {
        "contract": CONTRACT,
        "occurrence_id": name,
        "occurrence_version": 1,
        "kind": "sensor.unavailable" if unavailable else "state.property",
        "payload": payload,
    }


def _beliefs(core):
    return {
        "temperature": core.runtime.read_core_belief(SUBJECT, TEMP),
        "cooling": core.runtime.read_core_belief(SUBJECT, COOLING),
    }


def _admit(core, *, label, source, raw, deferred=False):
    # Deferred admission intentionally exercises the trusted Core outbox
    # boundary; it does not write to EventLog or Memory directly.
    if deferred:
        result = core.core_events.ingress.admit(raw, source_ref=source)
    else:
        result = core.runtime.ingest_core_event(raw, source_ref=source)
    outcome = (
        core.core_events.ingress.observation_outcome(result.event_id)
        if result.event_id is not None
        else None
    )
    receipt = (
        core.core_events.ingress.dispatch_receipt(result.event_id)
        if result.event_id is not None
        else None
    )
    return {
        "type": "input",
        "label": label,
        "source_ref": source,
        "raw": raw,
        "deferred": deferred,
        "admission": {
            "status": result.status,
            "event_id": result.event_id,
            "reason_code": result.reason_code,
        },
        # For ALREADY_SEEN/IDENTITY_CONFLICT this describes the ORIGINAL
        # event, not a new observation caused by the repeated delivery.
        "original_event_outcome": outcome,
        "dispatch_receipt": receipt,
        "beliefs_after": _beliefs(core),
        "pending_after": len(core.core_events.ingress.pending_event_ids()),
        "memory_count_after": core.memory.count(),
    }


def _checkpoint(core, label):
    return {
        "type": "checkpoint",
        "label": label,
        "identity": core.identity.get()["instance_id"],
        "beliefs": _beliefs(core),
        "pending": len(core.core_events.ingress.pending_event_ids()),
        "raw_event_count": len(core.event_log.load_events()),
        "memory_count": core.memory.count(),
    }


def _finish(core, label, admitted_ids):
    ingress = core.core_events.ingress
    return {
        "type": "final",
        "label": label,
        "identity": core.identity.get()["instance_id"],
        "beliefs": _beliefs(core),
        "belief_history": {
            "temperature": ingress.belief_history(SUBJECT, TEMP),
            "cooling": ingress.belief_history(SUBJECT, COOLING),
        },
        "core_events": [
            ingress.get_event(event_id) for event_id in admitted_ids
        ],
        "event_outcomes": [
            {"event_id": event_id, "outcome": ingress.observation_outcome(event_id)}
            for event_id in admitted_ids
        ],
        "dispatch_receipts": [
            {"event_id": event_id, "receipt": ingress.dispatch_receipt(event_id)}
            for event_id in admitted_ids
        ],
        "event_log": core.event_log.load_events(),
        "event_processing": core.event_processing.list_records(),
        "pending": list(ingress.pending_event_ids()),
        "rejections": ingress.rejection_count(),
        "memory_count": core.memory.count(),
        "runtime_state": core.runtime.snapshot()["state"],
        "limitations": [
            "This records Core/Belief processing, not autonomous reasoning.",
            "World observations intentionally do not become episodic Memory.",
            "Source registration is not transport authentication.",
        ],
    }


def _write_report(report_path, records):
    if report_path is None:
        return
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Refuse accidental replacement of an earlier experimental trace.
    with path.open("x", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(
                record, ensure_ascii=False, sort_keys=True, allow_nan=False
            ) + "\n")


def run_c2_a(root, *, report_path=None):
    """C2-A: 36 admitted mixed observations, bounded outbox catch-up, replay."""
    core = _build(root)
    records = [{"type": "experiment", "scenario": "C2-A",
                "format": "exp009.raw-jsonl/0.1"}]
    emitted = []
    deliveries = []
    for index in range(36):
        revision = index // 3 + 1
        tick = 100 + index
        if index % 3 == 0:
            source, raw = A, _input(
                f"a-{index:02d}", TEMP, tick, revision, 60 + index % 15
            )
        elif index % 3 == 1:
            source, raw = FAN, _input(
                f"fan-{index:02d}", COOLING, tick, revision,
                "on" if revision % 2 else "off"
            )
        else:
            source, raw = B, _input(
                f"b-{index:02d}", TEMP, tick, revision, 65 + index % 12
            )
        event = _admit(
            core, label=f"batch-{index:02d}", source=source,
            raw=raw, deferred=True
        )
        records.append(event)
        emitted.append(event)
        deliveries.append((source, raw))
    records.append(_checkpoint(core, "before_reopen"))

    # A normal wake drains only a bounded batch; remaining work survives.
    core = _build(root)
    records.append(_checkpoint(core, "after_reopen_before_wake"))
    core.runtime.wake()
    records.append(_checkpoint(core, "after_first_wake"))
    core.runtime.wake()
    records.append(_checkpoint(core, "after_second_wake"))

    records.append(_admit(
        core, label="repeat-original",
        source=deliveries[0][0], raw=deliveries[0][1]
    ))
    altered = _input("a-00", TEMP, 100, 1, 999)
    records.append(_admit(
        core, label="identity-conflict", source=A, raw=altered
    ))
    records.append(_admit(
        core, label="unregistered", source="sensor.unregistered",
        raw=_input("forged", TEMP, 145, 1, 500)
    ))
    ids = [item["admission"]["event_id"] for item in emitted]
    records.append(_finish(core, "C2-A", ids))
    _write_report(report_path, records)
    return records


def run_c2_b(root, *, report_path=None):
    """C2-B: evidence conflict, staleness, unavailable, and source authority."""
    core = _build(root)
    records = [{"type": "experiment", "scenario": "C2-B",
                "format": "exp009.raw-jsonl/0.1"}]
    cases = [
        ("t10-a", A, _input("temp-a10", TEMP, 10, 1, 65)),
        ("t10-b-conflict", B, _input("temp-b10", TEMP, 10, 1, 73)),
        ("t11-a-resolve", A, _input("temp-a11", TEMP, 11, 2, 70)),
        ("t09-b-late", B, _input("temp-b09", TEMP, 9, 2, 88)),
        ("t12-b-unavailable", B, _input(
            "temp-b12", TEMP, 12, 3, unavailable=True
        )),
        ("repeat-unavailable", B, _input(
            "temp-b12", TEMP, 12, 3, unavailable=True
        )),
        ("registered-no-authority", FAN, _input(
            "cooling-forges-temp", TEMP, 13, 1, 99
        )),
        ("t13-a-recover", A, _input("temp-a13", TEMP, 13, 3, 71)),
        ("unknown-source", "sensor.unregistered", _input(
            "unknown-claim", TEMP, 13, 1, 500
        )),
        ("occurrence-conflict", A, _input("temp-a13", TEMP, 13, 3, 72)),
        ("cooling-on", FAN, _input("cooling-10", COOLING, 10, 1, "on")),
        ("cooling-off", FAN, _input("cooling-11", COOLING, 11, 2, "off")),
        ("cooling-unavailable", FAN, _input(
            "cooling-12", COOLING, 12, 3, unavailable=True
        )),
        ("t14-a", A, _input("temp-a14", TEMP, 14, 4, 72)),
        ("t14-b-support", B, _input("temp-b14", TEMP, 14, 4, 72)),
        ("t13-b-late", B, _input("temp-b13", TEMP, 13, 5, 100)),
    ]
    ids = []
    for label, source, raw in cases:
        event = _admit(core, label=label, source=source, raw=raw)
        records.append(event)
        if event["admission"]["status"] == "ACCEPTED":
            ids.append(event["admission"]["event_id"])
    records.append(_finish(core, "C2-B", ids))
    _write_report(report_path, records)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario", choices=("a", "b", "both"), default="both"
    )
    parser.add_argument(
        "--report-dir", type=Path, required=True,
        help="New output directory outside tracked repo paths",
    )
    parser.add_argument(
        "--print-raw", action="store_true",
        help="Print every raw JSONL record to stdout as well",
    )
    args = parser.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="anima-exp009-c2-") as temp:
        for name, runner in (("a", run_c2_a), ("b", run_c2_b)):
            if args.scenario not in (name, "both"):
                continue
            output = args.report_dir / f"c2_{name}.jsonl"
            records = runner(
                Path(temp) / name, report_path=output
            )
            final = records[-1]
            print(
                f"C2-{name.upper()}: {len(records) - 2} trace entries; "
                f"raw world observations="
                f"{sum(x['type'] == 'world.observation' for x in final['event_log'])}; "
                f"memory={final['memory_count']}; "
                f"pending={len(final['pending'])}; report={output}"
            )
            if args.print_raw:
                print(output.read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
