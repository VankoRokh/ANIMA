"""R9.4.1a isolated offline H/Q/I/T-recorded controls. No policy authority.

Output directories are exclusive. Originals, generated inputs, maps and first
divergence are retained; an unmatched generated request NEVER receives an
archived response. ID arms are single-request and have no service dispatch.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import time
from unittest.mock import patch

from anima.agent.generation_termination import classify_termination
from anima.agent.native_tools import canonical
from . import e26_reproducibility as frozen
from ..cognition.cognitive_result import build_cognitive_result, _bound_records, _project_result
from ..cognition.claim_verification import ObservationClaimVerifier, _verify_captured_claim
from ..cognition.coordinator import E25LabCognitiveCoordinator
from ..cognition.host_temporal_projection import project_temporal_claims
from ..cognition.native_lab import NativeLabAdapter
from ..cognition.resource_budget import ResourceLimits

SCHEMA = "anima.lab.r941_experiment/0.1"


def _sha(value):
    return frozen.digest(canonical(value))


def _new_output(path):
    path = Path(path).resolve()
    if path == frozen.ROOT or frozen.ROOT in path.parents:
        raise ValueError("experimental output must be outside repository")
    path.mkdir(parents=True, exist_ok=False)
    return path


def _tool_bindings(request):
    declarations, replies = set(), set()
    for message in request.get("messages", []):
        for call in message.get("tool_calls", []):
            ident = call.get("id")
            if message.get("role") != "assistant" or type(ident) is not str or not ident or ident in declarations:
                raise ValueError("duplicate/invalid native tool binding")
            declarations.add(ident)
        if message.get("role") == "tool":
            ident = message.get("tool_call_id")
            if ident not in declarations or ident in replies:
                raise ValueError("stale/mismatched native tool binding")
            replies.add(ident)
    if declarations != replies:
        raise ValueError("unresolved native tool binding")
    return declarations


def _json_spans(text):
    """JSON leaf spans, preserving whitespace, key order and all other bytes."""
    decoder, leaves = json.JSONDecoder(), []
    def ws(i):
        while i < len(text) and text[i].isspace():
            i += 1
        return i
    def parse(i, path):
        i = ws(i)
        if text[i] == '{':
            i = ws(i + 1)
            seen = set()
            while text[i] != '}':
                key, j = decoder.raw_decode(text, i)
                if type(key) is not str or key in seen:
                    raise ValueError("duplicate/invalid JSON key")
                seen.add(key)
                j = ws(j)
                if text[j] != ':':
                    raise ValueError("JSON colon required")
                i = ws(parse(j + 1, path + (key,)))
                if text[i] == ',':
                    i = ws(i + 1)
                elif text[i] != '}':
                    raise ValueError("JSON delimiter required")
            return i + 1
        if text[i] == '[':
            i, n = ws(i + 1), 0
            while text[i] != ']':
                i, n = ws(parse(i, path + (n,))), n + 1
                if text[i] == ',':
                    i = ws(i + 1)
                elif text[i] != ']':
                    raise ValueError("JSON delimiter required")
            return i + 1
        value, end = decoder.raw_decode(text, i)
        leaves.append((path, i, end, value))
        return end
    if not text.strip():
        raise ValueError("empty JSON")
    end = parse(0, ())
    if ws(end) != len(text):
        raise ValueError("trailing JSON")
    return leaves


def id_variant(request, arm, mapping, *, known_ids=None):
    """Rename only typed occurrences. Unsupported opaque locations fail closed.

    Event IDs must be checked source bindings supplied by the caller. Turn IDs
    must be the checked turn identity. No Raw, journal, hashes or prose rewrite.
    """
    if arm not in ("I-event", "I-turn", "I-tool"):
        raise ValueError("unknown ID arm")
    if (type(mapping) is not dict or not mapping or len(set(mapping.values())) != len(mapping)
            or any(type(k) is not str or type(v) is not str or not k or not v or k == v for k,v in mapping.items())
            or set(mapping) & set(mapping.values())):
        raise ValueError("nontrivial disjoint bijection required; collision")
    tool_ids = _tool_bindings(request)
    if arm == "I-tool" and set(mapping) != tool_ids:
        raise ValueError("complete native tool binding mapping required")
    if arm != "I-tool" and (known_ids is None or not set(mapping) <= set(known_ids)):
        raise ValueError("unknown source/turn binding")
    fields = {"I-event": {"event_id", "event_ids", "last_seen_event_id", "last_event_id", "previous_event_id", "current_event_id", "evidence_event_ids"},
              "I-turn": {"turn_id"}, "I-tool": {"tool_call_id"}}[arm]
    found, changed = set(), []
    def typed(path):
        names = [p for p in path if type(p) is str]
        key = names[-1] if names else ""
        if arm == "I-tool" and key == "id" and "tool_calls" in names:
            return True
        return key in fields
    def transform(obj, path=()):
        if isinstance(obj, dict):
            return {k: transform(v, path + (k,)) for k,v in obj.items()}
        if isinstance(obj, list):
            return [transform(v, path + (i,)) for i,v in enumerate(obj)]
        if type(obj) is not str:
            return obj
        if typed(path):
            if obj not in mapping:
                raise ValueError("incomplete ID mapping")
            found.add(obj)
            changed.append(list(path))
            return mapping[obj]
        if path and path[-1] in ("content", "arguments"):
            try:
                spans = _json_spans(obj)
            except (ValueError, IndexError, json.JSONDecodeError):
                # Plain prose is never rewritten or used as equivalence proof.
                return obj
            edits = []
            for leaf_path, start, end, value in spans:
                new = transform(value, path + ("$json",) + leaf_path)
                if new != value:
                    edits.append((start, end, json.dumps(new, ensure_ascii=False)))
            for start, end, value in reversed(edits):
                obj = obj[:start] + value + obj[end:]
            return obj
        suffixes = {"I-event":("event_id","event_ids"), "I-turn":("turn_id",), "I-tool":("tool_call_id",)}[arm]
        if path and type(path[-1]) is str and path[-1].endswith(suffixes):
            raise ValueError("unsupported untyped ID field")
        return obj
    variant = transform(deepcopy(request))
    if found != set(mapping):
        raise ValueError("mapping contains unused/untyped ID occurrences")
    # Reverse transformation proves preservation of every non-ID byte/field.
    # The same transformer with inverse values is applied to the exact variant.
    original_mapping = mapping
    mapping = {v:k for k,v in mapping.items()}
    changed_before = deepcopy(changed)
    restored = transform(deepcopy(variant))
    if restored != request:
        raise ValueError("ID diff allowlist violation")
    return {"schema": SCHEMA, "arm": arm, "policy": "BIJECTIVE_RENAME", "request": variant,
            "original_request": deepcopy(request), "mapping": deepcopy(original_mapping),
            "inverse_mapping": deepcopy(mapping), "mapping_sha256": _sha(original_mapping),
            "original_sha256": _sha(request), "variant_sha256": _sha(variant),
            "changed_paths": changed_before, "tool_dispatch_performed": False}


def _response_view(response):
    choices = response.get("choices", []) if type(response) is dict else []
    return [{"finish": classify_termination(c.get("finish_reason"), wire="chat_completion"),
             "finish_reason": c.get("finish_reason"), "message": deepcopy(c.get("message"))}
            for c in choices if type(c) is dict]


def response_signature(response, *, inverse_mapping=None, arm=None):
    """Parsed operation/argument/content comparison; prose remains byte exact."""
    inverse = inverse_mapping or {}
    event_fields = {"event_id", "event_ids", "last_seen_event_id", "evidence_event_ids"}
    def mapped(obj, key=""):
        if isinstance(obj, dict):
            return {k:mapped(v,k) for k,v in obj.items()}
        if isinstance(obj, list):
            return [mapped(v,key) for v in obj]
        if type(obj) is str and ((arm == "I-event" and key in event_fields)
                                 or (arm == "I-turn" and key == "turn_id")):
            return inverse.get(obj,obj)
        return obj
    choices = []
    for choice in response.get("choices",[]):
        message = choice.get("message",{})
        operations = []
        for call in message.get("tool_calls",[]):
            function = call.get("function",{})
            arguments = function.get("arguments")
            try:
                arguments = json.loads(arguments)
                arguments_status = "PARSED_JSON"
            except (ValueError, TypeError):
                arguments_status = "UNPARSED"
            operations.append({"name":function.get("name"),"arguments":mapped(arguments),
                               "arguments_status":arguments_status})
        content = message.get("content")
        content_format = "EXACT_TEXT"
        try:
            from ..cognition.model_claims import parse_final
            structured = parse_final(content)
            content = mapped(structured)
            content_format = "TYPED_CLAIMS_JSON"
        except (ValueError, TypeError, KeyError, UnicodeError):
            pass
        choices.append({"finish_reason":choice.get("finish_reason"),
                        "termination":classify_termination(choice.get("finish_reason"),wire="chat_completion"),
                        "operations":operations,"content":content,"content_format":content_format,
                        "reasoning_content":message.get("reasoning_content")})
    return choices


def compare_id_responses(original, variant, arm, mapping):
    left = response_signature(original)
    right = response_signature(variant,inverse_mapping={v:k for k,v in mapping.items()},arm=arm)
    return {"original_response_sha256":_sha(original),"variant_response_sha256":_sha(variant),
            "response_exact_equal":original == variant,"choices_equal":original.get("choices") == variant.get("choices"),
            "parsed_original":left,"parsed_variant_inverse_mapped":right,
            "parsed_operations_content_equal":left == right,
            "free_text_comparison":"EXACT_PRESERVE_NO_PROSE_RENAMING",
            "new_tool_ids":"RETAINED_IN_ORIGINAL_RESPONSES_NOT_OPERATION_SIGNATURE"}


def repeat_request(request, transport, *, repetitions=20, output, original_response=None):
    if type(repetitions) is not int or not 1 <= repetitions <= 1000:
        raise ValueError("bounded repetitions required")
    _tool_bindings(request)
    root = _new_output(output)
    frozen.write_json(root / "request.json", request)
    if original_response is not None:
        frozen.write_json(root / "original-response.json", original_response)
    samples, reference = [], original_response
    for index in range(repetitions):
        started = time.monotonic_ns()
        record = {"index": index, "started_monotonic_ns": started, "request_sha256": _sha(request)}
        try:
            response = transport.complete(deepcopy(request))
            frozen.write_json(root / f"response-{index:04d}.json", response)
            if reference is None:
                reference = response
            record.update(status="RECEIVED", response_sha256=_sha(response),
                          response_exact_equal=response == reference,
                          choices_equal=response.get("choices") == reference.get("choices"),
                          parsed=_response_view(response), usage=deepcopy(response.get("usage")))
        except Exception as error:
            record.update(status="TRANSPORT_FAILED", error_type=type(error).__name__)
            # No retry or fabricated response; remaining repetitions stop.
            samples.append(record)
            frozen.write_json(root / f"sample-{index:04d}.json", record)
            break
        record["latency_ms"] = (time.monotonic_ns() - started) / 1e6
        samples.append(record)
        frozen.write_json(root / f"sample-{index:04d}.json", record)
    result = {"schema": SCHEMA, "arm":"Q", "policy":"EXACT_PRESERVE",
              "tool_dispatch_performed":False, "repetitions":samples, "requested_repetitions":repetitions,
              "first_divergence":next(({"index":s["index"],"status":s["status"],
                   "kind":"RESPONSE_SHA_MISMATCH" if s["status"] == "RECEIVED" else "TRANSPORT_FAILED"}
                   for s in samples if s["status"] != "RECEIVED" or not s["response_exact_equal"]),None)}
    frozen.write_json(root / "summary.json", result)
    return result


@contextmanager
def verification_cost(memory):
    """Serial offline instrumentation. Nested context checks are disjoint.

    Count successful public Raw rereads and integrity rows/bytes separately.
    Never sum nested elapsed times as a total. Restore even after exceptions.
    """
    costs, stack = {}, ["result_construction"]
    saved = {name: memory.__dict__.get(name) for name in ("raw_evidence", "context_for_cognition", "_verify_row")}
    originals = {name:getattr(memory, name) for name in saved}
    def bucket():
        return costs.setdefault(stack[-1], {"raw_rereads":0, "known_raw_bytes":0,
            "failed_rereads":0, "raw_rows_checked":0, "integrity_raw_bytes":0})
    def raw(sample):
        item = bucket()
        item["raw_rereads"] += 1
        try:
            result = originals["raw_evidence"](sample)
            item["known_raw_bytes"] += len(result.canonical_json.encode())
            return result
        except Exception:
            item["failed_rereads"] += 1
            raise
    def context(*args, **kwargs):
        stack.append("context_integrity")
        try:
            return originals["context_for_cognition"](*args, **kwargs)
        finally:
            stack.pop()
    def row(record, binding):
        item = bucket()
        item["raw_rows_checked"] += 1
        item["integrity_raw_bytes"] += len(record["raw_json"].encode())
        return originals["_verify_row"](record, binding)
    memory.raw_evidence, memory.context_for_cognition, memory._verify_row = raw, context, row
    try:
        yield costs, stack
    finally:
        for name, value in saved.items():
            if value is None:
                delattr(memory, name)
            else:
                setattr(memory, name, value)


def host_pair(coordinator, report, requirement, *, calls=()):
    records = _bound_records(coordinator, report)
    before = _sha([report, records, list(calls)])
    arms = {}
    for arm in ("H0", "H1"):
        with verification_cost(coordinator._memory) as (costs, phases):
            result = build_cognitive_result(coordinator, deepcopy(report), requirement=requirement, research_calls=deepcopy(calls))
            host = None
            if arm == "H1":
                phases[-1] = "host_projection"
                host = project_temporal_claims(coordinator, requirement, deepcopy(report))
        arms[arm] = {"result":result,"host":host,"cost":costs}
    if _sha([report, coordinator.decision_records(report["turn_id"]), list(calls)]) != before:
        raise ValueError("Host pair changed research inputs")
    if arms["H0"]["result"] != arms["H1"]["result"]:
        raise ValueError("unmatched Host pair")
    return {"schema":SCHEMA, "arm":"H0/H1", "checked_research_sha256":before,
            "journal_sha256":_sha(records), **arms}


class ReplayDivergence(BaseException):
    """Offline control signal bypassing the coordinator's adapter-error handler."""


