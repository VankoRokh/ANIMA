"""Deterministic resolution, independent of cognitive backends."""

from .contracts import DeterministicOutcome, ResolutionResult, ResolutionRoute
from .resolver import resolve

__all__ = ["DeterministicOutcome", "ResolutionResult", "ResolutionRoute", "resolve"]
