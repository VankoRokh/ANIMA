"""E26 synthetic evidence and exact-request replay, never Core authority.

Only explicit laboratory artifacts are exported. The local backend process
metadata is operator-selected, not attestation of the HTTP peer or model file.
Replay sends one frozen request, never dispatches a returned tool call.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from anima.agent.generation_termination import classify_termination
from anima.agent.native_tools import canonical, strict_json, NativeToolCatalog, LoopbackChatTransport
from .egocentric import EgocentricView
from anima.core.ingress import validate_event_envelope
from ..cognition.contracts import CognitiveStepProposal
from ..cognition.native_lab import lab_registry
from ..cognition.source_policy import E25CognitionError, TurnSourcePolicy
from .e24_working_memory import (
    E24WorkingMemory, SOURCE, PRODUCER, vision_source_registration,
)

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = "anima.e26.reproducibility/0.1"


def digest(data):
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def file_digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    # Exclusive creation: never overwrite an earlier run.
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(canonical(value) + "\n")


def read_json(path):
    from anima.agent.native_tools import strict_json
    return strict_json(Path(path).read_text(encoding="utf-8"))


def git_snapshot():
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, timeout=15).strip()
    sha = git("rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or git("status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("E26 evidence requires a clean Git worktree")
    return sha


def isolated_godot_project(destination):
    """Copy only tracked Godot sources; imports/UIDs stay outside the worktree."""
    prefix = "labs/virtual_anima_lab/godot/"
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--", prefix], cwd=ROOT,
    ).decode("utf-8").split("\0")
    destination = Path(destination)
    for name in filter(None, names):
        source = ROOT / name
        relative = Path(name).relative_to(prefix)
        if not source.is_file() or source.is_symlink():
            raise ValueError("unsupported Godot source")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    if not (destination / "project.godot").is_file():
        raise ValueError("missing tracked Godot project")
    return destination


def backend_snapshot(pid):
    """Capture exact executable hash and argv from the selected Linux process."""
    if type(pid) is not int or pid < 1:
        raise ValueError("positive backend PID required")
    proc = Path("/proc") / str(pid)
    def start_marker():
        return (proc / "stat").read_text().rpartition(")")[2].split()[19]
    started = start_marker()
    argv = (proc / "cmdline").read_bytes().decode("utf-8").rstrip("\0").split("\0")
    if not argv or not argv[0]:
        raise ValueError("backend command line unavailable")
    # Never bundle common credential-bearing switches or environment contents.
    if any(re.match(r"^--?[^=]*(?:api[-_]?key|token|password|secret|credential|auth)[^=]*(?:=|$)",
                    arg, re.I) for arg in argv[1:]):
        raise ValueError("credential-bearing backend argv must not be exported")
    binary = os.readlink(proc / "exe")
    sha = file_digest(proc / "exe")
    if started != start_marker():
        raise ValueError("backend process changed during capture")
    return {"pid": pid, "process_start_ticks": started, "executable": binary,
            "executable_sha256": sha, "argv": argv,
            "endpoint_process_attested": False, "environment_attested": False,
            "external_config_and_dynamic_libraries_attested": False}


def runtime_manifest(*, git_sha, godot, backend, base_url, model, model_sha, variant, scenarios):
    return {"schema": SCHEMA, "git_sha": git_sha, "git_clean_at_start": True,
            "python": sys.version, "platform": platform.platform(),
            "sqlite": sqlite3.sqlite_version,
            "godot": {"version": subprocess.check_output([godot, "--headless", "--version"],
                                                         text=True, timeout=15).strip(),
                      "executable_sha256": file_digest(godot)},
            "backend": backend, "base_url": base_url, "model_alias": model,
            "local_model_sha256": model_sha, "file_hash_not_attested_by_server": True,
            "variant": variant, "scenarios": scenarios, "world_seeds": [7, 8],
            "identity_generation": "fresh_random_not_seeded",
            "inference_seed": "not_explicitly_set_in_existing_profile",
            "request_encoding": "canonical_json_utf8",
            "response_encoding": "parsed_json_canonical_not_http_wire_bytes",
            "scope": "synthetic_lab_only", "alias_authority": False,
            "temperature": 0, "max_steps": 4, "max_output_tokens": 256}


def alias_mapping(samples):
    """Diagnostic-only stable aliases by first observation and relative geometry.

    No change to Raw, Context, live model input or Core identities. Aliases
    support comparison, not a guarantee of identical serialized prompt order.
    """
    mapping = {}
    counts = {"surface": 0, "obstacle": 0}
    for row in samples:
        view = json.loads(row["raw_json"])
        seq = view["sample_seq"]
        mapping[row["event_id"]] = f"ev_sample_{seq:04d}"
        mapping[view["world_instance_id"]] = "world_alias_0001"
        mapping[view["sample_id"]] = f"worldobs:world_alias_0001:{view['epoch']}:{seq}"
        mapping[row["raw_sha256"]] = f"raw_sha_sample_{seq:04d}"
        readings = sorted(view["readings"], key=lambda r: (
            r["category"], r["bearing_mdeg"], r["range_milli_cells"],
            canonical(r["properties"]), r["entity_ref"],
        ))
        for reading in readings:
            ref = reading["entity_ref"]
            if re.fullmatch(r"lab\.(surface|obstacle)\.[a-f0-9]{24}", ref) and ref not in mapping:
                kind = reading["category"]
                counts[kind] += 1
                mapping[ref] = f"lab.{kind}.alias_{counts[kind]:04d}"
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("non-bijective diagnostic alias mapping")
    return mapping


def export_raw(memory, root, seed):
    with closing(memory._connect()) as db:
        rows = db.execute("SELECT sample_id,core_event_id,raw_sha256 FROM e24_raw ORDER BY sample_seq").fetchall()
    samples = []
    ingress = memory._core.core_events.ingress
    for row in rows:
        view = memory.raw_evidence(row["sample_id"])
        event_id = row["core_event_id"]
        samples.append({"sample_id": row["sample_id"], "event_id": event_id,
                        "source_ref": SOURCE, "raw_json": view.canonical_json,
                        "raw_sha256": row["raw_sha256"],
                        "core_event": ingress.get_event(event_id),
                        "observation_outcome": ingress.observation_outcome(event_id),
                        "dispatch_receipt": ingress.dispatch_receipt(event_id)})
    fixture = {"schema": SCHEMA, "world_seed": seed, "samples": samples,
               "aliases": alias_mapping(samples)}
    verify_raw(fixture)
    write_json(Path(root) / f"raw-seed-{seed}.json", fixture)
    return fixture


def verify_raw(fixture):
    if fixture["schema"] != SCHEMA or len(fixture["samples"]) != 3:
        raise ValueError("expected three canonical synthetic Raw samples")
    events, worlds = set(), set()
    for index, row in enumerate(fixture["samples"], 1):
        raw = row["raw_json"]
        view = EgocentricView(json.loads(raw))
        snap = view.as_dict()
        event_id = row["event_id"]
        expected = E24WorkingMemory._event(snap, row["raw_sha256"])
        event = row["core_event"]
        if (raw != view.canonical_json or digest(raw) != row["raw_sha256"]
                or row["sample_id"] != snap["sample_id"] or snap["sample_seq"] != index
                or row["source_ref"] != snap["source_ref"] or row["source_ref"] != SOURCE
                or not isinstance(event_id, str) or not event_id or event_id in events
                or event["event_id"] != event_id
                or event["source_ref"] != SOURCE or event["producer_ref"] != PRODUCER
                or any(event[key] != expected[key] for key in
                       ("occurrence_id", "occurrence_version", "kind", "payload"))
                or row["observation_outcome"]["outcome"].startswith("REJECTED_")
                or row["dispatch_receipt"]["disposition"] != "forwarded"):
            raise ValueError("Raw/Core pointer mismatch")
        # Reuse the actual ingress envelope/fingerprint contract. This is
        # pure validation, not admission, a database write or attestation.
        checked = validate_event_envelope(expected, vision_source_registration())
        if checked is None or event["content_sha256"] != checked[2]:
            raise ValueError("Core event fingerprint mismatch")
        for record in (row["observation_outcome"], row["dispatch_receipt"]):
            if "event_id" in record and record["event_id"] != event_id:
                raise ValueError("Core event identity mismatch")
        events.add(event_id)
        worlds.add((snap["world_instance_id"], snap["epoch"]))
    if len(worlds) != 1 or fixture["aliases"] != alias_mapping(fixture["samples"]):
        raise ValueError("invalid world or diagnostic alias mapping")
    return len(events)


def normalized_request_sha(request_json, aliases):
    # Diagnostic string substitution only, not semantic or exact equivalence.
    keys = sorted(aliases, key=len, reverse=True)
    pattern = re.compile("|".join(map(re.escape, keys))) if keys else None
    return digest(pattern.sub(lambda m: aliases[m.group()], request_json)
                  if pattern else request_json)


def freeze_call(call, aliases, index):
    request = canonical(call["request"])
    response = canonical(call["raw_response"]) if call.get("raw_response") is not None else None
    return {"index": index, "phase": call.get("phase", "research"),
            "request_json": request, "request_sha256": digest(request),
            "diagnostic_alias_request_sha256": normalized_request_sha(request, aliases),
            "response_json": response, "response_sha256": digest(response) if response is not None else None,
            "transport_ok": call["transport_ok"], "valid": call["valid"]}


def export_case(root, seed, case_id, report, trace, calls, raw_fixture, *, result=None):
    all_calls = list(calls)
    projection = report.get("claim_projection", {}).get("call")
    if projection is not None:
        all_calls.append(projection)
    fixture = {"schema": SCHEMA, "world_seed": seed, "case": case_id,
               "turn": report, "trace": trace, "model_calls": all_calls,
               "result": result,
               "requests": [freeze_call(call, raw_fixture["aliases"], i)
                            for i, call in enumerate(all_calls)]}
    write_json(Path(root) / f"case-{seed}-{case_id}.json", fixture)


def _verify_journal_scope(fixture, rows):
    """Recheck the exported decision chain using the runtime source policy.

    No service calls, inference or database discovery. The Raw fixture is the
    only available event/sample identity inventory. This establishes internal
    consistency, not the historical authenticity of a fully rewritten bundle.
    """
    turn = fixture["turn"]
    trace = fixture["trace"]
    if turn["status"] not in ("STOPPED", "REJECTED", "STEP_BUDGET_EXHAUSTED"):
        raise ValueError("invalid cognitive turn status")
    if not trace:
        return
    context = trace[0]["context_snapshot"]
    context_id = context["context_snapshot_id"]
    base = {key: value for key, value in context.items() if key != "context_snapshot_id"}
    if (context_id != "ctx_" + digest(canonical(base))
            or context_id != turn["context_snapshot_id"]):
        raise ValueError("Context fingerprint mismatch")
    samples = {row["sample_id"]: json.loads(row["raw_json"]) for row in rows.values()}
    latest = samples.get(context["latest_sample_id"])
    if (latest is None or context["world_instance_id"] != latest["world_instance_id"]
            or context["epoch"] != latest["epoch"]
            or context["source_ref"] != latest["source_ref"]
            or context["coverage"] != latest["coverage"]
            or type(context["memory_enabled"]) is not bool):
        raise ValueError("Context/Raw scope mismatch")
    policy = TurnSourcePolicy(context)

    def verify_exposed():
        # Check even references that are never requested by the model.
        for event, sample in policy.exposed_bindings().items():
            if event not in rows or rows[event]["sample_id"] != sample:
                raise ValueError("Context/Raw event identity mismatch")

    verify_exposed()
    proposal_ids = set()
    for index, record in enumerate(trace):
        outcome = record["outcome"]
        if (record["turn_id"] != turn["turn_id"]
                or type(record["step_index"]) is not int or record["step_index"] != index
                or type(outcome["step_index"]) is not int or outcome["step_index"] != index
                or canonical(record["context_snapshot"]) != canonical(context)
                or record["admission"] not in ("ADMITTED", "REJECTED")
                or outcome["status"] not in ("COMPLETED", "REJECTED")
                or (record["admission"] == "REJECTED" and outcome["status"] != "REJECTED")):
            raise ValueError("journal turn/admission identity mismatch")
        proposal = record["proposal"]
        if proposal is None:
            if (record["admission"] != "REJECTED"
                    or outcome["proposal_id"] is not None
                    or "result" in outcome):
                raise ValueError("missing typed proposal")
            continue
        proposal = CognitiveStepProposal(proposal).as_dict()
        kind = proposal["operation_kind"]
        args = proposal["arguments"]
        proposal_id = proposal["proposal_id"]
        if (proposal["turn_id"] != turn["turn_id"]
                or proposal["context_snapshot_id"] != context_id
                or proposal_id in proposal_ids
                or outcome["proposal_id"] != proposal_id
                or outcome.get("operation_kind") != kind):
            raise ValueError("journal proposal identity mismatch")
        proposal_ids.add(proposal_id)
        if record["admission"] == "ADMITTED":
            if (record["reason_code"] != "POLICY_READ_ONLY"
                    or kind == "inspect_goal_status"
                    or (kind == "lookup_raw_evidence" and not policy.permits(args["event_ids"]))):
                raise ValueError("journal admission outside source policy")
        if outcome["status"] != "COMPLETED":
            if "result" in outcome:
                raise ValueError("rejected outcome contains result")
            continue
        if outcome["reason_code"] != "VERIFIED_SERVICE_READ":
            raise ValueError("invalid completed service outcome")
        result = outcome["result"]
        if kind in ("lookup_raw_evidence", "inspect_latest_observation"):
            if result["kind"] != "verified_raw_evidence":
                raise ValueError("invalid Raw evidence kind")
        elif kind == "retrieve_memory":
            if (result["kind"] != "working_world_memory_search"
                    or result["memory_enabled"] is not context["memory_enabled"]
                    or result["returned"] != len(result["records"])
                    or len(result["records"]) > args["top_k"]):
                raise ValueError("invalid Retrieval result")
        policy.check_result(kind, args, result)
        policy.record_completed(kind, result)
        verify_exposed()


def _verify_native_chain(fixture, scenario=None, *, required=False):
    """Bind native call evidence to its service journal, without inference.

    Historical generic/stub fixtures have no native-call contract. Do not
    interpret their opaque recorded requests as proof of model causality.
    """
    turn, trace = fixture["turn"], fixture["trace"]
    calls = fixture["model_calls"]
    projection = turn.get("claim_projection", {}).get("call")
    research = [call for call in calls if call.get("phase", "research") == "research"]
    projections = [call for call in calls if call.get("phase") == "claim_projection"]
    if (len(research) + len(projections) != len(calls)
            or projections != ([] if projection is None else [projection])
            or calls != research + projections):
        raise ValueError("invalid model call phase correspondence")
    # Older archives lack the additive diagnostic. When present it must
    # agree with the actual wire response, including rejected calls.
    for call in calls:
        if "termination_status" not in call:
            continue
        raw = call.get("raw_response")
        choices = raw.get("choices") if type(raw) is dict else None
        if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
            raise ValueError("terminal diagnostic lacks wire choice")
        reason = choices[0].get("finish_reason")
        if (call.get("finish_reason") != reason
                or call["termination_status"] != classify_termination(reason, wire="chat_completion")):
            raise ValueError("terminal diagnostic mismatch")
    native = required or any(call.get("profile") == "native" for call in research)
    if not native:
        return
    if any(call.get("profile") != "native" for call in research):
        raise ValueError("mixed or missing native call profile")
    if not research and (trace or turn["status"] == "STOPPED"):
        raise ValueError("missing native research calls")
    if "model_calls_used" in turn and turn["model_calls_used"] != len(research):
        raise ValueError("research call count mismatch")
    if "resource_budget" in turn and turn["resource_budget"]["reserved_calls"] != len(calls):
        raise ValueError("reserved call count mismatch")
    result = fixture.get("result")
    if result is not None:
        if (result["model_calls"] != len(research)
                or result["turn_status"] != turn["status"]
                or result.get("total_model_calls", len(calls)) != len(calls)):
            raise ValueError("case result call count/status mismatch")

    matched = set()
    last_step = -1
    terminal_unadmitted = False
    seen_wire_ids = set()
    initial_messages = None
    for index, call in enumerate(research):
        step = call["step_index"]
        if (call["turn_id"] != turn["turn_id"]
                or call["context_snapshot_id"] != turn["context_snapshot_id"]
                or type(call["model_call_index"]) is not int
                or call["model_call_index"] != index
                or type(step) is not int or step < 0 or step > len(trace)
                or step < last_step or step > last_step + 1):
            raise ValueError("native call identity or step mismatch")
        last_step = step
        messages = call["request"]["messages"]
        if (type(messages) is not list or len(messages) < 2
                or messages[0]["role"] != "system" or messages[1]["role"] != "user"):
            raise ValueError("invalid native request context")
        if initial_messages is None:
            initial_messages = messages[:2]
        elif canonical(messages[:2]) != canonical(initial_messages):
            raise ValueError("native initial context changed")
        prompt = strict_json(messages[1]["content"])
        if (type(prompt["memory_enabled"]) is not bool
                or (scenario is not None and "enabled" in scenario
                    and prompt["memory_enabled"] is not scenario["enabled"])
                or (trace and prompt["memory_enabled"]
                    is not trace[0]["context_snapshot"]["memory_enabled"])
                or (scenario is not None and "task" in scenario
                    and prompt["task"] != scenario["task"])):
            raise ValueError("native prompt scenario mismatch")
        record = trace[step] if step < len(trace) else None
        proposal = call.get("proposal")
        if type(call["valid"]) is not bool or type(call["transport_ok"]) is not bool:
            raise ValueError("invalid native call flags")
        if call["valid"]:
            if not call["transport_ok"]:
                raise ValueError("valid call without transport success")
            choices = call["raw_response"]["choices"]
            if type(choices) is not list or len(choices) != 1:
                raise ValueError("invalid native response choices")
            choice = choices[0]
            message = choice["message"]
            finish = choice["finish_reason"]
            if message["role"] != "assistant" or finish != call["finish_reason"]:
                raise ValueError("native wire terminal mismatch")
            wire_calls = message.get("tool_calls", [])
            if proposal is not None:
                if (classify_termination(finish, wire="chat_completion") != "TOOL_CALL_COMPLETE"
                        or type(wire_calls) is not list
                        or len(wire_calls) != 1):
                    raise ValueError("native proposal lacks complete wire call")
                wire = wire_calls[0]
                fn = wire["function"]
                wire_id = wire["id"]
                if (wire["type"] != "function" or wire_id != call["tool_call_id"]
                        or not isinstance(wire_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", wire_id)
                        or wire_id in seen_wire_ids):
                    raise ValueError("native wire identity mismatch")
                seen_wire_ids.add(wire_id)
                # Reuse the native registry and original bounds-before-dedup
                # decoder rather than inventing a second normalization rule.
                names = {item["function"]["name"] for item in call["request"]["tools"]}
                temporal = call["temporal"]
                compact = call["compact_temporal"]
                sets = call["canonical_sets"]
                if any(type(flag) is not bool for flag in (temporal, compact, sets)):
                    raise ValueError("invalid native profile flags")
                catalog = NativeToolCatalog(
                    lab_registry(temporal=temporal, compact_temporal=compact,
                                 latest_observation="inspect_latest_observation" in names),
                    set_arguments={("lookup_raw_evidence", "1"): ("event_ids",)} if sets else None,
                )
                if canonical(call["request"]["tools"]) != canonical(catalog.definitions()):
                    raise ValueError("native advertised tool catalog mismatch")
                descriptor, arguments = catalog.decode(fn["name"], fn["arguments"])
                typed = CognitiveStepProposal(proposal).as_dict()
                original = strict_json(fn["arguments"])
                if (typed["turn_id"] != turn["turn_id"]
                        or typed["context_snapshot_id"] != turn["context_snapshot_id"]
                        or typed["proposal_id"] != f'pr_{turn["turn_id"]}_{step}'
                        or typed["operation_kind"] != descriptor.name
                        or call["tool_name"] != descriptor.name
                        or canonical(typed["arguments"]) != canonical(arguments)
                        or canonical(call["arguments"]) != canonical(arguments)
                        or canonical(call["original_arguments"]) != canonical(original)
                        or call["arguments_normalized"] is not (original != arguments)):
                    raise ValueError("native wire/proposal arguments mismatch")
                if record is not None and record["proposal"] == typed and step not in matched:
                    matched.add(step)
                elif (index == len(research) - 1 and record is None
                        and turn["status"] == "STEP_BUDGET_EXHAUSTED"
                        and turn.get("resource_budget", {}).get("stop_reason") in (
                            "USAGE_UNAVAILABLE", "OUTPUT_USAGE_EXCEEDED",
                            "INPUT_USAGE_EXCEEDED", "ELAPSED_LIMIT")):
                    terminal_unadmitted = True
                elif (index == len(research) - 1 and record is not None
                        and record["proposal"] is None and record["admission"] == "REJECTED"
                        and record["reason_code"] == "STALE_CONTEXT"):
                    matched.add(step)
                else:
                    raise ValueError("native proposal not bound to journal")
            elif (classify_termination(finish, wire="chat_completion") != "TEXT_COMPLETE"
                  or wire_calls or type(message.get("content")) is not str
                  or not message["content"].strip()
                  or call.get("final_text") != message["content"]):
                raise ValueError("native stop response mismatch")
        elif proposal is not None:
            raise ValueError("invalid native call contains admitted proposal")
    if any(record["proposal"] is not None and i not in matched
           for i, record in enumerate(trace)):
        raise ValueError("journal proposal without native call")
    if turn["status"] == "STOPPED" and (not research or not research[-1]["valid"]
            or research[-1].get("proposal") is not None
            or classify_termination(research[-1].get("finish_reason"), wire="chat_completion") != "TEXT_COMPLETE"
            or terminal_unadmitted):
        raise ValueError("stopped turn lacks native terminal response")
    if projection is not None:
        if (projection["turn_id"] != turn["turn_id"]
                or projection["context_snapshot_id"] != turn["context_snapshot_id"]
                or projection["model_call_index"] != len(research)
                or turn["status"] != "STOPPED"
                or projection.get("proposal") is not None
                or "tools" in projection["request"]):
            raise ValueError("claim projection identity mismatch")


def verify_case(fixture, raw_fixture, *, scenario=None, require_native=False,
                require_cognitive_result=False, variant=None):
    if fixture["schema"] != SCHEMA or fixture["world_seed"] != raw_fixture["world_seed"]:
        raise ValueError("case fixture scope mismatch")
    expected = [freeze_call(call, raw_fixture["aliases"], i)
                for i, call in enumerate(fixture["model_calls"])]
    if fixture["requests"] != expected:
        raise ValueError("request/response fixture mismatch")
    rows = {r["event_id"]: r for r in raw_fixture["samples"]}
    if [r["outcome"] for r in fixture["trace"]] != fixture["turn"]["outcomes"]:
        raise ValueError("journal/turn outcome mismatch")
    try:
        _verify_journal_scope(fixture, rows)
        if scenario is not None and "enabled" in scenario and fixture["trace"]:
            if fixture["trace"][0]["context_snapshot"]["memory_enabled"] is not scenario["enabled"]:
                raise ValueError("journal scenario memory mode mismatch")
        _verify_native_chain(fixture, scenario, required=require_native)
    except (E25CognitionError, KeyError, TypeError) as exc:
        raise ValueError("journal source policy mismatch") from exc
    for record in fixture["trace"]:
        outcome = record["outcome"]
        if outcome["status"] != "COMPLETED" or outcome["operation_kind"] not in (
                "lookup_raw_evidence", "inspect_latest_observation"):
            continue
        for source in outcome["result"]["records"]:
            if source["status"] != "verified_source_view":
                continue
            row = rows[source["event_id"]]
            raw = json.loads(row["raw_json"])
            if (source["sample_id"] != row["sample_id"]
                    or source["raw_sha256"] != row["raw_sha256"]
                    or source["source_ref"] != row["source_ref"]
                    or source["sample_seq"] != raw["sample_seq"]
                    or source["coverage"] != raw["coverage"]
                    or source["entities_observed"] != [r["entity_ref"] for r in raw["readings"]]):
                raise ValueError("journal source differs from canonical Raw")
    aggregate = fixture.get("result")
    if require_cognitive_result or (type(aggregate) is dict and "cognitive_result" in aggregate):
        from .e26_result_verification import verify_exported_result
        verify_raw(raw_fixture)
        verify_exported_result(fixture, raw_fixture, scenario=scenario, variant=variant,
                               required=require_cognitive_result)
    return len(expected)


def seal_bundle(root, manifest, *, complete):
    root = Path(root)
    write_json(root / "manifest.json", {**manifest, "complete": complete})
    files = sorted(root.glob("*.json"))
    write_json(root / "checksums.json", {p.name: file_digest(p) for p in files})


def verify_bundle(root):
    root = Path(root)
    index = read_json(root / "checksums.json")
    actual = {p.name for p in root.iterdir() if p.name != "checksums.json"}
    if set(index) != actual or any(Path(name).name != name for name in index):
        raise ValueError("evidence file set mismatch")
    for name, sha in index.items():
        p = root / name
        if not p.is_file() or p.is_symlink() or file_digest(p) != sha:
            raise ValueError("evidence checksum mismatch: " + name)
    manifest = read_json(root / "manifest.json")
    if (manifest["schema"] != SCHEMA or manifest["complete"] is not True
            or not re.fullmatch(r"[0-9a-f]{40}", manifest["git_sha"])
            or not manifest["world_seeds"] or not manifest["scenarios"]):
        raise ValueError("incomplete experiment evidence")
    seeds = manifest["world_seeds"]
    scenarios = manifest["scenarios"]
    if (type(seeds) is not list or any(type(seed) is not int for seed in seeds)
            or len(set(seeds)) != len(seeds)
            or type(scenarios) is not list
            or any(type(c) is not dict or type(c.get("id")) is not str
                   or not re.fullmatch(r"C[0-9]{2}(?:_OFF|_ALT)?", c["id"])
                   for c in scenarios)
            or len({c["id"] for c in scenarios}) != len(scenarios)):
        raise ValueError("invalid or duplicate manifest experiment identity")
    result_schema = manifest.get("cognitive_result_schema")
    if result_schema is not None:
        from ..cognition.cognitive_result import SCHEMA as RESULT_SCHEMA
        if result_schema != RESULT_SCHEMA:
            raise ValueError("unsupported cognitive result schema")
    expected_cases = {(seed, c["id"]) for seed in manifest["world_seeds"]
                      for c in manifest["scenarios"]}
    scenario_by_id = {c["id"]: c for c in scenarios}
    if any("enabled" in c and type(c["enabled"]) is not bool for c in scenarios):
        raise ValueError("invalid scenario memory mode")
    expected_names = ({"manifest.json"} | {f"raw-seed-{seed}.json" for seed in seeds}
                      | {f"case-{seed}-{case}.json" for seed, case in expected_cases})
    if set(index) != expected_names:
        raise ValueError("unexpected or missing declared evidence members")
    raw = {seed: read_json(root / f"raw-seed-{seed}.json") for seed in manifest["world_seeds"]}
    if any(fixture["world_seed"] != seed for seed, fixture in raw.items()):
        raise ValueError("Raw fixture seed mismatch")
    count = sum(verify_raw(fixture) for fixture in raw.values())
    requests = 0
    actual_cases = set()
    for path in root.glob("case-*.json"):
        fixture = read_json(path)
        key = (fixture["world_seed"], fixture["case"])
        if key in actual_cases or path.name != f"case-{key[0]}-{key[1]}.json":
            raise ValueError("duplicate or mismatched case fixture")
        actual_cases.add(key)
        if key not in expected_cases:
            raise ValueError("unexpected case identity")
        requests += verify_case(fixture, raw[key[0]], scenario=scenario_by_id[key[1]],
                                require_native="variant" in manifest or fixture.get("result") is not None,
                                require_cognitive_result=result_schema is not None,
                                variant=manifest.get("variant"))
    if expected_cases != actual_cases:
        raise ValueError("missing or unexpected case fixtures")
    return {"status": "E26_EVIDENCE_VERIFIED", "git_sha": manifest["git_sha"],
            "raw_samples": count, "cases": len(actual_cases), "requests": requests,
            "scope": "integrity_and_source_binding_not_backend_attestation"}


def replay_request(root, *, seed, case_id, index, transport):
    if (type(seed) is not int or seed not in (7, 8)
            or type(case_id) is not str or not re.fullmatch(r"C[0-9]{2}(?:_OFF|_ALT)?", case_id)
            or type(index) is not int or index < 0):
        raise ValueError("invalid replay identity or request index")
    verify_bundle(root)
    fixture = read_json(Path(root) / f"case-{seed}-{case_id}.json")
    if index >= len(fixture["requests"]):
        raise ValueError("invalid request index")
    request = fixture["requests"][index]
    if request["index"] != index:
        raise ValueError("invalid request index")
    payload = json.loads(request["request_json"])
    if canonical(payload) != request["request_json"]:
        raise ValueError("noncanonical request")
    response = transport.complete(payload)
    response_json = canonical(response)
    original = json.loads(request["response_json"]) if request["response_json"] is not None else None
    def choices(value):
        return value.get("choices") if isinstance(value, dict) else None
    return {"schema": SCHEMA, "mode": "EXACT_REQUEST_REPLAY_NO_SERVICE_DISPATCH",
            "world_seed": seed, "case": case_id, "index": index,
            "request_sha256": request["request_sha256"],
            "original_response_sha256": request["response_sha256"],
            "replay_response_sha256": digest(response_json), "replay_response_json": response_json,
            "response_exact_equal": response_json == request["response_json"],
            "choices_equal": original is not None and choices(original) is not None
                             and choices(original) == choices(response),
            "tool_dispatch_performed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("bundle", type=Path)
    replay = sub.add_parser("replay")
    replay.add_argument("bundle", type=Path)
    replay.add_argument("--seed", type=int, choices=(7, 8), required=True)
    replay.add_argument("--case", required=True, choices=("C01","C02","C03","C06","C09","C02_OFF","C03_ALT"))
    replay.add_argument("--index", type=int, required=True)
    replay.add_argument("--base-url", default="http://127.0.0.1:8085")
    replay.add_argument("--backend-pid", type=int, required=True)
    replay.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "verify":
        print(canonical(verify_bundle(args.bundle)))
        return
    if args.output.resolve().is_relative_to(args.bundle.resolve()):
        parser.error("replay output must be outside frozen evidence")
    if args.output.exists():
        parser.error("replay output already exists")
    backend = backend_snapshot(args.backend_pid)
    original = read_json(args.bundle / "manifest.json")["backend"]
    result = replay_request(args.bundle, seed=args.seed, case_id=args.case, index=args.index,
                            transport=LoopbackChatTransport(args.base_url))
    result["backend"] = backend
    result["backend_executable_and_argv_equal"] = all(
        backend[key] == original[key] for key in ("executable_sha256", "argv"))
    result["backend_process_unchanged"] = backend_snapshot(args.backend_pid) == backend
    write_json(args.output, result)
    print(canonical({k: v for k,v in result.items() if k != "replay_response_json"}))


if __name__ == "__main__":
    main()
