# ANIMA Core v0.1 — Event / Observation / Belief Contract (P0)

**Статус:** PROPOSAL / design for owner review, not implemented.  
**Дата:** 2026-11-05.  
**Кодовая база:** `e2a1e6bfdb6126b82ac36873dce92e7c6876aa4b` (read-only review), плановая ветка `work/core-v0-1-planning`.  
**Контекст:** [P0 Boundary & Reuse Audit](Core_v0_1_P0_Boundary_Draft.md), [Core/VAL plan](Core_v0_1_VAL_v0_1_Plan_Draft.md).  
**Приоритет семантики:** [Stage 7 accepted boundary](Stage_7_Semantic_Boundary_v0.md), особенно `Claim`, `Evidence/Source/Producer`, `Observation vs Report`, `Time`, `Evidence dependence`. Этот документ **не** заменяет `classify_relation/0.1` и не объявляет Stage 7 write lifecycle реализованным.

## 1. Цель

Сформировать минимальный **system-owned** pipeline:

`trusted ingress → durable event occurrence → typed observation → versioned belief projection → events for bounded Core scheduler`.

Требования: без LLM, без GUI/виртуального движка; observation ≠ truth; known ≠ fresh; повторное поступление не создаёт новое подтверждение; late delivery не откатывает текущее представление; состояние восстановимо после crash в рамках явно определённых границ.

## 2. Аудит существующего контракта и ограничения

- [`anima/core/event_bus.py`](../../anima/core/event_bus.py): `Event` требует `id/type/timestamp/source/session_id/payload/references`; `EventBus` — FIFO в оперативной памяти. Поле `timestamp` одно; его нельзя молча переопределить как `observed_at`.
- [`anima/memory/event_log.py`](../../anima/memory/event_log.py): JSONL append с проверкой ID; повторный `event_id` **отвергается**, а `load_events()` читает файл полностью. Существующая строгость истории должна сохраниться при адаптации.
- [`anima/memory/event_processing.py`](../../anima/memory/event_processing.py): идемпотентная SQLite-проекция `memory_processor`, привязанная к raw EventLog. Эта гарантия не охватывает Belief, Goal и внешние действия.
- [`anima/runtime.py`](../../anima/runtime.py) / [`main.py`](../../main.py): event bus → EventLog → memory projection; устойчивый world-observation/belief-processing path отсутствует.
- [`anima/semantic/`](../../anima/semantic/): read-only relation evaluation и validation существуют, но production Knowledge authority/lifecycle остаётся вне P0/P2.

**План:** сохранить старые публичные Event/Memory contracts для совместимости. **Не** переписывать Event под новую семантику. Дополнить отдельным версионированным `CoreObservationEnvelope` и transaction-bound `CoreIngress/Belief`. Legacy EventLog — downstream-compatible view для соответствующих событий, но **не второй источник канонической истины для новой Core-проекции**. Механизм bridge/replay требует отдельного интеграционного теста.

## 3. Понятия и владение

| Тип | Вопрос | Owner | Отношение |
|---|---|---|---|
| `CoreEventOccurrence` | Что поступило в Core и откуда? | Core ingress | immutable receipt record, не факт мира |
| `Observation` | Что конкретный зарегистрированный источник измерил/наблюдал? | adapter producer + Core validator | evidence occurrence, не абсолютная truth |
| `Report` | Что источник **сообщил/утверждал**, не являясь зарегистрированным observer? | source/producer | не превращать автоматически в Measurement |
| `BeliefSnapshot` | Какая актуальная рабочая оценка известна ANIMA? | Core Belief policy/store | проекция по evidence, с revision и freshness |
| `BeliefRevision` | Почему и на основании чего изменена проекция? | Core | immutable history |
| `Knowledge` | Какие устойчивые сведения прошли собственную семантическую политику? | будущий Knowledge lifecycle | **не** пишется автоматически от Belief |
| `WorldState` | Каковы истинные значения в испытательной среде? | test/VAL adapter | Core получает только разрешённые observations |

