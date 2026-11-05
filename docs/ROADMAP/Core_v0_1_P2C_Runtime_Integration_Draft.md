# ANIMA Core v0.1 — P2-C Runtime / Durable Dispatch Integration

**Статус:** **P2-C PASS по сообщению владельца** (2026-11-05): все предложенные проверки выполнены успешно. Точный SHA локального тестового коммита и числовой итог pytest не предоставлены; не приписывать их этому отчёту.  
**Дата:** 2026-11-05.  
**Ветка:** `work/core-v0-1-p2c-runtime` (from owner-verified P2-B).  
**Родитель:** [P2-B Belief State](Core_v0_1_P2B_Belief_Draft.md), [P2-A Ingress](Core_v0_1_P2A_Ingress_Draft.md).  
**Рамки:** [P0 audit](Core_v0_1_P0_Boundary_Draft.md) и [Event / Observation / Belief](Core_v0_1_Event_Belief_Contract_Draft.md).

## 1. Цель

Подключить P2-A/B к **существующему Runtime**, не переписывая EventBus, EventLog, MemoryProcessor и CLI, и восстановить доставку accepted observations из канонического Core SQLite в legacy EventLog после прерывания.

```text
registered adapter
   ↓
Runtime.ingest_core_event(raw, source_ref=...)
   ↓
CoreIngress / core_state.db (authoritative journal)
   ├── core_events
   ├── core_observations
   ├── core_beliefs + revisions
   └── core_outbox (durable intent)
   ↓  bounded dispatcher, recoverable
EventLog / events.jsonl (compatibility projection)
   ↓
EventProcessingCoordinator / memory.db
   ↓
core_dispatch_receipts in core_state.db (acknowledgment)
   ↓
AnimaState.events_processed reconciliation
```

Core writes accepted world observations to the SQLite journal *before* dispatch. Knowledge writes, new autonomous Goal/Task, models and world effects are not part of this slice.

## 2. Изменённые файлы и конфигурация

- [`anima/core/dispatch.py`](../../anima/core/dispatch.py) — `CoreEventDispatcher`, explicit bridge with replay guards and bounded `drain(max_events=32)`. Type `CoreDispatchTurn` records forwarded/filtered decisions.
- [`anima/core/ingress.py`](../../anima/core/ingress.py) — additive schema **v3**: `core_dispatch_receipts` keyed by `event_id`. Existing `core_outbox` insert rows stay immutable; `pending_event_ids()` excludes acknowledged rows. Idempotent `acknowledge_dispatch`.
- [`anima/core/assembly.py`](../../anima/core/assembly.py) — `build_core(data_dir, sources=..., properties=...)` opt-in. Both registry arguments required together. Default `build_core()` remains existing P1 CLI flow (without separate Core journal).
- [`anima/runtime.py`](../../anima/runtime.py) — `ingest_core_event`, `read_core_belief`, bounded replay in `_ensure_recovered` on wake/user activity/ingress. Legacy recovery occurs first, then Core outbox catch-up.
- [`tests/test_core_p2c_runtime.py`](../../tests/test_core_p2c_runtime.py) — integration and fault-injection tests.
- [`tests/test_core_p2b_belief.py`](../../tests/test_core_p2b_belief.py) — migration check updated to schema v3. **P2-B's previously verified exact snapshot remains unchanged in its parent branch**.

No action execution, scheduler or LLM integration is granted by these additions.

## 3. Stable legacy identity and event content

For an accepted typed observation the bridge emits one `world.observation` legacy `Event` with **the same system-assigned `ev_UUIDv4`** as the Core journal record. Payload contains versioned observation and source/producer references; timestamp is the system-generated `received_at`, **not** inferred world observation time.

- If no matching ID exists in `EventLog`, write once.
- If exactly matching event already exists, continue processing **without re-appending**.
- If same ID but different bytes/record: fail closed, leave Core outbox pending; do not overwrite.
- Stage 1 `EventProcessingCoordinator` independently finalizes or replays the legacy Memory projection. With current `MemoryProcessor`, `world.observation` is **skipped by memory selection**, so no fake episodic memory or Knowledge entry is created.
- An invalid or P2-A-only raw event has no accepted typed observation outcome; it is marked `filtered` in the dispatch receipt, not sent to legacy. Raw event remains auditable in Core DB.

**Source registry is not authentication.** Only trusted adapters may supply `source_ref`. Exposing the raw method directly to anonymous IPC/HTTP clients would be an authority bypass; transport auth is outside P2-C.

## 4. Persistence / recovery semantics

A Core event, typed observation and Belief projection commit atomically in **one SQLite DB** (P2-B). EventLog JSONL and MemoryProcessor's SQLite remain separate commits. A durable outbox acknowledgment occurs last in Core DB.

Crash boundaries to test:

1. Before legacy append: Core outbox remains pending; retry writes the same stable event.
2. After append, before Memory projection: next startup validates matching legacy record and finishes processing.
3. After Memory projection, before Core acknowledgment: replay sees finalized idempotent legacy event; ack now succeeds.
4. After Core acknowledgment, before state counter reconciliation: state counter catches up on restart from persistent Memory event ledger.
5. Same event ID, different legacy record: **error and pending**, never silent repair.
6. Rejected raw world payload: filtered receipt; never spoofed as validated observation.

`core_dispatch_receipts` contains `forwarded` or `filtered`; original `core_outbox.status` remains `pending` as a historical immutable request. Pending is computed as rows **without receipt**, so these two interpretations must not be confused.

**Guarantee scope:** replay-safe under covered single-process failure points with healthy, parseable EventLog and SQLite. Not a global transaction, not a guarantee against power-loss corruption, concurrent independent writers, malicious caller impersonation, or arbitrary sensor truth. A truncated/malformed legacy JSONL remains an explicit failure, not automatically silently repaired.

`drain()` is bounded to 32 accepted events per call by default. Remaining work is retained in durable outbox and revisited at the next Runtime entry. No background processing, polling thread or perpetual scheduler exists yet.

## 5. Tests and evidence gate

From repo root, on the new branch and with an otherwise clean working directory:

```bash
git rev-parse HEAD
bash scripts/check.sh
.venv/bin/python -m pytest -q \
  tests/test_core_p2c_runtime.py \
  tests/test_core_p2b_belief.py \
  tests/test_core_p2a_ingress.py \
  tests/test_core_p1_bootstrap.py
.venv/bin/python -m pytest -q
```

Check that the default CLI (without registries) behaves exactly as before and that `core_state.db` is absent in that configuration. Fault injection, restart, invalid observations, duplicate event IDs, migration v2→v3, bounded pending queue and idempotent receipts are covered.

**P2-C acceptance evidence:** владелец проекта сообщил «Все проверки прошли успешно» после выполнения предложенных проверок. Это подтверждение **без приложенного терминального вывода/точного SHA**, поэтому повторный воспроизводимый прогон на зафиксированном коммите остаётся желательной контрольной проверкой перед объединением веток. Ни CI, ни ассистент эти тесты не запускали. Обязательные P2-C сценарии присутствуют в тестовом наборе; дальнейшая разработка P3 не означает независимую проверку P2-C на иных условиях.

## 6. Later work

With P2-C tested, Core can receive, store, inspect, and recover registered external observations, while its current Goal/Task/Decision logic remains separate. Next is **P3 — first safe autonomous vertical slice**, with explicit `ensure_once` Goal, typed criterion, bounded decision, Policy, authorized world adapter, independent postcondition verifier and recovery. Maintain/monitor goals, unrestricted planning, LLM inference and Godot Virtual Lab remain out of initial P3.
