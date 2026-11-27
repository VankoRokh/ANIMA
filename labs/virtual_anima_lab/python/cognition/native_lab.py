"""E2.6a native protocol binding to existing laboratory read-only services."""
from __future__ import annotations

from pathlib import Path
import re

from anima.agent.native_tools import (
    NativeToolCatalog, NativeToolSession, LoopbackChatTransport, canonical,
)
from anima.agent.tools import ToolDescriptor, ToolRegistry
from .contracts import SCHEMA, CognitiveStepProposal
from .local_fast import _compact_entity

SYSTEM = (
    "Investigate using available tools. Search for past evidence and inspect its source "
    "when available. Historical observations do not establish current visibility. "
    "Use only event IDs in your observations or verified tool results. "
    "If a search returns no evidence, report uncertainty rather than inventing facts. "
    "When you have sufficient information, finish with a brief answer without calling a tool."
)


def _object(properties, required=None):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required,
            "additionalProperties": False}


def _records_schema():
    # Detailed source verification is owned by E24WorkingMemory; this schema
    # validates the service envelope, not provenance authority.
    return {"type": "array", "maxItems": 20,
            "items": {"type": "object", "additionalProperties": True}}


def _sample_parts(sample_id):
    # EgocentricView validates this canonical identity at ingress.
    # Use numerical sequence only within the frozen world/epoch.
    if type(sample_id) is not str:
        raise ValueError("sample identity required")
    match = re.fullmatch(r"(worldobs:[^:]+:[0-9]+):([1-9][0-9]*)", sample_id)
    if match is None:
        raise ValueError("invalid sample identity")
    return match[1], int(match[2])


def _sample_seq_in_scope(sample_id, latest_sample_id):
    domain, seq = _sample_parts(sample_id)
    latest_domain, latest_seq = _sample_parts(latest_sample_id)
    if domain != latest_domain or seq > latest_seq:
        raise ValueError("sample outside frozen world/epoch or future")
    return seq


def lab_registry(*, temporal=False, compact_temporal=False, latest_observation=False):
    text = {"type": "string"}
    integer = {"type": "integer", "minimum": 0}
    boolean = {"type": "boolean"}
    return ToolRegistry([
        ToolDescriptor(name="retrieve_memory", version="1",
            description="Search captured observations by short English entity keywords. "
                        "Returns matching entities and their last source event IDs.",
            input_schema=_object({"query": {"type": "string", "minLength": 1, "maxLength": 512},
                                  "top_k": {"type": "integer", "minimum": 1, "maximum": 20}}),
            output_schema=_object({"kind": text, "strategy": text, "records": _records_schema(),
                                   "returned": integer, "possible_matches": integer,
                                   "truncated": boolean, "memory_enabled": boolean}),
            effect_class="read_only", idempotency="repeat_safe"),
        ToolDescriptor(name="lookup_raw_evidence", version="1",
            description=("Verify original captured observations by previously exposed source event IDs. "
                         "Verification concerns the source sample, not current visibility."
                         if temporal else "Verify original captured observations by previously exposed source event IDs."),
            input_schema=_object({"event_ids": {"type": "array", "minItems": 1, "maxItems": 16,
                                                "uniqueItems": True,
                                                "items": {"type": "string", "minLength": 1,
                                                          "maxLength": 128}}}),
            output_schema=_object({"kind": text, "records": _records_schema(),
                                   **({"as_of_sample_id": text} if temporal else {}),
                                   **({"as_of_sample_seq": integer} if compact_temporal else {})},
                                  required=["kind", "records"]),
            effect_class="read_only", idempotency="repeat_safe"),
        *([ToolDescriptor(name="inspect_latest_observation", version="1",
            description="Read the verified latest captured observation in this research context. "
                        "Returns the source event ID, sample sequence and observed entities. "
                        "Does not capture a new observation or prove absence from the world.",
            input_schema=_object({}),
            output_schema=_object({"kind": text, "records": _records_schema(),
                                   "as_of_sample_id": text, "as_of_sample_seq": integer},
                                  required=["kind","records"]),
            effect_class="read_only", idempotency="repeat_safe")] if latest_observation else []),
    ])


