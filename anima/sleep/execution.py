from dataclasses import dataclass

from anima.sleep.processors import FinalizeResult, ProcessorRegistry
from anima.sleep.store import SleepStore


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    work_item_id: str
    status: str
    resumed_from_sequence: int
    processed_chunks: int
    committed_chunks: int
    final_result: FinalizeResult | None

    @property
    def interrupted(self):
        return self.status == "checkpointed"


class SleepChunkExecutor:
    """Execute WorkItems in ordered chunks with persistent resume checkpoints."""

    def __init__(self, *, sleep_store, processor_registry):
        if not isinstance(sleep_store, SleepStore):
            raise ValueError("sleep_store must be a SleepStore")
        if not isinstance(processor_registry, ProcessorRegistry):
            raise ValueError("processor_registry must be a ProcessorRegistry")
        self.sleep_store = sleep_store
        self.processor_registry = processor_registry

    @staticmethod
    def _validate_interrupt_after(value):
        if value is None:
            return
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value <= 0
        ):
            raise ValueError(
                "interrupt_after_new_chunks must be a positive integer or null"
            )

    def run(
        self,
        work_item_id,
        chunks,
        *,
        interrupt_after_new_chunks=None,
    ):
        self._validate_interrupt_after(interrupt_after_new_chunks)
        try:
            iterator = iter(chunks)
        except TypeError as error:
            raise ValueError("chunks must be iterable") from error

        work_item = self.sleep_store.get_work_item(work_item_id)
        if work_item is None:
            raise ValueError(f"Unknown WorkItem: {work_item_id}")

        processor = self.processor_registry.resolve(work_item)
        latest = self.sleep_store.get_latest_checkpoint(work_item_id)
        if latest is None:
            resumed_from_sequence = 0
            checkpoint = processor.initial_checkpoint(work_item)
        else:
            resumed_from_sequence = latest["sequence"] + 1
            checkpoint = latest["checkpoint"]

        work_item = self.sleep_store.begin_work_item(work_item_id)
        processed_chunks = 0
        next_sequence = resumed_from_sequence

        for sequence, chunk in enumerate(iterator):
            if sequence < resumed_from_sequence:
                continue
            if sequence != next_sequence:
                raise ValueError(
                    "Chunk stream sequence changed during resume: "
                    f"expected {next_sequence}, got {sequence}"
                )

            result = processor.process_chunk(
                work_item,
                chunk=chunk,
                checkpoint=checkpoint,
            )
            self.sleep_store.commit_work_item_chunk(
                work_item_id,
                sequence=sequence,
                checkpoint=result.checkpoint,
                local_result=result.local_result,
            )
            checkpoint = result.checkpoint
            processed_chunks += 1
            next_sequence += 1

            if (
                interrupt_after_new_chunks is not None
                and processed_chunks >= interrupt_after_new_chunks
            ):
                paused = self.sleep_store.pause_work_item(work_item_id)
                return ExecutionOutcome(
                    work_item_id=work_item_id,
                    status=paused.status,
                    resumed_from_sequence=resumed_from_sequence,
                    processed_chunks=processed_chunks,
                    committed_chunks=next_sequence,
                    final_result=None,
                )

        final_result = processor.finalize(
            work_item,
            checkpoint=checkpoint,
        )
        completed = self.sleep_store.complete_work_item(work_item_id)
        return ExecutionOutcome(
            work_item_id=work_item_id,
            status=completed.status,
            resumed_from_sequence=resumed_from_sequence,
            processed_chunks=processed_chunks,
            committed_chunks=next_sequence,
            final_result=final_result,
        )
