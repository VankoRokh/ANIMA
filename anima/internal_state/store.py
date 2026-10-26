import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from anima.config.paths import get_data_dir
from anima.internal_state.config import load_internal_state_config


SCHEMA_VERSION = 1

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
            with self._connect() as connection:
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
            connection.execute("BEGIN")
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def schema_version(self):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
        return int(row["value"])

    def ruleset_version(self):
        with self._connect() as connection:
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

    def get_state(self, state_name):
        if not isinstance(state_name, str) or not state_name:
            raise ValueError("State name must be a non-empty string")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM state_values WHERE name = ?",
                (state_name,),
            ).fetchone()
        return self._row_to_state(row)

    def list_states(self):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM state_values ORDER BY name"
            ).fetchall()
        return [self._row_to_state(row) for row in rows]

    def export_debug(self):
        with self._connect() as connection:
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
        }
