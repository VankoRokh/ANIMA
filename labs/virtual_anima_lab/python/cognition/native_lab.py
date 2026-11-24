"""E2.6a native protocol binding to existing laboratory read-only services."""
from __future__ import annotations

from pathlib import Path

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


def lab_registry(*, temporal=False):
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
                                   **({"as_of_sample_id": text} if temporal else {})},
                                  required=["kind", "records"]),
            effect_class="read_only", idempotency="repeat_safe"),
    ])


class NativeLabAdapter:
    """Bind native calls to typed lab proposals; no access to service handles."""
    def __init__(self, *, base_url, model, trace_path, task, transport=None, registry=None,
                 first_tool_required=False, canonical_sets=False, temporal=False):
        self.temporal = temporal
        self.canonical_sets = canonical_sets
        self.catalog = NativeToolCatalog(
            registry if registry is not None else lab_registry(temporal=temporal),
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
                prompt_context["as_of_latest_sample_id"] = self.latest_sample_id
                prompt_context["observation_scope"] = "current_observation refers to latest captured sample; not_observed is not absent"
                for entity, original in zip(entities, (row for row in context["entities"] if row["category"] != "surface")):
                    entity["last_seen_sample_id"] = original["last_seen_sample"]
            self.session = NativeToolSession(self.catalog, model=self.model,
                system_prompt=SYSTEM, transport=self.transport,
                first_tool_required=self.first_tool_required,
                user_prompt=canonical(prompt_context))
        elif self.binding != binding or self.pending is None or len(outcomes) != step_index:
            raise ValueError("invalid native turn continuation")
        if self.pending is not None:
            descriptor, proposal_id, previous_step = self.pending
            outcome = outcomes[-1]
            if (outcome.get("proposal_id") != proposal_id
                    or outcome.get("operation_kind") != descriptor.name
                    or outcome.get("step_index") != previous_step
                    or outcome.get("status") != "COMPLETED"):
                raise ValueError("unverified or mismatched tool outcome")
            result = outcome["result"]
            descriptor.validate_output(result)
            if self.temporal and descriptor.name == "lookup_raw_evidence":
                result = {**result, "as_of_sample_id": self.latest_sample_id,
                          "records": [{**row, "temporal_scope": (
                              ("latest_captured_sample" if row["sample_id"] == self.latest_sample_id
                               else "historical_sample")
                              if row["status"] == "verified_source_view" else "unverified")}
                                      for row in result["records"]]}
            self.session.submit_result(descriptor, result)
            if descriptor.name == "retrieve_memory":
                self.allowed_ids.update(row["last_seen_event_id"] for row in result["records"]
                                        if "last_seen_event_id" in row)
            self.pending = None
        before = len(self.session.calls)
        try:
            selected = self.session.next()
            if selected is None:
                return None
            descriptor, args = selected
            if descriptor.name == "lookup_raw_evidence" and not set(args["event_ids"]) <= self.allowed_ids:
                raise ValueError("unexposed evidence ID")
            proposal = CognitiveStepProposal({
                "schema": SCHEMA, "proposal_id": f"pr_{turn_id}_{step_index}",
                "turn_id": turn_id, "context_snapshot_id": binding[1],
                "operation_kind": descriptor.name, "arguments": args,
                "expected_information": "",
            }).as_dict()
            self.pending = (descriptor, proposal["proposal_id"], step_index)
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
                              temporal=self.temporal, turn_id=turn_id, step_index=step_index,
                              context_snapshot_id=binding[1])
                self.calls.append(record)
                with self.trace_path.open("a", encoding="utf-8") as stream:
                    stream.write(canonical(record) + "\n")
