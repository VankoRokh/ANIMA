# Virtual ANIMA Lab — локальный испытательный мир

**Статус:** отдельный полигон Godot 4.7.2; P5-A/B/C и переключение Normal/Debug проверены владельцем. **Godot не включает ANIMA Core внутрь своей программы:** Core подключается только через внешний P6-адаптер. Сквозной M2 (Memory + Core + живой Godot) — CI PASS и owner-reported laptop PASS на Godot 4.7.2 / Python 3.14.4. Сводные результаты P5-C — в [документации](../../docs/ROADMAP/Virtual_ANIMA_Lab_P5C_Scenario_Replay_Draft.md).

## Возможности

- **Human** (синий) управляется клавиатурой WASD/стрелками; **E** меняет состояние двери, если персонаж рядом.
- **ANIMA** (зелёный) управляется только тестовым Python-контроллером.
- Три карты: `base`, `detour`, `clutter`. Стены, дверь, временные препятствия и шумовые события.
- **F3** переключает обычную панель и режим диагностики с World Truth, наблюдениями и журналом. Переключение не меняет мир.
- `val.bridge/0.1` — совместимость P5-A; `val.bridge/0.2` — типизированные наблюдения, условные действия, журнал и локальная защита от дубликатов.
- **Ограничение безопасности:** мост слушает `127.0.0.1`, а поле `role` не аутентифицировано. Не открывать порт в сеть, не подключать этот тестовый мост напрямую к Core и не считать receipt доказательством Goal.

## Установка и запуск

Нужен установленный Godot 4.7.2 (обычная Linux-сборка) и Python 3.12+.

**Ярлык Ubuntu:**

```bash
bash labs/virtual_anima_lab/install_desktop_launcher.sh
gtk-launch virtual-anima-lab
```

Обычный запуск — карта `base`, интерфейс Normal; контекстное меню ярлыка предлагает Detour, Clutter и Debug. Порт `46019` может занять только один экземпляр.

**Из терминала:**

```bash
GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
"$GODOT_BIN" --path labs/virtual_anima_lab/godot -- \
  --lab-port 46019 --lab-seed 7 --lab-scenario detour --lab-ui normal
```

**Контроллер ANIMA** (отдельный терминал из корня репозитория):

```bash
.venv/bin/python labs/virtual_anima_lab/python/controller.py \
  --port 46019 --typed --auto --steps 24
```

Открой окно Godot для ввода Human. В режиме `clutter` некоторые команды скрипта могут упираться в стены — это ожидаемый результат.

## Диагностика окна LifecycleWorld (E2.x visual)

На E1.2–E2.5a обычный `LifecycleWorld.tscn` отображает дизайнерскую геометрию и минимальный status; сам по себе **он не запускает Core, Memory, CognitiveCoordinator или FAST**.

Опциональная диагностическая панель оператора — отдельная **визуальная** надстройка, а **не** часть наблюдений агента. Из корня репозитория:

```bash
# Проверь, что другой LifecycleWorld на порту 46029 закрыт.
bash scripts/run_visual_lab_debug.sh
# Другая конфигурация стенда:
ANIMA_LAB_PORT=46030 ANIMA_LAB_SEED=8 bash scripts/run_visual_lab_debug.sh
```

Для нестандартного расположения движка укажи `GODOT_BIN=/путь/к/Godot_v4.7.2-stable_linux.x86_64`.

Флаг `--lifecycle-debug-ui` включён скриптом и действует **только на human/operator UI**:

