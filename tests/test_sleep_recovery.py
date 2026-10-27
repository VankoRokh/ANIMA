from uuid import uuid4

import pytest

from anima.memory.memory_store import MemoryStore
from anima.sleep.contracts import SourceRef, SourceRegistry, WorkItem
from anima.sleep.derived import DerivedResultRepository
from anima.sleep.execution import SleepChunkExecutor
from anima.sleep.processors import (
    ChunkResult,
    FinalizeResult,
    ProcessorDescriptor,
    ProcessorRegistry,
    SleepProcessor,
)
from anima.sleep.recovery import (
    CognitiveEffectStore,
    RecoveryOperationRepository,
    SleepRecoveryCoordinator,
    stable_operation_key,
)
from anima.sleep.store import SleepStore


class RecordingProcessor(SleepProcessor):
    def __init__(self):
        super().__init__(
            ProcessorDescriptor(
                name="recovery-test",
                version="1",
                work_kind="CONSOLIDATE",
                source_kinds=frozenset({"event"}),
            )
        )
        self.calls = []

    def _initial_checkpoint(self, work_item):
        return {"values": []}

    def _process_chunk(self, work_item, *, chunk, checkpoint):
        self.calls.append(chunk)
        values = list(checkpoint["values"])
        values.append(chunk)
        return ChunkResult(
            checkpoint={"values": values},
            local_result={"accepted": chunk},
        )

    def _finalize(self, work_item, *, checkpoint):
        return FinalizeResult.create(
            work_item=work_item,
            output={"values": checkpoint["values"]},
        )


def _environment(path, *, source=None):
    source = source or SourceRef("event", f"ev_{uuid4()}")
    source_registry = SourceRegistry().register(
        "event",
        lambda source_id: source_id == source.source_id,
    )
    sleep_store = SleepStore(path / "sleep.db")
    memory_store = MemoryStore(path / "memory.db")
    derived = DerivedResultRepository(sleep_store)
    operations = RecoveryOperationRepository(sleep_store, derived)
    effects = CognitiveEffectStore(memory_store)
    recovery = SleepRecoveryCoordinator(operations=operations, effects=effects)
    return {
        "source": source,
        "source_registry": source_registry,
        "sleep_store": sleep_store,
        "memory_store": memory_store,
        "derived": derived,
        "operations": operations,
        "effects": effects,
        "recovery": recovery,
    }


def _new_work(environment):
    store = environment["sleep_store"]
    job = store.create_job()
    item = WorkItem.create(
        job_id=job["id"],
        source_ref=environment["source"],
        processor="recovery-test",
        processor_version="1",
    )
    return store.create_work_item(
        item,
        source_registry=environment["source_registry"],
    )


def _executor(environment, processor=None):
    processor = processor or RecordingProcessor()
    executor = SleepChunkExecutor(
        sleep_store=environment["sleep_store"],
        processor_registry=ProcessorRegistry().register(processor),
        source_registry=environment["source_registry"],
        derived_results=environment["derived"],
    )
    return executor, processor


def _completed_result(environment, chunks=("alpha", "beta")):
    item = _new_work(environment)
    executor, processor = _executor(environment)
    outcome = executor.run(item.public_id, list(chunks))
    return item, outcome.final_result, processor


def _reopen(path, source):
    return _environment(path, source=source)


def test_recovery_schemas_reopen_without_changing_core_store_versions(tmp_path):
    environment = _environment(tmp_path)

    assert environment["sleep_store"].schema_version() == 3
    assert environment["memory_store"].schema_version() == 1
    assert environment["operations"].schema_version() == 1
    assert environment["effects"].schema_version() == 1

    reopened = _reopen(tmp_path, environment["source"])
    assert reopened["sleep_store"].schema_version() == 3
    assert reopened["memory_store"].schema_version() == 1
    assert reopened["operations"].schema_version() == 1
    assert reopened["effects"].schema_version() == 1


