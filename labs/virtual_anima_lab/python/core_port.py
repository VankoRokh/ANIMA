"""P6 experimental plug-in: VAL door I/O for CoreDoorExecution.

NOT part of anima/core and NOT a production trust boundary. The source name
used in Core is granted by the composition root, never copied from a Lab role.
No world truth 'inspect' and no operator commands are used. Bridge roles are
self-declared on loopback; protect against untrusted local clients separately.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable

from anima.agent.executor import SandboxHandler, SandboxToolError
from anima.core.door_world import (
    DOOR_PREDICATE, DOOR_PRODUCER, DOOR_SOURCE, DOOR_SUBJECT, DOOR_TOOL,
    DOOR_VERSION,
)
from anima.core.ingress import CONTRACT

from .contracts import LabContractError, validate_observation
from .lab_client import LabClient, LabProtocolError, LabRejected, PROTOCOL_V2


class VALPortError(RuntimeError):
    """Fail closed on an invalid sensor or a changed environment identity."""


class VALDoorPort:
    """Implements Core's narrow world port without Core importing the Lab.

    Logical Core 'lab_sample' time is a durable local SAMPLE sequence, not
    Godot's world tick or revision. Both original values are retained in the
    adapter evidence log. An epoch reset or Godot process replacement requires
    a NEW Core/adapter data directory; continuity is never inferred.
    """

    def __init__(
        self, root: str | Path, *, port: int = 46019, timeout: float = 3.0,
        client_factory: Callable = LabClient,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database_file = self.root / "val_p6_port.db"
        self.port = port
        self.timeout = timeout
        self.client_factory = client_factory
        with closing(sqlite3.connect(self.database_file)) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS world_binding (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    instance_id TEXT NOT NULL,
                    epoch INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sample_log (
                    sample_seq INTEGER PRIMARY KEY,
                    instance_id TEXT NOT NULL,
                    lab_observation_id TEXT UNIQUE NOT NULL,
                    epoch INTEGER NOT NULL,
                    world_tick INTEGER NOT NULL,
                    world_revision INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );
            """)

    def _client(self):
        return self.client_factory(
            self.port, role="agent", protocol=PROTOCOL_V2, timeout=self.timeout,
        )

    @staticmethod
    def _identity(hello: dict) -> str:
        if type(hello) is not dict:
            raise VALPortError("invalid VAL handshake")
        ident = hello.get("world_instance_id")
        if (
            type(ident) is not str
            or re.fullmatch(r"[0-9a-f]{32}", ident) is None
            or hello.get("world_version") != "p5a-grid/0.1"
            or hello.get("scenario") != "p6_door"
            or hello.get("source_ref") != "lab.sensor.anima.proximity"
        ):
            raise VALPortError("wrong or unauthenticated VAL demo world identity")
        if not {"observe", "act_door", "door_operation_status"} <= set(
            hello.get("capabilities", ())
        ):
            raise VALPortError("VAL bridge lacks P6 agent capabilities")
        return ident

    def _binding(self) -> tuple[str, int] | None:
        with closing(sqlite3.connect(self.database_file)) as db:
            row = db.execute(
                "SELECT instance_id,epoch FROM world_binding WHERE singleton=1"
            ).fetchone()
        return (row[0], row[1]) if row is not None else None

    def _check_binding(self, ident: str, epoch: int) -> None:
        bound = self._binding()
        if bound != (ident, epoch):
            raise VALPortError("VAL process/epoch changed; refusing stale Core session")

    def _next_sample(self, ident: str, obs: dict) -> int:
        clock = obs["observed_at"]
        epoch, tick = clock["epoch"], clock["tick"]
        with closing(sqlite3.connect(self.database_file)) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT instance_id,epoch FROM world_binding WHERE singleton=1"
                ).fetchone()
                if row is None:
                    db.execute(
                        "INSERT INTO world_binding(singleton,instance_id,epoch)"
                        " VALUES(1,?,?)", (ident, epoch),
                    )
                elif (row[0], row[1]) != (ident, epoch):
                    raise VALPortError(
                        "VAL process/epoch changed; start a fresh P6 test instance"
                    )
                existing = db.execute(
                    "SELECT sample_seq FROM sample_log WHERE lab_observation_id=?",
                    (obs["observation_id"],),
                ).fetchone()
                if existing is not None:
                    # Re-observing the exact same occurrence cannot create support.
                    return existing[0]
                seq = db.execute(
                    "SELECT COALESCE(MAX(sample_seq),0)+1 FROM sample_log"
                ).fetchone()[0]
                db.execute(
                    "INSERT INTO sample_log(sample_seq,instance_id,"
                    " lab_observation_id,epoch,world_tick,world_revision,payload_json)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (seq, ident, obs["observation_id"], epoch, tick,
                     obs["world_revision"], json.dumps(obs, sort_keys=True)),
                )
                db.commit()
                return seq
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def _door_reading(observation: dict) -> dict | None:
        matching = [
            row for row in observation["readings"]
            if row["subject_ref"] == "lab.door.01"
            and row["predicate_ref"] == "state"
        ]
        if len(matching) > 1:
            raise VALPortError("duplicate door readings")
        return matching[0] if matching else None

    def sense(self) -> tuple[dict, int]:
        with self._client() as client:
            ident = self._identity(client.call("hello")["data"])
            envelope = client.call("observe")
        obs = validate_observation(envelope["data"], envelope)
        seq = self._next_sample(ident, obs)
        observed = {"domain": "lab_sample", "value": seq}
        door = self._door_reading(obs)
        kind = "state.property" if door is not None else "sensor.unavailable"
        payload = {
            "subject_ref": DOOR_SUBJECT,
            "predicate_ref": DOOR_PREDICATE,
            "observed_at": observed,
            "temporal_scope": {"kind": "instant", "at": dict(observed)},
            "source_revision": seq,
        }
        if door is None:
            payload["reason"] = "DOOR_NOT_VISIBLE"
        else:
            payload["value"] = door["typed_value"]
        raw = {
            "contract": CONTRACT,
            "occurrence_id": f"p6:{ident}:{obs['observation_id']}",
            "occurrence_version": 1,
            "kind": kind,
            "payload": payload,
        }
        return raw, seq

    @staticmethod
    def _target(arguments: dict) -> None:
        if type(arguments) is not dict or arguments != {"subject_ref": DOOR_SUBJECT}:
            raise SandboxToolError(
                "UNREGISTERED_TARGET", "P6 can close only the registered door",
                effect_possible=False,
            )

    @staticmethod
    def _receipt(data: dict, operation_id: str) -> dict:
        if (
            type(data) is not dict or set(data) != {
                "schema", "operation_id", "status", "effect_applied", "reason",
                "event_id", "world_epoch", "world_revision", "tick", "replayed",
            }
            or data["schema"] != "val.door_receipt/0.1"
            or data["operation_id"] != operation_id
            or data["status"] not in ("APPLIED", "BLOCKED")
            or type(data["effect_applied"]) is not bool
            or data["effect_applied"] != (data["status"] == "APPLIED")
            or data["reason"] not in (
                "ok", "not_adjacent", "occupied", "already_closed"
            )
            or (data["reason"] == "ok") != data["effect_applied"]
            or type(data["replayed"]) is not bool
            or type(data["event_id"]) is not str
            or not data["event_id"].startswith("val_evt:")
            or any(type(data[key]) is not int or data[key] < 0
                   for key in ("world_epoch", "world_revision", "tick"))
        ):
            raise VALPortError("invalid P6 door receipt")
        return data

    def execute(self, root, arguments: dict, operation_id: str) -> dict:
        self._target(arguments)
        try:
            with self._client() as client:
                ident = self._identity(client.call("hello")["data"])
                envelope = client.call("observe")
                obs = validate_observation(envelope["data"], envelope)
                epoch = obs["observed_at"]["epoch"]
                self._check_binding(ident, epoch)
                reading = self._door_reading(obs)
                if reading is None:
                    raise SandboxToolError(
                        "DOOR_OUT_OF_VIEW", "door is not observed", effect_possible=False
                    )
                if reading["typed_value"] != {"type": "symbol", "value": "open"}:
                    raise SandboxToolError(
                        "DOOR_NOT_OPEN", "door does not require close", effect_possible=False
                    )
                result = client.call(
                    "act_door",
                    operation_id=operation_id,
                    action={"schema": "val.door_action/0.1", "kind": "close_door"},
                    expected_epoch=epoch,
                    expected_revision=obs["world_revision"],
                )
                receipt = self._receipt(result["data"], operation_id)
                if receipt["world_epoch"] != epoch:
                    raise VALPortError("door receipt epoch mismatch")
                if receipt["status"] != "APPLIED":
                    raise SandboxToolError(
                        "LAB_BLOCKED", receipt["reason"], effect_possible=False
                    )
                return {"operation_id": operation_id, "applied": True}
        except LabRejected as exc:
            raise SandboxToolError(
                "LAB_REJECTED", exc.error, effect_possible=False,
            ) from exc
        except (OSError, TimeoutError, ConnectionError, LabProtocolError,
                LabContractError, VALPortError) as exc:
            # Could have committed before a response was lost: never retry blindly.
            raise SandboxToolError(
                "LAB_UNCERTAIN", str(exc), effect_possible=True,
            ) from exc

    def reconcile(self, arguments: dict, operation_id: str) -> tuple[str, dict | None]:
        """ONLY query the live Lab ledger; missing entry is ambiguous, not retry."""
        self._target(arguments)
        try:
            with self._client() as client:
                ident = self._identity(client.call("hello")["data"])
                binding = self._binding()
                if binding is None or binding[0] != ident:
                    return "unknown", None
                response = client.call(
                    "door_operation_status", operation_id=operation_id
                )
                payload = response["data"]
                if type(payload) is not dict or type(payload.get("found")) is not bool:
                    return "unknown", None
                if not payload["found"]:
                    return "unknown", None
                receipt = self._receipt(payload.get("receipt"), operation_id)
                if receipt["world_epoch"] != binding[1]:
                    return "unknown", None
                if receipt["status"] == "APPLIED":
                    return "succeeded", {
                        "operation_id": operation_id, "applied": True,
                    }
        except (OSError, TimeoutError, ConnectionError, LabProtocolError,
                LabContractError, LabRejected, VALPortError):
            pass
        return "unknown", None

    def reconcile_tool(self, root, arguments: dict, operation_id: str):
        return self.reconcile(arguments, operation_id)

    def replay_output(self, root, arguments: dict, operation_id: str) -> dict:
        status, output = self.reconcile(arguments, operation_id)
        if status != "succeeded":
            raise SandboxToolError(
                "REPLAY_UNKNOWN", "cannot prove previous effect; no new effect issued"
            )
        return output

    def handlers(self):
        return {(DOOR_TOOL, DOOR_VERSION): SandboxHandler(
            execute=self.execute,
            reconcile=self.reconcile_tool,
            replay_output=self.replay_output,
        )}


__all__ = ["VALDoorPort", "VALPortError"]