class RecordedTransport:
    wire_protocol = "chat_completion"

    def __init__(self, calls, *, output, before_request=None):
        self.calls = deepcopy(calls)
        self.output = _new_output(output)
        self.index, self.first_divergence = 0, None
        self.before_request = before_request
        frozen.write_json(self.output / "original-calls.json", self.calls)

    def fail(self, kind, **detail):
        if self.first_divergence is None:
            self.first_divergence = {"kind":kind,"request_index":self.index,**detail}
            frozen.write_json(self.output / "first-divergence.json", self.first_divergence)
        raise ReplayDivergence(kind)

    def complete(self, payload):
        if self.first_divergence is not None:
            raise ReplayDivergence("replay already stopped")
        frozen.write_json(self.output / f"generated-request-{self.index:04d}.json", payload)
        if self.before_request:
            self.before_request()
        if self.index >= len(self.calls):
            self.fail("EXTRA_GENERATED_REQUEST", generated_sha256=_sha(payload))
        archived = self.calls[self.index]
        if _sha(payload) != _sha(archived["request"]):
            self.fail("REQUEST_SHA_MISMATCH", generated_sha256=_sha(payload), original_sha256=_sha(archived["request"]))
        if archived.get("raw_response") is None:
            self.fail("UNSUPPORTED_MISSING_RESPONSE")
        response = deepcopy(archived["raw_response"])
        frozen.write_json(self.output / f"delivered-response-{self.index:04d}.json", response)
        self.index += 1
        return response


