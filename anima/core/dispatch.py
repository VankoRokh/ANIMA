"""P2-C: idempotent Core event outbox → legacy event-processing bridge.

The Core SQLite event/Belief journal remains canonical for world observations.
The legacy EventLog is a downstream compatibility projection (not a second
Belief writer). There is no cross-DB transaction, so each boundary can replay.
"""

from dataclasses import dataclass
from typing import Callable

from anima.core.event_bus import Event
from anima.core.ingress import CoreIngress
from anima.memory.event_log import EventLog
from anima.memory.event_processing import EventProcessingCoordinator


@dataclass(frozen=True, slots=True)
class CoreDispatchTurn:
    event_id: str
    disposition: str


class CoreEventDispatcher:
    """Deliver admitted, validated observations without duplicate legacy effects.

    The service is invoked by the Core Runtime at recovery and ingress. It is
    deliberately synchronous, bounded per drain call, and never calls Goal,
    Task, tools, a model, or a virtual-world effect.

    fault_hook(stage, event_id) may inject controlled test crashes only.
    """

    def __init__(
        self,
        *,
        ingress: CoreIngress,
        event_log: EventLog,
        event_processing: EventProcessingCoordinator,
        fault_hook: Callable[[str, str], None] | None = None,
    ):
        if not isinstance(ingress, CoreIngress):
            raise TypeError("CoreEventDispatcher requires CoreIngress")
        if ingress.beliefs is None:
            raise ValueError("P2-C requires registered Core Belief projection")
        if not isinstance(event_log, EventLog):
            raise TypeError("CoreEventDispatcher requires EventLog")
        if not isinstance(event_processing, EventProcessingCoordinator):
            raise TypeError("CoreEventDispatcher requires EventProcessingCoordinator")
        if event_processing.event_log is not event_log:
            raise ValueError("Dispatcher and Memory processing must share EventLog")
        if fault_hook is not None and not callable(fault_hook):
            raise TypeError("fault_hook must be callable")
        self.ingress = ingress
        self.event_log = event_log
        self.event_processing = event_processing
        self.fault_hook = fault_hook

    def _fault(self, stage, event_id):
        if self.fault_hook is not None:
            self.fault_hook(stage, event_id)

    @staticmethod
    def _legacy_event(record):
        return Event(
            "world.observation",
            {
                "contract": "core.observation/0.1",
                "kind": record["kind"],
                "observation": record["payload"],
                "source_ref": record["source_ref"],
                "producer_ref": record["producer_ref"],
                "occurrence_id": record["occurrence_id"],
                "occurrence_version": record["occurrence_version"],
            },
            source="core.ingress",
            session_id=None,
            references=[],
            event_id=record["event_id"],
            timestamp=record["received_at"],
        )

    def _ensure_legacy_written(self, event):
        """Never overwrite or silently re-accept a conflicting legacy ID."""
        match = None
        for existing in self.event_log.load_events():
            if existing["id"] != event.event_id:
                continue
            match = existing
            break
        if match is None:
            self.event_log.write(event)
            return
        if match != event.to_dict():
            raise ValueError(
                f"Legacy EventLog identity conflict for Core event {event.event_id}"
            )

    def drain(self, *, max_events=32):
        if type(max_events) is not int or max_events < 1:
            raise ValueError("max_events must be a positive integer")
        # Bounded iteration; further work stays safely pending in Core journal.
        turns = []
        for event_id in self.ingress.pending_event_ids(limit=max_events):
            record = self.ingress.get_event(event_id)
            if record is None:
                raise RuntimeError(f"Outbox event {event_id} is missing from journal")
            projection = self.ingress.observation_outcome(event_id)
            # Old P2-A rows or rejected typed observations are not valid
            # world observations; do not launder them into legacy history.
            if projection is None or projection["outcome"].startswith("REJECTED_"):
                self._fault("before_filtered_ack", event_id)
                self.ingress.acknowledge_dispatch(event_id, disposition="filtered")
                turns.append(CoreDispatchTurn(event_id, "filtered"))
                continue

            event = self._legacy_event(record)
            self._ensure_legacy_written(event)
            self._fault("after_legacy_append", event_id)

            # Stage 1 coordinator verifies the legacy raw event and stores
            # idempotent memory projection status. World observations skip
            # episodic Memory under existing selection rules.
            self.event_processing.process(event)
            self._fault("after_legacy_projection", event_id)

            self.ingress.acknowledge_dispatch(event_id, disposition="forwarded")
            self._fault("after_core_ack", event_id)
            turns.append(CoreDispatchTurn(event_id, "forwarded"))

        return tuple(turns)


__all__ = ["CoreDispatchTurn", "CoreEventDispatcher"]
