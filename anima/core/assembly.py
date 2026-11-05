"""Single composition root for the existing ANIMA runtime.

P1 bootstrap only: this is not the autonomous Event→Belief→Action loop.
No model, GUI, world adapter, or Sleep worker is required to construct it.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from anima.config.paths import get_data_dir
from anima.core.belief import PropertyRule
from anima.core.dispatch import CoreEventDispatcher
from anima.core.event_bus import EventBus
from anima.core.ingress import CoreIngress, SourceRegistration
from anima.core.identity import Identity
from anima.core.state import AnimaState
from anima.diagnostics.metrics import DiagnosticMetrics
from anima.diagnostics.trace import DiagnosticTrace
from anima.internal_state.runtime_integration import InternalStateRuntime
from anima.internal_state.store import InternalStateStore
from anima.memory.composer import RuleBasedComposer
from anima.memory.episodic import EpisodicMemory
from anima.memory.event_log import EventLog
from anima.memory.event_processing import EventProcessingCoordinator
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor
from anima.runtime import Runtime


@dataclass(frozen=True, slots=True)
class CoreAssembly:
    """Named runtime dependencies; no side effects beyond initial store setup."""

    data_dir: Path
    state: AnimaState
    identity: Identity
    event_bus: EventBus
    event_log: EventLog
    memory_store: MemoryStore
    link_store: LinkStore
    memory: EpisodicMemory
    trace: DiagnosticTrace
    memory_composer: RuleBasedComposer
    memory_processor: MemoryProcessor
    event_processing: EventProcessingCoordinator
    metrics: DiagnosticMetrics
    internal_state_store: InternalStateStore
    internal_state: InternalStateRuntime
    runtime: Runtime
    core_events: CoreEventDispatcher | None


def build_core(
    data_dir: str | Path | None = None,
    *,
    sources: Mapping[str, SourceRegistration] | None = None,
    properties: Mapping[tuple[str, str], PropertyRule] | None = None,
) -> CoreAssembly:
    """Build the current, proven runtime stack once for CLI and headless use.

    No wakeup is implicit. Caller owns lifecycle. Registered Core inputs can
    be opted into the same Runtime; autonomous scheduling and actions are not
    assembled in P2-C.
    """

    if (sources is None) != (properties is None):
        raise ValueError("Core inputs require both source and property registries")
    root = (get_data_dir() if data_dir is None else Path(data_dir)).expanduser().resolve()
    state = AnimaState(root / "state.json")
    identity = Identity(root / "identity.json")
    event_bus = EventBus()
    event_log = EventLog(root / "events.jsonl")
    memory_store = MemoryStore(root / "memory.db")
    link_store = LinkStore(memory_store)
    memory = EpisodicMemory(memory_store)
    trace = DiagnosticTrace()
    memory_composer = RuleBasedComposer()
    memory_processor = MemoryProcessor(
        memory_store=memory_store,
        event_log=event_log,
        link_store=link_store,
        composer=memory_composer,
        trace=trace,
    )
    event_processing = EventProcessingCoordinator(
        memory_store=memory_store,
        memory_processor=memory_processor,
        event_log=event_log,
        trace=trace,
    )
    core_events = None
    if sources is not None and properties is not None:
        ingress = CoreIngress(
            root / "core_state.db",
            sources=sources,
            properties=properties,
        )
        core_events = CoreEventDispatcher(
            ingress=ingress,
            event_log=event_log,
            event_processing=event_processing,
        )
    metrics = DiagnosticMetrics()
    internal_state_store = InternalStateStore(root / "internal_state.db")
    internal_state = InternalStateRuntime(internal_state_store, trace=trace)
    runtime = Runtime(
        anima=state,
        identity=identity,
        event_bus=event_bus,
        event_log=event_log,
        memory=memory,
        memory_processor=memory_processor,
        event_processing=event_processing,
        trace=trace,
        metrics=metrics,
        internal_state=internal_state,
        core_events=core_events,
    )
    return CoreAssembly(
        data_dir=root,
        state=state,
        identity=identity,
        event_bus=event_bus,
        event_log=event_log,
        memory_store=memory_store,
        link_store=link_store,
        memory=memory,
        trace=trace,
        memory_composer=memory_composer,
        memory_processor=memory_processor,
        event_processing=event_processing,
        metrics=metrics,
        internal_state_store=internal_state_store,
        internal_state=internal_state,
        runtime=runtime,
        core_events=core_events,
    )


__all__ = ["CoreAssembly", "build_core"]
