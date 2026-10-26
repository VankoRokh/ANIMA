from anima.config.paths import get_data_dir
from anima.core.identity import Identity
from anima.memory.composer import RuleBasedComposer
from anima.memory.event_processing import EventProcessingCoordinator
from anima.memory.memory_store import MemoryStore
from anima.memory.link_store import LinkStore
from anima.memory.processor import MemoryProcessor
from anima.memory.episodic import EpisodicMemory
from anima.memory.event_log import EventLog
from anima.core.state import AnimaState
from anima.core.event_bus import EventBus
from anima.interfaces.cli import run_cli
from anima.runtime import Runtime
from anima.diagnostics.metrics import DiagnosticMetrics
from anima.diagnostics.trace import DiagnosticTrace
from anima.internal_state.runtime_integration import InternalStateRuntime
from anima.internal_state.store import InternalStateStore


def main():
    data_dir = get_data_dir()

    anima = AnimaState(
        data_dir / "state.json"
    )
    identity = Identity(
        data_dir / "identity.json"
    )
    event_bus = EventBus()
    event_log = EventLog(
        data_dir / "events.jsonl"
    )
    memory_store = MemoryStore(
        data_dir / "memory.db"
    )
    link_store = LinkStore(
        memory_store
    )
    memory = EpisodicMemory(
        memory_store
    )
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
    internal_state_store = InternalStateStore(
        data_dir / "internal_state.db"
    )
    internal_state = InternalStateRuntime(
        internal_state_store,
        trace=trace,
    )

    runtime = Runtime(
        anima=anima,
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

    run_cli(
        runtime=runtime,
        anima=anima,
        identity=identity,
        memory=memory,
    )


if __name__ == "__main__":
    main()
