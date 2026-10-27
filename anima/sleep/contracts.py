from dataclasses import dataclass
from uuid import UUID, uuid4


SOURCE_ID_PREFIXES = {
    "event": "ev_",
    "memory": "mem_",
    "knowledge": "kn_",
    "asset": "asset_",
}
WORK_KINDS = {"CONSOLIDATE"}
WORK_ITEM_ID_PREFIX = "wi_"
WORK_ITEM_STATUSES = {
    "queued",
    "running",
    "checkpointed",
    "completed",
    "failed",
    "skipped",
}
COST_HINTS = {"cheap", "normal", "expensive"}


def _validate_uuid4_id(public_id, *, prefix, label):
    if not isinstance(public_id, str) or not public_id.startswith(prefix):
        raise ValueError(f"{label} must be a {prefix}UUIDv4")

    raw_uuid = public_id[len(prefix):]
    try:
        parsed = UUID(raw_uuid)
    except (ValueError, AttributeError) as error:
        raise ValueError(f"{label} must be a {prefix}UUIDv4") from error

    if parsed.version != 4 or str(parsed) != raw_uuid:
        raise ValueError(f"{label} must be a {prefix}UUIDv4")


def _validate_non_empty_string(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class SourceRef:
    kind: str
    source_id: str

    def __post_init__(self):
        prefix = SOURCE_ID_PREFIXES.get(self.kind)
        if prefix is None:
            raise ValueError(f"Unsupported source kind: {self.kind!r}")
        _validate_uuid4_id(
            self.source_id,
            prefix=prefix,
            label=f"{self.kind} source_id",
        )

    def to_dict(self):
        return {
            "kind": self.kind,
            "id": self.source_id,
        }

    @classmethod
    def from_dict(cls, record):
        if not isinstance(record, dict):
            raise ValueError("SourceRef record must be an object")
        if set(record) != {"kind", "id"}:
            raise ValueError("SourceRef record fields must be exactly: kind, id")
        return cls(kind=record["kind"], source_id=record["id"])


class SourceRegistry:
    """Validate source existence without copying source payload into Sleep."""

    def __init__(self):
        self._exists = {}

    def register(self, kind, exists):
        if kind not in SOURCE_ID_PREFIXES:
            raise ValueError(f"Unsupported source kind: {kind!r}")
        if not callable(exists):
            raise ValueError("Source resolver must be callable")
        if kind in self._exists:
            raise ValueError(f"Source resolver already registered: {kind}")
        self._exists[kind] = exists
        return self

    def contains(self, source_ref):
        if not isinstance(source_ref, SourceRef):
            raise ValueError("source_ref must be a SourceRef")

        exists = self._exists.get(source_ref.kind)
        if exists is None:
            raise ValueError(
                f"No source resolver registered for kind: {source_ref.kind}"
            )

        result = exists(source_ref.source_id)
        if type(result) is not bool:
            raise ValueError(
                f"Source resolver for {source_ref.kind} must return bool"
            )
        return result

    def require(self, source_ref):
        if not self.contains(source_ref):
            raise ValueError(
                f"Dangling source: {source_ref.kind}:{source_ref.source_id}"
            )
        return source_ref


@dataclass(frozen=True, slots=True)
class WorkItem:
    public_id: str
    job_id: str
    work_kind: str
    source_ref: SourceRef
    processor: str
    processor_version: str
    priority: int = 0
    cost_hint: str = "normal"
    status: str = "queued"
    attempts: int = 0
    checkpoint_ref: str | None = None

    def __post_init__(self):
        _validate_uuid4_id(
            self.public_id,
            prefix=WORK_ITEM_ID_PREFIX,
            label="WorkItem public_id",
        )
        _validate_uuid4_id(
            self.job_id,
            prefix="sj_",
            label="WorkItem job_id",
        )
        if self.work_kind not in WORK_KINDS:
            raise ValueError(f"Unsupported work kind: {self.work_kind!r}")
        if not isinstance(self.source_ref, SourceRef):
            raise ValueError("WorkItem source_ref must be a SourceRef")
        _validate_non_empty_string(self.processor, "WorkItem processor")
        _validate_non_empty_string(
            self.processor_version,
            "WorkItem processor_version",
        )
        if (
            not isinstance(self.priority, int)
            or isinstance(self.priority, bool)
            or self.priority < 0
        ):
            raise ValueError("WorkItem priority must be a non-negative integer")
        if self.cost_hint not in COST_HINTS:
            raise ValueError(f"Unknown WorkItem cost_hint: {self.cost_hint!r}")
        if self.status not in WORK_ITEM_STATUSES:
            raise ValueError(f"Unknown WorkItem status: {self.status!r}")
        if (
            not isinstance(self.attempts, int)
            or isinstance(self.attempts, bool)
            or self.attempts < 0
        ):
            raise ValueError("WorkItem attempts must be a non-negative integer")
        if self.checkpoint_ref is not None:
            _validate_non_empty_string(
                self.checkpoint_ref,
                "WorkItem checkpoint_ref",
            )

    @classmethod
    def create(
        cls,
        *,
        job_id,
        source_ref,
        processor,
        processor_version,
        work_kind="CONSOLIDATE",
        priority=0,
        cost_hint="normal",
        status="queued",
        attempts=0,
        checkpoint_ref=None,
        public_id=None,
    ):
        return cls(
            public_id=public_id or f"{WORK_ITEM_ID_PREFIX}{uuid4()}",
            job_id=job_id,
            work_kind=work_kind,
            source_ref=source_ref,
            processor=processor,
            processor_version=processor_version,
            priority=priority,
            cost_hint=cost_hint,
            status=status,
            attempts=attempts,
            checkpoint_ref=checkpoint_ref,
        )

    def to_dict(self):
        return {
            "id": self.public_id,
            "job_id": self.job_id,
            "work_kind": self.work_kind,
            "source": self.source_ref.to_dict(),
            "processor": self.processor,
            "processor_version": self.processor_version,
            "priority": self.priority,
            "cost_hint": self.cost_hint,
            "status": self.status,
            "attempts": self.attempts,
            "checkpoint_ref": self.checkpoint_ref,
        }
