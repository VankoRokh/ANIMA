import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

VALID_STATUSES = {"created", "awake", "sleeping"}

class AnimaState:
    def __init__(self, state_file="data/state.json"):
        self.state_file = Path(state_file)
        self.state = self._load_or_create()

    def _now(self):
        return datetime.now().isoformat(timespec="seconds")

    def _default_state(self):
        now = self._now()

        return {
            "name": "ANIMA",
            "version": "00.1-alpha",
            "status": "created",
            "session": 0,
            "created_at": now,
            "last_wake": None,
            "last_sleep": None,
            "events_processed": 0,
        }

    def _validate_state(self, state):
        if not isinstance(state, dict):
            raise ValueError(
                f"Invalid state file {self.state_file}: "
                "root value must be an object"
            )

        required_fields = {
            "name",
            "version",
            "status",
            "session",
            "created_at",
            "last_wake",
            "last_sleep",
            "events_processed",
        }

        missing_fields = required_fields - state.keys()

        if missing_fields:
            missing = ", ".join(sorted(missing_fields))
            raise ValueError(
                f"Invalid state file {self.state_file}: "
                f"missing fields: {missing}"
            )

        if not isinstance(state["name"], str) or not state["name"]:
            raise ValueError(
                f"Invalid state file {self.state_file}: "
                "'name' must be a non-empty string"
            )

        if not isinstance(state["version"], str) or not state["version"]:
            raise ValueError(
                f"Invalid state file {self.state_file}: "
                "'version' must be a non-empty string"
            )

        if state["status"] not in VALID_STATUSES:
            raise ValueError(
                f"Invalid state file {self.state_file}: "
                f"unknown status {state['status']!r}"
            )

        for field in ("session", "events_processed"):
            value = state[field]

            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(
                    f"Invalid state file {self.state_file}: "
                    f"'{field}' must be a non-negative integer"
                )

        for field in ("created_at", "last_wake", "last_sleep"):
            value = state[field]

            if value is not None and not isinstance(value, str):
                raise ValueError(
                    f"Invalid state file {self.state_file}: "
                    f"'{field}' must be a string or null"
                )

        return state

    def _write_state(self, state):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        file_descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{self.state_file.name}.",
            suffix=".tmp",
            dir=self.state_file.parent,
            text=True,
        )

        temp_path = Path(temp_name)

        try:
            with os.fdopen(
                file_descriptor,
                "w",
                encoding="utf-8",
            ) as file:
                json.dump(
                    state,
                    file,
                    indent=4,
                    ensure_ascii=False,
                )
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())

            os.replace(temp_path, self.state_file)

        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    def _load_or_create(self):
        if self.state_file.exists():
            try:
                with self.state_file.open("r", encoding="utf-8") as file:
                    state = json.load(file)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Invalid state file {self.state_file}: malformed JSON"
                ) from error

            return self._validate_state(state)

        state = self._default_state()
        self._write_state(state)
        return state

    def save(self):
        self._write_state(self.state)

    def wake(self):
        self.state["status"] = "awake"
        self.state["session"] += 1
        self.state["last_wake"] = self._now()
        self.save()

    def sleep(self):
        self.state["status"] = "sleeping"
        self.state["last_sleep"] = self._now()
        self.save()

    def register_event(self):
        self.state["events_processed"] += 1
        self.save()

    def get(self):
        return self.state