def test_running_work_without_checkpoint_recovers_to_queued_and_replays_safely(tmp_path):
    environment = _environment(tmp_path)
    item = _new_work(environment)
    environment["sleep_store"].begin_work_item(item.public_id)

    reopened = _reopen(tmp_path, environment["source"])
    recovered = reopened["recovery"].recover_work_item(item.public_id)
    assert recovered.status == "queued"
    assert recovered.checkpoint_ref is None

    executor, processor = _executor(reopened)
    outcome = executor.run(item.public_id, ["alpha", "beta"])

    assert processor.calls == ["alpha", "beta"]
    assert outcome.status == "completed"
    assert outcome.final_result.output == {"values": ["alpha", "beta"]}
    assert len(reopened["derived"].list_results()) == 1


def test_running_work_after_checkpoint_recovers_to_checkpointed_and_skips_commit(tmp_path):
    environment = _environment(tmp_path)
    item = _new_work(environment)
    store = environment["sleep_store"]
    store.begin_work_item(item.public_id)
    checkpoint = store.commit_work_item_chunk(
        item.public_id,
        sequence=0,
        checkpoint={"values": ["alpha"]},
        local_result={"accepted": "alpha"},
    )

    reopened = _reopen(tmp_path, environment["source"])
    recovered = reopened["recovery"].recover_work_item(item.public_id)
    assert recovered.status == "checkpointed"
    assert recovered.checkpoint_ref == checkpoint["id"]

    executor, processor = _executor(reopened)
    outcome = executor.run(item.public_id, ["alpha", "beta"])

    assert processor.calls == ["beta"]
    assert outcome.final_result.output == {"values": ["alpha", "beta"]}
    assert [
        row["sequence"] for row in reopened["sleep_store"].list_checkpoints(item.public_id)
    ] == [0, 1]


def test_prepare_then_recover_pending_applies_external_effect_once(tmp_path):
    environment = _environment(tmp_path)
    _, result, _ = _completed_result(environment)
    operation = environment["recovery"].prepare_result(result)

    assert operation.status == "prepared"
    assert operation.attempts == 0
    assert environment["effects"].get(operation.operation_key) is None

    reopened = _reopen(tmp_path, environment["source"])
    receipts = reopened["recovery"].recover_pending()

    assert len(receipts) == 1
    assert receipts[0].operation_key == operation.operation_key
    assert reopened["effects"].count() == 1
    applied = reopened["operations"].get(operation.operation_key)
    assert applied.status == "applied"
    assert applied.attempts == 1


def test_crash_after_external_apply_before_ledger_ack_does_not_duplicate_effect(tmp_path):
    environment = _environment(tmp_path)
    _, result, _ = _completed_result(environment)
    operation = environment["recovery"].prepare_result(result)

    receipt = environment["effects"].apply_once(operation)
    assert receipt.operation_key == operation.operation_key
    assert environment["operations"].get(operation.operation_key).status == "prepared"
    assert environment["effects"].count() == 1

    reopened = _reopen(tmp_path, environment["source"])
    recovered_receipts = reopened["recovery"].recover_pending()

    assert [item.operation_key for item in recovered_receipts] == [operation.operation_key]
    assert reopened["effects"].count() == 1
    assert reopened["operations"].get(operation.operation_key).status == "applied"


def test_repeated_publish_of_same_result_is_idempotent(tmp_path):
    environment = _environment(tmp_path)
    _, result, _ = _completed_result(environment)

    first_operation, first_receipt = environment["recovery"].publish_result(result)
    second_operation, second_receipt = environment["recovery"].publish_result(result)

    assert first_operation.operation_key == second_operation.operation_key
    assert first_receipt == second_receipt
    assert environment["effects"].count() == 1
    assert len(environment["operations"].list_operations()) == 1
    assert environment["operations"].get(first_operation.operation_key).attempts == 1


def test_repeat_job_same_logical_work_reuses_operation_key_and_effect(tmp_path):
    environment = _environment(tmp_path)
    _, first_result, _ = _completed_result(environment, chunks=("same",))
    first_operation, _ = environment["recovery"].publish_result(first_result)

    _, second_result, _ = _completed_result(environment, chunks=("same",))
    assert second_result.public_id != first_result.public_id
    assert second_result.output_ref != first_result.output_ref
    assert stable_operation_key(second_result) == first_operation.operation_key

    second_operation, second_receipt = environment["recovery"].publish_result(
        second_result
    )

    assert second_operation.operation_key == first_operation.operation_key
    assert second_operation.canonical_result_id == first_result.public_id
    assert second_receipt.canonical_result_id == first_result.public_id
    assert environment["effects"].count() == 1
    assert len(environment["operations"].list_operations()) == 1


