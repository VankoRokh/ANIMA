# ANIMA v0.2 — E1.1: граница контрактов виртуального мира

**Статус:** `Implemented / Lab-only / PARTIAL`. **Не** E1-min PASS, не E2 и не release gate.  
**База:** `1364e62634669ef553df0b2f2d7a1159d404383f`.  
**Ветка:** `work/v02-e1-lifecycle-world-contracts`.  
**Программа:** [Continuous Lifecycle E0–E6](continuous-lifecycle-v02.md).  
**Область:** `labs/virtual_anima_lab/python/lifecycle/` и `tests/test_lifecycle_world_contracts.py`.

## Цель и архитектурное решение

Ввести собственные строгие, версионированные DTO для наблюдений, действий, результатов и статуса операции будущего `LifecycleWorld`. Это **подключаемая лаборатория**: не менять `anima/core/belief.py` и существующие P5/P6 schemas, не подключать world effects к релизному профилю.

Приняты D0.1–D0.4: владельцем Goal/Task/Execution/Recovery остаётся Core/Stage 6; FAST/stub может советовать только системный candidate ID или `NO_ADVICE`; E2 восстанавливает Core лишь при неизменном процессе Godot; поведенческие ошибки допустимы, обход полномочий, потеря событий и ложный proof — нет.

## Четыре DTO

| DTO | Schema | Назначение |
| --- | --- | --- |
| `WorldObservation` | `anima.lifecycle.world_observation/0.1` | Один локальный sensor sample, список типизированных наблюдений и их статусов |
| `WorldAction` | `anima.lifecycle.world_action/0.1` | Ограниченное намерение `world.move/pick/drop`, привязанное к sample/world epoch/revision |
| `WorldReceipt` | `anima.lifecycle.world_receipt/0.1` | Сохранённый ответ world effect; **не** подтверждение Goal |
| `WorldOperationStatus` | `anima.lifecycle.world_operation_status/0.1` | Read-only поиск результата по operation ID; `UNKNOWN` не разрешает повторный effect |

DTO отсекают неожиданные ключи, boolean вместо integer, невалидные идентификаторы, составные значения неверного типа и попытки добавить filesystem/shell capability в `action_type`. Входящий словарь захватывается в canonical JSON, `as_dict()` возвращает независимую копию.

**Различия сенсорных статусов:** `known` — sensor сообщает значение; `unknown` — значение не установлено; `absent` — sensor сообщает отрицательное наблюдение (в пределах своей компетенции); `unavailable` — данных получить не удалось. Последние три состояния не содержат `value`. Истинность `absent` должен доказать мир/датчик, DTO проверяет только форму.

## Домены времени и identity

| Поле | Значение | Не приравнивать к |
| --- | --- | --- |
| `world_instance_id` | Идентичность конкретного процесса мира, 32 hex | Identity самой ANIMA |
| `epoch` | Номер сброса виртуального мира | Python session / UTC |
| `revision` | Ревизия состояния мира | `tick`, Core belief revision |
| `tick` | Время симуляции | UTC / CPU wall-time |
| `sample_seq` | Порядок sensor sample | `tick`, event cursor |
| `sample_id` | `worldobs:<world_instance_id>:<epoch>:<sample_seq>` | Action ID / raw event ID |

Все readings одного `WorldObservation` наследуют один sample; составная позиция проверяется целиком (`grid_cell`) и не собирается из разновременных X/Y. `WorldAction` явно указывает `observation_id` и `expected_revision`. Проверку **фактической свежести и владения operation** впоследствии выполняет world admission, а не DTO-парсер.

## Проверки и ограничения выводов

Локально, на **изолированных исходных файлах**, выполнено:

```bash
PYTHONPATH=. python -m pytest -q tests/test_lifecycle_world_contracts.py
# 22 passed
```

Проверены: четыре корректных DTO, неизменяемость сохранённого снимка, отличия статусных сигналов, неверные координаты/энергия/типы, лишние поля, чужой world epoch, запрещённые действия, чрезмерно длинные/не-ASCII sample IDs, неправильная связь operation и receipt, невозможность считать `APPLIED` доказательством доставки.

**Не проверено / NOT_TESTED:** запуск этих DTO из настоящего Godot, авторизация источника, line-of-sight за стенами, достоверность `absent`, реальное сохранение operation ledger, full regression, проектный `scripts/check.sh`, remote CI, idempotent recovery и независимый sensor proof. `WorldReceipt` не является verification даже при `APPLIED`.

## Что дальше

**E1.2** — отдельная новая сцена `LifecycleWorld`: две комнаты, переносимый предмет, два реальных обхода и перекрытый короткий путь; seeded reset; локальные наблюдения, отсутствие готового маршрута у ANIMA; совместимость прежних P5/P6.

Далее E1.3/E1.4 — проверенные `world.move/pick/drop`, readback, operation-status и replay; только после их gate приступать к E2. Все изменения остаются внутри экспериментальной ветки, без переноса в v0.2 release profile.
