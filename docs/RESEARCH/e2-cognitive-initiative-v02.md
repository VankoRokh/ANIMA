# ANIMA v0.2 — решение о когнитивной инициативе FAST/DEEP и эксперимент E2.3–E3

**Статус:** `Design / Accepted direction, unimplemented`. Согласованные принципы эксперимента, **не** релиз, не доказательство реализованной когнитивной автономии и не новая пользовательская инструкция production.  
**Дата:** 23 ноября 2026.  
**Исходная кодовая база:** `work/v02-e22-raw-provenance-outbox`, `5288561d5af311e0468fb9df6740313ee8472573`; E2.2 имеет только `PASS_LAB_RAW_POINTER`.  
**Смежный эксперимент:** [Continuous lifecycle](continuous-lifecycle-v02.md). Следующие подэтапы E2.3–E3 ниже — рабочая детализация, **не** переименование уже завершённых E2.1/E2.2 и не утверждение о статусе реализации.

## 1. Цель эксперимента и нецели

Виртуальный мир — **измерительный стенд** для памяти, накопления опыта, гипотез, выбора/пересмотра целей и решений, а также изучения **вклада LLM**. Успех навигации сам по себе не является целью разработки ANIMA.

Основной вопрос: может ли Core непрерывно поддерживать идентичность, данные и допуск, пока сменные когнитивные модули — включая FAST/DEEP — **самостоятельно инициируют новые допустимые шаги обработки информации**, не становясь владельцами памяти, Knowledge, полномочий исполнения или независимого жизненного цикла?

Сравнить три режима с одинаковыми наблюдениями, полномочиями и правилами записи:
- `DETERMINISTIC`: детерминированный baseline без LLM.
- `STUB`: воспроизводимый typed cognitive proposal adapter.
- `LLM`: настоящая FAST, позже DEEP; получает тот же видимый Context, не скрытую истину Godot.

Обязательны не только success/failure действий, но и **фактический ход решений**, включая доступные данные, предложения, причины допуска/отклонения, ожидаемый эффект и независимый outcome. Нельзя использовать модельный текст «почему я так решила» как объективную причину принятия решения.

## 2. Ключевое архитектурное решение

**Принято направление B: LLM может инициировать дополнительные когнитивные операции.** Core **не** зашивает в программу всю последовательность мыслительных шагов. Доступные операции задаются типизированным реестром возможностей, а выбор следующих шагов и их аргументов может предлагаться FAST/DEEP.

**Разделить:**
1. `CognitiveProposal` — рекомендация недоверенного советчика, **ещё не действие и не подтверждённый факт**.
2. `CognitiveAdmission` — решение доверенной Core-политики: разрешить ограниченную read-only операцию, запросить дополнительную проверку либо отклонить.
3. `CognitiveOperation` — исполняемый Core-оркестрацией зарегистрированный, проверенный шаг с лимитами и идентификатором replay.
4. `CognitiveOutcome` — фактический typed результат с provenance/uncertainty, который нельзя выдумать из ожидаемого результата.
5. `DecisionRecord` — запись входа/выхода модели, набора вариантов, политики и следующего состояния, созданная **до/после соответствующей границы**.
6. `WorldActionProposal` и `GoalProposal` — **отдельные** заявки. Даже если LLM запросила осмотр, движение или промежуточную цель, это не получает права обхода Stage6 Goal/Task/Execution и независимого Verification.

`CognitiveCoordinator` — **оркестратор**, не второй Core, не владелец Identity, CoreIngress, Memory, Goal/Task, executor либо bearer-секретов. Его composition root — существующий `CoreAssembly` / Runtime. Все записи в канонические хранилища идут через действующие авторитетные службы. FAST/DEEP не получают прямых SQLite-файлов, raw TCP, секретов или прямых handlers.

## 3. Предлагаемый минимальный типизированный интерфейс

Ниже логический контракт для проектирования `anima.cognition` и тестов; **это не объявление существующего API**.