def rebuild_raw(raw, destination):
    """Rebuild NEW isolated Core/derived stores; never import a Decision Journal.

    Only verified three-sample E26 snapshots are supported. The local ingress
    UUID factory is fixed during each isolated admission to preserve source IDs.
    This is offline restoration, not a permission to alter canonical sources.
    """
    from anima.core.assembly import build_core
    from .e24_working_memory import E24WorkingMemory, SOURCE, SUBJECT, PREDICATE, vision_source_registration, vision_digest_rule
    from .egocentric import E23ObserverPort, EgocentricView
    frozen.verify_raw(raw)
    destination = _new_output(destination)
    core = build_core(destination, sources={SOURCE:vision_source_registration()},
                      properties={(SUBJECT,PREDICATE):vision_digest_rule()})
    memory = E24WorkingMemory(core, E23ObserverPort(port=46029, observer_key="x" * 43))
    for sample in raw["samples"]:
        if not sample["event_id"].startswith("ev_"):
            raise ValueError("unsupported archived Event ID format")
        view = EgocentricView(json.loads(sample["raw_json"]))
        memory._capture(view)
        with patch("anima.core.ingress.uuid4", return_value=sample["event_id"][3:]):
            memory.recover()
        actual = memory.raw_evidence(sample["sample_id"])
        if actual.canonical_json != sample["raw_json"]:
            raise ValueError("isolated Raw reconstruction mismatch")
    return memory


