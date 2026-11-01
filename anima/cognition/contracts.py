"""Dependency-light model-view contract shared by projection and FAST adapters."""

from collections.abc import Mapping
from dataclasses import dataclass

from anima.ir import freeze, plain


@dataclass(frozen=True)
class CognitiveView:
    consumer: str
    data: Mapping

    def __post_init__(self):
        if self.consumer != "FAST":
            raise ValueError("Stage 5 supports only the FAST consumer")
        if not isinstance(self.data, Mapping):
            raise ValueError("Cognitive view data must be a mapping")
        object.__setattr__(self, "data", freeze(self.data))

    def to_dict(self):
        return plain(self.data)


class FastTransportError(RuntimeError):
    """A backend transport failed before a successful completion."""


class FastModelOutputError(RuntimeError):
    """The model returned unusable output, rather than a completed FAST result."""