| Раздел окна | Что означает |
| --- | --- |
| `WORLD TRUTH (operator only)` | Текущая позиция ANIMA, направление, позиция ящика и состояние мира из Godot **для человека**, не для ANIMA |
| `cyan: sensor preview` | Показанная цветом **расчётная** зона наблюдения. В legacy E1.2 это радиус 3, в защищённом `--lifecycle-egocentric` — сектор 90° с окклюзией. Preview **не** создаёт Raw и **не** увеличивает `sample_seq` |
| `AGENT SENSOR (recorded only)` | **Только последние реальные** `observe` / `observe_view` данные, если отдельный клиент действительно запросил наблюдение |
| `CORE / MEMORY / COGNITION` | `Telemetry: NOT CONNECTED` — в сцене **нет** собственного канала телеметрии Core, не рисовать фиктивные решения |
| `RECENT WORLD EVENTS` | Три последних события Godot (reset, action, изменение препятствия). **Не** журналы мыслей ANIMA |

**Важно:** `WORLD TRUTH` и цветная подсветка доступны только человеку, не передаются через `observe_view` и не должны попадать в Context FAST/DEEP. Для компьютерного зрения по скриншоту в будущем этот overlay **нужно отключать**, иначе возникнет утечка истинного состояния мира. Для текущих E2.3+ испытаний агент получает только типизированные данные по отдельному observer credential.

Визуальный интерфейс с живым списком `DecisionRecord`, предложениями FAST, состоянием Goal/Task, pause/step и изменением памяти **ещё не реализован**. Его источником должен стать отдельный проверенный канал телеметрии Python/Core с явной маркировкой `observation / hypothesis / confirmed`, а не данные панели Godot.

## E2.5b Visual Decision Runner — настоящий STEP/RUN эксперимент

**Не запускай обычный `LifecycleWorld.tscn` вручную для этого этапа:** без Python-контура он по-прежнему будет только статической комнатой. Новый Runner поднимает Godot GUI, disposable CoreAssembly, E2.4a Raw/Memory, E2.4b viewpoint-trail, отдельный read-only канал телеметрии и аутентифицированные кнопки управления в одном запуске:

```bash
cd ~/Projects/ANIMA
git fetch origin work/v02-visual-decision-runner
git worktree add --detach ../ANIMA-visual-decisions origin/work/v02-visual-decision-runner
cd ~/Projects/ANIMA-visual-decisions
bash scripts/run_visual_decision_lab.sh

# Другая воспроизводимая сцена:
bash scripts/run_visual_decision_lab.sh --seed 8 --step-interval 2

# Если нужен интерпретатор из существующего venv:
PYTHON_BIN=~/Projects/ANIMA/.venv/bin/python bash scripts/run_visual_decision_lab.sh
```

Закрой прежние окна LifecycleWorld перед запуском. `GODOT_BIN` указывает на локальный Godot 4.7.2 (по умолчанию `~/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64`). После `ANIMA_VISUAL_RUNNER_READY` используй кнопки в правой нижней части окна:

| Кнопка | Фактическое поведение |
| --- | --- |
| **STEP** | Один полный проход: новое агентское наблюдение (если нужно), выбор действия детерминированной политикой, durable lab admission, Godot effect, readback и новый Core-backed Raw |
| **RUN** | Повторение ограниченных STEP с задержкой до выполнения экспериментальной цели или лимита |
| **PAUSE** | Запрет следующего шага; уже исполняемый шаг закончит атомарный переход и сохранит его исход |
| **TOGGLE MEMORY** | Включает/выключает исторический доступ для **следующего** решения; не изменяет Raw и не двигает объект |

Первая задача намеренно простая: **увидеть ящик, затем выполнить один подтверждённый шаг в его направлении**. На seed 7 после STEP ANIMA должна повернуться к ящику, после RUN/следующего STEP сделать forward step и остановиться с `COMPLETED_LAB_CONDITION`. Чтобы начать новый сеанс, закрой Godot и снова выполни команду запуска. Текущий `STEP` не даёт полностью остановленного/возобновлённого «мышления»: он выполняет один ограниченный action cycle.

