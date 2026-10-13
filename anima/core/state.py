import json
import os
import tempfile
from datetime import datetime
from pathlib import Path


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
            with self.state_file.open("r", encoding="utf-8") as file:
                return json.load(file)

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