```text
CognitiveStepProposal
  schema_version
  proposal_id
  origin {kind: deterministic|stub|fast|deep, module_version, model_hash?}
  cognitive_turn_id, parent_goal_id?, parent_operation_id?
  operation_kind
  input_refs [opaque ID; no arbitrary path or SQL]
  typed_arguments {validated per operation}
  requested_budget {items?, tokens?, time_ms?}
  expected_information / hypothesis / justification (non-authoritative)
  context_snapshot_id

CognitiveAdmission
  proposal_id
  status {admitted|rejected|needs_review}
  policy_version
  effective_limits
  reason_code
  operation_id?  (only when admitted)

CognitiveOutcome
  operation_id
  status {completed|rejected|failed|partial|unknown}
  output_refs [validated]
  provenance [source Event/Raw, data version, relation]
  uncertainty / coverage
  elapsed/budget_used
```

**Первый набор read-only возможностей:** `retrieve_memory`, `lookup_raw_evidence`, `inspect_current_belief`, `compare_evidence`, `evaluate_hypothesis`, `inspect_goal_status`. Последние две — проверяемые вычисления/выводы, не непосредственная запись Knowledge или Goal.

**Отдельные операции с последствиями:** `request_observation` (сенсорная активность/поворот), `propose_subgoal`, `propose_world_action`, `propose_knowledge_revision`. У них свой admission и, где применимо, Stage6, независимый readback, разрешение на изменение Knowledge и отдельный журнал доказательств. Не объединять их с read-only API на основании общего имени «когнитивная операция».

Новые типы операций добавляются в **реестр доверенной композиции**, а не создаются моделью динамически как исполняемый код. Модель может выбирать последовательность и параметры уже зарегистрированных шагов; это и есть её инициатива.

## 4. Пример сквозного цикла

```text
Core получает допустимое событие или активную Goal
   → строит bounded Context (world_state, Memory, Knowledge, uncertainty, provenance)
   → вызывает выбранный cognitive adapter (deterministic/stub/FAST)
   → adapter предлагает retrieve_memory(goal-relevant clue)
   → Core проверяет ID, доступ, источник, бюджет, цикл и допускает read-only Retrieval
   → validated result возвращается советчику; неполнота/источник явно указаны
   → adapter обнаруживает противоречие и предлагает request_observation
   → Core отделяет сенсорную/мировую операцию от анализа и проводит admission
   → Execution / independent Verification подтверждают или опровергают результат
   → Raw записан; Belief/Memory/Context обновляются через свои службы
   → новые proposals, пока есть смысл и бюджет, либо stop/park
```

Core обязан продолжать жизненный цикл без LLM. Отсутствие/таймаут модели приводит к наблюдаемому `partial/rejected/parked` или контролируемому deterministic fallback, но не к ложному подтверждению Goal или невидимому побочному эффекту.

Возможность **инициировать следующую мыслительную операцию в уже активном когнитивном цикле** принимается сейчас. Самостоятельное пробуждение без внешней задачи (новизна, незавершённая гипотеза, внутренний таймер, SLEEP) — **отдельный проверяемый механизм триггеров**. Предварительное одобрение LLM-initiative не означает неограниченную фоновую генерацию целей.

## 5. Пространство как среда испытаний, не продукт

В Godot **сохраняются скрытые абсолютные координаты**, необходимые для коллизий и независимого oracle. ANIMA их **не получает**. Текущий E1.2/E2.2 DTO содержит `self_position`, `reading.cell`, `position.value` и идентификаторы стен вида `lab.wall.x.y`, которые раскрывают координаты. Для нового opt-in E2.3 создать **версионированный агентский сенсорный контракт**, исключающий эти утечки; старые E1/E2.2 gates оставить неизменными.

- Эгоцентрическое зрение, первоначально 90° относительно направления взгляда; дальность без искусственного ограничения в небольшой комнате, но occlusion по стенам, непрозрачным объектам и корректному ray-cast.
- Изменение направления взгляда — явное действие/наблюдение; сенсор **не** передаёт полный список видимых из любых направлений предметов.
- Возвращаемые признаки: относительный bearing, приблизительный range/depth или порядок близости, идентичность/свойства объекта **только если реально наблюдаемы**, информация о неохваченной области. Нельзя молча превращать отсутствие reading в отсутствие объекта.
- Внутренняя карта — **топологические узлы/связи + локальная относительная геометрия**, с неопределённостью и provenance для каждого утверждения. Нет готового grid и стартовой глобальной позиции.
- Допустимы ошибки карты и локализации; нужна независимая проверка, применяет ли ANIMA прошлые наблюдения при повторном поиске и пересматривает ли ошибочные связи.

