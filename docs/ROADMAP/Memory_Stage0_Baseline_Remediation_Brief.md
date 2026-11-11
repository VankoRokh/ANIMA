# ANIMA — Memory Stage 0: Baseline & Remediation Brief

**Статус:** выполняется; выполнение тестов и приёмка не подтверждены.  
**Ветка:** `experiment/core-memory-information-baseline`.  
**Начало:** 2026-11-11.  
**Исследовательский baseline:** `cab955f82931feb16e5a7c2bf801e17aa736fd8f`.  
**План:** [Memory Architecture v1.0 / v1.1](Memory_Architecture_v1_Roadmap.md).  
**Источник выводов:** ANIMA Memory Architecture Research & Technical Review (2026-11-11), §3 «Confirmed Issues & Missing Capabilities».

## Назначение и границы

Этап 0 создаёт воспроизводимую основу для повторения EXP-009 и дальнейшей разработки Memory v1.0. Он **не** меняет Event/Memory/Knowledge semantics, Stage statuses, права источников, Core goal/verification policy или формат долговечных баз. Любая миграция и новый concurrent writer требуют отдельного решения.

## Профиль проблем, подтверждённых статическим чтением ветки

| ID | Файл | Дефект и риск | Минимальная мера | Проверка |
| --- | --- | --- | --- | --- |
| B0-01 | `anima/core/door_execution.py` | Конструктор `CoreDoorExecution` аннотирован `world: VirtualDoorWorld`, но имя не импортировано; `DoorWorldPort` уже импортирован и используется в `isinstance`. Отчёт сообщает, что импорт сборки падает на 3.12/3.13. | Использовать `DoorWorldPort` в аннотации. Не расширять допускаемые реализации и не менять выполнение действий. | `from anima.core.assembly import build_core` на 3.12/3.13/3.14, профильные tests и обычная сборка. |
| B0-02 | `tests/source_tree.py`, `tests/test_documentation.py`, `docs/ROADMAP/Research.md` | В ограниченном copy manifest отсутствуют пять `labs/exp009/*.py`, на которые ссылается Research. Временная копия ошибочно диагностирует broken links; три теста документации завершаются раньше целевого assertion. | Явный allowlist **ровно пяти** ссылочных файлов; не добавлять весь каталог `labs` или локальные данные. | Тест копирования пяти файлов, отрицательный тест на прочие `labs` пути, `test_documentation.py` и `scripts/check.sh`. |
| B0-03 | `anima/memory/event_processing.py`, `anima/memory/memory_store.py` | `process()` делает `get()` перед транзакцией; `transaction()` начинает `BEGIN`, а `_record_failure()` может перезаписать `done` на `failed`. Аудит воспроизвёл гонку двух coordinator. | На первом этапе зафиксировать **single-writer** контракт и запретить добавление фонового писателя. Для multiwriter потребуется атомарный claim, защита terminal status и отдельные concurrency/crash tests. | Последовательный replay одного Event даёт один эффект; допуск второго обработчика не объявляется поддерживаемым. Перед запуском двух писателей — новый gate с interleaving-тестом. |

## Порядок работы

1. Зафиксировать чистый проверяемый ref, версии Python/pytest/SQLite и команды повторения. Отдельно указать, если исполняемое окружение недоступно.
2. Минимально исправить B0-01. Добавить воспроизводимый smoke импорт сборки на каждой заявленной версии Python.
3. Минимально исправить B0-02; проверить, что тестовые копии содержат нужные пять файлов, не копируя личные артефакты или весь `labs`.
4. Для B0-03 задокументировать контракт одного писателя и отметить отсутствие multiwriter safety. Если понадобится конкурентный режим — проектировать и испытывать отдельно, а не объявлять решённым.
5. Выполнить профильный pytest, полный pytest, `scripts/check.sh`; повторить импорт на Python 3.12/3.13/3.14. Сообщить точные результаты и любой недоступный сценарий.
6. Зафиксировать SHA и отчёт тестов; только затем считать Stage 0 VERIFIED и переходить к матрице A/B/C/D EXP-009.

## Повторяемые команды

```bash
python -m pytest -q -p no:cacheprovider tests/test_core_p3b_execution.py tests/test_event_processing.py tests/test_documentation.py tests/test_source_tree.py
python -m pytest -q -p no:cacheprovider
bash scripts/check.sh
python -c "from anima.core.assembly import build_core; print('import OK')"
```

Импорт должен отдельно выполняться подходящими интерпретаторами Python 3.12, 3.13 и 3.14; один интерпретатор не подтверждает всю матрицу.

## Отрицательные сценарии и стоп-условия

- Тестовая копия с намеренно битой ссылкой по-прежнему сообщает `Broken link`; с намеренно неверным архитектурным test ref — нужную ошибку, а не отсутствие экспериментальных файлов.
- Symlink наружу и скрытые/личные файлы не должны попадать в тестовую копию.
- Повторная обработка финального Event не изменяет уже подтверждённый terminal status и не создаёт новую Memory в **заявленном single-writer режиме**.
- Любое предположение о двух одновременных писателях остаётся **UNVERIFIED/UNSUPPORTED**, пока нет claim/terminal guard и соответствующего прогона.
- Нельзя объявлять все тесты зелёными без фактического исполняемого прогона. Статический review и выполненный pytest фиксируются отдельно.

## Промежуточный результат — 2026-11-11

**Внесено в эту рабочую ветку (ещё без исполняемой приёмки):**

- B0-01: `anima/core/door_execution.py` — в аннотации конструктора используется импортированный `DoorWorldPort`. Добавлен тест `test_core_door_world_annotation_is_importable_on_supported_python` в `tests/test_core_p3b_execution.py`.
- B0-02: `tests/source_tree.py` — в bounded snapshot включены только пять исходников `labs/exp009`, на которые ссылается `Research.md`. Добавлен отрицательный тест в `tests/test_source_tree.py`, проверяющий отсутствие других lab-файлов в копии.
- B0-03: в docstring `EventProcessingCoordinator` явно закреплён single-writer контракт и запрет на вывод о concurrent safety. Поведение координации **не менялось**, гонка двух писателей **не исправлена**.

**Ограничение проверки:** среда исполнения полного checkout отсутствует; у коммитов нет результатов GitHub CI. Выполнено чтение изменённых файлов и проверено существование всех пяти referenced lab sources; полноценные `pytest`, `scripts/check.sh` и Python 3.12/3.13/3.14 smoke **не запускались**. Gate остаётся OPEN до результата исполняемых тестов.

## Приёмка

| Контроль | Состояние при создании brief |
| --- | --- |
| Конкретные причины B0-01/02/03 локализованы в коде | Подтверждены статическим чтением |
| Python 3.12/3.13/3.14 import smoke после исправления | Не выполнено |
| Три теста документации, source tree tests | Не выполнено |
| Последовательный replay и вся регрессия | Не выполнено |
| Зафиксирован single-writer контракт | Запланирован |
| Полный Stage 0 gate | **OPEN** |

После завершения результаты оформлять отдельно в [журнале испытаний](../TESTING/Results/README.md). Старый результат `1478 passed, 3 failed` относится к исследованному snapshot, не считается результатом после исправлений.