def _stable(value):
    # Only known runtime duration diagnostics are excluded. Budgets, verdicts,
    # flags, IDs, order and all terminal/content fields remain compared.
    if isinstance(value, dict):
        return {k:_stable(v) for k,v in value.items() if k not in ("latency_ms", "elapsed_ms")}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


def recorded_trajectory(fixture, raw, *, output, task, requirement, max_steps,
                        adapter_flags=None, coordinator_flags=None, resource_limits=None,
                        project_result_claims=False, host_profile=False, claim_phase=None):
    frozen.verify_case(fixture, raw)
    root = _new_output(output)
    frozen.write_json(root / "original-fixture.json", fixture)
    frozen.write_json(root / "original-raw.json", raw)
    memory = rebuild_raw(raw, root / "stores")
    coordinator = E25LabCognitiveCoordinator(memory, max_steps=max_steps, **(coordinator_flags or {}))
    original = fixture["turn"]
    readonly_before = {"events":_sha(memory._core.event_log.load_events()),
                       "memory_count":memory._core.memory_store.count()}
    turn = original["turn_id"]
    def check_prefix():
        records = coordinator.decision_records(turn)
        if records != fixture["trace"][:len(records)]:
            for i, record in enumerate(records):
                if i >= len(fixture["trace"]) or record != fixture["trace"][i]:
                    transport.fail("JOURNAL_PREFIX_MISMATCH", operation_index=i, generated_record=record)
    transport = RecordedTransport(fixture["model_calls"], output=root / "transport", before_request=check_prefix)
    calls = fixture["model_calls"]
    adapter = NativeLabAdapter(base_url="http://127.0.0.1:8085", model=calls[0]["request"]["model"],
        trace_path=root / "generated-calls.jsonl", task=task, transport=transport, **(adapter_flags or {}))
    report = None
    try:
        report = coordinator.run_turn(adapter, turn_id=turn,
            memory_enabled=(fixture["trace"][0]["context_snapshot"]["memory_enabled"] if fixture["trace"] else True),
            completion_requirement=requirement, resource_limits=resource_limits or ResourceLimits(max_calls=max_steps),
            project_result_claims=project_result_claims)
        if host_profile:
            report["host_temporal_projection"] = project_temporal_claims(coordinator, requirement, report)
            report["claim_projection"] = {"status":"NOT_REQUESTED_HOST_PROFILE","call":None}
        check_prefix()
        readonly_after = {"events":_sha(memory._core.event_log.load_events()),
                          "memory_count":memory._core.memory_store.count()}
        if readonly_after != readonly_before or memory._core.core_execution is not None:
            transport.fail("READ_ONLY_INVARIANT_CHANGED")
        if transport.index != len(calls):
            transport.fail("MISSING_GENERATED_REQUESTS", expected=len(calls), actual=transport.index)
        if _stable(report) != _stable(original):
            transport.fail("TURN_OR_BUDGET_MISMATCH", generated=report)
        records = coordinator.decision_records(turn)
        if records != fixture["trace"]:
            transport.fail("JOURNAL_LENGTH_MISMATCH")
        result = build_cognitive_result(coordinator, report, requirement=requirement, research_calls=adapter.calls, claim_phase=claim_phase)
        if fixture.get("result") is not None:
            expected_result = fixture["result"].get("cognitive_result", fixture["result"])
        else:
            verifier = ObservationClaimVerifier(coordinator)
            expected_result = _project_result(original, fixture["trace"], requirement=requirement,
                research_calls=fixture["model_calls"], claim_phase=None,
                verify=lambda t,c: _verify_captured_claim(t,c,fixture["trace"],verifier._load_view),
                evaluate_claims=lambda c: None)
        if _stable(result) != _stable(expected_result):
            transport.fail("COGNITIVE_RESULT_MISMATCH", generated=result, expected=expected_result)
        frozen.write_json(root / "generated-result.json", result)
    except ReplayDivergence:
        pass
    records = coordinator.decision_records(turn)
    frozen.write_json(root / "generated-journal.json", records)
    frozen.write_json(root / "generated-turn.json", report)
    summary = {"schema":SCHEMA,"arm":"T-recorded","policy":"EXACT_PRESERVE",
               "status":"DIVERGED" if transport.first_divergence else "MATCHED",
               "matched_requests":transport.index,"first_divergence":transport.first_divergence,
               "journal_equal":records == fixture["trace"],
               "result_equal":transport.first_divergence is None,
               "runtime_timing":"DIAGNOSTIC_ONLY", "source_authority":"ISOLATED_SYNTHETIC_RESTORATION",
               "read_only_invariant_checked":report is not None}
    frozen.write_json(root / "summary.json", summary)
    return summary


