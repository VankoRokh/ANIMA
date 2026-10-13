def _print_event(event):
    print(
        f"[EVENT] {event.timestamp} "
        f"{event.event_type} "
        f"{event.payload if event.payload else ''}"
    )


def _process_events(
    anima,
    event_bus,
    event_log,
    memory_filter,
    memory_store,
):
    while event_bus.has_events():
        event = event_bus.next_event()

        _print_event(event)
        event_log.write(event)

        if memory_filter.is_meaningful(event):
            memory = memory_filter.create_memory(event)
            memory_store.write(memory)

        anima.register_event()


def _put_to_sleep(
    anima,
    event_bus,
    event_log,
    memory_filter,
    memory_store,
):
    if anima.get()["status"] == "sleeping":
        return

    event_bus.emit("sleep")

    _process_events(
        anima,
        event_bus,
        event_log,
        memory_filter,
        memory_store,
    )

    anima.sleep()


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
            f"- [{stored_memory['timestamp']}] "
            f"{stored_memory['source']}: "
            f"{stored_memory['content']}"
        )

    print()


def run_cli(
    *,
    anima,
    identity,
    event_bus,
    event_log,
    memory,
    memory_store,
    memory_filter,
):
    anima.wake()

    event_bus.emit("wake")
    _process_events(
        anima,
        event_bus,
        event_log,
        memory_filter,
        memory_store,
    )

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

        _put_to_sleep(
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

    _process_events(
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

    _put_to_sleep(
        anima,
        event_bus,
        event_log,
        memory_filter,
        memory_store,
    )

    print("ANIMA is sleeping.")
