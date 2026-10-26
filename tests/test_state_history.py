import pytest

from anima.internal_state.store import InternalStateStore


TIMESTAMP_1 = "2026-10-26T18:00:00+00:00"
TIMESTAMP_2 = "2026-10-26T18:05:00+00:00"
TRANSITION_ID = "st_11111111-1111-4111-8111-111111111111"
SECOND_TRANSITION_ID = "st_22222222-2222-4222-8222-222222222222"


def test_state_transition_updates_value_and_records_cause(tmp_path):
    store = InternalStateStore(tmp_path / "internal_state.db")

    transition = store.apply_state_transition(
        state_name="fatigue",
        delta=0.25,
        cause_type="event",
        source_id="ev_test",
        rule_id="test.awake_load",
        reason="test load",
        timestamp=TIMESTAMP_1,
        public_id=TRANSITION_ID,
    )

    assert store.get_state("fatigue")["value"] == 0.25
    assert transition == {
        "id": TRANSITION_ID,
        "state_name": "fatigue",
        "timestamp": TIMESTAMP_1,
        "before": 0.0,
        "delta": 0.25,
        "after": 0.25,
        "cause_type": "event",
        "source_id": "ev_test",
        "rule_id": "test.awake_load",
        "reason": "test load",
        "importance": None,
        "repetition_factor": None,
        "elapsed_seconds": None,
        "goal_id": None,
        "candidate_id": None,
    }


def test_state_transition_preserves_optional_context_and_negative_delta(tmp_path):
    store = InternalStateStore(tmp_path / "internal_state.db")
    store.apply_state_transition(
        state_name="frustration",
        delta=0.6,
        cause_type="result",
        rule_id="test.failure",
        reason="first change",
        timestamp=TIMESTAMP_1,
        public_id=TRANSITION_ID,
    )

    transition = store.apply_state_transition(
        state_name="frustration",
        delta=-0.2,
        cause_type="result",
        source_id="ev_result",
        rule_id="test.progress",
        reason="verified progress",
        importance=2,
        repetition_factor=0.5,
        elapsed_seconds=30.0,
        goal_id="goal_test",
        candidate_id="candidate_test",
        timestamp=TIMESTAMP_2,
        public_id=SECOND_TRANSITION_ID,
    )

    assert transition["before"] == 0.6
    assert transition["after"] == pytest.approx(0.4)
    assert transition["importance"] == 2
    assert transition["repetition_factor"] == 0.5
    assert transition["elapsed_seconds"] == 30.0
    assert transition["goal_id"] == "goal_test"
    assert transition["candidate_id"] == "candidate_test"


def test_out_of_range_transition_rolls_back_state_and_history(tmp_path):
    store = InternalStateStore(tmp_path / "internal_state.db")

    with pytest.raises(ValueError, match="outside"):
        store.apply_state_transition(
            state_name="fatigue",
            delta=1.1,
            cause_type="test",
            rule_id="test.range",
            reason="must fail",
            timestamp=TIMESTAMP_1,
            public_id=TRANSITION_ID,
        )

    assert store.get_state("fatigue")["value"] == 0.0
    assert store.transition_count() == 0


def test_duplicate_transition_id_rolls_back_second_state_change(tmp_path):
    store = InternalStateStore(tmp_path / "internal_state.db")
    store.apply_state_transition(
        state_name="fatigue",
        delta=0.2,
        cause_type="test",
        rule_id="test.first",
        reason="first",
        timestamp=TIMESTAMP_1,
        public_id=TRANSITION_ID,
    )

    with pytest.raises(ValueError, match="Cannot apply StateTransition"):
        store.apply_state_transition(
            state_name="fatigue",
            delta=0.3,
            cause_type="test",
            rule_id="test.duplicate",
            reason="duplicate id",
            timestamp=TIMESTAMP_2,
            public_id=TRANSITION_ID,
        )

    assert store.get_state("fatigue")["value"] == 0.2
    assert store.transition_count("fatigue") == 1


def test_invalid_transition_metadata_is_rejected_before_write(tmp_path):
    store = InternalStateStore(tmp_path / "internal_state.db")

    with pytest.raises(ValueError, match="UTC offset"):
        store.apply_state_transition(
            state_name="fatigue",
            delta=0.1,
            cause_type="test",
            rule_id="test.time",
            reason="bad time",
            timestamp="2026-10-26T18:00:00",
        )

    with pytest.raises(ValueError, match="importance"):
        store.apply_state_transition(
            state_name="fatigue",
            delta=0.1,
            cause_type="test",
            rule_id="test.importance",
            reason="bad importance",
            importance=4,
            timestamp=TIMESTAMP_1,
        )

    assert store.get_state("fatigue")["value"] == 0.0
    assert store.transition_count() == 0


def test_state_history_filters_and_limits_recent_records(tmp_path):
    store = InternalStateStore(tmp_path / "internal_state.db")
    store.apply_state_transition(
        state_name="fatigue",
        delta=0.1,
        cause_type="test",
        rule_id="test.one",
        reason="one",
        timestamp=TIMESTAMP_1,
        public_id=TRANSITION_ID,
    )
    store.apply_state_transition(
        state_name="uncertainty",
        delta=0.2,
        cause_type="test",
        rule_id="test.two",
        reason="two",
        timestamp=TIMESTAMP_1,
        public_id=SECOND_TRANSITION_ID,
    )
    third_id = "st_33333333-3333-4333-8333-333333333333"
    store.apply_state_transition(
        state_name="fatigue",
        delta=0.15,
        cause_type="test",
        rule_id="test.three",
        reason="three",
        timestamp=TIMESTAMP_2,
        public_id=third_id,
    )

    assert [item["id"] for item in store.list_state_transitions(state_name="fatigue")] == [
        TRANSITION_ID,
        third_id,
    ]
    assert [item["id"] for item in store.list_state_transitions(limit=2)] == [
        SECOND_TRANSITION_ID,
        third_id,
    ]


def test_reopen_preserves_state_transition_history(tmp_path):
    database = tmp_path / "internal_state.db"
    first = InternalStateStore(database)
    first.apply_state_transition(
        state_name="satisfaction",
        delta=0.3,
        cause_type="result",
        rule_id="test.success",
        reason="verified success",
        timestamp=TIMESTAMP_1,
        public_id=TRANSITION_ID,
    )

    reopened = InternalStateStore(database)

    assert reopened.get_state("satisfaction")["value"] == 0.3
    assert reopened.get_state_transition(TRANSITION_ID)["reason"] == "verified success"
    assert reopened.transition_count() == 1


def test_transition_id_requires_canonical_uuidv4(tmp_path):
    store = InternalStateStore(tmp_path / "internal_state.db")

    with pytest.raises(ValueError, match="st_ UUIDv4"):
        store.apply_state_transition(
            state_name="fatigue",
            delta=0.1,
            cause_type="test",
            rule_id="test.id",
            reason="bad id",
            timestamp=TIMESTAMP_1,
            public_id="st_not-a-uuid",
        )

    assert store.transition_count() == 0
