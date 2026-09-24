from anima.core.state import AnimaState
from anima.core.event_bus import EventBus


def process_events(anima, event_bus):
    while event_bus.has_events():
        event = event_bus.next_event()

        print(
            f"[EVENT] {event.timestamp} "
            f"{event.event_type} "
            f"{event.payload if event.payload else ''}"
        )

        anima.register_event()


def main():
    anima = AnimaState()
    event_bus = EventBus()

    anima.wake()

    event_bus.emit("wake")
    process_events(anima, event_bus)

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
    print("=" * 40)
    print()

    user_input = input("Say something to ANIMA: ")

    event_bus.emit(
        "user_input",
        {
            "text": user_input
        }
    )

    process_events(anima, event_bus)

    input("Press Enter to put ANIMA to sleep...")

    event_bus.emit("sleep")
    process_events(anima, event_bus)

    anima.sleep()

    print("ANIMA is sleeping.")


if __name__ == "__main__":
    main()
