"""E4 isolated SQLite source-authority SIGKILL probe. NOT production Memory.

Run through subprocesses; actual signal 9 kills the worker while a SQLite
transaction is open or just after it was committed. A different interpreter
reopens the database for verification.
"""
import argparse
import json
import os
from pathlib import Path
import signal

from anima.core.event_bus import Event
from labs.exp009.e4_alias_lifecycle_lab import AliasLifecycleLab
from labs.exp009.e4_source_authority_gate import (
    AuthorizedAliasLifecycleLab, LabAdapterRegistration,
)

TOKEN_A = b"A" * 32
TOKEN_B = b"B" * 32


def _registry():
    return {
        "adapter.a": LabAdapterRegistration("adapter.a", "principal.a", TOKEN_A),
        "adapter.b": LabAdapterRegistration("adapter.b", "principal.b", TOKEN_B),
    }


def _raw(n, text, control=None, refs=None, session="s1", when=None):
    return Event(
        "conversation.user",
        {"text": text, **({"alias_control": control} if control is not None else {})},
        source="user", session_id=session, references=refs or [],
        event_id=f"ev_00000000-0000-4000-8000-{n:012d}",
        timestamp=when or f"2026-11-12T10:{n:02d}:00+00:00",
    ).to_dict()


def _events():
    a = _raw(1, "Мой адаптер А = БП alpha",
             {"action": "define", "alias_id": "a", "surface": "адаптер",
              "target_entity_id": "psu:alpha"},
             [{"kind": "entity", "id": "psu:alpha"}])
    b = _raw(2, "Мой адаптер Б = БП beta",
             {"action": "define", "alias_id": "b", "surface": "адаптер",
              "target_entity_id": "psu:beta"},
             [{"kind": "entity", "id": "psu:beta"}])
    obs = _raw(3, "Pi5 reports power problem")
    revoke = _raw(4, "Отзываю определение А",
                  {"action": "revoke", "alias_id": "a",
                   "definition_event_id": a["id"]},
                  [{"kind": "event", "id": a["id"]}],
                  session="s2", when="2026-11-13T10:00:00+00:00")
    return a, b, obs, revoke


def seed(db_path):
    j = AuthorizedAliasLifecycleLab(db_path, adapters=_registry())
    a, b, obs, rev = _events()
    j.admit_event(a, adapter_ref="adapter.a", token=TOKEN_A)
    j.admit_event(b, adapter_ref="adapter.b", token=TOKEN_B)
    j.append_event(obs)
    j.admit_event(rev, adapter_ref="adapter.a", token=TOKEN_A)
    j.define(alias_id="a", definition_event_id=a["id"], operation_key="define_a")
    j.define(alias_id="b", definition_event_id=b["id"], operation_key="define_b")
    j.create_node(node_id="S", kind="Story",
                  source_event_ids=[a["id"], obs["id"]],
                  alias_dependencies=[("a", 1)], node_dependencies=[],
                  operation_key="seed_S")
    j.create_node(node_id="E", kind="Episode",
                  source_event_ids=[obs["id"]],
                  alias_dependencies=[], node_dependencies=[("S", 1)],
                  operation_key="seed_E")
    j.create_node(node_id="U", kind="Story",
                  source_event_ids=[b["id"], obs["id"]],
                  alias_dependencies=[("b", 1)], node_dependencies=[],
                  operation_key="seed_U")
    return check(db_path, "before")


def _revocation(j):
    rev = _events()[3]
    return j.revoke(alias_id="a", revocation_event_id=rev["id"],
                    expected_head=1, operation_key="revoke_a")


def _kill(marker):
    print(marker, flush=True)
    os.kill(os.getpid(), signal.SIGKILL)
    raise AssertionError("Expected the process to be killed")


class _KillBefore(AuthorizedAliasLifecycleLab):
    @staticmethod
    def _save_op(db, operation_key, request, result):
        AliasLifecycleLab._save_op(db, operation_key, request, result)
        if request["kind"] == "revoke":
            _kill("CUT_INSIDE_UNCOMMITTED_TRANSACTION")


class _KillAfter(AuthorizedAliasLifecycleLab):
    def revoke(self, **kwargs):
        result = super().revoke(**kwargs)
        _kill("CUT_AFTER_COMMITTED_TRANSACTION")
        return result


def check(db_path, stage):
    j = AuthorizedAliasLifecycleLab(db_path, adapters=_registry())
    heads = {name: j.node(name)["head_state"] for name in ("S", "E", "U")}
    authority = j.authority_counts()
    receipt = j.allowed_decision("revoke_a")
    actual = {
        "alias_a": j.alias("a")["head_state"],
        "alias_b": j.alias("b")["head_state"],
        "heads": heads,
        "invalidations": j.invalidations("revoke_a"),
        "allowed": authority["allowed_revocations"],
        "operations": j.count("operations"),
        "raw_events": j.count("raw_events"),
        "alias_versions": j.count("alias_versions"),
        "decision": receipt,
    }
    assert j.owner("a")["owner_principal_id"] == "principal.a"
    assert j.alias("a", 1)["record"]["state"] == "active"
    assert j.node("S", 1)["record"]["dependencies"] == [["alias", "a", 1]]
    assert actual["alias_b"] == "active" and heads["U"] == "current"
    assert actual["raw_events"] == 4
    if stage == "before":
        assert actual["alias_a"] == "active" and heads == {
            "S": "current", "E": "current", "U": "current"}
        assert actual["invalidations"] == []
        assert actual["allowed"] == 0 and receipt is None
        assert actual["operations"] == 5 and actual["alias_versions"] == 2
    elif stage == "after":
        assert actual["alias_a"] == "revoked" and heads == {
            "S": "stale", "E": "stale", "U": "current"}
        assert actual["invalidations"] == ["E", "S"]
        assert actual["allowed"] == 1 and receipt is not None
        assert receipt["admitted_principal_id"] == "principal.a"
        assert receipt["revocation_event_id"] == _events()[3]["id"]
        assert actual["operations"] == 6 and actual["alias_versions"] == 3
    else:
        raise ValueError("Unknown stage")
    return {**actual, "decision": bool(receipt),
            "status": "SIGKILL_REOPEN_INVARIANTS_PASS"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=(
        "seed", "kill_before", "kill_after",
        "verify_before", "verify_after", "replay_before", "replay_after"
    ), required=True)
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.phase == "seed":
        result = seed(args.db)
    elif args.phase.startswith("kill_"):
        cls = _KillBefore if args.phase == "kill_before" else _KillAfter
        j = cls(args.db, adapters=_registry())
        _revocation(j)
        raise AssertionError("Signal kill did not happen")
    elif args.phase.startswith("verify_"):
        result = check(args.db, args.phase.removeprefix("verify_"))
    else:
        stage = args.phase.removeprefix("replay_")
        check(args.db, stage)
        j = AuthorizedAliasLifecycleLab(args.db, adapters=_registry())
        outcome = _revocation(j)
        expected_status = "revoked" if stage == "before" else "idempotent_replay"
        assert outcome["status"] == expected_status
        result = {**check(args.db, "after"), "replay_status": outcome["status"]}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
