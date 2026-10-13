from anima.config.paths import get_data_dir
from anima.core.identity import Identity
from anima.memory.memory_store import MemoryStore
from anima.memory.filter import MemoryFilter
from anima.memory.episodic import EpisodicMemory
from anima.memory.event_log import EventLog
from anima.core.state import AnimaState
from anima.core.event_bus import EventBus


def process_events(
    anima,
    event_bus,
    event_log,
    memory_filter,
    memory_store,
):
    while event_bus.has_events():
        event = event_bus.next_event()

        print(
            f"[EVENT] {event.timestamp} "
            f"{event.event_type} "
            f"{event.payload if event.payload else ''}"
        )

        event_log.write(event)

        if memory_filter.is_meaningful(event):
            memory = memory_filter.create_memory(event)
            memory_store.write(memory)

        anima.register_event()


def put_to_sleep(
    anima,
    event_bus,
    event_log,
    memory_filter,
    memory_store,
):
    if anima.get()["status"] == "sleeping":
        return

    event_bus.emit("sleep")

    process_events(
        anima,
        event_bus,
        event_log,
        memory_filter,
        memory_store,
    )

    anima.sleep()


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

    anima.wake()

    event_bus.emit("wake")
    process_events(
        anima,
        event_bus,
        event_log,
        memory_filter,
        memory_store,
    )

    state = anima.get()
    identity_data = identity.get()

    print()
    print("=" * 40)
    print(f"{state['name']} {state['version']}")
    print("=" * 40)
    print(f"Status:           {state['status']}")
    print(f"Instance ID:      {identity_data['instance_id']}")
    print(f"Session:          {state['session']}")
    print(f"Created:          {state['created_at']}")
    print(f"Last wake:        {state['last_wake']}")
    print(f"Events processed: {state['events_processed']}")
    print(f"Memories stored:  {memory.count()}")
    print("=" * 40)
    print()

    print("\nRecent memories:")

    for stored_memory in memory.last(3):
        print(
            f"- [{stored_memory['timestamp']}] "
            f"{stored_memory['source']}: "
            f"{stored_memory['content']}"
        )

    print()

    try:
        user_input = input("Say something to ANIMA: ")
    except (KeyboardInterrupt, EOFError) as error:
        print()
        print(
            f"Session interrupted: "
            f"{type(error).__name__}."
        )

        put_to_sleep(
            anima,
            event_bus,
            event_log,
            memory_filter,
            memory_store,
        )

        print("ANIMA is sleeping.")
        return

    event_bus.emit(
        "user_input",
        {
            "text": user_input
        }
    )

    process_events(
        anima,
        event_bus,
        event_log,
        memory_filter,
        memory_store,
    )

    try:
        input("Press Enter to put ANIMA to sleep...")
    except (KeyboardInterrupt, EOFError) as error:
        print()
        print(
            f"Session interrupted: "
            f"{type(error).__name__}."
        )

    put_to_sleep(
        anima,
        event_bus,
        event_log,
        memory_filter,
        memory_store,
    )

    print("ANIMA is sleeping.")


if __name__ == "__main__":
    main()