`SourceRef` — исходный канал/person/sensor, `ProducerRef` — модуль, создавший observation record; `ActorRef` — сущность, чьё действие наблюдается, при наличии. Они могут совпадать в конкретной реализации, но логически не одно и то же.

## 4. Core Event / Observation envelope v0.1 (proposed fields)

Контракт должен быть versioned/closed; названия ниже проектные:

```json
{
  "contract": "core.observation/0.1",
  "occurrence_id": "opaque-stable-source-occurrence",
  "event_id": "ev_<uuid4>",
  "source_ref": "sensor.door_01",
  "producer_ref": "adapter.virtual_sensor/0.1",
  "observation_kind": "state.property",
  "subject_ref": "entity.door_01@registry-r1",
  "predicate_ref": "world.door_state@1",
  "value": {"type": "symbol", "value": "open"},
  "temporal_scope": {"kind": "instant", "at": {"domain": "lab_tick", "value": 40}},
  "observed_at": {"domain": "lab_tick", "value": 40},
  "source_revision": 40,
  "received_at": "2026-11-05T11:00:00+00:00",
  "evidence_id": "obs_<uuid4>"
}
```

Правила:

1. Пример — **схема для обсуждения**, не production JSON Schema. `received_at` назначается system ingress и не принимается как авторитетное значение от внешнего клиента. В sample он показан как *результат* нормализации входа, а не payload клиента.
2. `event_id` может создаваться на ingress, а `occurrence_id` должен быть стабильным у источника или через доверенный event mapping; нельзя полагаться на новый random event ID как механизм dedupe повторной доставки того же наблюдения.
3. `source_ref`/`producer_ref`/`entity_ref`/`predicate_ref` валидируются против versioned registries. Незарегистрированное имя не получает право записи в Belief.
4. `observation_kind = state.property` разрешён только для зарегистрированного сенсора/адаптера и известной single-valued property с exact typed Value. Иное — unsupported/defer, не inference.
5. `observed_at`, `received_at` и `temporal_scope` различаются. Сопоставление часов возможно только через зарегистрированный clock mapping. `source_revision` может быть source-local monotonic sequence, **не** глобальный world revision и не доказательство истинности.
6. Отсутствующее/ошибочное чтение не представляет `false` и не придумывает значение `unknown` как `symbol`. Для этого нужен отдельный `ObservationUnavailable`/`UnknownReading` с reason, recorded occurrence и provenance.
7. Изменяемый Python dict на входе должен копироваться/замораживаться перед хешированием/сохранением. Нельзя поменять уже принятый payload путём изменения объекта вне Core.
8. Явное действие персонажа в тестовом полигоне тоже сначала становится world event; ANIMA увидит только то, что передал разрешённый observation adapter, а не privileged world event напрямую.

## 5. Belief state — ограниченный профиль exact-state/0.1

Belief key: `(canonical_entity_ref, registered_predicate_ref, normalized_qualifier_context)`; один single-valued predicate, известная scope applicability и exact typed atom.

Belief projection хранит **две независимые оси**:

- `epistemic_status: known | unknown | disputed` — что можно считать достаточно обоснованным на текущем объёме доступных evidence (в терминах узкой admission policy).
- `freshness_status: fresh | stale | undetermined` — достаточно ли измерение актуально по *внешне заданному policy*, а не истина состояния сейчас.

А также:

- `last_known_value` (optional; historical latest proven observed value);
- `current_value` (optional; only when policy permits), без произвольного перехода `unknown→false`;
- `evidence_refs`, `source_refs`, `scope/time`, `last_observed_at`, `last_received_at`;
- `revision`, `previous_revision`, `reason_code`, `updated_at`.

**Важное уточнение:** одиночное измерение в tick 40 показывает состояние в tick 40; оно **не** доказывает, что дверь остаётся открытой в tick 100. `fresh` позволяет применить ограниченную policy принятия решений, но не превращает snapshot в доказательство непрерывной истинности. Перед необратимым эффектом precondition проверяется заново, если capability так требует.

### 5.1. Minimal admission rules

