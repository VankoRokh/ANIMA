from dataclasses import dataclass

from anima.sleep.contracts import SourceRegistry
from anima.sleep.derived import DerivedResult, DerivedResultRepository
from anima.sleep.processors import ProcessorRegistry
from anima.sleep.store import SleepStore


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    work_item_id: str
    status: str
    resumed_from_sequence: int
    processed_chunks: int
    committed_chunks: int
    final_result: DerivedResult | None
    stop_reason: str | None = None

    @property
    def interrupted(self):
        return self.status == "checkpointed"


class SleepChunkExecutor:
    """Execute WorkItems in ordered chunks with persistent resume checkpoints."""

    def __init__(
        self,
        *,
        sleep_store,
        processor_registry,
        source_registry,
        derived_results=None,
    ):
        if not isinstance(sleep_store, SleepStore):
            raise ValueError("sleep_store must be a SleepStore")
        if not isinstance(processor_registry, ProcessorRegistry):
            raise ValueError("processor_registry must be a ProcessorRegistry")
        if not isinstance(source_registry, SourceRegistry):
            raise ValueError("source_registry must be a SourceRegistry")
        if derived_results is None:
            derived_results = DerivedResultRepository(sleep_store)
        if not isinstance(derived_results, DerivedResultRepository):
            raise ValueError("derived_results must be a DerivedResultRepository")
        if derived_results.sleep_store is not sleep_store:
            raise ValueError("derived_results must use the same SleepStore")

        self.sleep_store = sleep_store
        self.processor_registry = processor_registry
        self.source_registry = source_registry
        self.derived_results = derived_results

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

    @staticmethod
    def _resume_state(work_item, latest, processor):
        if latest is None:
            if work_item.status == "checkpointed" or work_item.checkpoint_ref is not None:
                raise ValueError(
                    "WorkItem checkpoint metadata exists without a persisted checkpoint"
                )
            return 0, processor.initial_checkpoint(work_item)

        if work_item.checkpoint_ref != latest["id"]:
            raise ValueError(
                "WorkItem checkpoint_ref does not match latest persisted checkpoint"
            )
        return latest["sequence"] + 1, latest["checkpoint"]

    def run(
        self,
        work_item_id,
        chunks,
        *,
        interrupt_after_new_chunks=None,
        interrupt_only_if_more_work=False,
    ):
        self._validate_interrupt_after(interrupt_after_new_chunks)
        if type(interrupt_only_if_more_work) is not bool:
            raise ValueError("interrupt_only_if_more_work must be bool")
        try:
            iterator = iter(chunks)
        except TypeError as error:
            raise ValueError("chunks must be iterable") from error

        work_item = self.sleep_store.get_work_item(work_item_id)
        if work_item is None:
            raise ValueError(f"Unknown WorkItem: {work_item_id}")

        processor = self.processor_registry.resolve(work_item)
        latest = self.sleep_store.get_latest_checkpoint(work_item_id)
        resumed_from_sequence, checkpoint = self._resume_state(
            work_item,
            latest,
            processor,
        )

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

            if (
                interrupt_only_if_more_work
                and interrupt_after_new_chunks is not None
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
                    stop_reason="chunk_limit",
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
                not interrupt_only_if_more_work
                and interrupt_after_new_chunks is not None
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
                    stop_reason="chunk_limit",
                )

        processor_result = processor.finalize(
            work_item,
            checkpoint=checkpoint,
        )
        derived_result = self.derived_results.commit_final_result(
            work_item_id,
            processor_result,
            source_registry=self.source_registry,
        )
        completed = self.sleep_store.get_work_item(work_item_id)
        return ExecutionOutcome(
            work_item_id=work_item_id,
            status=completed.status,
            resumed_from_sequence=resumed_from_sequence,
            processed_chunks=processed_chunks,
            committed_chunks=next_sequence,
            final_result=derived_result,
        )
