from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from anima.core.event_bus import Event


@dataclass(frozen=True)
class FastRequest:
    """Minimal Stage 5 ACI input for the FAST cognitive path."""

    input_event_id: str
    input_text: str
    context_bundle: dict

    def __post_init__(self):
        if (
            not isinstance(self.input_event_id, str)
            or not self.input_event_id.startswith("ev_")
        ):
            raise ValueError("FAST input_event_id must be an Event ID")
        if not isinstance(self.input_text, str) or not self.input_text.strip():
            raise ValueError("FAST input_text must be a non-empty string")
        if not isinstance(self.context_bundle, dict):
            raise ValueError("FAST context_bundle must be a dict")
        if self.context_bundle.get("consumer") != "FAST":
            raise ValueError("FAST context_bundle must use consumer='FAST'")


@dataclass(frozen=True)
class FastResult:
    """Minimal Stage 5 ACI output produced by a FAST backend."""

    response_text: str

    def __post_init__(self):
        if (
            not isinstance(self.response_text, str)
            or not self.response_text.strip()
        ):
            raise ValueError("FAST response_text must be a non-empty string")


@dataclass(frozen=True)
class FastTurn:
    """Observable request/result pair for one FAST cognition call."""

    request: FastRequest
    result: FastResult


@runtime_checkable
class FastBackend(Protocol):
    """Replaceable cognitive backend used by the FAST path."""

    def complete(self, request: FastRequest) -> FastResult:
        ...


class FastCognition:
    """Bridge a text Event and bounded Cognitive Memory context to FAST."""

    def __init__(self, *, context_builder, backend):
        if context_builder is None:
            raise TypeError("FAST context_builder is required")
        if not isinstance(backend, FastBackend):
            raise TypeError("FAST backend must implement FastBackend")

        self.context_builder = context_builder
        self.backend = backend

    def prepare_request(self, event):
        if not isinstance(event, Event):
            raise TypeError("FAST input must be an Event")
        if event.event_type != "conversation.user":
            raise ValueError("FAST baseline accepts only conversation.user Events")

        text = event.payload["text"]
        if not text.strip():
            raise ValueError("FAST baseline does not process empty user text")

        context_bundle = self.context_builder.build(
            text,
            consumer="FAST",
        )
        return FastRequest(
            input_event_id=event.event_id,
            input_text=text,
            context_bundle=context_bundle,
        )

    def process(self, event):
        request = self.prepare_request(event)
        result = self.backend.complete(request)
        if not isinstance(result, FastResult):
            raise TypeError("FAST backend must return FastResult")
        return FastTurn(request=request, result=result)
