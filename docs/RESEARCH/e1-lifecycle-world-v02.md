# ANIMA v0.2 — E1.2: первый двухкомнатный мир

**Статус:** `Validated Lab / E1.2 PASS` на проверенном кодовом SHA `811699dbaa9952fcb613794fb79dfa9b03e6459d` (23 ноября 2026 года, GitHub Actions). **Это не E1-min PASS и не E2.**  
**База:** `1364e62634669ef553df0b2f2d7a1159d404383f`.  
**Ветка:** `work/v02-e1-lifecycle-world-contracts`.  
**Программа:** [Continuous Lifecycle](continuous-lifecycle-v02.md); [DTO E1.1](e1-world-contracts-v02.md).  
**Архитектурные решения:** D0.1–D0.4 сохранены.

## Цель

Создать в Godot отдельную экспериментальную среду с двумя помещениями, одним переносимым предметом, зоной доставки, перекрытым прямым проходом и **двумя свободными обходами**. Мир содержит препятствия и локальную сенсорику, но не выдаёт ANIMA готовую карту, последовательность действий или скрытое состояние.

## Файлы

- `labs/virtual_anima_lab/godot/LifecycleScenario.json` — единая геометрия для Godot и независимого тестового оракула.
- `labs/virtual_anima_lab/godot/LifecycleWorld.gd` / `LifecycleWorld.tscn` — изолированный мир, сетевой read-only agent port и отрисовка.
- `labs/virtual_anima_lab/godot/LifecycleWorldTest.gd` — нативные проверки видимости, reset, прав и операторских изменений.
- `labs/virtual_anima_lab/python/lifecycle/scenarios.py` — **только harness**: независимая проверка достижимости обоих обходов (полная карта сюда доступна).
- `labs/virtual_anima_lab/python/lifecycle/world_smoke.py` — два живых Godot-прогона на одном seed с контрактной проверкой наблюдений.
- `tests/test_lifecycle_scenario.py` — проверки fixture, достижимости и отрицательные варианты.

Существующий `Main.gd` / `Main.tscn` и P5/P6 API **не изменялись**. Новый мир запускается явным указанием `res://LifecycleWorld.tscn`, а не подменой главной сцены. TCP bridge локальный (`127.0.0.1`), самообъявленные роли **не аутентифицируют** процессы.

## Геометрия и свобода выбора

Поля 14×11. Вертикальная перегородка `x=6` оставляет переходы на `y=2` и `y=8`. Центральный `(6,5)` заблокирован. ANIMA начинает в `(3,5)`, предмет находится в `(4,5)`, зона доставки — `(10,5)`. Один дополнительный obstacle выбирается детерминированно по `seed`; он не закрывает оба маршрута.

**Пути не кодируются в политике агента.** Алгоритм `reachable()` используется исключительно тестами геометрии; он не подключён к CognitivePipeline и не передаёт маршрут FAST/stub.

## Наблюдения и полномочия

- `agent.observe` возвращает `anima.lifecycle.world_observation/0.1` и проверяется E1.1 `WorldObservation`.
- Поле зрения — радиус 3 и трассировка промежуточных клеток; соседняя комната за перегородкой не раскрывается из-за геометрической близости.
- `agent.hello` сообщает версию мира и доступное `observe`, без seed или полной геометрии.
- `agent.inspect`, `agent.act`, `agent.set_obstacle` — `FORBIDDEN`.
- Только лабораторный `operator.inspect` видит всю геометрию; `operator.set_obstacle` создаёт внешнее изменение с новой world revision.
- `reset` сохраняет `world_instance_id` процесса, увеличивает `epoch` и восстанавливает seed-сцену; sample/event sequence в процессе не откатываются.

**В E1.2 нет агентских world effects, изменения владения предметом, расхода энергии и independent proof.** Это будущие E1.3–E1.5. Идентификаторы не доказывают подлинность внешнего процесса: это лабораторный интерфейс.

## Проверка

Проверка записанной геометрии отдельным статическим оракулом: **9 seed (0,1,2,3,7,8,13,31,100), оба обхода доступны; центральный блокирован**. Статический оракул сам по себе не доказывает работоспособность Godot или когнитивное поведение; отдельные нативные испытания ниже выполнены на Godot **4.7.2**.

Из корня репозитория:

```bash
python -m pytest -q tests/test_lifecycle_world_contracts.py tests/test_lifecycle_scenario.py

GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
"$GODOT_BIN" --headless --path labs/virtual_anima_lab/godot --script res://LifecycleWorldTest.gd

python -m labs.virtual_anima_lab.python.lifecycle.world_smoke \
  --godot "$GODOT_BIN" --seed 7
```

Для наблюдения за миром визуально (закрой обычное окно VAL либо выбери другой порт):

```bash
"$GODOT_BIN" --path labs/virtual_anima_lab/godot res://LifecycleWorld.tscn -- \
  --lifecycle-port 46029 --lifecycle-seed 7
```

## Результат независимого live-gate — 23 ноября 2026

**Кодовый snapshot:** `811699dbaa9952fcb613794fb79dfa9b03e6459d`; ветка `work/v02-e12-live-validation`. Проверены исходные файлы E1.2 и добавленный проверочный runner/CI; релизный тег `v0.2.0-rc.1` не изменён.

**Первичный источник:** [GitHub Actions run 45157427336](https://github.com/VankoRokh/ANIMA/actions/runs/45157427336); прикреплён артефакт `anima-e12-godot-4-7-2-live` с исходными логами и JSON. Испытание: Ubuntu x86_64, официальный Godot `4.7.2.stable.official.ed1daf0bf`, Python 3.12.16 / 3.13.18 / 3.14.10.

| Gate | Фактический результат |
| --- | --- |
| E1.1 DTO и E1.2 scenario tests | 27 PASS на каждой из трёх версий Python |
| Full pytest | 2342 PASS на каждой из Python 3.12, 3.13 и 3.14; 2342 PASS также в live job |
| `scripts/check.sh` | PASS; 185 страниц, 1344 локальные ссылки |
| `LifecycleWorldTest.gd` | `LIFECYCLE_E1_2_NATIVE_PASS` |
| `world_smoke` | `E1_2_LIVE_PASS` для seed 7 и 8, каждый seed — 2 свежих Godot-процесса |
| P5-A / P5-B / P5-C / UI / P6 native | PASS, без изменений существующего Main |
| P5-C scenario replay | 4/4 сценария, по два запуска |
| M2 Core/VAL + recovery | 3/3 `M2_CASE_PASS`, `M2_INTEGRATED_GODOT_PASS` |
| Общий нативный итог | **`E1_2_LIVE_GATE_PASS`** |

Ранние служебные CI-прогоны сбоили из-за неверного расположения GitHub expression и генерации неотслеживаемого Godot cache **до** clean-tree релизных тестов. Это ошибки оркестрации проверки: на окончательном snapshot полная регрессия выполняется до импорта Godot, затем запускаются нативные тесты. История прежних failed/cancelled runs остаётся в GitHub Actions и не подменяется PASS.

**Граница принятия:** подтверждён наблюдательный `LifecycleWorld`, локальная видимость, seeded reset и сохранение старых интеграций в лабораторных сценариях. Агент не исполняет `world.move/pick/drop`; receipt, independent readback/proof, operation ledger и Core continuity здесь не проверялись. Следующие обязательные работы — **E1.3/E1.4**, после них отдельный E1-min gate. Никаких новых функций в release v0.2 этот результат не добавляет.