На операторской панели содержится **состояние мира для человека**, ниже — живой **Core-backed агентский сенсор**, рабочая память, `last_choice/reason`, лабораторный допуск, verified result и последние записи trace. Истинные координаты Godot через телеметрию Runner в ANIMA не передаются. Синий preview и операторская карта никогда не считаются агентским Raw.

**Правило честной интерпретации:** `mode=DETERMINISTIC`, `FAST/DEEP: NOT CONNECTED`, `action_admission=LAB_ONLY_NOT_STAGE6`. Это не production Core Goal/Task/Execution и не «интеллектуальное поведение LLM». В данном этапе реальный Core фиксирует сенсорные события и их доказательства, но решения и допуск мировых действий реализованы отдельной лабораторной политикой. Независимая верификация физических целей и полноценный crash recovery впереди.

**Логи:** Python печатает путь временной директории `/tmp/anima-visual-runner-...`, где остаются `core/core_state.db`, `e24_working_memory.db`, `visual_decisions` и `godot-visual.log`. Профиль ANIMA в домашнем каталоге не изменяется.

**CI:** `bash scripts/run_visual_decision_gate.sh "$GODOT_BIN"` (headless Godot + реальный Core + API STEP/RUN + регрессия E1.2–E2.5a). Формальная приёмка/ограничения: [E2.5b research report](../../docs/RESEARCH/e2-5b-visual-decision-lab-acceptance-v02.md).

## E2.5c-M — визуальные эксперименты с памятью и устаревшими сведениями

В этой ветке Visual Decision Runner поддерживает два дополнительных исследовательских сценария. Они требуют **нового процесса Godot и нового временного Core на каждый запуск**; не нужно переписывать или очищать уже существующие данные:

```bash
# Доверенный harness сначала позволяет ANIMA увидеть предмет, затем отворачивает её.
# Дальнейшие действия выбирает детерминированный агент по текущим наблюдениям.
bash scripts/run_visual_decision_lab.sh --scenario familiar --memory on --seed 7
bash scripts/run_visual_decision_lab.sh --scenario familiar --memory off --seed 7

# Вторая ситуация: предмет незаметно перемещён только operator fixture.
# ANIMA получает только очередное эгоцентрическое наблюдение.
bash scripts/run_visual_decision_lab.sh --scenario relocated --memory on --seed 7
bash scripts/run_visual_decision_lab.sh --scenario relocated --memory off --seed 7
```

**Нажимай RUN** после появления нового окна; для подробного разбора используй STEP. В панели теперь указаны `Trial`, `Memory`, причина каждого решения и `MEMORY HYPOTHESES (not Knowledge)`. Статус `SUSPECTED_STALE` означает лишь несоответствие предполагаемого положения текущему обзору, а `REOBSERVED_AFTER_CONFLICT` — новое прямое наблюдение объекта. Это **не** автоматическое опровержение исходного воспоминания и не нативный Knowledge layer.

При фиксированном сценарии и seed итоговое число **оцениваемых** policy actions:
- FAMILIAR: память ON — 2, OFF — 4.
- RELOCATED: память ON — 4 (с пересмотром гипотезы), OFF — 2.

Внешние подготовительные повороты не входят в метрику. Новая operator-команда `relocate_item` доступна только при отдельном флаге `--lifecycle-e25c-fixtures`, который автоматически включается **только** для RELOCATED. Она не доступна observer/executor и не отдаёт свои координаты через agent Raw, Context или UI telemetry.

Для полного автоматического Godot+Python воспроизведения: `bash scripts/run_e25c_memory_gate.sh "$GODOT_BIN"`. Отчёт: [E2.5c-M](../../docs/RESEARCH/e2-5c-memory-conflict-acceptance-v02.md).

**Границы:** нет FAST/DEEP; `LAB_ADMISSION` остаётся исследовательским, не Core Stage6; созданная вручную история — экспериментальная подготовка, а не самостоятельное исследование среды. Опыт может как помочь, так и направить неверно; это именно то, что проверяется.

## Проверки

