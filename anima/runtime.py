from anima.internal_state.runtime_integration import InternalStateRuntime


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
        event_processing,
        trace=None,
        metrics=None,
        internal_state=None,
    ):
        if internal_state is not None and not isinstance(
            internal_state,
            InternalStateRuntime,
        ):
            raise TypeError(
                "Runtime internal_state must be an InternalStateRuntime or null"
            )

        self.trace = trace
        self.metrics = metrics
        self.anima = anima
        self.identity = identity
        self.event_bus = event_bus
        self.event_log = event_log
        self.memory = memory
        self.memory_processor = memory_processor
        self.event_processing = event_processing
        self.internal_state = internal_state
        self._recovery_checked = False

    def _session_id(self):
        session = self.anima.get()["session"]

        if session <= 0:
            return None

        return f"session_{session:08d}"

    def _ensure_recovered(self):
        if self._recovery_checked:
            return

        self.event_processing.recover()
        self.anima.reconcile_events_processed(
            self.event_processing.finalized_count()
        )
        self._recovery_checked = True

    def _process_events(self):
        processed = []

        while self.event_bus.has_events():
            event = self.event_bus.next_event()

            self.event_log.write(event)
            try:
                memory_result = self.event_processing.process(event)
            except Exception:
                self._recovery_checked = False
                raise

            self.anima.reconcile_events_processed(
                self.event_processing.finalized_count()
            )

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
        self._ensure_recovered()
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
        self._ensure_recovered()
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
        self._ensure_recovered()
        self.event_bus.emit(
            "system.sleep",
            source="runtime",
            session_id=self._session_id(),
        )
        processed = self._process_events()
        self.anima.sleep()

        self._trace("runtime: sleeping")

        return processed

    def _require_internal_state(self):
        if self.internal_state is None:
            raise RuntimeError(
                "Internal State runtime is not configured"
            )
        return self.internal_state

    def create_goal(self, **kwargs):
        return self._measure(
            "runtime.internal_state.create_goal",
            lambda: self._require_internal_state().create_goal(**kwargs),
        )

    def process_state_signal(self, signal):
        return self._measure(
            "runtime.internal_state.signal",
            lambda: self._require_internal_state().process_signal(signal),
        )

    def observe_goal(self, observation):
        return self._measure(
            "runtime.internal_state.goal_observation",
            lambda: self._require_internal_state().observe_goal(observation),
        )

    def evaluate_internal_time(self, *, now, mode, period_started_at):
        return self._measure(
            "runtime.internal_state.time",
            lambda: self._require_internal_state().evaluate_time(
                now=now,
                mode=mode,
                period_started_at=period_started_at,
            ),
        )

    def choose(self, goal_id, candidates):
        return self._measure(
            "runtime.internal_state.choice",
            lambda: self._require_internal_state().choose(
                goal_id,
                candidates,
            ),
        )

    def arbitrate_goals(self):
        return self._measure(
            "runtime.internal_state.goal_arbitration",
            self._require_internal_state().arbitrate_goals,
        )

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
            "internal_state": (
                self.internal_state.snapshot()
                if self.internal_state is not None
                else None
            ),
            "diagnostics": {
                "metrics": (
                    self.metrics.snapshot()
                    if self.metrics is not None
                    else None
                ),
                "trace": (
                    self.trace.entries()
                    if self.trace is not None
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
