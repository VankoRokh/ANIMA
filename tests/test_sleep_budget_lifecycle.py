from anima.sleep.observability import SleepResourceBudget
from tests.test_sleep_observability import _enter_sleep, _fixture


def test_exhausted_budget_retry_does_not_create_fake_job_resume_transition(tmp_path):
    fixture = _fixture(
        tmp_path,
        budget=SleepResourceBudget(max_committed_chunks=1),
    )
    _enter_sleep(fixture)
    item = fixture["items"][0]
    store = fixture["sleep_store"]
    job_id = fixture["job"]["id"]

    first = fixture["anima"].runtime.process_sleep_work(
        item.public_id,
        ["alpha", "beta"],
        max_new_chunks=None,
    )
    assert first.status == "checkpointed"
    assert first.stop_reason == "budget:committed_chunks"

    before = store.list_transitions(job_id)
    before_statuses = [entry["to_status"] for entry in before]
    assert before_statuses[-1] == "checkpointed"

    blocked = fixture["anima"].runtime.process_sleep_work(
        item.public_id,
        ["alpha", "beta"],
        max_new_chunks=None,
    )

    after = store.list_transitions(job_id)
    assert blocked.processed_chunks == 0
    assert blocked.stop_reason == "budget:committed_chunks"
    assert [entry["to_status"] for entry in after] == before_statuses
    assert store.get_job(job_id)["status"] == "checkpointed"
    assert store.get_work_item(item.public_id).attempts == 1
