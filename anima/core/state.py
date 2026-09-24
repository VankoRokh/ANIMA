import json
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

    def _load_or_create(self):
        if self.state_file.exists():
            with self.state_file.open("r", encoding="utf-8") as file:
                return json.load(file)

        state = self._default_state()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        with self.state_file.open("w", encoding="utf-8") as file:
            json.dump(state, file, indent=4, ensure_ascii=False)

        return state

    def save(self):
        with self.state_file.open("w", encoding="utf-8") as file:
            json.dump(
                self.state,
                file,
                indent=4,
                ensure_ascii=False,
            )

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
