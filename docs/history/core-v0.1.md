# Core v0.1 — путь от Stage 6 к typed Core

**Роль:** исторический отчёт о решениях, исправлениях и ограничениях, не текущий Roadmap и не заявка на принятие всего релиза. Точные тестовые результаты принадлежат своим SHA и профилям.

## 1. От Stage 6 к системной сборке

[Stage 6](stages.md#stage-6) завершил интеграцию Persistent Task, `CognitiveCoordinator`, FAST/DEEP routing, Goals, SLEEP и independent Verification — [TV-0051](../TESTING/Results/TV-0051.md), `123374b7eabf03fe1f65e9101626c2b26412dc08`.

Позднее typed Core v0.1 выделил общую [точку `build_core`](../../anima/core/assembly.py), [CoreIngress](../../anima/core/ingress.py), [BeliefProjection](../../anima/core/belief.py), event outbox, Goal binding, bounded Action и driver. Наличие Stage 6 не доказывало эти поздние контракты автоматически.

| Линия | Изменение | Условие применения |
| --- | --- | --- |
| P0/P1 | База Runtime, Identity/State, явная сборка и диагностика | Без скрытого исполнения |
| P2 | Typed `Core Event`, SourceRegistration, Belief, outbox и replay | Источник регистрируется системно; registry не является transport authentication |
| P3-A | Typed Goal criterion, binding, долговечный Task | Не создаёт исполнительную capability |
| P3-B | Ограниченная операция с VerificationSpec и independent proof | Только зарегистрированный world port |
| P3-C | Долговечные триггеры и bounded synchronous scheduling | Opt-in, нет бесконечного самостоятельного планировщика |
| P4 | Приёмка ограниченного typed Core и негативных случаев | Результат относится к проверенному срезу |

## 2. Независимый аудит B1–B4

На `aabe6553cec19d4cf1962dc4f26129eeca436328` обычные **1380/1380 PASS** не обнаружили четыре дефекта, выявленные дополнительной независимой проверкой. Вердикт по тому снимку — **BLOCKED**. Статус регулярной регрессии нельзя подменять статусом независимого аудита.

| Ошибка | Наблюдавшаяся опасность | Последующее решение |
| --- | --- | --- |
| B1 | Записанное действие без полного `VerificationSpec` | Одна транзакция сохранения намерения и проверки |
| B2 | Отмена Goal/Task препятствует корректному восстановлению после эффекта | Сохранить терминальный статус отмены, не терять proof |
| B3 | Повтор proof получает новый timestamp и теряет идемпотентность | Стабильная идентичность запроса доказательства |
| B4 | При `blocked → active` пропадает trigger | Парковать и возвращать ключ триггера |

В [плане исправлений](../ROADMAP/Core_v0_1_Independent_Audit_Remediation_Draft.md) описаны также **T1** (точная идентификация обязательных тестов) и **T2** (контроль SHA/tree и clean checkout). Владелец сообщил **1392 PASS** на `b639a52281eeaece1b5b00d8223d8f31bd492ca1`; независимый повторный формальный вердикт именно для этого снимка в проверенном материале **не найден**. Нынешняя ветка содержит регрессии B1–B4, но это не задним числом отменяет исходный BLOCKED.

## 3. P5/P6 — подключаемая виртуальная среда

P5-A/B/C проверяли Godot-сценарии, typed bridge и replay. P6 ввёл внешний [`VALDoorPort`](../../labs/virtual_anima_lab/python/core_port.py) и инъекцию `DoorWorldPort` вместо встраивания Godot в Core. Не переносить полномочия от прежней SQLite-двери к новому происхождению без отдельного допуска. Последующие живые M2 и M6-B1/B2 имеют собственные отчёты и условия.

**Важно:** документы, написанные до P6, могут содержать «P6 не начат». Это исторический статус планирования, не текущий факт. [Лабораторные отчёты](../TESTING/Laboratory_Integrations.md) сохраняют точные версии Godot/Python и границы сбоев.

## 4. Что унаследовано релизом

`ANIMA v0.1 Foundation` использует `build_core`, сохраняемый Runtime и ограниченную API-композицию. Базовый профиль имеет пустые registries и не включает `CoreDoorExecution`; `--sandbox-door` включает только локальное контролируемое действие. [Текущая матрица](../system/README.md#матрица-состава) · [приёмка релиза](../versions/v0.1/acceptance.md).

Не утверждается: общая аутентификация произвольных adapters, exactly-once внешних физических эффектов, приёмка всего Stage 8/9, автоматическое целеполагание и независимая заморозка Core без дополнительного решения.

**Первичные входы:** [TV-0051](../TESTING/Results/TV-0051.md), [TV-0054](../TESTING/Results/TV-0054.md), [инварианты аудита](../ROADMAP/Core_v0_1_Audit_Boundaries.md), [исправления](../ROADMAP/Core_v0_1_Independent_Audit_Remediation_Draft.md), [VAL runbook](../../labs/virtual_anima_lab/README.md).
