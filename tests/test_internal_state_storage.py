import json
import sqlite3

import pytest

from anima.internal_state.config import load_internal_state_config
from anima.internal_state.store import InternalStateStore


EXPECTED_STATES = {"fatigue", "uncertainty", "frustration", "satisfaction"}


def test_internal_state_store_initializes_schema_and_baselines(tmp_path):
    store = InternalStateStore(tmp_path / "internal_state.db")
    snapshot = store.export_debug()

    assert snapshot["schema_version"] == 1
    assert snapshot["ruleset_version"] == 1
    assert {item["name"] for item in snapshot["states"]} == EXPECTED_STATES
    assert all(item["value"] == 0.0 for item in snapshot["states"])

    assert {
        "state_values",
        "state_transitions",
        "goals",
        "goal_transitions",
    } <= set(snapshot["tables"])


def test_internal_state_store_reopens_without_resetting_live_state(tmp_path):
    database = tmp_path / "internal_state.db"
    first = InternalStateStore(database)

    with first.transaction() as connection:
        connection.execute(
            "UPDATE state_values SET value = 0.4 WHERE name = 'fatigue'"
        )

    reopened = InternalStateStore(database)

    assert reopened.get_state("fatigue")["value"] == 0.4
    assert reopened.ruleset_version() == 1


def test_internal_state_transaction_rolls_back(tmp_path):
    store = InternalStateStore(tmp_path / "internal_state.db")

    with pytest.raises(RuntimeError, match="rollback test"):
        with store.transaction() as connection:
            connection.execute(
                "UPDATE state_values SET value = 0.7 WHERE name = 'fatigue'"
            )
            raise RuntimeError("rollback test")

    assert store.get_state("fatigue")["value"] == 0.0


def test_internal_state_database_constraints(tmp_path):
    store = InternalStateStore(tmp_path / "internal_state.db")

    with store.transaction() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE state_values SET value = 1.5 WHERE name = 'fatigue'"
            )

    with store.transaction() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO goals(
                    public_id, source, priority, status, description,
                    success_criterion, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "goal_test",
                    "test",
                    1.0,
                    "unknown",
                    "invalid goal",
                    "never",
                    "2026-10-26T00:00:00+00:00",
                    "2026-10-26T00:00:00+00:00",
                ),
            )


def test_internal_state_foreign_keys_are_enabled(tmp_path):
    store = InternalStateStore(tmp_path / "internal_state.db")

    with store.transaction() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO state_transitions(
                    public_id, state_name, timestamp, before_value, delta,
                    after_value, cause_type, rule_id, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "st_test",
                    "missing_state",
                    "2026-10-26T00:00:00+00:00",
                    0.0,
                    0.1,
                    0.1,
                    "test",
                    "test_rule",
                    "foreign key test",
                ),
            )


def test_internal_state_database_reports_invalid_file(tmp_path):
    database = tmp_path / "internal_state.db"
    database.write_text("not sqlite", encoding="utf-8")

    with pytest.raises(ValueError, match="Cannot initialize Internal State database"):
        InternalStateStore(database)


def test_internal_state_config_validation_rejects_invalid_baseline(tmp_path):
    config_file = tmp_path / "internal_state.json"
    config = {
        "schema_version": 1,
        "ruleset_version": 1,
        "states": {
            "fatigue": {"minimum": 0.0, "baseline": 2.0, "maximum": 1.0},
            "uncertainty": {"minimum": 0.0, "baseline": 0.0, "maximum": 1.0},
            "frustration": {"minimum": 0.0, "baseline": 0.0, "maximum": 1.0},
            "satisfaction": {"minimum": 0.0, "baseline": 0.0, "maximum": 1.0},
        },
    }
    config_file.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="baseline must be within"):
        load_internal_state_config(config_file)


def test_internal_state_default_database_uses_anima_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ANIMA_DATA_DIR", str(tmp_path))

    store = InternalStateStore()

    assert store.database_file == tmp_path / "internal_state.db"
    assert store.database_file.exists()
