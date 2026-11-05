# Virtual ANIMA Lab — локальный испытательный мир

**Статус:** отдельный полигон Godot 4.7.2; P5-A/B/C и переключение Normal/Debug проверены владельцем. **ANIMA Core не подключён.** Сводные результаты и ограничения — в [документации](../../docs/ROADMAP/Virtual_ANIMA_Lab_P5C_Scenario_Replay_Draft.md).

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
