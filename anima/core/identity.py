import json
import uuid
from datetime import datetime
from pathlib import Path


class Identity:
    def __init__(self, identity_file="data/identity.json"):
        self.identity_file = Path(identity_file)
        self.identity = self._load_or_create()

    def _now(self):
        return datetime.now().isoformat(timespec="seconds")

    def _create_identity(self):
        return {
            "schema_version": 1,
            "instance_id": str(uuid.uuid4()),
            "created_at": self._now(),
        }

    def _load_or_create(self):
        if self.identity_file.exists():
            with self.identity_file.open("r", encoding="utf-8") as file:
                return json.load(file)

        identity = self._create_identity()

        self.identity_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self.identity_file.open("w", encoding="utf-8") as file:
            json.dump(
                identity,
                file,
                indent=4,
                ensure_ascii=False,
            )

        return identity

    def get(self):
        return self.identity
