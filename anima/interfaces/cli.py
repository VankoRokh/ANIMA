def _print_event(event):
    print(
        f"[EVENT] {event.timestamp} "
        f"{event.event_type} "
        f"{event.payload if event.payload else ''}"
    )


def _print_events(events):
    for event in events:
        _print_event(event)


def _print_status(
    anima,
    identity,
    memory,
):
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
            f"- [{stored_memory['created_at']}] "
            f"{stored_memory['type']}/{stored_memory['domain']}: "
            f"{stored_memory['content']}"
        )

    print()


def run_cli(
    *,
    runtime,
    anima,
    identity,
    memory,
):
    _print_events(runtime.wake())

    _print_status(
        anima,
        identity,
        memory,
    )

    try:
        user_input = input("Say something to ANIMA: ")
    except (KeyboardInterrupt, EOFError) as error:
        print()
        print(
            f"Session interrupted: "
            f"{type(error).__name__}."
        )

        _print_events(runtime.sleep())

        print("ANIMA is sleeping.")
        return

    _print_events(runtime.user_input(user_input))

    try:
        input("Press Enter to put ANIMA to sleep...")
    except (KeyboardInterrupt, EOFError) as error:
        print()
        print(
            f"Session interrupted: "
            f"{type(error).__name__}."
        )

    _print_events(runtime.sleep())

    print("ANIMA is sleeping.")
