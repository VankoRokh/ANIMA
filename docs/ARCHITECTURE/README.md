# Архитектура ANIMA — действующая система

**Этот раздел отвечает на вопрос «как устроена ANIMA сейчас».** Для ответа «как мы пришли к этому» существует [хронология Stage D0–6](../STAGES/README.md); для ответа «что входит в выпуск v0.1» — [реестр релизов](../RELEASES/README.md). Название существующей функции не означает, что она включена в стандартный релизный профиль.

## Главный принцип

ANIMA организована вокруг **непрерывного системного экземпляра**, а не вокруг конкретной языковой модели. Идентичность, исходные события, память, внутреннее состояние, задачи, разрешения и проверка результатов принадлежат системным службам. FAST и DEEP — заменяемые обработчики, которые могут участвовать в интерпретации, но не владеют состоянием.

```text
Внешний ввод / зарегистрированный адаптер
                       ↓
             Runtime / Identity / State
                       ↓
                 EventLog / CoreIngress
                 ├─ raw Event → Memory
                 └─ trusted observation → Belief
                       ↓
           Goals / Tasks / Internal State
                       ↓
              Canonical IR / Resolver
                 ├─ точный ответ
                 ├─ недостаточно данных
                 └─ когнитивная задача → FAST / DEEP
                       ↓
             System Policy / Choice
                       ↓
      (только при разрешённой capability)
             ExecutionAction / Tool
                       ↓
           Receipt → Observation → Verification
                       ↓
              Goal / Task progress
```

SLEEP организует отдельные безопасные ограниченные работы с сохранением checkpoints; долговечные журналы и recovery помогают возобновлять операции после перезапуска.

## Карта механизмов

| Подсистема | Что делает | Действующая документация | Стадия происхождения |
| --- | --- | --- | --- |
| Identity, EventBus, State, Runtime | Постоянный экземпляр и обработка событий | [Фундамент и Runtime](Foundation_Runtime.md) | [0](../STAGES/00_Foundation.md), [D1](../STAGES/D1_Runtime_Observability.md) |
| Cognitive Memory, Knowledge, provenance, Retrieval | Сохранение опыта, источники, поиск и bounded Context | [Память и извлечение](Memory_and_Retrieval.md) | [1](../STAGES/01_Cognitive_Memory.md) |
| Internal State, Goal, Choice | Ограниченные регуляторы выбора и жизненный цикл целей | [Внутреннее состояние](Internal_State_and_Goals.md) | [2](../STAGES/02_Internal_State.md) |
| SleepJob, WorkItem, checkpoint, consolidation | Прерываемая пакетная работа и производные результаты | [SLEEP и восстановление](Sleep_and_Recovery.md) | [3](../STAGES/03_Sleep.md) |
| Canonical IR, Resolver, FAST/DEEP, Router | Детерминированное разрешение и сменяемая когнитивная обработка | [Когнитивный контур](Cognition_FAST_DEEP.md) | [5](../STAGES/05_FAST_Cognition.md), [6](../STAGES/06_Core_Integration.md) |
| Tasks, Policy, Execution, Verification | Допуск действий, состояние работы, независимое подтверждение | [Исполнение и проверка](Execution_and_Verification.md) | [4](../STAGES/04_Agent_Experiment.md), [6](../STAGES/06_Core_Integration.md) |
| Общая интеграция и UnifiedTrace | Взаимодействие системных компонентов и восстановление | [Подробная архитектура Stage 6](Stage_6_Cognitive_Integration_Core.md) | [6](../STAGES/06_Core_Integration.md) |
| ANIMA v0.1 Foundation | Подтверждённая минимальная конфигурация | [Release Contract](../RELEASES/ANIMA_v0_1_Release_Contract.md) | Отдельная релизная интеграция |

**Важное различие статусов:** Stage 6 `Complete` подтверждает ограниченный интеграционный контур того Stage. ANIMA v0.1 — **другой контракт**, для которого нужен отдельный набор испытаний. Отчёты лабораторий M0–M6-B2 и Stage 7 не делают автоматически работающими новые production-модули.

## Работающая конфигурация ANIMA v0.1

Штатная точка входа: [`anima/release_v01.py`](../../anima/release_v01.py). Она использует существующие [`CoreAssembly`](../../anima/core/assembly.py) и [`Runtime`](../../anima/runtime.py); сохраняет Identity, State, EventLog, MemoryStore/LinkStore, Event Retrieval, Internal State и typed Core-интерфейсы. Через локальный JSONL stdin доступны несколько reports, статус, точный поиск исходных Events, ограниченный Context и завершение.

В **базовом профиле** нет обязательной LLM, Godot, сети, Raspberry Pi, зарегистрированного внешнего sensor или разрешённого Tool. Отдельный `--sandbox-door` включает **тестовую** capability для Goal/Task/Policy/Verification над детерминированной SQLite-фикстурой; этот профиль не равен реальному внешнему исполнителю. Система не трактует текст `conversation.user` как доверенное `state.property` наблюдение.