- Проверка контракта/registry/allowlist/typed value обязательна. `unknown source` → reject to Belief, log audit reason.
- Один и тот же `(source_ref, occurrence_id, version)` + идентичное содержимое → `ALREADY_SEEN`, без новой BeliefRevision/support. Идентичное `event_id` с несовместимым содержимым → `IDENTITY_CONFLICT` (не overwrite).
- Известный `source_revision` в одном source/clock domain задаёт порядок **для этого источника**. Если source_revision старше текущего и нет ретроактивной correction policy, сохраняем evidence history, но не откатываем текущий Belief.
- Если сравнимые accepted observations утверждают разные значения об одном single-valued предикате **в доказуемо совпадающем effective scope**, mark `disputed`, не выбираем «сильнейший» source по глобальной иерархии.
- Если новые observations достоверно **позже**, при сохранённой provenance фиксируем новую last-observed оценку (temporal succession), а не «опровергаем» старую. Две отметки не доказывают время точного перехода.
- Если time/source scope не позволяет установить порядок или сравнимость, outcome `unknown/disputed` с reason; не выбираем последнюю по `received_at`.
- `sensor_unavailable` создаёт evidence о невозможности наблюдения, не удаляет прошлое `last_known_value`; `current_value` может стать unavailable/unknown согласно freshness policy.
- Срок `fresh` на первой версии задаётся policy (например, logical tick budget), а не вычисляется из некоего общего `confidence` score. Отсутствует самопридуманная числовая вероятность.

**Разделение:** read-only `classify_relation/0.1` может быть позднее использован для оценки совместимых Claims, но его CONTENT/REVISION output **не является** разрешением на `BeliefStore.update` или `Knowledge.confirm`. Здесь есть scoped deterministic admission policy для explicit observation; её семантические ограничения должны оставаться видимыми.

### 5.2. Projection outcomes

`ACCEPTED_NEW | UPDATED_LATER | ALREADY_SEEN | HISTORY_ONLY | MARKED_DISPUTED | MARKED_UNKNOWN | REJECTED_INVALID | REJECTED_UNAUTHORIZED | DEFERRED_UNCOMPARABLE`.

Это проектные `reason_codes`, а не новая параллельная Knowledge taxonomy.

## 6. Persistence / replay boundary (предлагаемое решение)

**Рекомендуемый вариант:** одна SQLite transaction boundary **для Core event occurrence + validated Observation + BeliefRevision + projection checkpoint** (в отдельном `core_state.db` или как часть осмысленно выделенной SQLite-схемы). Legacy `events.jsonl` и MemoryProcessor остаются существующим путём; их запись для совместимых событий — downstream projection/outbox/replay, **не условие принятия нового Core observation в Belief**.

Почему:

- JSONL append и SQLite БД нельзя объявить общей транзакцией;
- действующий `EventLog.write` отклоняет одинаковый ID и не поддерживает safe redelivery admission;
- `EventProcessingCoordinator.process()` защищает только legacy memory projection, не Core Belief;
- запись accepted event и его belief effect в одной SQLite transaction допускает restart/replay без двойной ревизии для этого узкого участка.

**Граница гарантии:** атомарность этих записей внутри одной SQLite БД при корректном transaction/commit; НЕ exactly-once внешнего side effect, НЕ multi-DB atomicity, НЕ достоверность sensor reading, НЕ неизменность при разрушении носителя. После crash outbox/reconciliation догоняет legacy projection; повтор outbox message должен быть idempotent. Не создавать два конкурирующих источника истины для одного `CoreEvent`.

Перед implementation P1/P2 решить, должен ли новый Core event journal быть единственным accepted ingress для **всех новых** событий, а legacy events мигрировать только постепенно; рекомендовано **да** для новых Core inputs, без ретроактивной миграции Stage0–6 истории в P1.

## 7. Interface operations (conceptual, P1–P2)

