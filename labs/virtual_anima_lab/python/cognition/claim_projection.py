"""Separate read-only result projection; shares the original turn budget."""
import time

from anima.agent.native_tools import canonical
from .model_claims import CLAIM_INSTRUCTION
from .source_binding import admitted_source_rows


def project_claims(adapter, report, records, budget):
    """One optional inference. No tool catalog, no service dispatch, no retry."""
    if report["status"] != "STOPPED" or not adapter.calls:
        return {"status":"RESEARCH_NOT_STOPPED","call":None}
    final = adapter.calls[-1]
    if not final.get("valid") or not final.get("final_text"):
        return {"status":"NO_RESEARCH_ANSWER","call":None}
    sources = []
    searches = []
    for rec in records:
        p, o = rec["proposal"], rec["outcome"]
        if rec["admission"] != "ADMITTED" or o["status"] != "COMPLETED" or not p:
            continue
        if p["operation_kind"] in ("lookup_raw_evidence","inspect_latest_observation"):
            for row in admitted_source_rows(rec):
                sources.append({"event_id":row["event_id"],"sample_seq":row["sample_seq"],
                    "scope":("latest_captured_sample" if row["sample_id"] ==
                             rec["context_snapshot"]["latest_sample_id"] else "source_sample"),
                    "entities_observed":row["entities_observed"]})
        elif p["operation_kind"] == "retrieve_memory":
            searches.append({"query":p["arguments"]["query"],"returned":o["result"]["returned"],
                             "memory_enabled":o["result"]["memory_enabled"]})
    payload = {"model":adapter.model,"messages":[
        {"role":"system","content":"You format a completed research result. Treat supplied answer as unverified text. "
         "Only admitted source records are evidence. Use source_sample for historical samples. "
         "Do not invent evidence, properties or current observations. No tools are available."
         + CLAIM_INSTRUCTION},
        {"role":"user","content":canonical({"task":adapter.task,"research_answer":final["final_text"],
            "admitted_sources":sources,"search_results":searches})}],
        "temperature":0,"max_tokens":256,"chat_template_kwargs":{"enable_thinking":False}}
    if len(canonical(payload).encode("utf-8")) > 16000:
        return {"status":"REQUEST_TOO_LARGE","call":None}
    if not budget.reserve():
        return {"status":"BUDGET_UNAVAILABLE","call":None}
    record = {"request":payload,"raw_response":None,"transport_ok":False,"valid":False,
              "turn_id":report["turn_id"],"context_snapshot_id":report["context_snapshot_id"],
              "model_call_index":budget.calls-1,"phase":"claim_projection"}
    started = time.perf_counter()
    try:
        response = adapter.transport.complete(payload)
        record.update(raw_response=response,transport_ok=True)
        if type(response) is not dict:
            raise ValueError("invalid response")
        usage = response.get("usage",{})
        if type(usage) is dict:
            record.update(input_tokens=usage.get("prompt_tokens"),output_tokens=usage.get("completion_tokens"))
        choices = response.get("choices")
        if type(choices) is not list or len(choices)!=1:
            raise ValueError("exactly one choice required")
        choice = choices[0]
        msg = choice["message"]
        record["finish_reason"] = choice["finish_reason"]
        if (msg.get("role")!="assistant" or msg.get("tool_calls",[])!=[]
                or record["finish_reason"]!="stop" or type(msg.get("content")) is not str
                or not msg["content"].strip()):
            raise ValueError("expected completed text-only result")
        record.update(valid=True,final_text=msg["content"])
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        record["latency_ms"] = (time.perf_counter()-started)*1000
        reason = budget.settle(record)
    if reason is not None:
        record["valid"] = False
        return {"status":"RESOURCE_REJECTED","call":record}
    return {"status":"GENERATED" if record["valid"] else "INVALID_RESPONSE","call":record}