def test_same_logical_operation_with_different_output_is_diagnostic_conflict(tmp_path):
    environment = _environment(tmp_path)
    _, first_result, _ = _completed_result(environment, chunks=("first",))
    environment["recovery"].publish_result(first_result)

    _, changed_result, _ = _completed_result(environment, chunks=("changed",))
    assert stable_operation_key(changed_result) == stable_operation_key(first_result)

    with pytest.raises(ValueError, match="different payload"):
        environment["recovery"].prepare_result(changed_result)

    assert environment["effects"].count() == 1
    assert len(environment["operations"].list_operations()) == 1


def test_failed_external_reconciliation_remains_visible_and_retryable(tmp_path):
    environment = _environment(tmp_path)
    _, result, _ = _completed_result(environment)
    operation = environment["recovery"].prepare_result(result)

    with environment["memory_store"].transaction() as connection:
        connection.execute(
            """
            INSERT INTO sleep_effect_receipts(
                operation_key, effect_kind, canonical_result_id,
                canonical_output_ref, logical_payload_json, applied_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                operation.operation_key,
                operation.effect_kind,
                "dr_conflict",
                "dout_conflict",
                "{}",
                "2026-10-27T13:00:00+00:00",
            ),
        )

    with pytest.raises(ValueError, match="conflicts with operation"):
        environment["recovery"].apply(operation.operation_key)

    failed = environment["operations"].get(operation.operation_key)
    assert failed.status == "failed"
    assert failed.attempts == 1
    assert "conflicts with operation" in failed.last_error
    assert environment["operations"].list_pending() == [failed]

    with environment["memory_store"].transaction() as connection:
        connection.execute(
            "DELETE FROM sleep_effect_receipts WHERE operation_key = ?",
            (operation.operation_key,),
        )

    receipts = environment["recovery"].recover_pending()
    assert len(receipts) == 1
    recovered = environment["operations"].get(operation.operation_key)
    assert recovered.status == "applied"
    assert recovered.attempts == 2
    assert recovered.last_error is None
    assert environment["effects"].count() == 1


def test_effect_receipt_does_not_create_memory_or_knowledge_authority(tmp_path):
    environment = _environment(tmp_path)
    memory_count_before = environment["memory_store"].count()
    with environment["memory_store"].transaction() as connection:
        knowledge_before = connection.execute(
            "SELECT COUNT(*) AS count FROM knowledge"
        ).fetchone()["count"]

    _, result, _ = _completed_result(environment)
    operation, receipt = environment["recovery"].publish_result(result)

    assert operation.status == "applied"
    assert receipt.logical_payload["authority"] == "derived"
    assert environment["memory_store"].count() == memory_count_before
    with environment["memory_store"].transaction() as connection:
        knowledge_after = connection.execute(
            "SELECT COUNT(*) AS count FROM knowledge"
        ).fetchone()["count"]
    assert knowledge_after == knowledge_before
    assert environment["effects"].count() == 1


def test_completed_work_item_without_derived_result_is_diagnostic(tmp_path):
    environment = _environment(tmp_path)
    item = _new_work(environment)
    store = environment["sleep_store"]
    store.begin_work_item(item.public_id)
    store.complete_work_item(item.public_id)

    with pytest.raises(ValueError, match="missing its persistent DerivedResult"):
        environment["recovery"].recover_work_item(item.public_id)


def test_completed_work_item_with_result_is_safe_recovery_terminal(tmp_path):
    environment = _environment(tmp_path)
    item, result, _ = _completed_result(environment)

    recovered = environment["recovery"].recover_work_item(item.public_id)
    assert recovered.status == "completed"
    assert environment["derived"].get_by_work_item(item.public_id) == result

    first_operation, _ = environment["recovery"].publish_result(result)
    reopened = _reopen(tmp_path, environment["source"])
    recovered_again = reopened["recovery"].recover_work_item(item.public_id)
    second_operation, _ = reopened["recovery"].publish_result(result)

    assert recovered_again.status == "completed"
    assert second_operation.operation_key == first_operation.operation_key
    assert reopened["effects"].count() == 1
