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
        memory_processor,
        trace=None,
        metrics=None,
    ):
        self.trace = trace
        self.metrics = metrics
        self.anima = anima
        self.identity = identity
        self.event_bus = event_bus
        self.event_log = event_log
        self.memory = memory
        self.memory_processor = memory_processor

    def _session_id(self):
        session = self.anima.get()["session"]

        if session <= 0:
            return None

        return f"session_{session:08d}"

    def _process_events(self):
        processed = []

        while self.event_bus.has_events():
            event = self.event_bus.next_event()

            self.event_log.write(event)
            memory_result = self.memory_processor.process_event(event)
            self.anima.register_event()

            self._trace(
                f"event: {event.event_type} processed, "
                f"memory={memory_result['action']}"
            )

            processed.append(event)

        return processed

    def wake(self):
        self._trace("runtime: wake requested")

        return self._measure(
            "runtime.wake",
            self._wake,
        )

    def _wake(self):
        self.anima.wake()
        self.event_bus.emit(
            "system.wake",
            source="runtime",
            session_id=self._session_id(),
        )
        return self._process_events()

    def user_input(self, text):
        self._trace("runtime: user_input received")

        return self._measure(
            "runtime.user_input",
            lambda: self._user_input(text),
        )

    def _user_input(self, text):
        self.event_bus.emit(
            "conversation.user",
            {
                "text": text,
            },
            source="user",
            session_id=self._session_id(),
        )

        return self._process_events()

    def sleep(self):
        if self.anima.get()["status"] == "sleeping":
            self._trace(
                "runtime: sleep skipped, already sleeping"
            )
            return []

        self._trace("runtime: sleep requested")

        return self._measure(
            "runtime.sleep",
            self._sleep,
        )

    def _sleep(self):
        self.event_bus.emit(
            "system.sleep",
            source="runtime",
            session_id=self._session_id(),
        )
        processed = self._process_events()
        self.anima.sleep()

        self._trace("runtime: sleeping")

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
            "diagnostics": {
                "metrics": (
                    self.metrics.snapshot()
                    if self.metrics is not None
                    else None
                ),
            },
        }

    def _trace(self, message):
        if self.trace is not None:
            self.trace.record(message)

    def _measure(self, name, operation):
        if self.metrics is None:
            return operation()

        return self.metrics.measure(
            name,
            operation,
        )
