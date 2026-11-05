# ANIMA Core v0.1 — P2-A SQLite Event Ingress

**Status:** **P2-A PASS** (owner-reported local checks, 2026-11-05). P2-B and P2-C are not included and remain unverified.  
**Date:** 2026-11-05.  
**Branch:** `work/core-v0-1-p2a-ingress` (based on P1 bootstrap PASS branch).  
**Contracts:** [Event / Observation / Belief](Core_v0_1_Event_Belief_Contract_Draft.md), [P0 audit](Core_v0_1_P0_Boundary_Draft.md).

## 1. Scope

P2-A implements only **durable system-owned event admission** as the first slice of approved SQLite Core journal. It is not a full Observer, BeliefStore, Knowledge write lifecycle, autonomous scheduler, world adapter or legacy EventLog replacement.

- New module: [`anima/core/ingress.py`](../../anima/core/ingress.py).
- New tests: [`tests/test_core_p2a_ingress.py`](../../tests/test_core_p2a_ingress.py).
- Existing P1 assembly, CLI, EventBus, EventLog and MemoryProcessor remain unchanged.
- P2-B will add validated Observation/Belief revisions **inside the same SQLite transaction boundary**, rather than independently committing Belief in another store.
- P2-C will define dispatch acknowledgement, Core→legacy bridge, integration into Runtime and restart reconciliation.

## 2. Data ownership

`CoreIngress(database_file, sources=...)` takes an **immutable snapshot** of a trusted adapter registry with `SourceRegistration(source_ref, producer_ref, allowed_kinds)`. The caller supplies `source_ref` as a trusted adapter identity, and the ingress rejects any registration missing from the allowlist.

**Security boundary:** source registry matching is **not remote authentication**. External transport, session binding and credentials remain the adapter's responsibility; do not expose `admit(raw, source_ref=...)` as an unauthenticated HTTP/IPC endpoint. `producer_ref` is taken from the registry, not untrusted input.

First event envelope (closed key set):

```json
{
  "contract": "core.event/0.1",
  "occurrence_id": "sensor-sequence-47",
  "occurrence_version": 1,
  "kind": "state.property",
  "payload": {
    "subject_ref": "entity.door_01@registry-r1",
    "predicate_ref": "world.door_state@1",
    "value": {"type": "symbol", "value": "open"}
  }
}
```

This is a **P2-A raw event envelope**, not a validated `core.observation/0.1`. Type/registry validation for `entity_ref`, `predicate_ref`, typed Value, clock domain and source revision is scheduled for P2-B. Until P2-B, no event is permitted to mutate Belief, Goal, Task or Knowledge.

`received_at` and `event_id` are assigned by the system; raw input cannot supply them. Event ID is a new `ev_<uuid4>` assigned on first acceptance. Stable redelivery identity is `(source_ref, occurrence_id, occurrence_version)`, not the newly generated event ID. Values may be exact integers or strings but **floating-point Python values are not accepted** at this boundary; decimal/quantity representation belongs to typed observation schema.

## 3. Persistence and behavior

Database: `core_state.db` (path provided by caller, no hard-coded project data path).

Tables:

| Table | Purpose |
|---|---|
| `schema_meta` | Versioned SQLite schema (P2-A v1) |
| `core_events` | Immutable accepted event row + content SHA-256 |
| `core_outbox` | Durable `core.dispatch` intent, initially pending |
| `ingress_rejections` | Bounded audit reason codes, **without raw malicious payload** |

Each accepted event and its outbox intent are committed with one `BEGIN IMMEDIATE` SQLite transaction. An injected error after the two inserts but before `commit` must roll both back. The subsequent P2-B implementation will extend this atomic boundary to include normalized Observation and Belief projection/revision. Current implementation cannot claim that completed D1 end-to-end guarantee.

`AdmissionResult` statuses:

| Status | Meaning |
|---|---|
| `ACCEPTED` | First successful durable write; returns generated event ID |
| `ALREADY_SEEN` | Same source occurrence/version and canonical content; returns original event ID; no new outbox |
| `IDENTITY_CONFLICT` | Same source occurrence/version but different canonical content; original record never overwritten; rejection audited |
| `REJECTED` | Unregistered source or invalid/unsupported envelope; rejection reason audited |

Canonical JSON is order-independent for dictionary keys; mutable external payloads are serialized before commit. Numeric exactness is preserved by excluding Python float input; no LLM or semantic source ranking is consulted.

**Important missing capabilities:** Outbox items are not yet acknowledged or sent to existing Legacy EventLog. No claim is made for exactly-once side effects or cross-DB transactionality. `get_event` and `pending_event_ids` are read-only inspection operations.

## 4. P2-A tests and evidence gate

```bash
bash scripts/check.sh
.venv/bin/python -m pytest -q tests/test_core_p2a_ingress.py tests/test_core_p1_bootstrap.py
.venv/bin/python -m pytest -q
```

Expected cases:
- acceptance persists event + outbox together;
- redelivery after object restart does not duplicate event/outbox;
- JSON key order irrelevant;
- conflicting redelivery remains visible and does not overwrite original;
- separate sources/occurrence versions are separate occurrences;
- invalid kind/version/payload/unknown source rejected without event mutation;
- Python payload mutation after `admit` cannot modify stored history;
- controlled fault before commit rolls back event+outbox;
- no legacy `events.jsonl`, `memory.db` or Runtime lifecycle created by standalone ingress;
- source registry is frozen after construction.

**P2-A gate: PASS**, по переданному владельцем терминальному выводу, а не по CI/выполнению на стороне ассистента. Python 3.14.4:
- `scripts/check.sh`: **PASS** (88 страниц документации, 498 локальных ссылок, 293 Python-файла, 3 JSON, 3 Bash, проверки чистоты репозитория).
- прицельный `pytest`: **23 passed in 0.41s**.
- полный `pytest -q`: **1271 passed in 17.25s**.
- SHA локального тестового checkout не предоставлен: branch head на момент фиксации результата указан в истории GitHub, но не объявляется подтверждённым локальным snapshot. Для следующего отчёта сохранять `git rev-parse HEAD`.
- Подтверждена только область P2-A. Атомарная Belief-проекция, отложенный outbox dispatch и восстановление между БД ещё не реализованы.

## 5. Next steps

**P2-B:** define strict typed `Observation` normalization, registered entity/predicate/time fields, and `BeliefStore` projected revisions in the **same database transaction**; preserve Evidence versus current Belief separation. The P2-A raw event row should not be treated as validated world fact.

**P2-C:** integrate CoreIngress with a single Core runtime driver while maintaining P1 legacy behavior, then make outbox dispatch/replay safe and prove recovery. Neither is implemented here.
