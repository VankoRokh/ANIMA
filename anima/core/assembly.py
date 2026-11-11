"""Single composition root for the existing ANIMA runtime.

Incremental Core composition: P1 runtime, P2 observations, P3-A decisions,
optional P3-B sandbox-local door actions, and P3-C bounded auto scheduling.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from anima.config.paths import get_data_dir
from anima.core.belief import PropertyRule
from anima.core.dispatch import CoreEventDispatcher
from anima.core.event_bus import EventBus
from anima.core.ingress import CoreIngress, SourceRegistration
from anima.core.goal_decision import CoreGoalDecision
from anima.core.door_execution import CoreDoorExecution
from anima.core.autonomy import CoreAutonomy
from anima.core.door_world import DoorWorldPort, VirtualDoorWorld, door_tool_registry, door_handlers
from anima.core.identity import Identity
from anima.core.state import AnimaState
from anima.execution.contracts import ActionSpec
from anima.execution.store import ExecutionStore
from anima.execution.sandbox import SandboxExecutor
from anima.tasks.store import TaskStore
from anima.diagnostics.metrics import DiagnosticMetrics
from anima.diagnostics.trace import DiagnosticTrace
from anima.internal_state.runtime_integration import InternalStateRuntime
from anima.internal_state.store import InternalStateStore
from anima.memory.composer import RuleBasedComposer
from anima.memory.episodic import EpisodicMemory
from anima.memory.event_log import EventLog
from anima.memory.event_retrieval import EventRetrieval
from anima.memory.event_processing import EventProcessingCoordinator
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.processor import MemoryProcessor
from anima.runtime import Runtime


@dataclass(frozen=True, slots=True)
class CoreAssembly:
    """Named runtime dependencies; no side effects beyond initial store setup."""

    data_dir: Path
    state: AnimaState
    identity: Identity
    event_bus: EventBus
    event_log: EventLog
    memory_store: MemoryStore
    link_store: LinkStore
    memory: EpisodicMemory
    trace: DiagnosticTrace
    memory_composer: RuleBasedComposer
    memory_processor: MemoryProcessor
    event_processing: EventProcessingCoordinator
    metrics: DiagnosticMetrics
    internal_state_store: InternalStateStore
    internal_state: InternalStateRuntime
    runtime: Runtime
    core_events: CoreEventDispatcher | None
    core_decision: CoreGoalDecision | None
    core_execution: CoreDoorExecution | None
    core_autonomy: CoreAutonomy | None
    event_retrieval: EventRetrieval | None


def build_core(
    data_dir: str | Path | None = None,
    *,
    sources: Mapping[str, SourceRegistration] | None = None,
    properties: Mapping[tuple[str, str], PropertyRule] | None = None,
    goal_actions: Mapping[tuple[str, str, str], ActionSpec] | None = None,
    virtual_door_root: str | Path | None = None,
    world_port: DoorWorldPort | None = None,
    world_handlers: Mapping[tuple[str, str], object] | None = None,
    auto_core: bool = False,
    enable_event_retrieval: bool = False,
) -> CoreAssembly:
    """Build the current, proven runtime stack once for CLI and headless use.

    No wakeup is implicit. Caller owns lifecycle. Registered Core inputs and
    a bounded decision driver and explicit virtual-world adapter can be opted
    in. P3-C automation is opt-in, synchronous and bounded per trigger.
    """

    if (sources is None) != (properties is None):
        raise ValueError("Core inputs require both source and property registries")
    if goal_actions is not None and sources is None:
        raise ValueError("Core goal decisions require registered Core input and Belief")
    if virtual_door_root is not None and goal_actions is None:
        raise ValueError("Core world execution requires typed Goal decision configuration")
    if world_port is not None:
        if not isinstance(world_port, DoorWorldPort):
            raise TypeError("world_port must implement DoorWorldPort")
        if virtual_door_root is not None or goal_actions is None or world_handlers is None:
            raise ValueError("Injected world requires a Goal registry and explicit handlers, not virtual_door_root")
    elif world_handlers is not None:
        raise ValueError("world_handlers require explicit world_port")
    if type(auto_core) is not bool:
        raise TypeError("auto_core must be boolean")
    if type(enable_event_retrieval) is not bool:
        raise TypeError("enable_event_retrieval must be boolean")
    if auto_core and virtual_door_root is None and world_port is None:
        raise ValueError("Autonomous Core requires explicitly registered virtual world")
    root = (get_data_dir() if data_dir is None else Path(data_dir)).expanduser().resolve()
    state = AnimaState(root / "state.json")
    identity = Identity(root / "identity.json")
    event_bus = EventBus()
    event_log = EventLog(root / "events.jsonl")
    memory_store = MemoryStore(root / "memory.db")
    event_retrieval = (
        EventRetrieval(event_log, root / "event_index.db", memory_store=memory_store)
        if enable_event_retrieval else None
    )
    link_store = LinkStore(memory_store)
    memory = EpisodicMemory(memory_store)
    trace = DiagnosticTrace()
    memory_composer = RuleBasedComposer()
    memory_processor = MemoryProcessor(
        memory_store=memory_store,
        event_log=event_log,
        link_store=link_store,
        composer=memory_composer,
        trace=trace,
    )
    event_processing = EventProcessingCoordinator(
        memory_store=memory_store,
        memory_processor=memory_processor,
        event_log=event_log,
        trace=trace,
    )
    core_events = None
    if sources is not None and properties is not None:
        ingress = CoreIngress(
            root / "core_state.db",
            sources=sources,
            properties=properties,
        )
        core_events = CoreEventDispatcher(
            ingress=ingress,
            event_log=event_log,
            event_processing=event_processing,
        )
    metrics = DiagnosticMetrics()
    internal_state_store = InternalStateStore(root / "internal_state.db")
    internal_state = InternalStateRuntime(internal_state_store, trace=trace)
    core_decision = None
    if goal_actions is not None:
        task_store = TaskStore(root / "tasks.db")
        core_decision = CoreGoalDecision(
            database_file=root / "core_work.db",
            goals=internal_state.goals,
            tasks=task_store,
            ingress=core_events.ingress,
            actions=goal_actions,
        )
    core_execution = None
    if virtual_door_root is not None or world_port is not None:
        world = world_port if world_port is not None else VirtualDoorWorld(virtual_door_root)
        registry = door_tool_registry()
        execution_store = ExecutionStore(root / "execution.db")
        executor = SandboxExecutor(
            root=world.root,
            registry=registry,
            store=execution_store,
            handlers=world_handlers if world_port is not None else door_handlers(),
        )
        core_execution = CoreDoorExecution(
            decisions=core_decision,
            internal_state=internal_state,
            world=world,
            execution_store=execution_store,
            registry=registry,
            executor=executor,
        )
    core_autonomy = (
        CoreAutonomy(decisions=core_decision, executor=core_execution)
        if auto_core else None
    )
    runtime = Runtime(
        anima=state,
        identity=identity,
        event_bus=event_bus,
        event_log=event_log,
        memory=memory,
        memory_processor=memory_processor,
        event_processing=event_processing,
        trace=trace,
        metrics=metrics,
        internal_state=internal_state,
        core_events=core_events,
        core_decision=core_decision,
        core_execution=core_execution,
        core_autonomy=core_autonomy,
    )
    return CoreAssembly(
        data_dir=root,
        state=state,
        identity=identity,
        event_bus=event_bus,
        event_log=event_log,
        memory_store=memory_store,
        link_store=link_store,
        memory=memory,
        trace=trace,
        memory_composer=memory_composer,
        memory_processor=memory_processor,
        event_processing=event_processing,
        metrics=metrics,
        internal_state_store=internal_state_store,
        internal_state=internal_state,
        runtime=runtime,
        core_events=core_events,
        core_decision=core_decision,
        core_execution=core_execution,
        core_autonomy=core_autonomy,
        event_retrieval=event_retrieval,
    )


__all__ = ["CoreAssembly", "build_core"]
