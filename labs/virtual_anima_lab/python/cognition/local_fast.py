"""E2.6a local FAST read-only proposal adapter. No executor or memory handles."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from anima.agent.llama_cpp_transport import LlamaCppSmallModelTransport
from .contracts import SCHEMA, CognitiveStepProposal

SYSTEM = (
    "You are a read-only information investigator. Find evidence about the crate. "
    "Choose one next information operation, not a physical action. "
    "retrieve_memory searches by query. lookup_raw_evidence checks original source event IDs "
    "from your supplied observations or previous verified results. If no evidence exists, stop. "
    "Retrieve before checking the original source if useful; stop after sufficient evidence. "
    "An old observation is not current visibility. Never invent event IDs. "
    "Return only JSON with operation, query, event_ids. "
    "For retrieve_memory use a short English query and empty event_ids. "
    "For lookup_raw_evidence use empty query and real event_ids. "
    "For stop use empty query and empty event_ids."
)
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "operation": {"type": "string", "enum": [
            "retrieve_memory", "lookup_raw_evidence", "stop"]},
        "query": {"type": "string", "maxLength": 128},
        "event_ids": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
    },
    "required": ["operation", "query", "event_ids"],
    "additionalProperties": False,
}


def _unique_pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate JSON key")
        obj[key] = value
    return obj


def _compact_entity(row):
    return {k: row[k] for k in (
        "entity_ref", "category", "current_observation", "last_seen_event_id",
        "last_seen_view", "evidence_count") if k in row}


def _compact_outcome(outcome):
    result = outcome.get("result", {})
    rows = result.get("records", [])
    if outcome.get("operation_kind") == "retrieve_memory":
        rows = [_compact_entity(row) for row in rows]
    else:
        rows = [{k: row[k] for k in ("event_id", "status", "entities_observed")
                 if k in row} for row in rows]
    return {"operation": outcome.get("operation_kind"), "status": outcome["status"],
            "records": rows}


def _decode(text, allowed_ids, *, turn_id, step_index, context_id):
    if type(text) is not str or len(text.encode("utf-8")) > 4096:
        raise ValueError("invalid response byte budget")
    raw = json.loads(text, object_pairs_hook=_unique_pairs,
                     parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    if type(raw) is not dict or set(raw) != {"operation", "query", "event_ids"}:
        raise ValueError("invalid response fields")
    op, query, ids = raw["operation"], raw["query"], raw["event_ids"]
    if type(query) is not str or len(query) > 128 or type(ids) is not list:
        raise ValueError("invalid arguments")
    if len(ids) > 3 or any(type(i) is not str for i in ids):
        raise ValueError("invalid source IDs")
    if op == "stop" and not query and not ids:
        return None
    if op == "retrieve_memory" and query.strip() and not ids:
        arguments = {"query": query, "top_k": 3}
    elif op == "lookup_raw_evidence" and not query and ids:
        if not set(ids) <= allowed_ids:
            raise ValueError("unexposed source ID; no historical ablation bypass")
        arguments = {"event_ids": ids}
    else:
        raise ValueError("operation/arguments outside read-only contract")
    return CognitiveStepProposal({
        "schema": SCHEMA, "proposal_id": f"pr_{turn_id}_{step_index}",
        "turn_id": turn_id, "context_snapshot_id": context_id,
        "operation_kind": op, "arguments": arguments,
        "expected_information": "",
    }).as_dict()


class LocalFastEvidenceAdapter:
    """Trusted wrapper; only the model's operation and arguments are proposals."""
    def __init__(self, *, base_url, model, trace_path, timeout=45.0, transport=None):
        url = urlsplit(base_url)
        if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "::1")
                or url.port is None or url.username or url.password
                or url.path not in ("", "/") or url.query or url.fragment):
            raise ValueError("explicit loopback HTTP endpoint required")
        self.transport = transport or LlamaCppSmallModelTransport(
            base_url=base_url, model=model, provider="llama.cpp",
            temperature=0.0, top_k=1, top_p=1.0, min_p=0.0,
            max_output_tokens=256, constrain_json=True)
        self.trace_path = Path(trace_path)
        self.timeout = timeout
        self.calls = []

    def propose(self, context, outcomes, *, turn_id, step_index):
        entities = [_compact_entity(row) for row in context["entities"]
                    if row["category"] != "surface"]
        prior = [_compact_outcome(row) for row in outcomes]
        allowed_ids = {row["last_seen_event_id"] for row in entities
                       if "last_seen_event_id" in row}
        for result in prior:
            if result["status"] == "COMPLETED" and result["operation"] == "retrieve_memory":
                allowed_ids.update(row["last_seen_event_id"] for row in result["records"]
                                   if "last_seen_event_id" in row)
        payload = {"memory_enabled": context["memory_enabled"], "entities": entities,
                   "previous_verified_results": prior,
                   "coverage": "captured observations only"}
        prompt = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
        if len(prompt.encode("utf-8")) > 12000:
            raise ValueError("model input exceeds compact budget")
        trace = {"turn_id": turn_id, "step_index": step_index,
                 "context_snapshot_id": context["context_snapshot_id"],
                 "system_prompt": SYSTEM, "user_prompt": prompt,
                 "response_schema": RESPONSE_SCHEMA, "raw_response": None,
                 "transport_ok": False, "valid": False}
        try:
            response = self.transport.complete_structured(
                system_prompt=SYSTEM, user_prompt=prompt, timeout_seconds=self.timeout,
                response_schema=RESPONSE_SCHEMA)
            trace.update(transport_ok=True, raw_response=response.text,
                         latency_ms=response.latency_ms, input_tokens=response.input_tokens,
                         output_tokens=response.output_tokens, finish_reason=response.finish_reason)
            try:
                proposal = _decode(response.text, allowed_ids, turn_id=turn_id,
                                   step_index=step_index,
                                   context_id=context["context_snapshot_id"])
            except (ValueError, TypeError) as exc:
                trace["error"] = str(exc)
                # Invalid candidate is explicitly rejected by the coordinator.
                return {"invalid_model_output": True}
            trace["valid"] = True
            trace["proposal"] = proposal
            return proposal
        except Exception as exc:
            trace["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self.calls.append(trace)
            with self.trace_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(trace, ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
