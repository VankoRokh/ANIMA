from dataclasses import dataclass
from uuid import uuid4

from anima.agent.events import AgentExperienceCapture
from anima.core.event_bus import Event
from anima.memory.composer import RuleBasedComposer
from anima.memory.event_processing import EventProcessingCoordinator
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MEMORY_ID_PREFIX, MemoryStore
from anima.memory.processor import MemoryProcessor


AGENT_MEMORY_PROCESSOR_NAME = "agent_experience_memory"
AGENT_MEMORY_PROCESSOR_VERSION = "1.0"
AGENT_MEMORY_IMPORTANCE = 2
AGENT_MEMORY_EVENT_TYPES = {
    "agent.failure",
    "agent.strategy_change",
    "agent.action",
    "agent.observation",
    "agent.result",
}


def _require_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _payload(record, label):
    payload = record.get("payload")
    if not isinstance(payload, dict):
        raise ValueError(f"{label} payload must be an object")
    return payload


class AgentExperienceMemoryProcessor(MemoryProcessor):
    """Consolidate one completed agent run into one bounded self episodic Memory."""

    @staticmethod
    def _select(event):
        if not isinstance(event, Event):
            raise ValueError("AgentExperienceMemoryProcessor requires an Event")
        if event.event_type == "agent.result":
            return True, event.event_id, "selection:agent_result"
        return False, None, "selection:not_agent_result"

    def process_event(
        self,
        event,
        *,
        connection=None,
        trace_result=True,
    ):
        if not isinstance(event, Event):
            raise ValueError("AgentExperienceMemoryProcessor requires an Event")

        if event.event_type != "agent.result":
            result = self._result(
                event,
                action="skip",
                reasons=["selection:not_agent_result"],
            )
            if trace_result:
                self._trace_result(result)
            return result

        records = self._run_records(event)
        content = self._compose_episode(event, records)
        result = self._apply_with_connection(
            connection,
            lambda active: self._create_agent_episode_tx(
                active,
                event,
                records,
                content,
            ),
        )
        if trace_result:
            self._trace_result(result)
        return result

    def _run_records(self, result_event):
        result_payload = result_event.payload
        if not isinstance(result_payload, dict):
            raise ValueError("agent.result payload must be an object")
        run_id = _require_text(result_payload.get("run_id"), "agent.result run_id")
        _require_text(result_payload.get("goal_id"), "agent.result goal_id")

        selected = []
        found_result = False
        for record in self.event_log.load_events():
            if record["type"] in AGENT_MEMORY_EVENT_TYPES:
                payload = record.get("payload")
                if isinstance(payload, dict) and payload.get("run_id") == run_id:
                    selected.append(record)
            if record["id"] == result_event.event_id:
                found_result = True
                break

        if not found_result:
            raise ValueError(
                f"Raw agent.result Event {result_event.event_id} is missing from EventLog"
            )
        if not selected or selected[-1]["id"] != result_event.event_id:
            raise ValueError("agent.result must terminate its selected AgentRun event sequence")

        result_records = [record for record in selected if record["type"] == "agent.result"]
        if len(result_records) != 1:
            raise ValueError("AgentRun experience requires exactly one agent.result Event")
        return tuple(selected)

    def _compose_episode(self, result_event, records):
        result_payload = result_event.payload
        goal_id = _require_text(result_payload.get("goal_id"), "agent.result goal_id")
        run_status = _require_text(
            result_payload.get("run_status"),
            "agent.result run_status",
        )
        goal_status = _require_text(
            result_payload.get("goal_status"),
            "agent.result goal_status",
        )
        stop_reason = _require_text(
            result_payload.get("stop_reason"),
            "agent.result stop_reason",
        )
        turn_count = result_payload.get("turn_count")
        if not isinstance(turn_count, int) or isinstance(turn_count, bool) or turn_count < 0:
            raise ValueError("agent.result turn_count must be a non-negative integer")

        units = [
            (
                f"Goal {goal_id}: agent run ended with run_status={run_status} "
                f"and goal_status={goal_status} after {turn_count} turns."
            )
        ]

        for record in records:
            payload = _payload(record, record["type"])
            event_type = record["type"]
            if event_type == "agent.failure":
                tool = _require_text(payload.get("tool"), "agent.failure tool")
                version = _require_text(
                    payload.get("tool_version"),
                    "agent.failure tool_version",
                )
                receipt_status = _require_text(
                    payload.get("receipt_status"),
                    "agent.failure receipt_status",
                )
                error_code = payload.get("error_code")
                detail = f"Failure: {tool}@{version} ended with {receipt_status}"
                if isinstance(error_code, str) and error_code:
                    detail += f" ({error_code})"
                verification = payload.get("verification_outcome")
                if isinstance(verification, str) and verification not in {"", "none"}:
                    detail += f"; verification={verification}"
                units.append(detail + ".")
            elif event_type == "agent.strategy_change":
                before = _require_text(
                    payload.get("from_tool"),
                    "agent.strategy_change from_tool",
                )
                after = _require_text(
                    payload.get("to_tool"),
                    "agent.strategy_change to_tool",
                )
                units.append(
                    f"Strategy changed from {before} to {after} after a failed turn."
                )
            elif event_type == "agent.action":
                tool = _require_text(payload.get("tool"), "agent.action tool")
                version = _require_text(
                    payload.get("tool_version"),
                    "agent.action tool_version",
                )
                effect_class = _require_text(
                    payload.get("effect_class"),
                    "agent.action effect_class",
                )
                units.append(
                    f"Action: {tool}@{version} applied a {effect_class} effect."
                )
            elif event_type == "agent.observation":
                kind = _require_text(
                    payload.get("observation_kind"),
                    "agent.observation observation_kind",
                )
                outcome = _require_text(
                    payload.get("verification_outcome"),
                    "agent.observation verification_outcome",
                )
                criterion_satisfied = payload.get("criterion_satisfied")
                if type(criterion_satisfied) is not bool:
                    raise ValueError(
                        "agent.observation criterion_satisfied must be boolean"
                    )
                units.append(
                    (
                        f"Verification: {kind} produced {outcome}; "
                        f"criterion_satisfied={str(criterion_satisfied).lower()}."
                    )
                )

        units.append(f"Result: {stop_reason}.")
        composition = self.composer.compose_create(" ".join(units))
        return composition["content"]

    def _create_agent_episode_tx(self, connection, event, records, content):
        public_id = f"{MEMORY_ID_PREFIX}{uuid4()}"
        first_timestamp = records[0]["timestamp"]
        connection.execute(
            """
            INSERT INTO memories(
                public_id, type, domain, status, content, importance,
                created_at, updated_at, closed_at, merged_into
            ) VALUES (?, 'episodic', 'self', 'open', ?, ?, ?, ?, NULL, NULL)
            """,
            (
                public_id,
                content,
                AGENT_MEMORY_IMPORTANCE,
                first_timestamp,
                event.timestamp,
            ),
        )
        for record in records:
            connection.execute(
                "INSERT INTO memory_sources(memory_id, event_id) VALUES (?, ?)",
                (public_id, record["id"]),
            )

        row = connection.execute(
            "SELECT * FROM memories WHERE public_id = ?",
            (public_id,),
        ).fetchone()
        memory = self.memory_store._row_to_memory(row)
        return self._result(
            event,
            action="create",
            memory_id=memory["id"],
            reasons=[
                "selection:agent_result",
                f"aggregation:agent_run_events={len(records)}",
            ],
        )