def retrieval_metrics(candidates, relevance, *, available_relevant):
    """Evaluator-only pure consumer. No path back to policy/context."""
    relevant = [relevance.get(c) for c in candidates]
    complete = all(type(v) is bool for v in relevant)
    positives = sum(v is True for v in relevant)
    denominator = available_relevant
    return {"precision":positives/len(relevant) if relevant and complete else None,
            "recall":positives/denominator if denominator and complete else None,
            "recall_status":"NOT_ASSESSED" if denominator is None else "NOT_APPLICABLE" if denominator == 0 else "ASSESSED",
            "mrr":next((1/(i+1) for i,v in enumerate(relevant) if v), 0) if denominator and complete else None}


def prepare_manifest(bundle, *, output, baseline_sha):
    """Freeze selected requests and the order table WITHOUT contacting a model."""
    verification = frozen.verify_bundle(bundle)
    bundle = Path(bundle).resolve()
    import re
    if not re.fullmatch(r"[0-9a-f]{40}",baseline_sha):
        raise ValueError("full baseline SHA required")
    if Path(output).resolve() == bundle or bundle in Path(output).resolve().parents:
        raise ValueError("experimental output must be outside frozen bundle")
    root = _new_output(output)
    manifest = frozen.read_json(bundle / "manifest.json")
    scenarios = {s["id"]:s for s in manifest["scenarios"]}
    entries = []
    for case_path in sorted(bundle.glob("case-*.json")):
        fixture = frozen.read_json(case_path)
        seed, case = fixture["world_seed"], fixture["case"]
        raw = frozen.read_json(bundle / f"raw-seed-{seed}.json")
        all_source_ids = {r["event_id"] for r in raw["samples"]}
        selected = []
        # One frozen initial request per scenario for Q; the earliest request
        # carrying typed complete IDs per I arm (no prose/token substitution).
        for arm in ("Q", "I-event", "I-turn", "I-tool"):
            selection, unsupported = None, "NO_TYPED_IDS_IN_MODEL_VISIBLE_REQUEST"
            for i, call in enumerate(fixture["model_calls"]):
                if arm == "Q":
                    selection = {"arm":arm,"index":0,"policy":"EXACT_PRESERVE","request":fixture["model_calls"][0]["request"]}
                    break
                request = call["request"]
                if arm == "I-tool":
                    try:
                        ids = _tool_bindings(request)
                    except ValueError:
                        continue
                    known = ids
                else:
                    known = all_source_ids if arm == "I-event" else {fixture["turn"]["turn_id"]}
                    # Try the complete checked set; remove absent IDs only by
                    # testing typed occurrences, never by replacing substrings.
                    fields = ("event_id", "event_ids", "last_seen_event_id", "last_event_id", "previous_event_id", "current_event_id", "evidence_event_ids") if arm == "I-event" else ("turn_id",)
                    def collect(obj):
                        ids = set()
                        if isinstance(obj, dict):
                            for k,v in obj.items():
                                if k in fields:
                                    ids.update([v] if type(v) is str else v if type(v) is list else [])
                                elif k in ("content", "arguments") and type(v) is str:
                                    try:
                                        ids.update(collect(json.loads(v)))
                                    except ValueError:
                                        pass
                                else:
                                    ids.update(collect(v))
                        elif isinstance(obj, list):
                            for v in obj:
                                ids.update(collect(v))
                        return ids
                    ids = collect(request)
                if not ids:
                    continue
                mapping = {ident:("ev_r941_" if arm == "I-event" else "r941_turn_" if arm == "I-turn" else "r941_tool_") + str(n) for n,ident in enumerate(sorted(ids),1)}
                try:
                    selection = {"index":i, **id_variant(request, arm, mapping, known_ids=known)}
                except ValueError as error:
                    unsupported = str(error)
                    continue
                break
            if selection:
                path = f"{seed}-{case}-{arm}.json"
                frozen.write_json(root / path, selection)
                selected.append({"arm":arm,"status":"PREPARED","fixture":path,"fixture_sha256":frozen.file_digest(root/path),
                                 "index":selection["index"], "request_sha256":_sha(selection["request"])})
            else:
                selected.append({"arm":arm,"status":"UNSUPPORTED","reason_code":unsupported})
        entries.append({"seed":seed,"case":case,"case_path":str(case_path),"case_sha256":frozen.file_digest(case_path),
                        "raw_path":str(bundle/f"raw-seed-{seed}.json"),"raw_sha256":frozen.file_digest(bundle/f"raw-seed-{seed}.json"),
                        "scenario":scenarios[case], "arms":selected})
    result = {"schema":SCHEMA,"stage":"R9.4.1b","status":"PREPARED_NOT_RUN","baseline_sha":baseline_sha,
        "bundle":str(bundle),"bundle_verification":verification,"archived_manifest":manifest,
        "bundle_files":{p.name:frozen.file_digest(p) for p in sorted(bundle.iterdir()) if p.is_file()},
        "repetitions":20,"concurrency":1,"one_outstanding_request":True,
        "order_table":[{"pair":i,"order":["A","B"] if i%2 == 0 else ["B","A"]} for i in range(20)],
        "cache_state":"UNKNOWN","warm_state":"UNKNOWN","slot_reuse":"UNKNOWN",
        "backend_runtime":"REQUIRED_AT_RUN","generation_seed":"NOT_SET_IN_PROFILE",
        "generation_defaults":"UNKNOWN_UNLESS_EXPLICIT_IN_REQUEST","latency_analysis":"EXPLORATORY_IF_CACHE_UNKNOWN",
        "primary_endpoints":["information_completeness_by_availability","redundant_acquisition_rows","post_sufficiency_research_calls"],
        "safety_endpoints":["source_integrity","read_only_invariants","terminal_contracts"],
        "analysis":{"clustering":"frozen_scenario_template_seed_context_hash","equal_scenario_weight":True,
                    "bootstrap_resamples":10000,"analysis_rng_seed":940,"interval":"95_percentile",
                    "insufficient_scenarios_or_unknown_backend":"INCONCLUSIVE"},
        "entries":entries,"tool_dispatch_in_Q_I":False,"T_fresh":"NOT_IMPLEMENTED_R941a"}
    frozen.write_json(root / "run-manifest.json", result)
    return result