class NativeLabAdapter:
    """Bind native calls to typed lab proposals; no access to service handles."""
    def __init__(self, *, base_url, model, trace_path, task, transport=None, registry=None,
                 first_tool_required=False, canonical_sets=False, temporal=False,
                 compact_temporal=False, error_feedback=False, model_claims=False,
                 latest_observation=False):
        if type(latest_observation) is not bool or (latest_observation and not compact_temporal):
            raise ValueError("latest observation requires compact temporal projection")
        if type(model_claims) is not bool or (model_claims and not compact_temporal):
            raise ValueError('model claims require compact temporal projection')
        self._host_result_profile = "baseline"
        self.model_claims = model_claims
        if type(error_feedback) is not bool:
            raise TypeError("error_feedback must be boolean")
        self.error_feedback = error_feedback
        self.feedback_used = False
        self.rejected_pending = None
        if compact_temporal and not temporal:
            raise ValueError("compact temporal projection requires temporal scope")
        self.compact_temporal = compact_temporal
        self.temporal = temporal
        self.canonical_sets = canonical_sets
        self.catalog = NativeToolCatalog(
            registry if registry is not None else lab_registry(temporal=temporal, compact_temporal=compact_temporal,
                                                              latest_observation=latest_observation),
            set_arguments={("lookup_raw_evidence", "1"): ("event_ids",)} if canonical_sets else None)
        self.transport = transport if transport is not None else LoopbackChatTransport(base_url)
        self.model = model
        self.first_tool_required = first_tool_required
        self.task = task
        self.trace_path = Path(trace_path)
        self.session = None
        self.calls = []
        self.pending = None
        self.allowed_ids = set()
        self.binding = None
        self._resuming = False

    def configure_host_profile(self, profile):
        if profile != 'r945/0.1' or self.session is not None or self.calls:
            raise ValueError('host result profile must bind before first call')
        self._host_result_profile = profile

    def resume_after_stop(self, *, turn_id, context_snapshot_id, feedback):
        if (self.binding != (turn_id, context_snapshot_id) or self.session is None
                or self.pending is not None or self.rejected_pending is not None):
            raise ValueError('continuation does not bind stopped turn')
        self.session.resume_after_stop(feedback)
        self._resuming = True

    def propose(self, context, outcomes, *, turn_id, step_index):
        binding = (turn_id, context["context_snapshot_id"])
        if self.session is None:
            if step_index != 0 or outcomes:
                raise ValueError("new native session requires initial step")
            entities = [_compact_entity(row) for row in context["entities"]
                        if row["category"] != "surface"]
            self.allowed_ids = {row["last_seen_event_id"] for row in entities
                                if "last_seen_event_id" in row}
            self.binding = binding
            prompt_context = {"task": self.task, "observations": entities,
                              "memory_enabled": context["memory_enabled"],
                              "coverage": "captured observations only"}
            if self.temporal:
                self.latest_sample_id = context["latest_sample_id"]
                if type(self.latest_sample_id) is not str or not self.latest_sample_id:
                    raise ValueError("latest captured sample identity required")
                if self.compact_temporal:
                    prompt_context["latest_sample_seq"] = _sample_parts(self.latest_sample_id)[1]
                else:
                    prompt_context["as_of_latest_sample_id"] = self.latest_sample_id
                prompt_context["observation_scope"] = "current_observation refers to latest captured sample; not_observed is not absent"
                for entity, original in zip(entities, (row for row in context["entities"] if row["category"] != "surface")):
                    if self.compact_temporal:
                        entity["last_seen_sample_seq"] = _sample_seq_in_scope(original["last_seen_sample"], self.latest_sample_id)
                    else:
                        entity["last_seen_sample_id"] = original["last_seen_sample"]
            system_prompt = SYSTEM
            if self.model_claims:
                from .model_claims import CLAIM_INSTRUCTION
                system_prompt += CLAIM_INSTRUCTION
            self.session = NativeToolSession(self.catalog, model=self.model,
                system_prompt=system_prompt, transport=self.transport,
                first_tool_required=self.first_tool_required,
                argument_feedback=self.error_feedback,
                user_prompt=canonical(prompt_context))
        elif (self.binding != binding or len(outcomes) != step_index
              or (self.pending is None and self.rejected_pending is None and not self._resuming)):
            raise ValueError("invalid native turn continuation")
        self._resuming = False
        if self.rejected_pending is not None:
            call, previous_step, reason_code = self.rejected_pending
            outcome = outcomes[-1]
            if (outcome.get("step_index") != previous_step
                    or outcome.get("status") != "REJECTED"
                    or outcome.get("reason_code") != reason_code
                    or outcome.get("proposal_id") is not None
                    or outcome.get("execution_performed") is not False):
                raise ValueError("rejection not bound to previous denied call")
            self.session.reject_pending(call, reason_code=reason_code)
            self.rejected_pending = None
        if self.pending is not None:
            call, proposal_id, previous_step = self.pending
            descriptor = call.descriptor
            outcome = outcomes[-1]
            if (outcome.get("proposal_id") != proposal_id
                    or outcome.get("operation_kind") != descriptor.name
                    or outcome.get("step_index") != previous_step
                    or outcome.get("status") != "COMPLETED"):
                raise ValueError("unverified or mismatched tool outcome")
            result = outcome["result"]
            descriptor.validate_output(result)
            if descriptor.name == "inspect_latest_observation":
                rows = result["records"]
                if (result["kind"] != "verified_raw_evidence" or len(rows) != 1
                        or rows[0]["status"] != "verified_source_view"
                        or rows[0]["sample_id"] != self.latest_sample_id):
                    raise ValueError("latest observation result mismatch")
            if self.temporal and descriptor.name in ("lookup_raw_evidence", "inspect_latest_observation"):
                result = {**result, "as_of_sample_id": self.latest_sample_id,
                          "records": [{**row, "temporal_scope": (
                              ("latest_captured_sample" if row["sample_id"] == self.latest_sample_id
                               else "historical_sample")
                              if row["status"] == "verified_source_view" else "unverified")}
                                      for row in result["records"]]}
            if self.compact_temporal and descriptor.name in ("lookup_raw_evidence", "inspect_latest_observation"):
                projected = []
                for row in result["records"]:
                    entry = dict(row)
                    if row["status"] == "verified_source_view":
                        seq = _sample_seq_in_scope(entry.pop("sample_id"), self.latest_sample_id)
                        if type(entry["sample_seq"]) is not int or entry["sample_seq"] != seq:
                            raise ValueError("source sample sequence mismatch")
                    projected.append(entry)
                result = {**result, "records": projected,
                          "as_of_sample_seq": _sample_parts(self.latest_sample_id)[1]}
                del result["as_of_sample_id"]
            elif self.compact_temporal and descriptor.name == "retrieve_memory":
                projected = []
                for row in result["records"]:
                    entry = dict(row)
                    entry["last_seen_sample_seq"] = _sample_seq_in_scope(
                        entry.pop("last_seen_sample"), self.latest_sample_id)
                    projected.append(entry)
                result = {**result, "records": projected}
            if self._host_result_profile == 'r945/0.1' and descriptor.name == 'retrieve_memory':
                from .retrieval_representation import model_search_view
                result = model_search_view(result)
            self.session.submit_result(call, result)
            if descriptor.name == "retrieve_memory":
                self.allowed_ids.update(row["last_seen_event_id"] for row in result["records"]
                                        if "last_seen_event_id" in row)
            if descriptor.name == "inspect_latest_observation":
                self.allowed_ids.add(result["records"][0]["event_id"])
            self.pending = None
        before = len(self.session.calls)
        try:
            selected = self.session.next()
            if selected is None:
                return None
            descriptor, args = selected.descriptor, selected.arguments
            reason_code = None
            if args is None and self.session.pending_error == "INVALID_TOOL_ARGUMENTS":
                reason_code = "INVALID_TOOL_ARGUMENTS"
            elif descriptor.name == "lookup_raw_evidence" and not set(args["event_ids"]) <= self.allowed_ids:
                reason_code = "UNEXPOSED_EVIDENCE_ID"
            if reason_code is not None:
                record = self.session.calls[-1]
                record.update(valid=False, error_code=reason_code, execution_performed=False)
                record.setdefault("error", "unexposed evidence ID")
                if self.error_feedback and not self.feedback_used:
                    self.feedback_used = True
                    self.rejected_pending = (selected, step_index, reason_code)
                    record["feedback_eligible"] = True
                    return {"rejected_native_call": reason_code}
                raise ValueError(record["error"])
            proposal = CognitiveStepProposal({
                "schema": SCHEMA, "proposal_id": f"pr_{turn_id}_{step_index}",
                "turn_id": turn_id, "context_snapshot_id": binding[1],
                "operation_kind": descriptor.name, "arguments": args,
                "expected_information": "",
            }).as_dict()
            self.pending = (selected, proposal["proposal_id"], step_index)
            self.session.calls[-1]["proposal"] = proposal
            return proposal
        except (ValueError, TypeError, KeyError) as exc:
            if len(self.session.calls) == before:
                raise
            self.session.calls[-1].update(valid=False, error=str(exc))
            return {"invalid_model_output": True}
        finally:
            for record in self.session.calls[before:]:
                record.update(profile="native", canonical_sets=self.canonical_sets,
                              temporal=self.temporal, compact_temporal=self.compact_temporal,
                              error_feedback=self.error_feedback,
                              turn_id=turn_id, step_index=step_index,
                              model_call_index=len(self.calls),
                              context_snapshot_id=binding[1])
                self.calls.append(record)
                with self.trace_path.open("a", encoding="utf-8") as stream:
                    stream.write(canonical(record) + "\n")
