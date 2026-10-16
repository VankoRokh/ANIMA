from anima.config.paths import get_data_dir
from anima.core.identity import Identity
from anima.memory.memory_store import MemoryStore
from anima.memory.filter import MemoryFilter
from anima.memory.episodic import EpisodicMemory
from anima.memory.event_log import EventLog
from anima.core.state import AnimaState
from anima.core.event_bus import EventBus
from anima.interfaces.cli import run_cli
from anima.runtime import Runtime


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
    memory = EpisodicMemory(
        data_dir / "memories.jsonl"
    )
    memory_store = MemoryStore(
        data_dir / "memories.jsonl"
    )
    memory_filter = MemoryFilter()

    runtime = Runtime(
        anima=anima,
        event_bus=event_bus,
        event_log=event_log,
        memory_filter=memory_filter,
        memory_store=memory_store,
    )

    run_cli(
        runtime=runtime,
        anima=anima,
        identity=identity,
        memory=memory,
    )


if __name__ == "__main__":
    main()
