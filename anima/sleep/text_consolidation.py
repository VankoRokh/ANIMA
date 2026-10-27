from dataclasses import dataclass

from anima.memory.event_log import EventLog
from anima.memory.knowledge import KnowledgeLayer
from anima.memory.memory_store import MemoryStore
from anima.sleep.contracts import SourceRef, WorkItem
from anima.sleep.processors import (
    ChunkResult,
    FinalizeResult,
    ProcessorDescriptor,
    SleepProcessor,
)


def _require_non_empty_string(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")


def _require_non_negative_int(value, label):
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ValueError(f"{label} must be a non-negative integer")


def _normalize_text(value):
    if not isinstance(value, str):
        raise ValueError("Text fragment text must be a string")
    return " ".join(value.split())


@dataclass(frozen=True, slots=True)
class TextFragment:
    group: str
    text: str

    def __post_init__(self):
        _require_non_empty_string(self.group, "Text fragment group")
        if not isinstance(self.text, str):
            raise ValueError("Text fragment text must be a string")

    def to_dict(self):
        return {"group": self.group, "text": self.text}


@dataclass(frozen=True, slots=True)
class TextSourceRecord:
    source_ref: SourceRef
    fragments: tuple[TextFragment, ...]

    def __post_init__(self):
        if not isinstance(self.source_ref, SourceRef):
            raise ValueError("TextSourceRecord source_ref must be a SourceRef")
        if not isinstance(self.fragments, tuple):
            raise ValueError("TextSourceRecord fragments must be a tuple")
        if not all(isinstance(fragment, TextFragment) for fragment in self.fragments):
            raise ValueError("TextSourceRecord fragments must contain TextFragment objects")

    def to_chunk(self):
        return {
            "source": self.source_ref.to_dict(),
            "fragments": [fragment.to_dict() for fragment in self.fragments],
        }


def _event_text_fragments(value, *, group):
    fragments = []
    if isinstance(value, str):
        fragments.append(TextFragment(group=group, text=value))
    elif isinstance(value, dict):
        for key in sorted(value, key=lambda item: str(item)):
            fragments.extend(
                _event_text_fragments(
                    value[key],
                    group=f"{group}.{key}",
                )
            )
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            fragments.extend(
                _event_text_fragments(
                    item,
                    group=f"{group}[{index}]",
                )
            )
    return fragments


class TextSourceReader:
    """Read baseline text sources without changing their owning stores."""

    def __init__(
        self,
        *,
        event_log=None,
        memory_store=None,
        knowledge_layer=None,
    ):
        if event_log is not None and not isinstance(event_log, EventLog):
            raise ValueError("event_log must be an EventLog or null")
        if memory_store is not None and not isinstance(memory_store, MemoryStore):
            raise ValueError("memory_store must be a MemoryStore or null")
        if knowledge_layer is not None and not isinstance(
            knowledge_layer,
            KnowledgeLayer,
        ):
            raise ValueError("knowledge_layer must be a KnowledgeLayer or null")
        self.event_log = event_log
        self.memory_store = memory_store
        self.knowledge_layer = knowledge_layer

    def read(self, source_ref):
        if not isinstance(source_ref, SourceRef):
            raise ValueError("source_ref must be a SourceRef")

        if source_ref.kind == "event":
            return self._read_event(source_ref)
        if source_ref.kind == "memory":
            return self._read_memory(source_ref)
        if source_ref.kind == "knowledge":
            return self._read_knowledge(source_ref)
        raise ValueError(
            f"Text source reader does not support source kind: {source_ref.kind!r}"
        )

    def _read_event(self, source_ref):
        if self.event_log is None:
            raise ValueError("No EventLog configured for text source reader")
        record = next(
            (
                event
                for event in self.event_log.load_events()
                if event["id"] == source_ref.source_id
            ),
            None,
        )
        if record is None:
            raise ValueError(
                f"Dangling text source: event:{source_ref.source_id}"
            )
        fragments = tuple(
            _event_text_fragments(
                record["payload"],
                group=f"event:{record['type']}:payload",
            )
        )
        return TextSourceRecord(source_ref=source_ref, fragments=fragments)

    def _read_memory(self, source_ref):
        if self.memory_store is None:
            raise ValueError("No MemoryStore configured for text source reader")
        memory = self.memory_store.get_memory(source_ref.source_id)
        if memory is None:
            raise ValueError(
                f"Dangling text source: memory:{source_ref.source_id}"
            )
        if memory["status"] != "closed":
            raise ValueError(
                "Ineligible memory source for consolidation: "
                f"{source_ref.source_id} is {memory['status']}"
            )
        fragment = TextFragment(
            group=f"memory:{memory['domain']}:{memory['type']}",
            text=memory["content"],
        )
        return TextSourceRecord(
            source_ref=source_ref,
            fragments=(fragment,),
        )

    def _read_knowledge(self, source_ref):
        if self.knowledge_layer is None:
            raise ValueError("No KnowledgeLayer configured for text source reader")
        knowledge = self.knowledge_layer.get(source_ref.source_id)
        if knowledge is None:
            raise ValueError(
                f"Dangling text source: knowledge:{source_ref.source_id}"
            )
        if knowledge["status"] != "confirmed":
            raise ValueError(
                "Ineligible knowledge source for consolidation: "
                f"{source_ref.source_id} is {knowledge['status']}"
            )
        description = self.knowledge_layer.describe(source_ref.source_id)
        if not description["supporting_sources"]:
            raise ValueError(
                "Confirmed knowledge source has no supporting evidence: "
                f"{source_ref.source_id}"
            )
        fragment = TextFragment(
            group=f"knowledge:{knowledge['domain']}",
            text=knowledge["statement"],
        )
        return TextSourceRecord(
            source_ref=source_ref,
            fragments=(fragment,),
        )


class DeterministicTextConsolidationProcessor(SleepProcessor):
    """Canonical Stage 3.5 text processor with bounded deterministic output."""

    NAME = "deterministic-text"
    VERSION = "1"

    def __init__(self, *, max_items=32, max_chars=4096):
        _require_non_negative_int(max_items, "max_items")
        _require_non_negative_int(max_chars, "max_chars")
        self.max_items = max_items
        self.max_chars = max_chars
        super().__init__(
            ProcessorDescriptor(
                name=self.NAME,
                version=self.VERSION,
                work_kind="CONSOLIDATE",
                source_kinds=frozenset({"event", "memory", "knowledge"}),
            )
        )

    @staticmethod
    def _validate_checkpoint(checkpoint):
        if not isinstance(checkpoint, dict):
            raise ValueError("Text consolidation checkpoint must be an object")
        if set(checkpoint) != {
            "fragments",
            "input_fragments",
            "dropped_empty",
        }:
            raise ValueError(
                "Text consolidation checkpoint fields must be exactly: "
                "fragments, input_fragments, dropped_empty"
            )
        if not isinstance(checkpoint["fragments"], list):
            raise ValueError("Text consolidation checkpoint fragments must be a list")
        _require_non_negative_int(
            checkpoint["input_fragments"],
            "Text consolidation input_fragments",
        )
        _require_non_negative_int(
            checkpoint["dropped_empty"],
            "Text consolidation dropped_empty",
        )
        for fragment in checkpoint["fragments"]:
            if not isinstance(fragment, dict) or set(fragment) != {"group", "text"}:
                raise ValueError("Invalid text consolidation checkpoint fragment")
            _require_non_empty_string(fragment["group"], "Text fragment group")
            _require_non_empty_string(fragment["text"], "Text fragment text")

    def _initial_checkpoint(self, work_item):
        return {
            "fragments": [],
            "input_fragments": 0,
            "dropped_empty": 0,
        }

    def _process_chunk(self, work_item, *, chunk, checkpoint):
        self._validate_checkpoint(checkpoint)
        if not isinstance(chunk, dict):
            raise ValueError("Text consolidation chunk must be an object")
        if set(chunk) != {"source", "fragments"}:
            raise ValueError(
                "Text consolidation chunk fields must be exactly: source, fragments"
            )
        source_ref = SourceRef.from_dict(chunk["source"])
        if source_ref != work_item.source_ref:
            raise ValueError("Text consolidation chunk source does not match WorkItem")
        if not isinstance(chunk["fragments"], list):
            raise ValueError("Text consolidation chunk fragments must be a list")

        stored = [dict(fragment) for fragment in checkpoint["fragments"]]
        input_fragments = checkpoint["input_fragments"]
        dropped_empty = checkpoint["dropped_empty"]
        accepted = 0

        for fragment in chunk["fragments"]:
            if not isinstance(fragment, dict) or set(fragment) != {"group", "text"}:
                raise ValueError(
                    "Text consolidation fragment fields must be exactly: group, text"
                )
            _require_non_empty_string(fragment["group"], "Text fragment group")
            normalized = _normalize_text(fragment["text"])
            input_fragments += 1
            if not normalized:
                dropped_empty += 1
                continue
            stored.append(
                {
                    "group": fragment["group"].strip(),
                    "text": normalized,
                }
            )
            accepted += 1

        return ChunkResult(
            checkpoint={
                "fragments": stored,
                "input_fragments": input_fragments,
                "dropped_empty": dropped_empty,
            },
            local_result={
                "input_fragments": len(chunk["fragments"]),
                "accepted_fragments": accepted,
            },
        )

    @staticmethod
    def _sort_key(entry):
        return (
            entry["group"].casefold(),
            entry["group"],
            entry["text"].casefold(),
            entry["text"],
        )

    def _finalize(self, work_item, *, checkpoint):
        self._validate_checkpoint(checkpoint)
        unique = {
            (entry["group"], entry["text"]): dict(entry)
            for entry in checkpoint["fragments"]
        }
        ordered = sorted(unique.values(), key=self._sort_key)

        accepted = []
        output_chars = 0
        dropped_budget = 0
        for entry in ordered:
            if len(accepted) >= self.max_items:
                dropped_budget += 1
                continue
            text_size = len(entry["text"])
            if output_chars + text_size > self.max_chars:
                dropped_budget += 1
                continue
            accepted.append(entry)
            output_chars += text_size

        groups = []
        for entry in accepted:
            if not groups or groups[-1]["group"] != entry["group"]:
                groups.append({"group": entry["group"], "items": []})
            groups[-1]["items"].append(entry["text"])

        output = {
            "kind": "text_consolidation",
            "source": work_item.source_ref.to_dict(),
            "groups": groups,
            "stats": {
                "input_fragments": checkpoint["input_fragments"],
                "unique_fragments": len(ordered),
                "output_fragments": len(accepted),
                "dropped_empty": checkpoint["dropped_empty"],
                "dropped_duplicates": (
                    len(checkpoint["fragments"]) - len(ordered)
                ),
                "dropped_budget": dropped_budget,
            },
            "limits": {
                "max_items": self.max_items,
                "max_chars": self.max_chars,
            },
            "output_chars": output_chars,
        }
        return FinalizeResult.create(work_item=work_item, output=output)
