"""Conservative text adapter: only complete, bounded arithmetic expressions."""

import re
from decimal import Decimal

from anima.core.event_bus import Event
from anima.ir import CanonicalTask

_EXPRESSION = re.compile(r"\s*(?P<left>[+-]?\d{1,12}(?:\.\d{1,6})?)\s*(?P<operator>[+*/×÷-])\s*(?P<right>[+-]?\d{1,12}(?:\.\d{1,6})?)\s*")


def task_from_event(event):
    if not isinstance(event, Event):
        raise TypeError("Cognitive input must be an Event")
    if event.event_type != "conversation.user":
        raise ValueError("Cognitive Event path accepts only conversation.user")
    text = event.payload["text"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Cognitive Event path does not process empty user text")
    match = _EXPRESSION.fullmatch(text)
    arguments = {}
    if match:
        for name in ("left", "right"):
            value = match[name]
            arguments[name] = Decimal(value) if "." in value else int(value)
        arguments["operator"] = {"×": "*", "÷": "/"}.get(match["operator"], match["operator"])
    return CanonicalTask(
        task_id=event.event_id,
        source_id=event.event_id,
        operation="CALCULATE" if match else "OPEN",
        arguments=arguments,
        raw_input=text,
    )