Поддержать в исследовании минимальную направленную среду, **не тратить текущий этап на совершенный навигационный алгоритм**.

## 6. Что на самом деле требует разработки

В текущей базе:
- `CoreIngress` валидирует типизированные Core события и хранит их в `core_state.db`; `SourceRegistration` не удостоверяет транспорт сам по себе.
- `E2.2` сохраняет **полный** `WorldObservation` в sidecar `e22_raw_capture`, а Core получает **digest pointer**, а не весь снимок.
- `BeliefProjection.PropertyRule` поддерживает только `symbol/string/boolean/integer`; эгоцентрическая геометрия и структурированные наблюдения требуют нового явного типа/проекции.
- `MemoryProcessor` выбирает `conversation.user`, и сенсорные world Events автоматически **не** становятся эпизодической памятью.
- `ContextBuilder` выбирает Knowledge/Memory и опциональные доказательные Events для DEEP; отдельного `world_state` интерфейса сейчас нет.
- У E2.2 **нет** защищённого рабочего канала на выполнение WorldActions через Stage6 и нет общего full-Raw/Core transaction. Эти границы нельзя скрывать под меткой `PASS_LAB_RAW_POINTER`.

Таким образом, интерфейс perception, spatial memory, cognitive proposal/admission и decision trace являются **новыми контрактами и кодом**, а не конфигурацией существующей модели. Это допустимо внутри изолированной исследовательской ветки.

## 7. Приоритет работ (не блокировать cognition полной миграцией Raw)

| Направление | Действие | Gate |
| --- | --- | --- |
| E2.3 / Agent perception | Направленное 90° зрение, взгляд/поворот, relative DTO, отсутствие утечек hidden coordinates, сохранение прежних gates | Строгая схема, occlusion, spoof/hidden-state negative tests |
| E2.4 / Working world model | Простая топологическая память, противоречия, freshness, distinction unknown/absent/unobserved; source/sample provenance | Без готовой карты, replay и сравнение с cold start |
| **Параллельно E2.4** / Cognitive contract | Типизированные proposals, bounded read-only tools, provenance-backed response, CognitiveCoordinator+DecisionRecord, deterministic adapter | Невозможно прямое изменение Memory/Knowledge/Action; negative tests и trace до исполнения |
| E2.5 / Minimal live loop | Event → world_state/Memory → proposals → Core admission → independent verification → new Event | На фиксированных задачах видны причины выбора, реальные ошибки/пересмотр |
| **Раннее E2.5/E2.6** / FAST lab | FAST на **том же** сенсорном Context и полномочиях, сравнение с deterministic/stub | Seeded multi-run, candidate validity, context use, revision quality, cost |
| E2.6 / Acceptance | Абляции памяти, contradictory evidence, novelty, energy/task conflict, adversarial proposals, ограниченные crash tests | Research verdict без автоматического релиза |
| E3 / Cognitive integration | FAST/DEEP resource routing, richer tool interface, reflection на сохранённом опыте | Сменность модели, гарантия отсутствия прямых полномочий |
| E4 / Persistence | Единый durable Core Raw+cursor+event либо доказанный эквивалент, backup/recovery, длительные прогоны | Не переносить E2.2 sidecar PASS на постоянный экземпляр |

Этапы cognition и модельного сравнения допускается вести **параллельно** разработке perception и map; не ждать «идеальной навигации» и не подменять это соревнованием path planners.

## 8. Неподлежащие обходу инварианты

