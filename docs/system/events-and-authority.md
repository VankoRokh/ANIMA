# Events, Belief и полномочия источников

**Задача:** не превращать полученный текст, технический факт записи и утверждение о мире в одно и то же доказательство.

## Два канала событий

| Канал | Первичный источник | Когда используется | Что не следует из записи |
| --- | --- | --- | --- |
| Legacy `Event` | `events.jsonl` (`EventLog`) | `Runtime.user_input` создаёт `conversation.user` | Истинность содержания пользовательского сообщения |
| Typed `Core Event` | `core_state.db` (`CoreIngress`) | Зарегистрированный адаптер с явным `source_ref` | Реальная аутентификация источника только по его строковому имени |

`Event` фиксирует, **что было получено**. `Observation` — типизированное сообщение о конкретном свойстве мира. `Belief` — системная проекция допущенных наблюдений: значение, история ревизий, freshness и ссылки на evidence. `Claim` — квалифицированное утверждение в семантическом контракте Stage 7, а не синоним runtime Belief. `Knowledge` имеет собственный lifecycle в Memory.

`Evidence` указывает фактическое основание утверждения; `provenance` отвечает за происхождение, цепочку преобразований, источник и версию. Наличие provenance само по себе не доказывает истинность.

## Путь typed ingress

```text
доверенный host/adaptor связывает вызывающего с source_ref
   → CoreIngress.admit(raw, source_ref=...)
   → проверка SourceRegistration / allowed_kinds / envelope
   → транзакция SQLite: core_events + core_outbox + BeliefProjection
   → CoreEventDispatcher.drain() (ограниченно и с replay)
   → legacy events.jsonl (как downstream совместимое представление)
   → EventProcessingCoordinator (без нового authority)
```

[`SourceRegistration`](../../anima/core/ingress.py) фиксирует `source_ref`, `producer_ref`, `allowed_kinds`, но **не** аутентифицирует транспорт. `PropertyRule` задаёт разрешённые источники, тип значения, clock domain и freshness. При пересылке одного Core Event сохраняется идентичность `event_id`, поэтому downstream запись не считается вторым независимым доказательством.

## Дубликаты, конфликты и неполнота

`CoreIngress.admit` различает `ACCEPTED`, `ALREADY_SEEN`, `IDENTITY_CONFLICT` и `REJECTED`. Совпавшая тройка `(source_ref, occurrence_id, occurrence_version)` при ином содержимом — конфликт, а не новое показание. Отказы записывают reason code; исключения ввода-вывода не маскируются под `REJECTED`.

`BeliefProjection` хранит `revision`, `status`, `observed_tick`, `last_known` и `evidence_event_ids`. `fresh/stale/undetermined` вычисляются относительно указанной системы отсчёта. Устаревшее наблюдение нельзя молча использовать как новое разрешение на эффект.

`CoreEventDispatcher` воспроизводит недоставленный outbox после перезапуска; между `core_state.db` и `events.jsonl` нет общей физической транзакции. Повторный drain обязан обнаружить конфликт идентичности вместо переписывания журнала.

## Границы исполнения

Операторский `report` не создаёт `state.property`, не регистрирует новый источник, не повышает Belief и не создаёт binding Goal. Даже корректный Belief **не** означает автоматически разрешение Tool — требуется отдельный GoalCriterion, policy и зарегистрированная capability.

`M6-B1` и `M6-B2` проверяли перенос контекста и авторизацию в **изолированной** среде, не удалённую аутентификацию реального датчика. [Лабораторная хронология](../TESTING/Laboratory_Integrations.md).

**Код:** [ingress.py](../../anima/core/ingress.py), [belief.py](../../anima/core/belief.py), [dispatch.py](../../anima/core/dispatch.py), [event_log.py](../../anima/memory/event_log.py). **Проверки:** [test_release_v01.py](../../tests/test_release_v01.py), [test_core_audit_blockers.py](../../tests/test_core_audit_blockers.py), [TV-0052](../TESTING/Results/TV-0052.md). **Семантический контракт:** [Stage 7](../ROADMAP/Stage_7_Semantic_Boundary_v0.md).