```text
CoreIngress.admit(raw_external_record, registry_context) -> AdmitResult
  : ACCEPTED | ALREADY_SEEN | REJECTED | DEFERRED

ObservationNormalizer.normalize(accepted_occurrence) -> TypedObservation
  : bounded, no hidden world state access

BeliefPolicy.evaluate(current_snapshot, typed_observation, context)
  -> ProjectedRevisionDecision
  : deterministic, no LLM, no direct writes

BeliefStore.commit(observation, revision_decision, checkpoint)
  : same transaction as CoreEvent/Observation; idempotent under replay

BeliefStore.read(key, as_of=...) -> BeliefSnapshot | Unknown
  : read-only for Task/Decision consumers

EventSubscriber.notify(committed_revision) -> WakeSignal
  : notification may be repeated; state truth remains in durable store
```

Здесь нет обязательного создания шести новых файлов/классов; это логические операции, которые можно реализовать компактно. Driver не должен полагаться только на непостоянную RAM queue как источник pending work.

## 8. Explicit test matrix for this contract

| ID | Fixture | Expected |
|---|---|---|
| EB-01 | known door state from registered source | one accepted occurrence, one belief revision, provenance preserved |
| EB-02 | same occurrence redelivered with same content | `ALREADY_SEEN`, no double revision |
| EB-03 | same `event_id` but different payload | hard identity conflict, no overwrite |
| EB-04 | earlier `source_revision` arrives after later one | evidence recorded, current snapshot not rolled back |
| EB-05 | two sensor values same provable scope/time and conflict | `disputed`, no arbitrary winner |
| EB-06 | two values at comparable ordered ticks | temporal succession, latest observed state, no inferred transition instant |
| EB-07 | unknown/unregistered source | reject to Belief, preserve audit |
| EB-08 | source unavailable / unknown reading | no false value, preserve last-known + unknown freshness |
| EB-09 | incomparable clock domains | no fabricated ordering; defer/dispute according to policy |
| EB-10 | crash before/after SQLite commit | recovery yields zero/one committed projection, never partial inconsistent projection in same DB |
| EB-11 | crash after Core commit before legacy outbox | replay catches up once, no duplicate Memory |
| EB-12 | mutate external Python payload after admit | stored validated occurrence unchanged |
| EB-13 | unrelated noise observations | history recorded, unrelated belief keys remain stable |
| EB-14 | original Stage0–6 EventLog/Memory tests | existing behavior unchanged |
| EB-15 | read Belief after restart under same source clock policy | snapshot + revision/provenance restored, no new synthetic evidence |

**Core v0.1 does not require** generic natural-language claim extraction, LLM arbitration, source-ranking heuristics, probabilistic confidence, or global ontology fusion to pass these fixtures.

## 9. P0 decisions and remaining review

**D1 — Store boundary (Accepted in principle, 2026-11-05).** Owner согласовал выделенный SQLite-журнал нового Core и одну транзакцию для ingress/Observation/Belief, с сохранением legacy `EventLog`/Memory и downstream bridge/outbox для совместимости. Статус **не означает**, что реализованы durable outbox, schema migration или power-loss proof: детали и тесты остаются blocking. JSONL-first как основной вариант для новых Core-входов отклонён.

**D2 — Conflict policy.** В v0.1 опираться только на registered source, comparable logical time/revision и explicit equal-scope conflict; без глобального source ranking и universal probabilistic score? Рекомендация — да.

**D3 — Freshness rule.** Ввести per-predicate logical-tick TTL/refresh requirements (для физических каналов — policy с отдельным clock mapping). Для неизвестных clock domains не объявлять `fresh`. Рекомендация — да.

**D4 — Scope.** Ограничить first belief profile зарегистрированными canonical entities / single-valued exact predicates / known scope и typed atomic values. Рекомендация — да.

**D5 — Compatibility gate.** Старые `Event` и `EventLog` сохраняют contract; новый Core ingress — адаптер к ним, а не изменение historical event schema. Рекомендация — да.

До P1/P2: отдельно рассмотреть D2–D5, source/predicate registry fixtures, explicit crash test protocol, baseline `scripts/check.sh` и `pytest`. D1 согласован концептуально, но требует проверяемого implementation/replay contract. P0 не считается Complete одним только созданием этого draft.
