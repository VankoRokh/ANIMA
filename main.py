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


def main():
    anima = AnimaState()
    event_bus = EventBus()
    event_log = EventLog()
    memory = EpisodicMemory()
    memory_store = MemoryStore()
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

    print()
    print("=" * 40)
    print(f"{state['name']} {state['version']}")
    print("=" * 40)
    print(f"Status:           {state['status']}")
    print(f"Session:          {state['session']}")
    print(f"Created:          {state['created_at']}")
    print(f"Last wake:        {state['last_wake']}")
    print(f"Events processed: {state['events_processed']}")
    print(f"Memories stored:  {memory.count()}")
    print("=" * 40)
    print()

    print("\nRecent memories:")

    for event in memory.last(3):
        print(
            f"- [{event['timestamp']}] "
            f"{event['type']}: "
            f"{event['payload']}"
        )

    print()

    user_input = input("Say something to ANIMA: ")

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


    input("Press Enter to put ANIMA to sleep...")

    event_bus.emit("sleep")
    process_events(
        anima,
        event_bus,
        event_log,
        memory_filter,
        memory_store,
    )


    anima.sleep()

    print("ANIMA is sleeping.")


if __name__ == "__main__":
    main()
