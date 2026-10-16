class Runtime:
    """Orchestrate ANIMA lifecycle independently from user interfaces."""

    def __init__(
        self,
        *,
        anima,
        identity,
        event_bus,
        event_log,
        memory,
        memory_filter,
        memory_store,
    ):
        self.anima = anima
        self.identity = identity
        self.event_bus = event_bus
        self.event_log = event_log
        self.memory = memory
        self.memory_filter = memory_filter
        self.memory_store = memory_store

    def _process_events(self):
        processed = []

        while self.event_bus.has_events():
            event = self.event_bus.next_event()

            self.event_log.write(event)

            if self.memory_filter.is_meaningful(event):
                memory = self.memory_filter.create_memory(event)
                self.memory_store.write(memory)

            self.anima.register_event()
            processed.append(event)

        return processed

    def wake(self):
        self.anima.wake()
        self.event_bus.emit("wake")
        return self._process_events()

    def user_input(self, text):
        self.event_bus.emit(
            "user_input",
            {
                "text": text,
            },
        )
        return self._process_events()

    def sleep(self):
        if self.anima.get()["status"] == "sleeping":
            return []

        self.event_bus.emit("sleep")
        processed = self._process_events()
        self.anima.sleep()
        return processed

    def snapshot(self):
        identity = self.identity.get()
        state = self.anima.get()

        return {
            "identity": {
                "instance_id": identity["instance_id"],
                "created_at": identity["created_at"],
            },
            "state": {
                "name": state["name"],
                "version": state["version"],
                "status": state["status"],
                "session": state["session"],
                "created_at": state["created_at"],
                "last_wake": state["last_wake"],
                "last_sleep": state["last_sleep"],
                "events_processed": state["events_processed"],
            },
            "memory": {
                "count": self.memory.count(),
            },
        }