def run_manifest(manifest_path, *, arm, output, backend_pid=None, backend_state=None):
    """Explicit operator entry point for R9.4.1b. Never called by preparation."""
    from ..cognition.completion import CompletionRequirement
    from ..cognition.observable import measure_turn
    from anima.agent.native_tools import LoopbackChatTransport
    plan_path = Path(manifest_path).resolve()
    plan = frozen.read_json(plan_path)
    bundle = Path(plan["bundle"])
    frozen.verify_bundle(bundle)
    if {p.name:frozen.file_digest(p) for p in bundle.iterdir() if p.is_file()} != plan["bundle_files"]:
        raise ValueError("frozen bundle changed")
    if arm not in ("H", "Q", "I-event", "I-turn", "I-tool", "T-recorded"):
        raise ValueError("unsupported experiment arm")
    if Path(output).resolve() == bundle or bundle in Path(output).resolve().parents:
        raise ValueError("experimental output must be outside frozen bundle")
    implementation = frozen.git_snapshot()
    runtime = None
    if arm == "Q" or arm.startswith("I-"):
        if backend_pid is None or backend_state is None:
            raise ValueError("backend PID and declared backend state required for inference")
        runtime = frozen.backend_snapshot(backend_pid)
        expected_backend = plan["archived_manifest"]["backend"]
        if any(runtime[k] != expected_backend[k] for k in ("executable_sha256", "argv")):
            raise ValueError("INVALID_PAIR: backend/config differs from archived profile")
        argv = runtime["argv"]
        if "-m" not in argv or frozen.file_digest(argv[argv.index("-m")+1]) != plan["archived_manifest"]["local_model_sha256"]:
            raise ValueError("INVALID_PAIR: model file differs from archived profile")
        required = {"cache_state","warm_state","slot_reuse","chat_template_sha256","hardware","threads","batch","parallel_slots","external_config_hashes"}
        if not required <= backend_state.keys():
            raise ValueError("explicit backend state fields required (UNKNOWN allowed)")
    root = _new_output(output)
    frozen.write_json(root / "run-inputs.json", {"plan":plan,"plan_sha256":frozen.file_digest(plan_path),
        "implementation_sha":implementation,"backend":runtime,"backend_state":backend_state,"arm":arm})
    summaries = []
    for entry in plan["entries"]:
        label = f'{entry["seed"]}-{entry["case"]}'
        fixture = frozen.read_json(entry["case_path"])
        raw = frozen.read_json(entry["raw_path"])
        if frozen.file_digest(entry["case_path"]) != entry["case_sha256"] or frozen.file_digest(entry["raw_path"]) != entry["raw_sha256"]:
            raise ValueError("frozen scenario changed")
        if arm in ("H", "T-recorded"):
            # Explicitly supported R9.3/R9.2 temporal_completion profile only.
            if plan["archived_manifest"].get("variant") != "temporal_completion":
                summaries.append({"scenario":label,"status":"UNSUPPORTED_PROFILE"})
                continue
            from .e26b_cognitive_suite import information_requirement
            req = information_requirement({**entry["scenario"],"targets":tuple(entry["scenario"].get("targets",()))}, temporal_completion=True)
            if arm == "H" and req.kind != "historical_and_latest_observation":
                summaries.append({"scenario":label,"arm":"H","status":"NOT_APPLICABLE_NON_TEMPORAL"})
                continue
            first = fixture["model_calls"][0]
            flags = {k:first[k] for k in ("canonical_sets","temporal","compact_temporal","error_feedback")}
            flags.update(model_claims=False,latest_observation=True)
            use_host = plan["archived_manifest"].get("host_temporal_projection",False) and req.kind == "historical_and_latest_observation"
            # Reconstruct the original research once; H arms then consume the
            # SAME checked in-process journal, never two independent runs.
            replay = recorded_trajectory(fixture,raw,output=root/(label+"-recorded"),task=entry["scenario"]["task"],
                requirement=req,max_steps=plan["archived_manifest"]["max_steps"],adapter_flags=flags,
                coordinator_flags={"ranked":True,"error_feedback":True,"latest_observation":True},
                project_result_claims=not use_host,host_profile=use_host,claim_phase="claim_projection")
            summaries.append({"scenario":label,**replay})
            if arm == "H" and replay["status"] == "MATCHED":
                # Fresh isolated replay-owned stores, not the owner's files.
                from .e24_working_memory import E24WorkingMemory, SOURCE, SUBJECT, PREDICATE, vision_source_registration, vision_digest_rule
                from .egocentric import E23ObserverPort
                from anima.core.assembly import build_core
                core = build_core(root/(label+"-recorded")/"stores",sources={SOURCE:vision_source_registration()},properties={(SUBJECT,PREDICATE):vision_digest_rule()})
                memory = E24WorkingMemory(core,E23ObserverPort(port=46029,observer_key="x"*43))
                coord = E25LabCognitiveCoordinator(memory)
                report = frozen.read_json(root/(label+"-recorded")/"generated-turn.json")
                if req.kind != "historical_and_latest_observation":
                    summaries.append({"scenario":label,"arm":"H","status":"NOT_APPLICABLE_NON_TEMPORAL"})
                    continue
                calls = [json.loads(line) for line in (root/(label+"-recorded")/"generated-calls.jsonl").read_text().splitlines() if line]
                observed_calls = list(calls)
                if report.get("claim_projection",{}).get("call") is not None:
                    observed_calls.append(report["claim_projection"]["call"])
                # H comparison excludes optional model claim projection in BOTH
                # arms. Preserve research budget, excluding that presentation call.
                pair_report = deepcopy(report)
                projection = pair_report.pop("claim_projection",{}).get("call")
                pair_report.pop("host_temporal_projection",None)
                if projection is not None:
                    # Host pair's result constructor accepts calls plus report
                    # projection metadata; no model claim phase is selected.
                    pair_report["claim_projection"] = {"status":"RECORDED_NOT_EVALUATED","call":projection}
                pair = host_pair(coord,pair_report,req,calls=calls)
                frozen.write_json(root/(label+"-host-pair.json"),pair)
                state = measure_turn(coord, report, baseline_sha=plan["baseline_sha"],case_id=entry["case"],requirement=req,calls=observed_calls,claim_phase="claim_projection")
                frozen.write_json(root/(label+"-observable.json"),state)
            continue
        selected = next(e for e in entry["arms"] if e["arm"] == arm)
        if selected["status"] != "PREPARED":
            summaries.append({"scenario":label,**selected})
            continue
        arm_path = plan_path.parent / selected["fixture"]
        if frozen.file_digest(arm_path) != selected["fixture_sha256"]:
            raise ValueError("frozen arm/map changed")
        payload = frozen.read_json(arm_path)
        delegate = LoopbackChatTransport(plan["archived_manifest"]["base_url"])
        class PinnedTransport:
            def complete(self,payload):
                current = frozen.backend_snapshot(backend_pid)
                if current != runtime:
                    raise ValueError("INVALID_PAIR: backend changed during run")
                response = delegate.complete(payload)
                if frozen.backend_snapshot(backend_pid) != runtime:
                    raise ValueError("INVALID_PAIR: backend changed during response")
                return response
        transport = PinnedTransport()
        if arm == "Q":
            summaries.append({"scenario":label,**repeat_request(payload["request"],transport,
                repetitions=plan["repetitions"],output=root/label,original_response=fixture["model_calls"][selected["index"]]["raw_response"])})
        else:
            pair_root = _new_output(root/label)
            frozen.write_json(pair_root/"variant-and-map.json",payload)
            pair_samples = []
            for order in plan["order_table"]:
                pair_index = order["pair"]
                pair = {"pair":pair_index,"order":order["order"],"arms":{},
                        "backend_start_marker":runtime["process_start_ticks"],
                        "backend_state":deepcopy(backend_state)}
                for member in order["order"]:
                    request = payload["original_request"] if member == "A" else payload["request"]
                    sample = repeat_request(request,transport,repetitions=1,output=pair_root/f"{pair_index:02d}-{member}")
                    pair["arms"][member] = sample
                    if sample["repetitions"][0]["status"] != "RECEIVED":
                        pair["status"] = "INVALID_PAIR"
                        break
                if pair.get("status") != "INVALID_PAIR":
                    a = frozen.read_json(pair_root/f"{pair_index:02d}-A"/"response-0000.json")
                    b = frozen.read_json(pair_root/f"{pair_index:02d}-B"/"response-0000.json")
                    pair["comparison"] = compare_id_responses(a,b,arm,payload["mapping"])
                frozen.write_json(pair_root/f"pair-{pair_index:02d}.json",pair)
                pair_samples.append(pair)
                if pair.get("status") == "INVALID_PAIR":
                    break
            summaries.append({"scenario":label,"arm":arm,"pairs":pair_samples,
                "first_divergence":next(({"pair":p["pair"],"comparison":p.get("comparison"),"status":p.get("status")}
                    for p in pair_samples if p.get("status") == "INVALID_PAIR" or not p["comparison"]["parsed_operations_content_equal"]),None)})
    result = {"schema":SCHEMA,"arm":arm,"summaries":summaries}
    frozen.write_json(root/"summary.json",result)
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command",required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("bundle",type=Path)
    prepare.add_argument("--baseline-sha",required=True)
    prepare.add_argument("--output",type=Path,required=True)
    run = sub.add_parser("run")
    run.add_argument("manifest",type=Path)
    run.add_argument("--arm",choices=("H","Q","I-event","I-turn","I-tool","T-recorded"),required=True)
    run.add_argument("--output",type=Path,required=True)
    run.add_argument("--backend-pid",type=int)
    run.add_argument("--backend-state",type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_manifest(args.bundle,output=args.output,baseline_sha=args.baseline_sha)
        print(canonical({"status":result["status"],"scenarios":len(result["entries"])}))
    else:
        result = run_manifest(args.manifest,arm=args.arm,output=args.output,backend_pid=args.backend_pid,
            backend_state=frozen.read_json(args.backend_state) if args.backend_state else None)
        print(canonical({"arm":result["arm"],"scenarios":len(result["summaries"])}))


if __name__ == "__main__":
    main()
