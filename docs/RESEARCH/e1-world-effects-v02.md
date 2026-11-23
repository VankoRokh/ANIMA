# ANIMA v0.2 — E1.3: виртуальные действия и независимый readback

**Статус:** `Validated Lab / E1.3 PASS` в ограниченной лабораторной сборке (23 ноября 2026). **Не** `E1-min PASS`, не E1.4, не E2, не release gate.  
**Кодовый snapshot проверки:** `e3ec16b90f8dc839364aaf9a5187151f261d101b`.  
**База:** `1364e62634669ef553df0b2f2d7a1159d404383f` (v0.2.0-rc.1); непосредственный родитель — проверенный [E1.2](e1-lifecycle-world-v02.md).  
**Ветка:** `work/v02-e13-world-effects-readback`.  
**Первичные доказательства:** [GitHub Actions run 45160793477](https://github.com/VankoRokh/ANIMA/actions/runs/45160793477), артефакт `anima-e13-world-effects-live`, лог нативного Godot и Python test runs.

## 1. Цель и граница реализации

Разрешить испытательному агентскому порту строго три виртуальных действия и подтверждать эффект **свежим сенсорным наблюдением**. Реальная ANIMA Core, Memory, Goal/Task, FAST и внешние исполнительные устройства к этому циклу пока не подключены. Штатная сцена `Main.tscn`, контракт P5/P6 и релизный профиль остаются без изменений.

В `LifecycleWorld.tscn` действие доступно **только** при явном `--lifecycle-effects`; без него остаётся режим E1.2 `observe`-only. Локальный TCP-порт слушает `127.0.0.1`. Поля `role=agent/operator` самообъявленные и **не аутентифицируют** источник, поэтому интерфейс нельзя считать безопасным для физического мира или произвольных локальных процессов.

Типизированный `WorldAction` — намерение с `world_instance_id`, `epoch`, `expected_revision`, `observation_id`, `operation_id`, `action_type` и `arguments`. Godot проверяет форму **независимо** от Python DTO, соответствие последнему наблюдению, текущий world binding и allowlist:

| Action | Поведение | Как доказать эффект |
| --- | --- | --- |
| `world.move` | Один шаг `N/S/E/W`; препятствие даёт `BLOCKED` | Новое `self_position` в ожидаемой соседней клетке; переносимый предмет движется с агентом |
| `world.pick` | Подбор `lab.item.crate` на соседней/текущей клетке | `owner` становится `lab.actor.anima`, `item.position` соответствует actor |
| `world.drop` | Положить переносимый предмет в текущей клетке | Свежий `item.position` и `owner=absent`; доставка подтверждается только при наблюдаемой зоне `lab.zone.delivery` |

Сама `WorldReceipt.status=APPLIED` **не** завершает `Goal` и не доказывает действия. Экспериментальный `verify_world_effect()` из `labs/virtual_anima_lab/python/lifecycle/world_verification.py` принимает `WorldObservation` до/после, `WorldAction` и `WorldReceipt`, сравнивает world/epoch/operation/sample, порядок наблюдений, revision, tick и наблюдаемое состояние. Итог: `VERIFIED_SUCCESS`, `VERIFIED_BLOCKED` или `UNVERIFIED`; `delivery_verified` — отдельный признак только для наблюдаемого `drop` в зоне доставки. Сенсор остаётся лабораторным, не криптографически аутентифицированным.

## 2. Первичные испытания

**Environment:** GitHub Actions Ubuntu x86_64, официальный Godot `4.7.2.stable.official.ed1daf0bf`, Python 3.12 / 3.13 / 3.14. Кодовый SHA `e3ec16b90f8dc839364aaf9a5187151f261d101b`; все четыре CI jobs завершились успешно.

| Проверка | Результат |
| --- | --- |
| Python E1.1–E1.3 contracts и proof tests | PASS; 27 tests E1.1/E1.2 + 5 новых E1.3 proof tests |
| Full Python regression | **2347 PASS** на Python 3.12, 3.13, 3.14 и в Godot-job |
| `scripts/check.sh` | PASS; 185 страниц, 1344 локальные ссылки на кодовом snapshot |
| `LifecycleWorldActionTest.gd` | `LIFECYCLE_E1_3_NATIVE_PASS` |
| `world_action_smoke` | `E1_3_LIVE_PASS` при seed 7 и 8; для каждого seed два свежих процесса |
| Свойства эффекта | По 16 операций на прогон, включая 1 законный `BLOCKED`; `drop` в зоне доставки имеет `delivery_verified=true` |
| Негативные границы | Stale revision, повтор operation ID, неизвестный tool, операторский `act`, spoofed/stale/неподтверждённый receipt — отказ или `UNVERIFIED` |
| Legacy P5/P6 и M2 | E1.2 native/live, P5/P6, P5-C replay 4/4 ×2, M2 3/3 — PASS |
| Общий итог | **`E1_3_LIVE_GATE_PASS`** |

Воспроизведение из чистого checkout, с отдельным лабораторным экземпляром и Godot 4.7.2:

```bash
GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
bash scripts/run_e13_live_gate.sh "$GODOT_BIN"
```

Команды запускают эксперимент без пользовательских данных и без настоящего LLM. Тестовая последовательность движений принадлежит **harness**, не агенту: успешная доставка здесь не доказывает самостоятельного планирования или извлечения карты из памяти.

## 3. Обнаруженная ошибка геометрии и её исправление

При первом реальном E1.3 проходе действие на верхних воротах `(6,2)` неожиданно дало `VERIFIED_BLOCKED`, несмотря на положительную статическую Python-проверку маршрута. Это показало ограничение прежнего E1.2 gate: алгоритм `reachable()` использовал JSON fixture, но не реальные `_walls`, созданные Godot. В `LifecycleWorld.gd` координаты проходов теперь явно нормализуются до целых чисел перед созданием стен, а `LifecycleWorldActionTest.gd` отдельно проверяет **оба открытых прохода** `(6,2)`, `(6,8)` и **закрытый** `(6,5)`. Новый end-to-end маршрут действительно пересекает верхние ворота. Прежние CI-провалы сохранены в истории, не названы PASS.

## 4. Остаточные ограничения и следующий E1.4

В E1.3 есть только процессный bounded **duplicate guard**: уже использованный `operation_id` повторно отвергается; лимит новых ID — 256, включая `BLOCKED`. Это **не** журнал операций и **не** idempotent replay. Повтор после потери ответа запрещён; прошлый эффект может быть `UNKNOWN`. `operation_status`, канонический payload digest, conflict/replay и сохранение ledger после restart **не реализованы**. Reset world не является восстановлением effects.

Следующий обязательный этап **E1.4**: bounded ledger, `WorldOperationStatus`, сверка payload при повторе, replay без нового эффекта, корректный `UNKNOWN`, защита capacity и reconciliation. Затем — отдельный `E1-min` gate и только после него E2 Core + Memory + stub.

**Релизная граница:** никакие исследования E1.3 не меняют опубликованный кодовый тег `v0.2.0-rc.1`; здесь нет новой автономности, production authority или гарантии exactly-once при сбое питания.