Из корня репозитория при закрытом окне Lab:

```bash
bash scripts/check.sh
.venv/bin/python -m pytest -q

GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
"$GODOT_BIN" --headless --path labs/virtual_anima_lab/godot --script res://BridgeProtocolTest.gd
"$GODOT_BIN" --headless --path labs/virtual_anima_lab/godot --script res://BridgeV2ContractTest.gd
"$GODOT_BIN" --headless --path labs/virtual_anima_lab/godot --script res://BridgeP5CScenarioTest.gd
"$GODOT_BIN" --headless --path labs/virtual_anima_lab/godot --script res://BridgeUiModeTest.gd

.venv/bin/python labs/virtual_anima_lab/python/smoke.py --godot "$GODOT_BIN" --seed 7
.venv/bin/python labs/virtual_anima_lab/python/p5b_smoke.py --godot "$GODOT_BIN" --seed 7

report_dir="$(mktemp -d)"
.venv/bin/python labs/virtual_anima_lab/python/scenario_runner.py \
  --godot "$GODOT_BIN" --report-dir "$report_dir"
cat "$report_dir/summary.md"
```

Реальный replay P5-C: четыре сценария по два запуска и одинаковые трассы; проверенный код `e995169e61385a3e1c2e44a60b27e6bf501211e2`, общий Python-suite 1450/1450. Изменения после этого SHA требуют повторной проверки.

**Граница доказательства:** тесты подтверждают заданные последовательности команд, не произвольную интерактивную сессию, подлинность источника, распределённую exactly-once доставку, независимую проверку Core или устойчивость к реальному отключению питания.

Полные первые P5-A/B и P5-C протоколы доступны в [Git-истории](../../docs/ARCHIVE/Development_Snapshots.md); избыточные повторные описания в текущем README не поддерживаются.

## P6 — подключаемый адаптер Core ↔ VAL (эксперимент)

**Статус: реализован.** P6-порт повторно использован в M2 и успешно прошёл реальный Godot 4.7.2 CI-gate; локальная проверка полного M2 на ноутбуке владельца пройдена (отчёт 2026-11-13). Это отдельный модуль `labs/virtual_anima_lab/python/core_port.py` и композиционный запуск `run_core_demo.py`, **не** часть `anima/core/`. В ядре добавлена только узкая точка внедрения `DoorWorldPort`; по умолчанию продолжает работать прежний `VirtualDoorWorld`. Сам Core не импортирует Lab и не знает TCP-протокол.

**Первый сценарий:** `p6_door` ставит ANIMA рядом с **открытой дверью**. Внешне заданная Goal «Закрой дверь» проходит существующий Core Goal → Belief → Policy → Executor → отдельное наблюдение/Verification. Навигация и самостоятельная постановка целей здесь ещё не проверяются.

Сначала запусти Godot в отдельном терминале (из корня репозитория):

```bash
GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
"$GODOT_BIN" --path labs/virtual_anima_lab/godot -- \
  --lab-port 46019 --lab-seed 7 --lab-scenario p6_door --lab-ui debug
```

Затем в другом терминале, **с новым пустым каталогом данных**:

```bash
P6_DATA="$(mktemp -d)"
.venv/bin/python -m labs.virtual_anima_lab.python.run_core_demo \
  --port 46019 --data-dir "$P6_DATA"
```

При успехе будет `P6_CORE_VAL_DOOR_PASS`. Не используй производственный `ANIMA_DATA_DIR`: этот запуск намеренно ограничен тестовым экземпляром. Путь `P6_DATA` сохраняй для изучения журнала; после перезапуска Godot нужен **новый** каталог. Повтор операции никогда не выдаётся автоматически при неопределённом эффекте.

**Проверка до ручного запуска:**

```bash
.venv/bin/python -m pytest -q tests/test_p6_val_port.py
"$GODOT_BIN" --headless --path labs/virtual_anima_lab/godot --script res://BridgeP6DoorTest.gd
bash scripts/check.sh
.venv/bin/python -m pytest -q
```

