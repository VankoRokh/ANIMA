"""Pure termination classification for explicitly selected wire protocols.

A completed generation is not a valid schema, a permitted operation, a
verified claim or a successful task. Preserve the backend's original reason
in the caller's trace. Do not infer normal termination from JSON syntax.
"""


def classify_termination(reason, *, wire):
    """Return TEXT_COMPLETE, TOOL_CALL_COMPLETE, INCOMPLETE or UNKNOWN.

    llama.cpp native /completion uses stop_type; OpenAI-compatible
    /v1/chat/completions uses finish_reason. A reason from a different
    protocol is not interchangeable. Only exact documented strings qualify.
    """
    if wire not in ("llama_cpp_completion", "chat_completion"):
        raise ValueError("unsupported generation wire protocol")
    if type(reason) is not str:
        return "UNKNOWN"
    if wire == "llama_cpp_completion":
        if reason in ("eos", "word"):
            return "TEXT_COMPLETE"
        if reason in ("limit", "none"):
            return "INCOMPLETE"
    else:
        if reason == "stop":
            return "TEXT_COMPLETE"
        if reason == "tool_calls":
            return "TOOL_CALL_COMPLETE"
        if reason in ("length", "content_filter"):
            return "INCOMPLETE"
    return "UNKNOWN"


def transport_termination(transport, reason):
    """Bind terminal classification to a trusted transport declaration.

    Custom transports must explicitly declare their wire protocol. Missing
    or unsupported declarations never acquire authority from provider names
    or from a plausible finish reason.
    """
    wire = getattr(transport, "wire_protocol", None)
    if type(wire) is not str or wire not in ("llama_cpp_completion", "chat_completion"):
        return None, "UNKNOWN"
    return wire, classify_termination(reason, wire=wire)


MAX_REJECTED_RESPONSE_HISTORY = 64


def reported_token_count(value):
    """Only backend-reported non-negative integer counters are evidence."""
    return value if type(value) is int and value >= 0 else None


def record_rejected_response(transport, error, *, provider, model, latency_ms,
                             finish_reason, input_tokens, output_tokens,
                             content, reasoning_content, reason_code):
    """Attach metadata to an existing typed error; never retain response text.

    Only call after a generation response envelope was received. The history
    is process-local and does not grant authority or imply complete accounting.
    """
    wire, status = transport_termination(transport, finish_reason)
    record = {
        "provider": provider,
        "model": model,
        "wire_protocol": wire,
        "finish_reason": finish_reason if type(finish_reason) is str and len(finish_reason) <= 64 else None,
        "termination_status": status,
        "input_tokens": reported_token_count(input_tokens),
        "output_tokens": reported_token_count(output_tokens),
        "latency_ms": latency_ms,
        "content_chars": len(content) if isinstance(content, str) else 0,
        "reasoning_chars": len(reasoning_content) if isinstance(reasoning_content, str) else 0,
        "reason_code": reason_code,
    }
    history = transport.rejected_response_history
    history.append(record)
    if len(history) > MAX_REJECTED_RESPONSE_HISTORY:
        del history[:-MAX_REJECTED_RESPONSE_HISTORY]
    # A caller may modify its exception metadata without rewriting history.
    error.generation_diagnostic = dict(record)
    return error


__all__ = [
    "classify_termination", "transport_termination", "reported_token_count",
    "record_rejected_response", "MAX_REJECTED_RESPONSE_HISTORY",
]
