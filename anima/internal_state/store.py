import math
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from anima.config.paths import get_data_dir
from anima.internal_state.config import load_internal_state_config


SCHEMA_VERSION = 1
STATE_TRANSITION_ID_PREFIX = "st_"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS state_values (
    name TEXT PRIMARY KEY,
    value REAL NOT NULL CHECK (value >= 0.0 AND value <= 1.0),
    updated_at TEXT NOT NULL,
    ruleset_version INTEGER NOT NULL CHECK (ruleset_version >= 1)
);

CREATE TABLE IF NOT EXISTS state_transitions (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    state_name TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    before_value REAL NOT NULL CHECK (before_value >= 0.0 AND before_value <= 1.0),
    delta REAL NOT NULL,
    after_value REAL NOT NULL CHECK (after_value >= 0.0 AND after_value <= 1.0),
    cause_type TEXT NOT NULL,
    source_id TEXT,
    rule_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    importance INTEGER CHECK (importance BETWEEN 0 AND 3),
    repetition_factor REAL CHECK (repetition_factor IS NULL OR repetition_factor >= 0.0),
    elapsed_seconds REAL CHECK (elapsed_seconds IS NULL OR elapsed_seconds >= 0.0),
    goal_id TEXT,
    candidate_id TEXT,
    FOREIGN KEY (state_name) REFERENCES state_values(name)
);

CREATE INDEX IF NOT EXISTS idx_state_transitions_state_time
    ON state_transitions(state_name, timestamp);
CREATE INDEX IF NOT EXISTS idx_state_transitions_source
    ON state_transitions(source_id);
CREATE INDEX IF NOT EXISTS idx_state_transitions_goal
    ON state_transitions(goal_id);

