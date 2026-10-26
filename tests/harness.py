from pathlib import Path

from anima.core.event_bus import EventBus
from anima.core.identity import Identity
from anima.core.state import AnimaState
from anima.memory.episodic import EpisodicMemory
from anima.memory.event_log import EventLog
from anima.memory.filter import MemoryFilter
from anima.memory.memory_store import MemoryStore
from anima.runtime import Runtime
from anima.scenario import ScenarioRunner
from anima.diagnostics.trace import DiagnosticTrace
from anima.diagnostics.metrics import DiagnosticMetrics


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

        self.memory = EpisodicMemory(
            self.memory_store
        )

        self.memory_filter = MemoryFilter()

        self.trace = DiagnosticTrace()
        self.metrics = DiagnosticMetrics()

        self.runtime = Runtime(
            anima=self.state,
            identity=self.identity,
            event_bus=self.event_bus,
            event_log=self.event_log,
            memory=self.memory,
            memory_filter=self.memory_filter,
            memory_store=self.memory_store,
            trace=self.trace,
            metrics=self.metrics,
        )

        self.scenario_runner = ScenarioRunner(
            self.runtime
        )

    def run_scenario(self, steps):
        return self.scenario_runner.run(steps)

    def snapshot(self):
        return self.runtime.snapshot()
