"""P3-B: isolated, deterministic virtual door capability and independent sensor.

This is a headless test adapter. It is NOT a general-purpose world engine.
The Sandbox handler writes a sandbox-local SQLite fixture, while observations
are produced by a separate readback path that does not use tool receipts.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

from anima.agent.executor import SandboxHandler, SandboxToolError
from anima.agent.tools import ToolDescriptor, ToolRegistry
from anima.core.ingress import CONTRACT

DOOR_SUBJECT = "entity.door_01@registry-r1"
DOOR_PREDICATE = "world.door_state@1"
DOOR_SOURCE = "sensor.door_01"
DOOR_PRODUCER = "adapter.virtual_door_sensor/0.1"
DOOR_TOOL = "world.door.close"
DOOR_VERSION = "0.1"
WORLD_FILE = "virtual_door.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS door_world (
    subject_ref TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK(state IN ('open','closed')),
    tick INTEGER NOT NULL CHECK(tick>=0)
);
CREATE TABLE IF NOT EXISTS door_effects (
    operation_id TEXT PRIMARY KEY,
    subject_ref TEXT NOT NULL,
    applied INTEGER NOT NULL CHECK(applied IN (0,1)),
    FOREIGN KEY(subject_ref) REFERENCES door_world(subject_ref)
);
"""