CREATE TABLE IF NOT EXISTS goals (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    priority REAL NOT NULL CHECK (priority >= 0.0),
    status TEXT NOT NULL CHECK (status IN ('active', 'blocked', 'completed', 'cancelled')),
    description TEXT NOT NULL,
    success_criterion TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_goals_status_priority
    ON goals(status, priority DESC);

CREATE TABLE IF NOT EXISTS goal_transitions (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    goal_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    from_status TEXT CHECK (
        from_status IS NULL OR from_status IN ('active', 'blocked', 'completed', 'cancelled')
    ),
    to_status TEXT NOT NULL CHECK (
        to_status IN ('active', 'blocked', 'completed', 'cancelled')
    ),
    source_id TEXT,
    reason TEXT NOT NULL,
    FOREIGN KEY (goal_id) REFERENCES goals(public_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_goal_transitions_goal_time
    ON goal_transitions(goal_id, timestamp);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_timestamp(value, label):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must be ISO 8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")


def _validate_non_empty_string(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")


def _validate_optional_string(value, label):
    if value is not None:
        _validate_non_empty_string(value, label)


def _validate_transition_id(public_id):
    if (
        not isinstance(public_id, str)
        or not public_id.startswith(STATE_TRANSITION_ID_PREFIX)
    ):
        raise ValueError("StateTransition public_id must be an st_ UUIDv4")

    raw_uuid = public_id[len(STATE_TRANSITION_ID_PREFIX):]
    try:
        parsed = UUID(raw_uuid)
    except (ValueError, AttributeError) as error:
        raise ValueError("StateTransition public_id must be an st_ UUIDv4") from error

    if parsed.version != 4 or str(parsed) != raw_uuid:
        raise ValueError("StateTransition public_id must be an st_ UUIDv4")


def _validate_optional_non_negative_number(value, label):
    if value is None:
        return
    if not _is_number(value) or not math.isfinite(float(value)) or value < 0.0:
        raise ValueError(f"{label} must be a finite non-negative number or null")


class InternalStateStore:
    def __init__(self, database_file=None, config_file=None):
        self.database_file = (
            Path(database_file)
            if database_file is not None
            else get_data_dir() / "internal_state.db"
        )
        self.config = load_internal_state_config(config_file)
        self.database_file.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_file)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self):
        try:
            with closing(self._connect()) as connection, connection:
                connection.executescript(SCHEMA_SQL)
                connection.execute(
                    "INSERT OR IGNORE INTO schema_meta(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO schema_meta(key, value) VALUES('ruleset_version', ?)",
                    (str(self.config["ruleset_version"]),),
                )

                schema_row = connection.execute(
                    "SELECT value FROM schema_meta WHERE key = 'schema_version'"
                ).fetchone()
                ruleset_row = connection.execute(
                    "SELECT value FROM schema_meta WHERE key = 'ruleset_version'"
                ).fetchone()

                if schema_row is None or schema_row["value"] != str(SCHEMA_VERSION):
                    raise ValueError(
                        f"Unsupported Internal State database schema in {self.database_file}"
                    )

                if (
                    ruleset_row is None
                    or ruleset_row["value"] != str(self.config["ruleset_version"])
                ):
                    raise ValueError(
                        f"Internal State ruleset mismatch in {self.database_file}"
                    )

                timestamp = _now()
                for state_name, spec in self.config["states"].items():
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO state_values(
                            name, value, updated_at, ruleset_version
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            state_name,
                            float(spec["baseline"]),
                            timestamp,
                            self.config["ruleset_version"],
                        ),
                    )

                rows = connection.execute(
                    "SELECT name FROM state_values"
                ).fetchall()
                stored_states = {row["name"] for row in rows}
                configured_states = set(self.config["states"])
                unknown_states = stored_states - configured_states
                if unknown_states:
                    names = ", ".join(sorted(unknown_states))
                    raise ValueError(
                        "Internal State database contains states absent from config: "
                        f"{names}"
                    )
        except ValueError:
            raise
        except sqlite3.DatabaseError as error:
            raise ValueError(
                f"Cannot initialize Internal State database {self.database_file}: {error}"
            ) from error

    @contextmanager
    def transaction(self):
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def schema_version(self):
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
        return int(row["value"])

    def ruleset_version(self):
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'ruleset_version'"
            ).fetchone()
        return int(row["value"])

    @staticmethod
    def _row_to_state(row):
        if row is None:
            return None
        return {
            "name": row["name"],
            "value": row["value"],
            "updated_at": row["updated_at"],
            "ruleset_version": row["ruleset_version"],
        }

    @staticmethod
    def _row_to_state_transition(row):
        if row is None:
            return None
        return {
            "id": row["public_id"],
            "state_name": row["state_name"],
            "timestamp": row["timestamp"],
            "before": row["before_value"],
            "delta": row["delta"],
            "after": row["after_value"],
            "cause_type": row["cause_type"],
            "source_id": row["source_id"],
            "rule_id": row["rule_id"],
            "reason": row["reason"],
            "importance": row["importance"],
            "repetition_factor": row["repetition_factor"],
            "elapsed_seconds": row["elapsed_seconds"],
            "goal_id": row["goal_id"],
            "candidate_id": row["candidate_id"],
        }

    def get_state(self, state_name):
        if not isinstance(state_name, str) or not state_name:
            raise ValueError("State name must be a non-empty string")
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM state_values WHERE name = ?",
                (state_name,),
            ).fetchone()
        return self._row_to_state(row)

    def list_states(self):
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT * FROM state_values ORDER BY name"
            ).fetchall()
        return [self._row_to_state(row) for row in rows]

    def apply_state_transition(
        self,
        *,
        state_name,
        delta,
        cause_type,
        rule_id,
        reason,
        source_id=None,
        importance=None,
        repetition_factor=None,
        elapsed_seconds=None,
        goal_id=None,
        candidate_id=None,
        timestamp=None,
        public_id=None,
    ):
        if state_name not in self.config["states"]:
            raise ValueError(f"Unknown Internal State: {state_name!r}")

        if not _is_number(delta) or not math.isfinite(float(delta)):
            raise ValueError("StateTransition delta must be a finite number")
        delta = float(delta)

        _validate_non_empty_string(cause_type, "StateTransition cause_type")
        _validate_non_empty_string(rule_id, "StateTransition rule_id")
        _validate_non_empty_string(reason, "StateTransition reason")
        _validate_optional_string(source_id, "StateTransition source_id")
        _validate_optional_string(goal_id, "StateTransition goal_id")
        _validate_optional_string(candidate_id, "StateTransition candidate_id")

        if importance is not None and (
            not isinstance(importance, int)
            or isinstance(importance, bool)
            or importance not in range(4)
        ):
            raise ValueError(
                "StateTransition importance must be an integer from 0 to 3 or null"
            )

        _validate_optional_non_negative_number(
            repetition_factor,
            "StateTransition repetition_factor",
        )
        _validate_optional_non_negative_number(
            elapsed_seconds,
            "StateTransition elapsed_seconds",
        )

        timestamp = timestamp or _now()
        _validate_timestamp(timestamp, "StateTransition timestamp")

        public_id = public_id or f"{STATE_TRANSITION_ID_PREFIX}{uuid4()}"
        _validate_transition_id(public_id)

        spec = self.config["states"][state_name]

        try:
            with self.transaction() as connection:
                row = connection.execute(
                    "SELECT value FROM state_values WHERE name = ?",
                    (state_name,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"Unknown Internal State: {state_name!r}")

                before = float(row["value"])
                after = before + delta
                minimum = float(spec["minimum"])
                maximum = float(spec["maximum"])

                if not minimum <= after <= maximum:
                    raise ValueError(
                        f"StateTransition would move {state_name!r} outside "
                        f"{minimum}..{maximum}: {before} + {delta} = {after}"
                    )

                connection.execute(
                    """
                    UPDATE state_values
                    SET value = ?, updated_at = ?, ruleset_version = ?
                    WHERE name = ?
                    """,
                    (
                        after,
                        timestamp,
                        self.config["ruleset_version"],
                        state_name,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO state_transitions(
                        public_id, state_name, timestamp, before_value, delta,
                        after_value, cause_type, source_id, rule_id, reason,
                        importance, repetition_factor, elapsed_seconds,
                        goal_id, candidate_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        public_id,
                        state_name,
                        timestamp,
                        before,
                        delta,
                        after,
                        cause_type.strip(),
                        source_id.strip() if source_id is not None else None,
                        rule_id.strip(),
                        reason.strip(),
                        importance,
                        float(repetition_factor)
                        if repetition_factor is not None
                        else None,
                        float(elapsed_seconds) if elapsed_seconds is not None else None,
                        goal_id.strip() if goal_id is not None else None,
                        candidate_id.strip() if candidate_id is not None else None,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                f"Cannot apply StateTransition {public_id}: {error}"
            ) from error

        return self.get_state_transition(public_id)

    def get_state_transition(self, public_id):
        _validate_transition_id(public_id)
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM state_transitions WHERE public_id = ?",
                (public_id,),
            ).fetchone()
        return self._row_to_state_transition(row)

    def list_state_transitions(self, *, state_name=None, limit=None):
        if state_name is not None and state_name not in self.config["states"]:
            raise ValueError(f"Unknown Internal State: {state_name!r}")

        if limit is not None and (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 0
        ):
            raise ValueError(
                "StateTransition limit must be a non-negative integer or null"
            )

        if limit == 0:
            return []

        clauses = []
        values = []
        if state_name is not None:
            clauses.append("state_name = ?")
            values.append(state_name)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit_sql = ""
        if limit is not None:
            limit_sql = " LIMIT ?"
            values.append(limit)

        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                f"""
                SELECT * FROM state_transitions
                {where}
                ORDER BY row_id DESC
                {limit_sql}
                """,
                values,
            ).fetchall()

        return [
            self._row_to_state_transition(row)
            for row in reversed(rows)
        ]

    def transition_count(self, state_name=None):
        if state_name is not None and state_name not in self.config["states"]:
            raise ValueError(f"Unknown Internal State: {state_name!r}")

        query = "SELECT COUNT(*) AS count FROM state_transitions"
        values = ()
        if state_name is not None:
            query += " WHERE state_name = ?"
            values = (state_name,)

        with closing(self._connect()) as connection, connection:
            row = connection.execute(query, values).fetchone()
        return row["count"]

    def export_debug(self):
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        return {
            "schema_version": self.schema_version(),
            "ruleset_version": self.ruleset_version(),
            "tables": [row["name"] for row in rows],
            "states": self.list_states(),
            "state_transition_count": self.transition_count(),
        }
