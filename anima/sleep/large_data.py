import hashlib
from dataclasses import dataclass
from math import ceil

from anima.sleep.contracts import SourceRef, WorkItem
from anima.sleep.processors import (
    ChunkResult,
    FinalizeResult,
    ProcessorDescriptor,
    SleepProcessor,
)


GIB = 1024 ** 3
MIB = 1024 ** 2
DEFAULT_SAMPLE_BYTES = 4096


def _require_positive_int(value, label):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")


@dataclass(frozen=True, slots=True)
class SyntheticLargeChunk:
    sequence: int
    offset_bytes: int
    logical_size_bytes: int
    sample: bytes

    def __post_init__(self):
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence < 0:
            raise ValueError("SyntheticLargeChunk sequence must be a non-negative integer")
        if not isinstance(self.offset_bytes, int) or isinstance(self.offset_bytes, bool) or self.offset_bytes < 0:
            raise ValueError("SyntheticLargeChunk offset_bytes must be a non-negative integer")
        _require_positive_int(self.logical_size_bytes, "SyntheticLargeChunk logical_size_bytes")
        if not isinstance(self.sample, bytes) or not self.sample:
            raise ValueError("SyntheticLargeChunk sample must be non-empty bytes")

    @property
    def sample_sha256(self):
        return hashlib.sha256(self.sample).hexdigest()


class SyntheticLargeSource:
    """Lazy synthetic Asset with a large logical size and bounded materialized chunks."""

    def __init__(
        self,
        *,
        source_ref,
        logical_size_bytes,
        chunk_size_bytes,
        sample_bytes=DEFAULT_SAMPLE_BYTES,
    ):
        if not isinstance(source_ref, SourceRef) or source_ref.kind != "asset":
            raise ValueError("SyntheticLargeSource source_ref must be an asset SourceRef")
        _require_positive_int(logical_size_bytes, "logical_size_bytes")
        _require_positive_int(chunk_size_bytes, "chunk_size_bytes")
        _require_positive_int(sample_bytes, "sample_bytes")
        if sample_bytes > chunk_size_bytes:
            raise ValueError("sample_bytes must not exceed chunk_size_bytes")

        self.source_ref = source_ref
        self.logical_size_bytes = logical_size_bytes
        self.chunk_size_bytes = chunk_size_bytes
        self.sample_bytes = sample_bytes
        self._iter_starts = []
        self._yielded_sequences = []

    @property
    def chunk_count(self):
        return ceil(self.logical_size_bytes / self.chunk_size_bytes)

    @property
    def iter_starts(self):
        return tuple(self._iter_starts)

    @property
    def yielded_sequences(self):
        return tuple(self._yielded_sequences)

    @property
    def materialized_payload_limit_bytes(self):
        return self.sample_bytes

    def _chunk_logical_size(self, sequence):
        offset = sequence * self.chunk_size_bytes
        remaining = self.logical_size_bytes - offset
        return min(self.chunk_size_bytes, remaining)

    def _sample(self, sequence, logical_size):
        seed = (
            f"{self.source_ref.source_id}:{sequence}:{logical_size}"
        ).encode("utf-8")
        digest = hashlib.sha256(seed).digest()
        repeat = (self.sample_bytes + len(digest) - 1) // len(digest)
        return (digest * repeat)[: self.sample_bytes]

    def iter_from(self, start_sequence=0):
        if (
            not isinstance(start_sequence, int)
            or isinstance(start_sequence, bool)
            or start_sequence < 0
            or start_sequence > self.chunk_count
        ):
            raise ValueError("start_sequence is outside synthetic source")
        self._iter_starts.append(start_sequence)

        for sequence in range(start_sequence, self.chunk_count):
            logical_size = self._chunk_logical_size(sequence)
            self._yielded_sequences.append(sequence)
            yield SyntheticLargeChunk(
                sequence=sequence,
                offset_bytes=sequence * self.chunk_size_bytes,
                logical_size_bytes=logical_size,
                sample=self._sample(sequence, logical_size),
            )

    def __iter__(self):
        return self.iter_from(0)


class SyntheticLargeAssetProcessor(SleepProcessor):
    """Bounded-state processor used to prove large-source orchestration readiness."""

    def __init__(self, *, name="synthetic-large-asset", version="1"):
        super().__init__(
            ProcessorDescriptor(
                name=name,
                version=version,
                work_kind="CONSOLIDATE",
                source_kinds=frozenset({"asset"}),
            )
        )

    def _initial_checkpoint(self, work_item):
        return {
            "chunks_processed": 0,
            "logical_bytes_processed": 0,
            "last_sequence": None,
            "rolling_sha256": hashlib.sha256(b"").hexdigest(),
        }

    def _process_chunk(self, work_item, *, chunk, checkpoint):
        if not isinstance(chunk, SyntheticLargeChunk):
            raise ValueError("SyntheticLargeAssetProcessor requires SyntheticLargeChunk")
        expected = checkpoint["chunks_processed"]
        if chunk.sequence != expected:
            raise ValueError(
                "Synthetic large chunk sequence mismatch: "
                f"expected {expected}, got {chunk.sequence}"
            )

        digest = hashlib.sha256()
        digest.update(bytes.fromhex(checkpoint["rolling_sha256"]))
        digest.update(str(chunk.sequence).encode("ascii"))
        digest.update(str(chunk.offset_bytes).encode("ascii"))
        digest.update(str(chunk.logical_size_bytes).encode("ascii"))
        digest.update(bytes.fromhex(chunk.sample_sha256))

        next_checkpoint = {
            "chunks_processed": expected + 1,
            "logical_bytes_processed": (
                checkpoint["logical_bytes_processed"] + chunk.logical_size_bytes
            ),
            "last_sequence": chunk.sequence,
            "rolling_sha256": digest.hexdigest(),
        }
        return ChunkResult(
            checkpoint=next_checkpoint,
            local_result={
                "sequence": chunk.sequence,
                "offset_bytes": chunk.offset_bytes,
                "logical_size_bytes": chunk.logical_size_bytes,
                "sample_sha256": chunk.sample_sha256,
            },
        )

    def _finalize(self, work_item, *, checkpoint):
        return FinalizeResult.create(
            work_item=work_item,
            output={
                "kind": "synthetic_large_asset_summary",
                "chunks_processed": checkpoint["chunks_processed"],
                "logical_bytes_processed": checkpoint["logical_bytes_processed"],
                "last_sequence": checkpoint["last_sequence"],
                "rolling_sha256": checkpoint["rolling_sha256"],
            },
        )