@dataclass(frozen=True, slots=True)
class AgentMemoryIntegrationResult:
    publications: tuple
    processing_results: tuple
    memory_id: str

    def __post_init__(self):
        _require_text(self.memory_id, "AgentMemoryIntegrationResult memory_id")


class AgentMemoryIntegration:
    """Publish significant Agent experience and process it through Stage 1 exactly-once machinery."""

    def __init__(
        self,
        *,
        capture,
        memory_store,
        link_store,
        composer=None,
        trace=None,
    ):
        if not isinstance(capture, AgentExperienceCapture):
            raise TypeError("AgentMemoryIntegration capture must be an AgentExperienceCapture")
        if not isinstance(memory_store, MemoryStore):
            raise TypeError("AgentMemoryIntegration memory_store must be a MemoryStore")
        if not isinstance(link_store, LinkStore):
            raise TypeError("AgentMemoryIntegration link_store must be a LinkStore")
        if link_store.memory_store is not memory_store:
            raise ValueError(
                "AgentMemoryIntegration LinkStore must use the supplied MemoryStore"
            )
        if composer is not None and not isinstance(composer, RuleBasedComposer):
            raise TypeError("AgentMemoryIntegration composer must be a RuleBasedComposer or null")

        self.capture = capture
        self.memory_store = memory_store
        self.event_log = capture.publisher.event_log
        self.processor = AgentExperienceMemoryProcessor(
            memory_store=memory_store,
            event_log=self.event_log,
            link_store=link_store,
            composer=composer,
            trace=trace,
        )
        self.coordinator = EventProcessingCoordinator(
            memory_store=memory_store,
            memory_processor=self.processor,
            event_log=self.event_log,
            trace=trace,
            processor_name=AGENT_MEMORY_PROCESSOR_NAME,
            processor_version=AGENT_MEMORY_PROCESSOR_VERSION,
        )

    def integrate(self, result):
        publications = self.capture.capture(result)
        processing_results = tuple(
            self.coordinator.process(publication.event)
            for publication in publications
        )
        memory_ids = {
            item["memory_id"]
            for item in processing_results
            if item["memory_id"] is not None
        }
        if len(memory_ids) != 1:
            raise ValueError(
                "AgentRun memory integration must resolve to exactly one episodic Memory"
            )
        return AgentMemoryIntegrationResult(
            publications=tuple(publications),
            processing_results=processing_results,
            memory_id=next(iter(memory_ids)),
        )

    def recover(self):
        return self.coordinator.recover()


__all__ = [
    "AGENT_MEMORY_EVENT_TYPES",
    "AGENT_MEMORY_IMPORTANCE",
    "AGENT_MEMORY_PROCESSOR_NAME",
    "AGENT_MEMORY_PROCESSOR_VERSION",
    "AgentExperienceMemoryProcessor",
    "AgentMemoryIntegration",
    "AgentMemoryIntegrationResult",
]