**Ограничения доверия:** старый `val.bridge/0.2` по-прежнему использует самообъявленные роли на `127.0.0.1`; проверка формата, уникального ID процесса и epoch защищает от случайных ошибок, **но не аутентифицирует локальный процесс**. Нельзя открывать порт в сеть или использовать этот адаптер для реальных физических действий. В P6-адаптере запрещены `inspect`/`set_door` и другие операторские команды; для эффекта добавлена ограниченная команда агента `act_door`, доступная только у двери. При пропаже ключа из журнала Lab результат считается неизвестным и **не повторяется вслепую**. Результат `APPLIED` не завершает Goal: Core повторно читает независимый от receipt сенсорный путь.

**Приёмка:** все старые тесты P5-A/B/C и Core должны остаться зелёными, плюс отрицательные P6-кейсы. Результаты испытания с указанием SHA необходимо сохранить до объявления P6 завершённым.

## M2 — Core + историческая Memory + живой Godot + recovery

Это **интеграционная приёмка** с реальным Godot 4.7.2, а не запуск новой постоянно работающей ANIMA. Используется прежний P6 VALDoorPort (роль `agent`), настоящий Core EventLog/Memory/Event Retrieval/Context/FAST stub, операторская typed Goal и независимая сенсорная Verification. Проверены три режима: обычное закрытие двери; hard exit Core до эффекта; hard exit Core после эффекта, но до receipt. World остаётся одним и тем же процессом, Core восстанавливается в новом Python-процессе.

**GitHub CI:** [M2 приёмка](../../docs/TESTING/Memory_v1_Integrated_External_VAL_M2_v0.md) — реальный Godot `4.7.2`, матрица Python 3.12–3.14 `1667 PASS` на каждом окружении. Ноутбук владельца: M2 PASS по предоставленному JSON-отчёту; команда сохранена для воспроизведения.

Из корня проекта с установленным Godot 4.7.2 (отдельное окно Godot предварительно **не** запускай):

```bash
GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
python -m labs.virtual_anima_lab.python.m2_integrated_gate \
  --godot "$GODOT_BIN" --report /tmp/anima-m2-PC.json
```

Runner сам создаёт/останавливает три headless-инстанса на временных loopback портах, использует только одноразовые данные и не затрагивает рабочую ANIMA. Не использовать этот тест с сетевым адресом, физическими исполнительными устройствами и приватными данными. Используется `os._exit`, **не** физическое отключение питания или реальный `SIGKILL`. Успех приёмки M2 не означает автономного планирования на основе памяти.


## E1.2 — отдельный LifecycleWorld (эксперимент v0.2)

**Статус:** лабораторная сцена и тесты добавлены; Godot live-gate ещё не подтверждён. Не является заменой P5/P6 Main, не управляет Core и не выполняет действия от имени ANIMA.

```bash
GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"

# Из корня репозитория; все P5/P6 останутся на Main.tscn:
"$GODOT_BIN" --headless --path labs/virtual_anima_lab/godot --script res://LifecycleWorldTest.gd
python -m labs.virtual_anima_lab.python.lifecycle.world_smoke --godot "$GODOT_BIN" --seed 7

# Наглядная отдельная сцена (по умолчанию порт 46029):
"$GODOT_BIN" --path labs/virtual_anima_lab/godot res://LifecycleWorld.tscn -- \
  --lifecycle-port 46029 --lifecycle-seed 7
```

В **режиме E1.2** agent через `val.bridge/0.2` может только `hello` и `observe`. Текст маршрута, полная карта, инспекция и управление препятствиями агенту недоступны. Операторские fixture-команды существуют только для изолированного стенда и не аутентифицируют процесс. Более поздние E1.3/E1.4 эффекты и status доступны исключительно при явном opt-in.

