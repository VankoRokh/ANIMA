from anima.config.paths import get_data_dir
from anima.core.identity import Identity
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
    memory_processor = MemoryProcessor(
        memory_store=memory_store,
        event_log=event_log,
        link_store=link_store,
        trace=trace,
    )
    metrics = DiagnosticMetrics()

    runtime = Runtime(
        anima=anima,
        identity=identity,
        event_bus=event_bus,
        event_log=event_log,
        memory=memory,
        memory_processor=memory_processor,
        trace=trace,
        metrics=metrics,
    )

    run_cli(
        runtime=runtime,
        anima=anima,
        identity=identity,
        memory=memory,
    )


if __name__ == "__main__":
    main()
