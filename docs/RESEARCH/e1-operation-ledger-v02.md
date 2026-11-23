# ANIMA v0.2 — E1.4: bounded Operation Ledger и восстановление ответа

**Статус:** `Validated Lab / E1.4 PASS` (23 ноября 2026 года). **Не является** `E1-min PASS`, E2, интеграцией с Core или выпуском новой версии.  
**Проверенный кодовый snapshot:** `c896ba9f3a1b610cfcddb8b58ac8a33299f71f1f`.  
**Исследовательская ветка:** `work/v02-e14-operation-ledger`.  
**База:** [E1.3 — world effects/readback](e1-world-effects-v02.md), опубликованный релиз `v0.2.0-rc.1` остаётся неизменным.  
**Первичные доказательства:** [GitHub Actions #45164124776](https://github.com/VankoRokh/ANIMA/actions/runs/45164124776), артефакт `anima-e14-godot-4-7-2-evidence` с raw log и JSON.

## 1. Контракт и безопасность

E1.4 расширяет **только изолированный** `LifecycleWorld` в Godot. Порт по-прежнему слушает `127.0.0.1` и имеет самообъявленные роли — **никакой настоящей аутентификации нет**. `ANIMA Core`, Memory, Goal/Task, FAST/DEEP, ОС и физические устройства не подключены.

Режимы строго разделены:

| Запуск | Доступные действия agent |
| --- | --- |
| Без флагов | `observe`, как в E1.2 |
| `--lifecycle-effects` | `observe`, `act` и **отказ в повторе operation ID**, как в E1.3 |
| `--lifecycle-effects --lifecycle-ledger` | `observe`, `act`, `operation_status` с ограниченным E1.4 ledger |
| `--lifecycle-ledger` без effects | Ошибка конфигурации; не предназначено для штатного запуска |

Одна эпоха живого процесса мира содержит максимум **256 терминальных записей**. Идентичность записи связана с `world_instance_id`, `epoch` и `operation_id`. Для сравнения payload строится канонический SHA-256 digest из упорядоченного набора: schema, world ID, epoch, expected revision, observation ID, operation ID, action type и точного аргумента. Порядок JSON-ключей не меняет digest; изменение параметров под старым ID — конфликт.

### Состояния и эффекты

| Ситуация | Поведение |
| --- | --- |
| Новый разрешённый `WorldAction` | Одно выполнение, один исходный `WorldReceipt` с `replayed=false` |
| Тот же ID и **тот же полный payload** | Сохранённый receipt с `replayed=true`; **нет** второго события, эффекта, изменения tick или revision |
| Тот же ID с другим payload | `OPERATION_CONFLICT`; действие запрещено |
| Исходный `BLOCKED` | Записывается как завершённая попытка; replay снова возвращает `BLOCKED`, не двигает мир |
| Заполнены 256 записей | Новый ID получает `OPERATION_CAPACITY`; старые status и replay продолжают работать, **без eviction** |
| `operation_status` по полной исходной операции | `RECORDED` + оригинальный receipt либо `UNKNOWN` + null |
| Status-запрос с чужим payload при известном ID | `OPERATION_CONFLICT`; чужой receipt не присваивается запросу |
| Reset мира | Новый `epoch`; старый ledger недоступен. Старый запрос сообщает `UNKNOWN`, а действие старой эпохи запрещено |
| Перезапуск Godot-процесса | Новый `world_instance_id`, старые записи не сохраняются; отсутствие записи **не** доказывает отсутствие эффекта |

`RECORDED` — только подтверждение того, что мир **заявил** о сохранённом результате. Это **не независимая** верификация выполненного действия и не терминальный успех Goal. `UNKNOWN` означает отсутствие подтверждённой записи в доступном ledger — **не** разрешение вновь исполнить неизвестную операцию.

Python helper `labs/virtual_anima_lab/python/lifecycle/recovery.py` проверяет typed `WorldOperationStatus` по полной исходной `WorldAction`, сохраняет `safe_to_reissue=False` даже для `UNKNOWN`, и **никогда сам не вызывает** `act` при неудаче поиска. Для `VERIFIED_SUCCESS` всё ещё необходимы свежий независимый `WorldObservation` и проверка `verify_world_effect()`; replayed receipt сам по себе не становится новым proof.

### Атомарность и границы

В одном процессе Godot обработка действия, фиксация receipt в памяти и выдача ответа выполняются последовательно в обработчике запроса. Это проверенная **процессная** модель, а не durable transaction с `fsync`, persistent journal или защитой от отключения питания. Обрыв процесса между физическим эффектом и сохранением состояния внешней системы не испытывался и не покрывается E1.4. Reset — **не** восстановление мира.

При потере ответа клиент обязан использовать `operation_status`, если тот же процесс и эпоха доступны. Воспроизведение полученного `RECORDED` receipt без эффекта и его независимое прочтение проверены; при `UNKNOWN` клиент останавливается и не повторяет операцию автоматически.

## 2. Испытания и воспроизведение

**Environment:** GitHub Actions Ubuntu x86_64, официальный Godot `4.7.2.stable.official.ed1daf0bf`, Python 3.12.16 / 3.13.18 / 3.14.10. Кодовый snapshot `c896ba9f3a1b610cfcddb8b58ac8a33299f71f1f`. Все **4/4 jobs SUCCESS**.

| Проверка | Фактический результат |
| --- | --- |
| Python E1.1–E1.4 targeted DTO, scenario, proof, reconciliation | **41 PASS** на Python 3.12, 3.13, 3.14 |
| Полная Python-регрессия | **2356 PASS** на каждой версии Python и в реальном Godot job |
| `scripts/check.sh` до нового docs-only commit | PASS; **186 страниц / 1346 ссылок** |
| `LifecycleWorldLedgerTest.gd` | `LIFECYCLE_E1_4_NATIVE_PASS` |
| Полный 256-capacity, конфликт и повтор `BLOCKED` | PASS в native Godot |
| Live reconnect и application-discarded receipt | `E1_4_LIVE_PASS`, seed 7 и 8, каждый по **2** независимых процесса |
| Корректное восстановление claim и отдельный свежий сенсорный proof | PASS |
| Reset epoch / старый action | `UNKNOWN` / отказ `EPOCH_CHANGED` |
| E1.2/E1.3, P5/P6, P5-C, M2 | Все прежние real-Godot gate PASS |
| **Итог** | **`E1_4_LIVE_GATE_PASS`** |

Из корня **чистого временного checkout**:

```bash
GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
bash scripts/run_e14_live_gate.sh "$GODOT_BIN"
```

Runner повторяет E1.2/E1.3/P5/P6/M2 и новые E1.4 тесты с одноразовыми world/data. Ни реальные пользовательские базы, ни релизные файлы не изменяются.

Ранний [run #45163340856](https://github.com/VankoRokh/ANIMA/actions/runs/45163340856) остановился на ошибке вывода типа переменных **в новом GDScript тесте**, при этом Python 2356 PASS и E1.2/E1.3/P5/P6/M2 PASS. После исправления добавлена дополнительная защита: статус теперь запрашивается **по полному action**, а не по одному ID. Сбой сохранён в CI-истории, не переименован в успешный результат.

## 3. Что не проверено

- **E1.4 не сохраняет** ledger на диск и не восстанавливает его после перезапуска Godot, рестарта ОС или отключения питания; persistent world относится к будущим исследованиям E4.
- Потеря ответа симулировалась на границе **приложения** (discard + disconnect/reconnect). Умышленное обрывание TCP-пакета между world effect и ответом и настоящий `SIGKILL` Godot не тестировались.
- Даже реальные тесты `RECORDED` не удостоверяют подлинность сенсора при недоверенном локальном процессе. Trust boundary остаётся лабораторным.
- Никаких интегрированных `Core Goal/Task/Admission`, `Raw Event`, `Memory`, `FAST`, автономного выбора действий, питания/зарядки либо долговременной истории агентского экземпляра E1.4 не предоставляет.
- Этот профиль не входит в опубликованный release `v0.2.0-rc.1`. Он не расширяет его доверенный контур.

**Следующее решение:** выполнить самостоятельный **E1-min интеграционный gate** для E1.1–E1.4 со сквозными отрицательными сценариями и только после его принятия переходить к E2 (`event → memory/context → candidate → admission → action → proof → event`, сначала stub). Более широкий E1 с виртуальной энергией, зарядкой и многоэтапным исследованием мира остаётся отдельной работой.