Дизайн, геометрия и статус проверок: [E1.2](../../docs/RESEARCH/e1-lifecycle-world-v02.md).

## E1.3 — opt-in world.move/pick/drop и сенсорный proof

**Статус:** `Validated Lab / E1.3 PASS` на SHA `e3ec16b90f8dc839364aaf9a5187151f261d101b`. В GitHub Actions `45160793477` — 2347 Python PASS, Godot native/live на seed 7/8 ×2, старые P5/P6, M2. Это лаборатория: нет Core Goal/Task, памяти, FAST или самостоятельного планирования.

По умолчанию `LifecycleWorld` остаётся `observe`-only. Для явного включения трёх виртуальных действий:

```bash
GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
"$GODOT_BIN" --path labs/virtual_anima_lab/godot res://LifecycleWorld.tscn -- \
  --lifecycle-port 46029 --lifecycle-seed 7 --lifecycle-effects

# В отдельном чистом checkout: полные E1.2/P5/P6 и E1.3 native/live проверки
bash scripts/run_e13_live_gate.sh "$GODOT_BIN"
```

Блокирующий receipt не доказывает движение; `verify_world_effect` требует свежий `WorldObservation` и согласованные world/epoch/revision/operation/sample. `delivery_verified=true` относится только к реальному `drop` в наблюдаемой зоне доставки. Старые native/Godot тесты остаются неизменными; после обнаруженного расхождения координат новая нативная проверка дополнительно фиксирует реальную проходимость `(6,2)` и `(6,8)`.

**Граница режима E1.3:** без дополнительного `--lifecycle-ledger` повторный `operation_id` только отклоняется; `operation_status` и replay здесь не доступны. E1.4 вводит отдельный **in-process** ledger без долговременного восстановления. В обоих режимах `role` самообъявленная и не является аутентификацией; к физическим устройствам порт подключать нельзя.

Подробности, команды и доказательства: [E1.3](../../docs/RESEARCH/e1-world-effects-v02.md).

## E1.4 — opt-in operation ledger / idempotent replay