def _connect(root):
    path = Path(root).resolve() / WORLD_FILE
    if not path.is_file():
        raise SandboxToolError("WORLD_MISSING", "virtual world is not seeded", effect_possible=False)
    connection = sqlite3.connect(path, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _check_target(arguments):
    if (
        type(arguments) is not dict
        or set(arguments) != {"subject_ref"}
        or arguments["subject_ref"] != DOOR_SUBJECT
    ):
        raise SandboxToolError("UNREGISTERED_TARGET", "unknown door target", effect_possible=False)


def _door_close(root, arguments, operation_id):
    """Keyed idempotent effect. Record effect and state in one World DB commit."""
    _check_target(arguments)
    with closing(_connect(root)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            prior = connection.execute(
                "SELECT applied, subject_ref FROM door_effects WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if prior is not None:
                if prior["subject_ref"] != DOOR_SUBJECT:
                    raise SandboxToolError("KEY_COLLISION", "operation identity mismatch")
                result = {"operation_id": operation_id, "applied": bool(prior["applied"])}
            else:
                door = connection.execute(
                    "SELECT state, tick FROM door_world WHERE subject_ref=?",
                    (DOOR_SUBJECT,),
                ).fetchone()
                if door is None:
                    raise SandboxToolError("WORLD_MISSING", "door is not registered", effect_possible=False)
                applied = door["state"] != "closed"
                if applied:
                    connection.execute(
                        "UPDATE door_world SET state='closed', tick=tick+1 WHERE subject_ref=?",
                        (DOOR_SUBJECT,),
                    )
                connection.execute(
                    "INSERT INTO door_effects(operation_id, subject_ref, applied)"
                    " VALUES (?, ?, ?)",
                    (operation_id, DOOR_SUBJECT, int(applied)),
                )
                result = {"operation_id": operation_id, "applied": applied}
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
    return result


def _door_reconcile(root, arguments, operation_id):
    """Read-only effect lookup; SandboxExecutor decides if a keyed retry is safe."""
    _check_target(arguments)
    with closing(_connect(root)) as connection:
        row = connection.execute(
            "SELECT applied, subject_ref FROM door_effects WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
    if row is None:
        return "retry", None
    if row["subject_ref"] != DOOR_SUBJECT:
        raise SandboxToolError("KEY_COLLISION", "operation identity mismatch")
    return "succeeded", {"operation_id": operation_id, "applied": bool(row["applied"])}


def _door_replay(root, arguments, operation_id):
    state, output = _door_reconcile(root, arguments, operation_id)
    if state != "succeeded":
        raise SandboxToolError("REPLAY_MISSING", "saved keyed effect was not found")
    return output


def door_tool_registry():
    """Only one exact-target tool, no arbitrary paths, scripts or shell access."""
    return ToolRegistry([ToolDescriptor(
        name=DOOR_TOOL,
        version=DOOR_VERSION,
        description="Close the single registered virtual lab door",
        input_schema={
            "type": "object",
            "properties": {
                "subject_ref": {"type": "string", "const": DOOR_SUBJECT}
            },
            "required": ["subject_ref"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "operation_id": {"type": "string"},
                "applied": {"type": "boolean"},
            },
            "required": ["operation_id", "applied"],
            "additionalProperties": False,
        },
        effect_class="reversible_write",
        idempotency="keyed",
        timeout_seconds=5.0,
    )])


def door_handlers():
    return {(DOOR_TOOL, DOOR_VERSION): SandboxHandler(
        execute=_door_close,
        reconcile=_door_reconcile,
        replay_output=_door_replay,
    )}


class VirtualDoorWorld:
    """Explicitly seeded fixture with a sensor independent of action receipts."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / WORLD_FILE
        with sqlite3.connect(self.path) as connection:
            connection.executescript(_SCHEMA)

    def seed(self, *, state="open", tick=40):
        """Seed once, never reset an existing world when rebuilding Core."""
        if state not in {"open", "closed"}:
            raise ValueError("Virtual door state must be open or closed")
        if type(tick) is not int or not 0 <= tick < 2**63 - 2:
            raise ValueError("Invalid virtual-world logical tick")
        with closing(_connect(self.root)) as connection:
            with connection:
                connection.execute(
                    "INSERT OR IGNORE INTO door_world(subject_ref, state, tick)"
                    " VALUES (?, ?, ?)",
                    (DOOR_SUBJECT, state, tick),
                )

    def current(self):
        """Test-operator view only; never pass direct state to Core policy."""
        with closing(_connect(self.root)) as connection:
            row = connection.execute(
                "SELECT state, tick FROM door_world WHERE subject_ref=?",
                (DOOR_SUBJECT,),
            ).fetchone()
        if row is None:
            raise ValueError("Virtual door not seeded")
        return {"state": row["state"], "tick": row["tick"]}

    def change_by_environment(self, state):
        """Test-only independent external change to exercise false receipts/races."""
        if state not in {"open", "closed"}:
            raise ValueError("Invalid environment door state")
        with closing(_connect(self.root)) as connection:
            with connection:
                connection.execute(
                    "UPDATE door_world SET state=?, tick=tick+1 WHERE subject_ref=?",
                    (state, DOOR_SUBJECT),
                )

    def sense(self):
        """Read the world and create a distinct immutable observation occurrence.

        No action receipt or operation log is consulted by this observation path.
        The returned event still must pass CoreIngress's source/property checks.
        """
        with closing(_connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                door = connection.execute(
                    "SELECT state,tick FROM door_world WHERE subject_ref=?",
                    (DOOR_SUBJECT,),
                ).fetchone()
                if door is None:
                    raise ValueError("Virtual door not seeded")
                tick = door["tick"] + 1
                value = door["state"]
                connection.execute(
                    "UPDATE door_world SET tick=? WHERE subject_ref=?",
                    (tick, DOOR_SUBJECT),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        observed = {"domain": "lab_tick", "value": tick}
        raw = {
            "contract": CONTRACT,
            "occurrence_id": f"door-reading-{tick}",
            "occurrence_version": 1,
            "kind": "state.property",
            "payload": {
                "subject_ref": DOOR_SUBJECT,
                "predicate_ref": DOOR_PREDICATE,
                "observed_at": observed,
                "temporal_scope": {"kind": "instant", "at": dict(observed)},
                "source_revision": tick,
                "value": {"type": "symbol", "value": value},
            },
        }
        return raw, tick


__all__ = [
    "DOOR_SUBJECT", "DOOR_PREDICATE", "DOOR_SOURCE", "DOOR_PRODUCER",
    "DOOR_TOOL", "DOOR_VERSION", "VirtualDoorWorld", "door_tool_registry",
    "door_handlers",
]
