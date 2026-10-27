import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

from anima.sleep.contracts import (
    SOURCE_ID_PREFIXES,
    WORK_KINDS,
    SourceRef,
    WorkItem,
    _validate_non_empty_string,
    _validate_uuid4_id,
)


def _validate_json_value(value, label):
    try:
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be JSON-serializable") from error


@dataclass(frozen=True, slots=True)
class ProcessorDescriptor:
    name: str
    version: str
    work_kind: str
    source_kinds: frozenset[str]

    def __post_init__(self):
        _validate_non_empty_string(self.name, "Processor name")
        _validate_non_empty_string(self.version, "Processor version")
        if self.work_kind not in WORK_KINDS:
            raise ValueError(f"Unsupported processor work kind: {self.work_kind!r}")
        if not isinstance(self.source_kinds, frozenset) or not self.source_kinds:
            raise ValueError("Processor source_kinds must be a non-empty frozenset")
        unsupported = self.source_kinds - SOURCE_ID_PREFIXES.keys()
        if unsupported:
            names = ", ".join(sorted(unsupported))
            raise ValueError(f"Unsupported processor source kinds: {names}")


@dataclass(frozen=True, slots=True)
class ChunkResult:
    checkpoint: object
    local_result: object | None = None

    def __post_init__(self):
        _validate_json_value(self.checkpoint, "Processor checkpoint")
        if self.local_result is not None:
            _validate_json_value(self.local_result, "Processor local_result")


@dataclass(frozen=True, slots=True)
class FinalizeResult:
    work_item_id: str
    source_ref: SourceRef
    processor: str
    processor_version: str
    output: object

    def __post_init__(self):
        _validate_uuid4_id(
            self.work_item_id,
            prefix="wi_",
            label="FinalizeResult work_item_id",
        )
        if not isinstance(self.source_ref, SourceRef):
            raise ValueError("FinalizeResult source_ref must be a SourceRef")
        _validate_non_empty_string(self.processor, "FinalizeResult processor")
        _validate_non_empty_string(
            self.processor_version,
            "FinalizeResult processor_version",
        )
        _validate_json_value(self.output, "FinalizeResult output")

    @classmethod
    def create(cls, *, work_item, output):
        if not isinstance(work_item, WorkItem):
            raise ValueError("FinalizeResult.create() requires a WorkItem")
        return cls(
            work_item_id=work_item.public_id,
            source_ref=work_item.source_ref,
            processor=work_item.processor,
            processor_version=work_item.processor_version,
            output=output,
        )


class SleepProcessor(ABC):
    """Replaceable processor contract; orchestration treats chunks as opaque values."""

    descriptor: ProcessorDescriptor

    def __init__(self, descriptor):
        if not isinstance(descriptor, ProcessorDescriptor):
            raise ValueError("descriptor must be a ProcessorDescriptor")
        self.descriptor = descriptor

    def require_supported(self, work_item):
        if not isinstance(work_item, WorkItem):
            raise ValueError("work_item must be a WorkItem")
        if work_item.processor != self.descriptor.name:
            raise ValueError(
                "Processor name mismatch: "
                f"work item requires {work_item.processor!r}, "
                f"adapter is {self.descriptor.name!r}"
            )
        if work_item.processor_version != self.descriptor.version:
            raise ValueError(
                "Processor version mismatch: "
                f"work item requires {work_item.processor_version!r}, "
                f"adapter is {self.descriptor.version!r}"
            )
        if work_item.work_kind != self.descriptor.work_kind:
            raise ValueError(
                "Processor does not support work kind: "
                f"{work_item.work_kind!r}"
            )
        if work_item.source_ref.kind not in self.descriptor.source_kinds:
            raise ValueError(
                "Processor does not support source kind: "
                f"{work_item.source_ref.kind!r}"
            )
        return work_item

    @abstractmethod
    def initial_checkpoint(self, work_item):
        """Return JSON-serializable checkpoint state for a new WorkItem."""

    @abstractmethod
    def process_chunk(self, work_item, *, chunk, checkpoint):
        """Process one opaque chunk and return ChunkResult."""

    @abstractmethod
    def finalize(self, work_item, *, checkpoint):
        """Finalize processing and return FinalizeResult."""


class ProcessorRegistry:
    def __init__(self):
        self._processors = {}

    @staticmethod
    def _key(name, version):
        return (name, version)

    def register(self, processor):
        if not isinstance(processor, SleepProcessor):
            raise ValueError("processor must be a SleepProcessor")
        key = self._key(processor.descriptor.name, processor.descriptor.version)
        if key in self._processors:
            raise ValueError(
                "Processor already registered: "
                f"{processor.descriptor.name}@{processor.descriptor.version}"
            )
        self._processors[key] = processor
        return self

    def resolve(self, work_item):
        if not isinstance(work_item, WorkItem):
            raise ValueError("work_item must be a WorkItem")
        key = self._key(work_item.processor, work_item.processor_version)
        processor = self._processors.get(key)
        if processor is None:
            raise ValueError(
                "No processor registered for: "
                f"{work_item.processor}@{work_item.processor_version}"
            )
        processor.require_supported(work_item)
        return processor