Механизмы FAST, DEEP, SLEEP и расширенный Core продолжают существовать как проверенные компоненты и opt-in interfaces, но не обязаны работать одновременно при каждом штатном запуске v0.1.

## Владение данными и полномочия

- **Identity и состояние**: системный Runtime, не модель.
- **Raw Event**: первичный источник; summary не заменяет историю.
- **Memory**: хранит производные представления и provenance; не даёт разрешений на действия.
- **Knowledge**: отдельный статус и свидетельства; сообщение пользователя не равно факту о мире.
- **Internal State**: влияет на Choice только в разрешённом диапазоне, но не создаёт Goals/Candidates.
- **FAST/DEEP**: предложения и ответы под системной валидацией, без прав записи в системные хранилища.
- **Execution**: только через проверяемую регистрируемую capability; receipt сам по себе не завершает Goal.
- **Verification**: независимая от заявления модели и подтверждения самого исполнителя.
- **SLEEP**: прерываемый сервис, который сохраняет происхождение результатов и не владеет исходными данными.

## Каталог и контракты данных

Различать **файлы экземпляра** и исходники проекта. `ANIMA_DATA_DIR` выбирает внешний каталог для штатной сборки, а профиль `anima.release_v01 --data-dir` требует отдельный явный каталог. Не переносить рабочие данные в Git.

| Файл | Назначение | Когда создаётся |
| --- | --- | --- |
| `identity.json` | постоянный `instance_id` | базовый экземпляр |
| `state.json` | режим, сессии, счётчики | базовый экземпляр |
| `events.jsonl` | первичные неизменяемые Event-записи | базовый экземпляр |
| `memory.db` | Memory, Knowledge, Entity/Relation, provenance, история | базовый экземпляр |
| `event_index.db` | производный SQLite/FTS5 индекс исходных Events | при включённом EventRetrieval |
| `internal_state.db` | Goal, state variables, причинные переходы | при Internal State |
| `core_state.db` / `core_work.db` | typed observations/Belief и Goal bindings | при typed Core |
| `tasks.db` | долговечные Task/transition history | при соответствующей сборке Core |
| `execution.db` | операции, `ExecutionAction`, `VerificationSpec` | при разрешённой execution capability |
| `sleep.db` | SleepJob, WorkItem, checkpoints, derived results | при включённом SLEEP |
| `trace.db` | persistent UnifiedTrace Stage 6 | при соответствующей интеграции |
| `release_profile.json` | закреплённый набор возможностей v0.1 | релизный профиль |

Разные SQLite и JSONL **не** образуют одну физическую транзакцию. При backup нужно безопасно остановить экземпляр и сохранить весь каталог, включая профиль, исходный журнал и записи. Проверка восстановления обязательна.

## Границы доказанного

**Реализовано и испытано в указанных условиях:** базовое сохранение Identity/Events/Memory, typed Core и ограниченная автономия, deterministic resolution, Fast/Deep routing, Internal State/Choice, SLEEP checkpoints, recovery и independent verification. Доказательства относятся к конкретным сценариям, версиям Python и Git snapshots — см. [результаты](../TESTING/Results/README.md).

**Не является подтверждённым общим production-контрактом:** свободное самостоятельное формирование любых целей, аутентификация произвольных внешних источников, универсальное понимание, автоматический write/revision Knowledge по полной спецификации Stage 7, непрерывный Godot-мир, перенос на Pi, обучение весов, метапамять, физическая периферия и гарантии отсутствия ошибок на произвольном масштабе.

Отдельно: `EventBus` остаётся временной очередью; полные сканы `events.jsonl` могут быть дорогими. Производный Event Retrieval и другие оптимизации не доказывают универсальной субмиллисекундной задержки. Измерения и ограничения — в [релизном отчёте](../RELEASES/ANIMA_v0_1_Notebook_Evidence.md), [Memory](Memory_and_Retrieval.md) и [исследованиях](../RESEARCH/README.md).

## Исторические и будущие границы

Историческая Stage 4 с LLM Planner **остановлена**, но её Tool/Execution/Recovery результаты использовались при создании новой архитектуры. Семантический Stage 7 имеет [проект контракта](../ROADMAP/Stage_7_Semantic_Boundary_v0.md), однако полный lifecycle и правила DP-08/09/10b/11 остаются открытыми.

**Чтобы изучить путь развития:** [История Stage D0–6](../STAGES/README.md).  
**Чтобы найти оставшиеся эксперименты:** [Исследовательский реестр](../RESEARCH/README.md).  
**Чтобы понять актуальные задачи:** [Дорожная карта](../ROADMAP/README.md).
