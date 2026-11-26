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


__all__ = ["classify_termination", "transport_termination"]
