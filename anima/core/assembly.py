"""Single composition root for the existing ANIMA runtime.

P1 bootstrap only: this is not the autonomous Event→Belief→Action loop.
No model, GUI, world adapter, or Sleep worker is required to construct it.
"""

from dataclasses import dataclass
from pathlib import Path

from anima.config.paths import get_data_dir
from anima.core.event_bus import EventBus
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


def build_core(data_dir: str | Path | None = None) -> CoreAssembly:
    """Build the current, proven runtime stack once for CLI and headless use.

    No wakeup is implicit. The caller owns lifecycle and must explicitly call
    runtime.wake()/sleep(). World Belief, autonomous scheduling and actions are
    intentionally not created in P1.
    """

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
    )


__all__ = ["CoreAssembly", "build_core"]