1. **Core — единственный доверенный владелец admission и lifecycle.** CognitiveCoordinator не создаёт второй Goal/Task/Executor.
2. **LLM outputs — недоверенные предложения.** Нельзя принимать self-reported confidence, reason или `source_ref` за evidence/trust.
3. **Операции имеют ресурсы и завершение.** Лимит шагов, глубины рекурсии, токенов, времени, Retrieval, повторов, max pending; детерминированный останов/park при исчерпании.
4. **Idempotency и provenance.** У каждой принятой операции уникальная идентичность, verified outputs, trace; повтор не создаёт второго эффекта.
5. **Данные прежних состояний мира не становятся актуальными без проверки.** `world_instance_id+epoch`, clocks и visibility/coverage явно учитываются.
6. **Нет прямого записи Knowledge/Belief моделью.** Изменение проходит typed validator, разрешённый lifecycle/evidence rules и audit.
7. **Нет hidden-state leakage.** Сравнения FAST/stub/deterministic проходят через одинаковый агентский DTO, oracle недоступен.
8. **Качество измеряется.** Ценность LLM — проверяемое улучшение выбора/проверки/пересмотра решений, а не свободный рассказ модели о «рассуждении».
9. **Не переписывать релиз v0.2.0-rc.1** и пользовательские данные. Все эксперименты в disposable Core/world instance.
10. **Защитные границы** действуют даже при приглашении модели инициировать дополнительные шаги: никаких секретов Godot и OS-доступа недоверенному коду.

## 9. Испытания когнитивной инициативы

Минимальные black-box сценарии:
- **Memory helps:** знакомая топология после перезапуска и повтор задачи vs fresh instance.
- **Novelty:** неизвестная область без встроенной награды, модель/алгоритм инициирует информационный шаг лишь при обоснованной неопределённости.
- **False belief:** объект переместился; пересмотр старой гипотезы по подтверждённому новому наблюдению.
- **Contradictory sources:** два неэквивалентных свидетельства, отсутствие автоматической перезаписи Knowledge.
- **Goal decomposition:** промежуточная цель из недостающей информации; проверенный родительский Goal и критерий остановки.
- **Faulty LLM:** недопустимая операция, поддельный `source_ref`, чужой `event_id`, циклический запрос, попытка записать Knowledge, выполнение `act` в обход Stage6, timeout — fail-closed.
- **Independent evaluation:** отдельная трасса того, что было известно агенту *до* действия; отдельно хранится скрытая истина Godot для оценки, не для подсказки.
- **Model-off recovery:** модель недоступна в середине когнитивного цикла; ANIMA может сохранить состояние и перейти к ограниченному fallback/park.

Метрики: цель выполнена, число действий и проверок, повторные ошибки, попытки получения новой информации, качество/свежесть retrieval, доля необоснованных гипотез, корректность пересмотра, доля недопустимых предложений, время/токены FAST, полнота trace и соблюдение trust boundary. Нужны несколько seed, повторения и ablation; **не** оценивать мышление только успешной доставкой ящика.

## 10. Открытые архитектурные вопросы (обсуждать при выборе, а не тормозить технику)

- **Активация инициативы вне активного Goal:** какие внутренние novelty/uncertainty triggers разрешают начать автономный cognitive turn, а какие следует отложить до E5?
- **Право сохранять гипотезы:** временная рабочая гипотеза, долговременный candidate, confirmed Knowledge должны иметь разную власть и сроки жизни.
- **Распределение FAST/DEEP:** стоимость запуска, критерий эскалации, возможность самостоятельного запроса DEEP из FAST и верхние бюджеты.
- **Общая картина «я»:** эгоцентрический viewpoint, память о собственных действиях и карте — это рабочая само-локализация, **не** утверждение о наличии субъективного сознания.

**Первый технический шаг:** E2.3 opt-in view cone / relative observations + test fixture; параллельно подготовить минимальные `CognitiveStepProposal` / `DecisionRecord` контракты и сравнимый deterministic baseline. Никакой merge/release gate автоматически из этого design-текста не следует.


## R9.4.0 — управление циклом: текущая исследовательская граница

На baseline `5448e8ee8b09a3ad8d079896d85367201ed13d5a` подготовлены [инвентаризация, characterization, метрики и контролируемый протокол R9.4.0](e2-6-r940-characterization-v02.md). [Реестр R9](e2-6-r9-remediation-v02.md) сохраняет прежние finding IDs и исторические результаты. Зафиксированные ограничения sufficiency/continuation/redundancy/availability относятся к изолированному read-only lab loop; они не означают разрешение на изменение canonical coordinator. Реализация R9.4.1–R9.4.4 начинается только после рассмотрения characterization и протокола. Hybrid Cognitive Result, source binding и terminal contracts R9.3 сохранены; PASS воспроизводителя не закрывает дефект.
