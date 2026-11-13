# Virtual ANIMA Lab — локальный испытательный мир

**Статус:** отдельный полигон Godot 4.7.2; P5-A/B/C и переключение Normal/Debug проверены владельцем. **Godot не включает ANIMA Core внутрь своей программы:** Core подключается только через внешний P6-адаптер. Сквозной M2 (Memory + Core + живой Godot) — CI PASS, ноутбук владельца M2 пока не проверен. Сводные результаты P5-C — в [документации](../../docs/ROADMAP/Virtual_ANIMA_Lab_P5C_Scenario_Replay_Draft.md).

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

**Статус: реализован.** P6-порт повторно использован в M2 и успешно прошёл реальный Godot 4.7.2 CI-gate; локальная проверка полного M2 на ноутбуке владельца ещё открыта. Это отдельный модуль `labs/virtual_anima_lab/python/core_port.py` и композиционный запуск `run_core_demo.py`, **не** часть `anima/core/`. В ядре добавлена только узкая точка внедрения `DoorWorldPort`; по умолчанию продолжает работать прежний `VirtualDoorWorld`. Сам Core не импортирует Lab и не знает TCP-протокол.

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

**GitHub CI:** [M2 приёмка](../../docs/TESTING/Memory_v1_Integrated_External_VAL_M2_v0.md) — реальный Godot `4.7.2`, матрица Python 3.12–3.14 `1667 PASS` на каждом окружении. Ноутбук владельца требует отдельного запуска.

Из корня проекта с установленным Godot 4.7.2 (отдельное окно Godot предварительно **не** запускай):

```bash
GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
python -m labs.virtual_anima_lab.python.m2_integrated_gate \
  --godot "$GODOT_BIN" --report /tmp/anima-m2-PC.json
```

Runner сам создаёт/останавливает три headless-инстанса на временных loopback портах, использует только одноразовые данные и не затрагивает рабочую ANIMA. Не использовать этот тест с сетевым адресом, физическими исполнительными устройствами и приватными данными. Используется `os._exit`, **не** физическое отключение питания или реальный `SIGKILL`. Успех приёмки M2 не означает автономного планирования на основе памяти.