**Статус:** `Validated Lab / E1.4 PASS` на кодовом snapshot `c896ba9f3a1b610cfcddb8b58ac8a33299f71f1f`. В [CI](https://github.com/VankoRokh/ANIMA/actions/runs/45164124776): 2356 Python PASS на 3.12–3.14, Godot 4.7.2, E1.2/E1.3/P5/P6/M2 regressions PASS, native bounded ledger, live reconnect seed 7/8 ×2.

```bash
GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"

# Изолированный E1.4 мир; без флагов E1.2/E1.3 не получают ledger:
"$GODOT_BIN" --path labs/virtual_anima_lab/godot res://LifecycleWorld.tscn -- \
  --lifecycle-port 46029 --lifecycle-seed 7 \
  --lifecycle-effects --lifecycle-ledger

# Полная воспроизводимая лабораторная приёмка и архив логов:
bash scripts/run_e14_live_gate.sh "$GODOT_BIN"
```

Клиент использует typed `WorldAction` и `WorldOperationStatus`; status-запрос содержит **исходный полный action**. Повтор идентичного ID/payload возвращает исходный receipt с `replayed=true` без повторного эффекта. Другой payload даёт `OPERATION_CONFLICT`. Журнал ограничен **256 записями**; при переполнении новые действия отклоняются, но старые доступны. `UNKNOWN` **не разрешает повтор**. Даже `RECORDED` требует отдельного `WorldObservation` и проверки proof.

**Не реализовано:** запись ledger на диск или восстановление после перезапуска Godot, аутентификация локальных клиентов, автоматическое действие Core/FAST, долговременное хранение опыта. Полная E1-min приёмка и E2 отдельно.

Дизайн, негативные проверки и точные evidence: [E1.4](../../docs/RESEARCH/e1-operation-ledger-v02.md).
 
## E2.1 — Core-bound read-only gateway и guarded bearer mode

**Validated Lab / E2.1 PASS_LAB_APP_BOUNDARY** ([CI 45171807284](https://github.com/VankoRokh/ANIMA/actions/runs/45171807284), 2380 pytest PASS на Python 3.12–3.14 и Godot, E1-min regression PASS). Не release и не E2 full. Обычные E1.2–E1.4 опции сохранены, включая прежние self-declared роли. Новый opt-in `--lifecycle-guarded` использует **три разные** сильные ключевые строки (observer, executor, operator) из переменных окружения процесса Godot. Ключи *не* являются параметрами CLI или данными `hello`. `role=operator` без operator credential отвергается даже при прямом TCP-подключении. Ключ observer не разрешает `act` и `operation_status`, а executor не разрешает `observe`. Для теста ключи генерируются одноразово.

`labs/virtual_anima_lab/python/lifecycle/core_gateway.py` привязан к зарегистрированному `CoreAssembly` и создаёт только типизированные `WorldObservation`; он сохраняет `world_instance_id/epoch/sample_seq/revision/tick` в отдельной SQLite, отклоняет смену мира и откат часов. Он не является вторым исполнителем и не подключает FAST/Raw/Goal.

Воспроизводимый прогон (на чистой исследовательской копии):

```bash
GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
bash scripts/run_e21_live_gate.sh "$GODOT_BIN"
```

Runner повторяет E1.2–E1.4 и независимый E1-min, затем запускает guarded-Godot с закрытыми одноразовыми ключами при seed 7 и 8, проверяет отказ в старте без валидных ключей/ledger и имитирует отказ авторизации, перезапуск Core и перезапуск мира. **Ключ исполнителя в E2.1 не подключён к Stage6**; исполнять действия через новый gateway невозможно.

**Предупреждение:** bearer-ключи в environment/plaintext loopback и Python private fields не защищены от процесса с доступом к тому же UID, `/proc` или памяти. FAST и недоверенные плагины должны исполняться без raw TCP и доступа к ключам; гарантии такой OS-изоляции здесь нет. Оригинальный E1-min endpoint без guarded flag по-прежнему позволяет самообъявленную операторскую роль. Это разные профили, их нельзя смешивать.

[Подробный контракт и список проверок E2.1](../../docs/RESEARCH/e2-core-world-boundary-v02.md).

## E2.2 — атомарный Raw capture и Core provenance (lab only)

**Статус: `PASS_LAB_RAW_POINTER`**, [проверенный CI](https://github.com/VankoRokh/ANIMA/actions/runs/45175700030) — 2392 full pytest PASS на Python 3.12–3.14 и Godot 4.7.2, `E2_2_LIVE_GATE_PASS` на seed 7/8. **Релизный код ANIMA не изменён.**

`CoreBoundObservationGateway(..., capture_raw=True)` сохраняет весь immutable `WorldObservation` и SHA-256 в таблице `e22_raw_capture` *в той же SQLite-транзакции*, что и фиксацию sample-курсора. `E22RawCaptureService` восстанавливает ещё не переданные снимки, записывает Core event `snapshot_digest` через обычный `CoreIngress` и дожидается `CoreEventDispatcher` receipt. При повторе после аварии уже существующий `event_id` не дублируется.

```bash
GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
bash scripts/run_e22_live_gate.sh "$GODOT_BIN"
```

Гарантия **не** распространяется на потерю sidecar SQLite, power-loss, межхостовую аутентификацию или восстанавливаемую память самого Godot. Core EventLog хранит **ссылку с digest**, а не полный сенсорный JSON. Нет FAST, Goal/Task, WorldAction, Knowledge и самостоятельного цикла. [Подробный контракт](../../docs/RESEARCH/e2-raw-provenance-v02.md) · [Итоговый отчёт](../../docs/RESEARCH/e2-2-acceptance-report-v02.md).
