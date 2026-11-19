"""R8.2 / H57-03: every Knowledge publication validates dormant timestamps.

All deliberate SQL corruption is isolated under pytest tmp_path.
Nothing touches the GitHub audit snapshot or the owner's instance data.
"""

from uuid import UUID

import pytest

from anima.core.assembly import build_core
from anima.core.event_bus import Event
from anima.memory.knowledge import KnowledgeLayer


T0 = "2020-01-01T00:00:00+00:00"
T2 = "2020-01-01T00:02:00+00:00"
T3 = "2020-01-01T00:03:00+00:00"
T4 = "2020-01-01T00:04:00+00:00"
T5 = "2020-01-01T00:05:00+00:00"
T7 = "2020-01-01T00:07:00+00:00"
T8 = "2020-01-01T00:08:00+00:00"
T9 = "2020-01-01T00:09:00+00:00"

# 'naive', invalid text, impossible calendar values and inverted windows are
# corrupted legacy rows, not valid LinkStore API inputs.
BAD_INTERVALS = [
    pytest.param(T8, T7, id="inverted"),
    pytest.param(T8, T8, id="equal"),
    pytest.param("2020-01-01T00:08:00", T9, id="naive_start"),
    pytest.param("not-a-date", T9, id="non_iso_start"),
    pytest.param("", None, id="empty_start"),
    pytest.param(T8, "bad-end", id="non_iso_end"),
    pytest.param(T8, "2020-01-01T00:09:00", id="naive_end"),
    pytest.param("2020-02-30T00:08:00+00:00", None, id="invalid_calendar_start"),
]

VALID_INTERVALS = [
    pytest.param(T8, T9, id="finite_future"),
    pytest.param(
        "2020-01-01T11:08:00+11:00",
        "2020-01-01T02:09:00+02:00",
        id="cross_timezone_equivalent",
    ),
    pytest.param(T8, None, id="open_ended_future"),
]

TRANSITIONS = [
    "confirm_implicit",
    "confirm_explicit",
    "challenge",
    "reject",
    "supersede",
]


def uid(prefix, number):
    return prefix + str(UUID(int=(4 << 76) | (2 << 62) | number))


def closed_raw_memory(core, number):
    event = Event(
        "conversation.user",
        {"text": f"r82-h5703: independent Raw observation #{number}"},
        source="user",
        session_id="session_00000001",
        event_id=uid("ev_", number),
        timestamp=T0,
    )
    core.event_log.write(event)
    result = core.memory_store.create_memory(
        memory_type="episodic",
        domain="user",
        status="closed",
        content=event.payload["text"],
        created_at=T0,
        source_event_id=event.event_id,
        public_id=uid("mem_", number),
    )
    return result["id"]


def setup(root, transition):
    core = build_core(root)
    a, b, c, d = [
        closed_raw_memory(core, n) for n in (8201, 8202, 8203, 8204)
    ]
    layer = KnowledgeLayer(memory_store=core.memory_store)
    k = layer.create_candidate(
        domain="user", statement="R8.2 canonical evidence condition",
        source_memory_id=a, created_at=T2, public_id=uid("kn_", 8201),
    )["knowledge"]["id"]

    # Build a legitimate future support before the lifecycle transition.
    dormant = core.link_store.create_relation(
        source_kind="memory", source_id=c,
        relation_type="supports", target_kind="knowledge", target_id=k,
        created_at=T8, valid_until=T9,
    )

    if transition not in {"confirm_implicit", "confirm_explicit"}:
        layer.confirm(k, confirmed_at=T3)
    if transition in {"reject", "supersede"}:
        layer.challenge(k, b, challenged_at=T4)

    return core, layer, k, a, b, c, d, dormant


def attempt(layer, k, a, b, d, transition):
    if transition == "confirm_implicit":
        return layer.confirm(k, confirmed_at=T5)
    if transition == "confirm_explicit":
        return layer.confirm(k, source_memory_id=a, confirmed_at=T5)
    if transition == "challenge":
        return layer.challenge(k, b, challenged_at=T5)
    if transition == "reject":
        return layer.reject(k, rejected_at=T5)
    if transition == "supersede":
        return layer.supersede(
            k, statement="R8.2 newer supported assertion",
            source_memory_id=d, superseded_at=T5,
            public_id=uid("kn_", 8299),
        )
    raise AssertionError(f"Unknown transition: {transition}")


def logical_state(core):
    tables = ("knowledge", "relations", "history", "memory_sources")
    with core.memory_store.transaction() as connection:
        rows = {
            table: [
                tuple(row) for row in connection.execute(
                    f"SELECT * FROM {table} ORDER BY rowid"
                )
            ]
            for table in tables
        }
    rows["raw"] = core.event_log.log_file.read_bytes()
    return rows


@pytest.mark.parametrize("transition", TRANSITIONS)
@pytest.mark.parametrize("start,end", BAD_INTERVALS)
def test_r82_h5703_invalid_dormant_support_has_uniform_value_error(
    tmp_path, transition, start, end,
):
    core, layer, k, a, b, c, d, dormant = setup(tmp_path, transition)

    # Deliberately damage only the temporary SQLite fixture after creating
    # valid physical Raw evidence and staging all previous lifecycle states.
    with core.memory_store.transaction(immediate=True) as connection:
        connection.execute(
            "UPDATE relations SET created_at=?, valid_until=? WHERE public_id=?",
            (start, end, dormant["id"]),
        )
    before = logical_state(core)

    with pytest.raises(ValueError, match="Knowledge evidence"):
        attempt(layer, k, a, b, d, transition)

    assert logical_state(core) == before
    if transition == "supersede":
        assert layer.get(uid("kn_", 8299)) is None
    expected_status = (
        "provisional" if transition.startswith("confirm")
        else "confirmed" if transition == "challenge"
        else "challenged"
    )
    assert layer.get(k)["status"] == expected_status


@pytest.mark.parametrize("transition", TRANSITIONS)
@pytest.mark.parametrize("start,end", VALID_INTERVALS)
def test_r82_valid_dormant_support_preserves_lifecycle_and_interval(
    tmp_path, transition, start, end,
):
    core, layer, k, a, b, c, d, dormant = setup(tmp_path, transition)
    with core.memory_store.transaction(immediate=True) as connection:
        connection.execute(
            "UPDATE relations SET created_at=?, valid_until=? WHERE public_id=?",
            (start, end, dormant["id"]),
        )

    before = logical_state(core)
    result = attempt(layer, k, a, b, d, transition)
    expected_status = {
        "confirm_implicit": "confirmed",
        "confirm_explicit": "confirmed",
        "challenge": "challenged",
        "reject": "rejected",
        "supersede": "superseded",
    }[transition]
    assert layer.get(k)["status"] == expected_status
    assert result is not None

    with core.memory_store.transaction() as connection:
        row = connection.execute(
            "SELECT created_at, valid_until FROM relations WHERE public_id=?",
            (dormant["id"],),
        ).fetchone()
    assert row["created_at"] == start
    assert row["valid_until"] == end
    assert core.event_log.log_file.read_bytes() == before["raw"]
