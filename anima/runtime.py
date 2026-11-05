from anima.core.dispatch import CoreEventDispatcher
from anima.core.goal_decision import CoreGoalDecision
from anima.core.door_execution import CoreDoorExecution
from anima.core.autonomy import CoreAutonomy
from anima.internal_state.runtime_integration import InternalStateRuntime
from anima.sleep.runtime_integration import SleepRuntimeIntegration


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
        sleep_runtime=None,
        core_events=None,
        core_decision=None,
        core_execution=None,
        core_autonomy=None,
    ):
        if internal_state is not None and not isinstance(
            internal_state,
            InternalStateRuntime,
        ):
            raise TypeError(
                "Runtime internal_state must be an InternalStateRuntime or null"
            )
        if sleep_runtime is not None and not isinstance(
            sleep_runtime,
            SleepRuntimeIntegration,
        ):
            raise TypeError(
                "Runtime sleep_runtime must be a SleepRuntimeIntegration or null"
            )

        if core_events is not None and not isinstance(
            core_events, CoreEventDispatcher
        ):
            raise TypeError("Runtime core_events must be CoreEventDispatcher or null")
        if core_decision is not None and not isinstance(
            core_decision, CoreGoalDecision
        ):
            raise TypeError("Runtime core_decision must be CoreGoalDecision or null")
        if core_execution is not None and not isinstance(
            core_execution, CoreDoorExecution
        ):
            raise TypeError("Runtime core_execution must be CoreDoorExecution or null")
        if core_autonomy is not None and not isinstance(core_autonomy, CoreAutonomy):
            raise TypeError("Runtime core_autonomy must be CoreAutonomy or null")
        if core_autonomy is not None and core_autonomy.executor is not core_execution:
            raise ValueError("Autonomy must share registered Core executor")

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
        self.sleep_runtime = sleep_runtime
        self.core_events = core_events
        self.core_decision = core_decision
        self.core_execution = core_execution
        self.core_autonomy = core_autonomy
        self._recovery_checked = False

    def _session_id(self):
        session = self.anima.get()["session"]

        if session <= 0:
            return None

        return f"session_{session:08d}"

    def _drain_core_events(self, *, max_events=32):
        if self.core_events is None:
            return ()
        try:
            turns = self.core_events.drain(max_events=max_events)
            self.anima.reconcile_events_processed(
                self.event_processing.finalized_count()
            )
            return turns
        except Exception:
            self._recovery_checked = False
            raise

    def _ensure_recovered(self):
        if not self._recovery_checked:
            self.event_processing.recover()
            self.anima.reconcile_events_processed(
                self.event_processing.finalized_count()
            )
            if self.sleep_runtime is not None:
                self.sleep_runtime.recover()
            self._recovery_checked = True
        # Persistent outbox is the wake signal: after crash or on each normal
        # lifecycle entry, dispatch a bounded batch without needing RAM queue.
        self._drain_core_events()

    def ingest_core_event(self, raw, *, source_ref):
        """Trusted adapter path; raw caller names are not authentication."""
        if self.core_events is None:
            raise RuntimeError("Core event ingress is not configured")
        self._ensure_recovered()
        admitted = self.core_events.ingress.admit(raw, source_ref=source_ref)
        if admitted.status in {"ACCEPTED", "ALREADY_SEEN"}:
            self._drain_core_events()
            if self.core_autonomy is not None:
                self.run_core_autonomous()
        return admitted

    def read_core_belief(self, subject_ref, predicate_ref, *, as_of_tick=None):
        if self.core_events is None:
            raise RuntimeError("Core event ingress is not configured")
        return self.core_events.ingress.read_belief(
            subject_ref, predicate_ref, as_of_tick=as_of_tick
        )

    def _require_core_decision(self):
        if self.core_decision is None:
            raise RuntimeError("Core Goal/Decision is not configured")
        return self.core_decision

    def bind_core_goal(self, criterion):
        """Bind typed criterion; opt-in P3-C treats a new binding as work."""
        inserted = self._require_core_decision().bind(criterion)
        if inserted and self.core_autonomy is not None:
            self.run_core_autonomous()
        return inserted

    def plan_core_step(self, goal_id, *, as_of_tick):
        """Bounded proposal step; no Tool invocation or Goal completion."""
        planner = self._require_core_decision()
        self._ensure_recovered()
        return planner.step(goal_id, as_of_tick=as_of_tick)

    def plan_next_core_step(self, *, as_of_tick):
        planner = self._require_core_decision()
        self._ensure_recovered()
        return planner.step_next(as_of_tick=as_of_tick)

    def run_core_door_goal(self, goal_id):
        """P3-B explicitly triggered bounded action + independent readback.

        This does not schedule itself or confer authority to unregistered tools.
        """
        if self.core_execution is None:
            raise RuntimeError("Core door execution is not configured")
        self._ensure_recovered()
        try:
            return self.core_execution.run(goal_id)
        finally:
            # World observations are canonical in Core DB first. Legacy outbox
            # catch-up remains bounded and replay-safe on the next Runtime entry.
            self._drain_core_events()

    def run_core_autonomous(
        self, *, max_steps=4, max_triggers=32, max_new_events=64
    ):
        """Bounded synchronous scheduler; no thread or unbounded polling."""
        if self.core_autonomy is None:
            raise RuntimeError("Core autonomous scheduler is not configured")
        self._ensure_recovered()
        try:
            return self.core_autonomy.drain(
                max_steps=max_steps,
                max_triggers=max_triggers,
                max_new_events=max_new_events,
            )
        finally:
            self._drain_core_events()

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
        if self.sleep_runtime is not None:
            self.sleep_runtime.prepare_wake()
        self.anima.wake()
        self.event_bus.emit(
            "system.wake",
            source="runtime",
            session_id=self._session_id(),
        )
        processed = self._process_events()
        if self.core_autonomy is not None:
            self.run_core_autonomous()
        return processed

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
        if self.sleep_runtime is not None:
            self.sleep_runtime.enter_sleep()

        self._trace("runtime: sleeping")

        return processed

    def _require_sleep_runtime(self):
        if self.sleep_runtime is None:
            raise RuntimeError(
                "Sleep runtime is not configured"
            )
        return self.sleep_runtime

    def activate_sleep_job(self, job_id, *, budget=None):
        return self._measure(
            "runtime.sleep.activate_job",
            lambda: self._require_sleep_runtime().activate_job(
                job_id,
                budget=budget,
            ),
        )

    def configure_sleep_budget(self, job_id, budget):
        return self._measure(
            "runtime.sleep.configure_budget",
            lambda: self._require_sleep_runtime().configure_budget(
                job_id,
                budget,
            ),
        )

    def process_sleep_work(
        self,
        work_item_id,
        chunks,
        *,
        max_new_chunks=1,
    ):
        if self.anima.get()["status"] != "sleeping":
            raise RuntimeError(
                "Sleep work can be processed only while ANIMA is sleeping"
            )
        return self._measure(
            "runtime.sleep.process_work",
            lambda: self._require_sleep_runtime().process_work(
                work_item_id,
                chunks,
                max_new_chunks=max_new_chunks,
            ),
        )

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
            "sleep": (
                self.sleep_runtime.snapshot()
                if self.sleep_runtime is not None
                else None
            ),
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
