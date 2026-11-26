"""R9.2.3: separate model output from verified typed claims.

Consumes trusted in-process native adapter records and the coordinator's
optional projection report. Correlation/terminal checks are not backend
attestation. No model calls, tool dispatch, writes or semantic prose grader.
"""
from copy import deepcopy

from .model_claims import temporal_claim_coverage


def _text_attempt(call, report, *, phase, index, terminal):
    if (call.get("turn_id") != report["turn_id"]
            or call.get("context_snapshot_id") != report["context_snapshot_id"]
            or type(call.get("model_call_index")) is not int
            or call["model_call_index"] != index):
        raise ValueError("model call does not bind cognitive result")
    if phase == "research":
        if call.get("profile") != "native" or call.get("phase", "research") != "research":
            raise ValueError("native research call required")
    elif call.get("phase") != "claim_projection":
        raise ValueError("claim projection call required")
    raw = call.get("raw_response")
    choices = raw.get("choices") if type(raw) is dict else None
    if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
        return None
    choice = choices[0]
    message = choice.get("message")
    if (type(message) is not dict or message.get("role") != "assistant"
            or message.get("tool_calls", []) != []
            or type(message.get("content")) is not str):
        return None
    text = message["content"]
    accepted = (terminal and report["status"] == "STOPPED"
                and call.get("transport_ok") is True and call.get("valid") is True
                and choice.get("finish_reason") == call.get("finish_reason") == "stop"
                and text == call.get("final_text") and bool(text.strip())
                and call.get("proposal") is None)
    return {
        "origin": "MODEL", "phase": phase, "model_call_index": index,
        "turn_id": report["turn_id"], "context_snapshot_id": report["context_snapshot_id"],
        "finish_reason": choice.get("finish_reason"),
        "protocol_status": ("ACCEPTED_FINAL" if accepted else
                            "INTERMEDIATE_OR_UNACCEPTED"),
        "original_text": text, "authority": "UNVERIFIED",
    }


def build_reasoning(report, completion, *, evaluate_claims, research_calls=(), claim_phase=None):
    """Return reasoning, model-claim assessment and separate presentation.

    claim_phase is a trusted profile choice, not inferred from arbitrary
    model text. None means no structured claim format was requested.
    Accepted terminal output is still semantically unverified.
    """
    if claim_phase not in (None, "research", "claim_projection"):
        raise ValueError("unknown model claim phase")
    if type(research_calls) not in (tuple, list):
        raise TypeError("native research call sequence required")
    if research_calls or claim_phase is not None:
        if ("model_calls_used" in report
                and report["model_calls_used"] != len(research_calls)):
            raise ValueError("research call count does not bind cognitive result")
        budget = report.get("resource_budget")
        if budget is not None:
            projection_count = int(report.get("claim_projection", {}).get("call") is not None)
            if budget["reserved_calls"] != len(research_calls) + projection_count:
                raise ValueError("reserved call count does not bind cognitive result")
    attempts = []
    for index, call in enumerate(research_calls):
        attempt = _text_attempt(call, report, phase="research", index=index,
                                terminal=index == len(research_calls) - 1)
        if attempt is not None:
            attempts.append(attempt)
    research = next((a for a in attempts if a["protocol_status"] == "ACCEPTED_FINAL"), None)
    projection_info = report.get("claim_projection", {})
    projection_call = projection_info.get("call")
    projection = None
    if projection_call is not None:
        attempt = _text_attempt(projection_call, report, phase="claim_projection",
                                index=len(research_calls),
                                terminal=projection_info.get("status") == "GENERATED"
                                and research is not None)
        if attempt is not None:
            attempts.append(attempt)
            if attempt["protocol_status"] == "ACCEPTED_FINAL":
                projection = attempt
    selected = research if claim_phase == "research" else (
        projection if claim_phase == "claim_projection" else None)
    selected_call = (research_calls[-1] if selected is research and research is not None
                     else projection_call if selected is not None else None)
    evaluation = None
    status = "NOT_REQUESTED"
    coverage = "NOT_ASSESSED"
    verified = []
    if claim_phase is not None:
        evaluation = evaluate_claims([selected_call] if selected_call is not None else [])
        if evaluation["format_status"] != "VALID":
            status = evaluation["format_status"]
        elif not evaluation["claims"]:
            status = "NO_CLAIMS"
        else:
            verdicts = evaluation["verdicts"]
            status = ("ALL_CLAIMS_VERIFIED" if all(v["status"] == "VERIFIED" for v in verdicts)
                      else "CLAIMS_NOT_ALL_VERIFIED")
            verified = [{"origin": "MODEL_CANDIDATE_VERIFIED", "verdict": deepcopy(v)}
                        for v in verdicts if v["status"] == "VERIFIED"]
        if completion is not None:
            kind = completion["requirement"]["kind"]
            if kind in ("verified_observation", "historical_and_latest_observation"):
                sufficient = False
                if status == "ALL_CLAIMS_VERIFIED" and completion["information_requirement_satisfied"]:
                    if kind == "historical_and_latest_observation":
                        sufficient = temporal_claim_coverage(completion, evaluation)
                    else:
                        sufficient = set(completion["requirement"]["entities"]) <= set(
                            evaluation["verified_positive_entities"])
                coverage = "COMPLETE" if sufficient else "INCOMPLETE"
            else:
                coverage = "NOT_APPLICABLE"
    reasoning = {
        "model_text_attempts": attempts,
        "research_final_index": research["model_call_index"] if research else None,
        "projection_final_index": projection["model_call_index"] if projection else None,
        "projection_status": projection_info.get("status", "NOT_REQUESTED"),
        "structured_interpretations": "NOT_EXTRACTED",
        "free_text_authority": "UNVERIFIED",
    }
    claims = {
        "phase": claim_phase,
        "status": status,
        "coverage": coverage,
        "evaluation": evaluation,
        "verified_candidates": verified,
        "free_text_verified": False,
    }
    # Keep the original research answer available even if projection succeeds.
    # Parsed answer is a display convenience only, never verified prose.
    model_text = research["original_text"] if research else None
    if claim_phase == "research" and evaluation["format_status"] == "VALID":
        model_text = evaluation["answer"]
    presentation = {
        "model_text": model_text,
        "model_text_authority": "UNVERIFIED",
        "projection_text": (evaluation["answer"] if claim_phase == "claim_projection"
                            and evaluation["format_status"] == "VALID" else
                            projection["original_text"] if projection else None),
        "projection_text_authority": "UNVERIFIED",
        "verified_data_path": "evidence.facts",
        "verified_model_claims_path": "evidence.model_claims.verified_candidates",
        "semantic_review": "NOT_PERFORMED",
        "whole_answer_verified": False,
    }
    return reasoning, claims, presentation
