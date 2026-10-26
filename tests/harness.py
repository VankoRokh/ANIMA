from pathlib import Path

from anima.core.event_bus import EventBus
from anima.core.identity import Identity
from anima.core.state import AnimaState
from anima.memory.composer import RuleBasedComposer
from anima.memory.episodic import EpisodicMemory
from anima.memory.event_log import EventLog
from anima.memory.event_processing import EventProcessingCoordinator
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor
from anima.runtime import Runtime
from anima.scenario import ScenarioRunner
from anima.diagnostics.trace import DiagnosticTrace
from anima.diagnostics.metrics import DiagnosticMetrics
from anima.internal_state.runtime_integration import InternalStateRuntime
from anima.internal_state.store import InternalStateStore


class AnimaTestHarness:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)

        self.state = AnimaState(
            self.data_dir / "state.json"
        )

        self.identity = Identity(
            self.data_dir / "identity.json"
        )

        self.event_bus = EventBus()

        self.event_log = EventLog(
            self.data_dir / "events.jsonl"
        )

        self.memory_store = MemoryStore(
            self.data_dir / "memory.db"
        )

        self.link_store = LinkStore(
            self.memory_store
        )

        self.memory = EpisodicMemory(
            self.memory_store
        )

        self.trace = DiagnosticTrace()
        self.memory_composer = RuleBasedComposer()
        self.memory_processor = MemoryProcessor(
            memory_store=self.memory_store,
            event_log=self.event_log,
            link_store=self.link_store,
            composer=self.memory_composer,
            trace=self.trace,
        )
        self.event_processing = EventProcessingCoordinator(
            memory_store=self.memory_store,
            memory_processor=self.memory_processor,
            event_log=self.event_log,
            trace=self.trace,
        )
        self.metrics = DiagnosticMetrics()
        self.internal_state_store = InternalStateStore(
            self.data_dir / "internal_state.db"
        )
        self.internal_state = InternalStateRuntime(
            self.internal_state_store,
            trace=self.trace,
        )

        self.runtime = Runtime(
            anima=self.state,
            identity=self.identity,
            event_bus=self.event_bus,
            event_log=self.event_log,
            memory=self.memory,
            memory_processor=self.memory_processor,
            event_processing=self.event_processing,
            trace=self.trace,
            metrics=self.metrics,
            internal_state=self.internal_state,
        )

        self.scenario_runner = ScenarioRunner(
            self.runtime
        )

    def run_scenario(self, steps):
        return self.scenario_runner.run(steps)

    def snapshot(self):
        return self.runtime.snapshot()
