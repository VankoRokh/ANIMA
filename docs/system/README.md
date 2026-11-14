# Архитектура ANIMA

**Срез:** 14 ноября 2026 года; реализация в [`build_core`](../../anima/core/assembly.py) и [`anima.release_v01`](../../anima/release_v01.py). Эта страница описывает, **что подключено и откуда вызывается**, а не назначает статус выпуска. Состояние приёмки — в [карточке v0.1](../versions/v0.1/acceptance.md).

## Принцип и границы

ANIMA сохраняет Identity, State, первичные Events, Memory, Goals/Tasks и проверку отдельно от сменяемых FAST/DEEP. Наличие кода или успешного эксперимента не означает обязательное подключение механизма к базовому профилю.

Важные разграничения: `Event` о полученном сообщении не является проверенным фактом мира; `Memory` и `Knowledge` не выдают разрешений на действие; `ExecutionReceipt` не заменяет независимое доказательство результата.

## Исполняемые маршруты

### 1. Штатный `ANIMA v0.1 Foundation` — без внешних действий

```text
stdin JSONL → release_v01.serve → ReleaseSession.handle("report")
          → Runtime.user_input → EventBus → events.jsonl
          → EventProcessingCoordinator → MemoryStore/LinkStore
              ├─ "search_events": EventRetrieval (raw FTS5, top_k=5)
              └─ "context": RetrievalEngine → ContextBuilder
                               (Memory-only, max_items=4, max_chars=900)
```

`report` создаёт `conversation.user`, **не** `state.property`. Команды `search_events` и `context` отказывают при неполном/изменённом индексе: не превращают отсутствие результата в утверждение об отсутствии событий. `context` использует политику consumer `FAST`, но **не запускает модель**.

### 2. Явный профиль `--sandbox-door`

```text
локальный оператор "ensure_sandbox_door_closed"
  → GoalStore.create_goal → GoalCriterion → CoreGoalDecision.bind
  → bounded CoreAutonomy → CoreDoorExecution / SandboxExecutor
  → VirtualDoorWorld SQLite → новое readback-наблюдение
  → независимая Verification → Goal/Task transition
```

Это другой **неизменяемый профиль capabilities** в отдельной папке данных. Он не подключает Godot и не даёт текстовым `report` права исполнения.

### 3. Типизированный Core и внешняя лаборатория

```text
доверенный адаптер (вне Core) → CoreIngress
 → core_state.db: immutable Core Event + Belief + outbox
 → CoreEventDispatcher → events.jsonl / Memory (совместимая проекция)
 → CoreGoalDecision → Policy → Execution (только с capability)
```

При восстановлении outbox повторно доставляет событие, но не создаёт второе независимое доказательство. Внешний `DoorWorldPort`/VAL подключается **через инъекцию адаптера**, не является обязательным компонентом `release_v01`.

### 4. SLEEP и когнитивные компоненты

`FAST/DEEP`, `CognitiveRouter`, `UnifiedTrace` и обработка `SLEEP WorkItem` имеют собственные контракты и испытания. По умолчанию `build_core` не инъецирует `SleepRuntimeIntegration` или backend модели; в `Runtime` используется `DiagnosticTrace`. `Runtime.sleep()` без `sleep_runtime` означает завершение жизненного цикла, а не автоматическую консолидацию.

## Матрица состава

| Функция | Базовый `release_v01` | `--sandbox-door` | Прочие сборки / лаборатории |
| --- | --- | --- | --- |
| Identity, State, EventLog, Memory, Internal State | Да | Да | Да, согласно конфигурации |
| EventRetrieval, ограниченный Context | Да | Да | Opt-in |
| `CoreIngress` и `CoreGoalDecision` | Созданы с **пустыми** реестрами источников, свойств и действий | С зарегистрированным door-источником и критерием | Только при явной настройке |
| `CoreDoorExecution` / `CoreAutonomy` | Нет | Да, для SQLite-двери | Opt-in через явный world port |
| FAST/DEEP inference | Нет | Нет | Отдельная интеграция Stage 5–6 |
| SLEEP WorkItems | Нет | Нет | Только с `SleepRuntimeIntegration` |
| Godot, Pi, датчики | Не требуются | Не требуются | Отдельные сценарии |

## Разделы по ответственности

| Слой | Что здесь объясняется | Код и профильная проверка |
| --- | --- | --- |
| [Runtime](runtime.md) | Композиция, Identity, State, запуск, storage и жизненный цикл | [assembly.py](../../anima/core/assembly.py), [test_runtime.py](../../tests/test_runtime.py) |
| [Events и полномочия](events-and-authority.md) | Raw Event, typed observation, outbox, Belief, источник истины | [ingress.py](../../anima/core/ingress.py), [test_core_audit_blockers.py](../../tests/test_core_audit_blockers.py) |
| [Memory и Retrieval](memory-and-retrieval.md) | Первичные источники, Memory/Knowledge, два пути чтения | [event_retrieval.py](../../anima/memory/event_retrieval.py), [test_event_retrieval.py](../../tests/test_event_retrieval.py) |
| [Goals и Execution](goals-and-execution.md) | Goal, Task, Policy, допуск, эффект, Verification, recovery | [door_execution.py](../../anima/core/door_execution.py), [test_release_v01.py](../../tests/test_release_v01.py) |
| [Cognition](cognition.md) | Canonical IR, Resolver, FAST/DEEP, Choice и предложения | [routing.py](../../anima/cognition/routing.py), [test_cognitive_routing.py](../../tests/test_cognitive_routing.py) |
| [SLEEP](sleep-and-recovery.md) | WorkItem, checkpoints, bounded processing и границы восстановления | [execution.py](../../anima/sleep/execution.py), [test_stage6_sleep_lifecycle.py](../../tests/test_stage6_sleep_lifecycle.py) |

**Как читать:** сначала [релизный контракт](../versions/v0.1/contract.md), затем профильный маршрут выше, тематическую страницу и ссылку на проверку. Происхождение решений — в [истории](../history/stages.md), выводы лабораторий — в [исследованиях](../research/README.md).
