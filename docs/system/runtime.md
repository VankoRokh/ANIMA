# Runtime, Identity и жизненный цикл

**Назначение:** запуск одного системного экземпляра с непрерывной идентичностью и событиями; код исполнения не должен зависеть от интерфейса, модели и расположения пользовательских данных.

## Сборка и владельцы состояния

[`build_core`](../../anima/core/assembly.py) — общая composition root. Создаёт `Identity`, `AnimaState`, `EventBus`, `EventLog`, `MemoryStore`, `LinkStore`, обработчик Memory, Internal State, диагностику и `Runtime`. Опционально добавляет EventRetrieval, CoreIngress/Belief, GoalDecision, DoorExecution и bounded Autonomy. **Сборка сама не вызывает `wake()`** — жизненным циклом управляет вызывающий код.

| Владелец | Состояние | Особенность |
| --- | --- | --- |
| `Identity` | `identity.json`, стабильный `instance_id` | Не совпадает с session ID |
| `AnimaState` | `state.json`, статус, сессии, счётчики | Внутреннее `00.1-alpha` не является релизным тегом |
| `EventBus` | Очередь RAM | Не долговечный источник истины |
| `EventLog` | `events.jsonl` | Первичный журнал событий Runtime |
| `EventProcessingCoordinator` | Статус обработки в SQLite Memory | Восстанавливает обработку после прерывания |
| `Runtime` | Согласование служб | Не исполняет произвольный запрос без отдельной capability |

## Штатный профиль

Точка входа [`anima.release_v01`](../../anima/release_v01.py) принимает `--data-dir`, проверяет `release_profile.json` и использует POSIX `flock` для кооперативного одного writer. Только новый каталог либо ранее закреплённый **совместимый** экземпляр допустим. Вызов `open_release()` запускает `runtime.wake()`, а при нормальном выходе — `runtime.sleep()`.

`serve()` обрабатывает последовательные JSONL-команды из локального stdin: `report`, `search_events`, `context`, `status`, `stop`. Протокол не является аутентифицированной сетевой границей. `report` допускает до 4096 символов, `query` — до 256; неизвестные операции отклоняются. Текст не может сам объявить себя зарегистрированным sensor.

## Жизненный цикл и восстановление

```text
open_release → проверка профиля и блокировка
             → build_core → Runtime.wake()
             → обработка команд по порядку
             → Runtime.sleep() → закрытие процесса
```

`Runtime._ensure_recovered()` восстанавливает статус обработки Events, учитывает завершённые события и дренирует ограниченную партию persistent Core outbox. Если `sleep_runtime` не подключён (как в `release_v01`), никаких SLEEP WorkItems эта процедура не выполняет.

## Данные экземпляра

| Файл / каталог | Владелец | Профиль |
| --- | --- | --- |
| `identity.json`, `state.json`, `events.jsonl`, `memory.db`, `internal_state.db` | Runtime / Memory / Internal State | Оба профиля |
| `event_index.db` | Производный EventRetrieval | Оба профиля v0.1 |
| `core_state.db`, `core_work.db`, `tasks.db` | Typed Core и GoalDecision | Создаются и при пустых реестрах v0.1 |
| `execution.db`, `sandbox_world/` | Execution / VirtualDoorWorld | Только `--sandbox-door` |
| `release_profile.json` | Версионирование capabilities | Оба профиля, не менять вручную |
| `sleep.db`, persistent `trace.db` | Отдельные Stage 3/6 интеграции | Не создаются обязательной базовой сборкой |

Нет одной транзакции поверх `events.jsonl` и всех SQLite. Для резервного копирования остановить экземпляр и сохранить **весь каталог**, а восстановление проверить в отдельной директории. `flock` не защищает от процесса, открывающего SQLite напрямую.

## Ошибки и проверка

Не подтверждённый append при аварии нельзя считать долговечным. Подтверждённый raw Event и состояние обработки подлежат восстановлению по поддержанному сценарию; случайные локальные изменения файлов требуют проверки целостности и не дают обещаний exactly-once во внешнем мире.

**Код:** [runtime.py](../../anima/runtime.py), [assembly.py](../../anima/core/assembly.py), [state.py](../../anima/core/state.py), [identity.py](../../anima/core/identity.py). **Проверки:** [test_runtime.py](../../tests/test_runtime.py), [test_release_v01.py](../../tests/test_release_v01.py), [TV-0001](../TESTING/Results/TV-0001.md), [TV-0051](../TESTING/Results/TV-0051.md). **История:** [D0, Stage 0 и D1](../history/stages.md#stage-0).
