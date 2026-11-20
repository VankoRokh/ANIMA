# ANIMA v0.2 — E1.2: первый двухкомнатный мир

**Статус:** `Implemented / Lab-only / PARTIAL`. **Native/Live Godot: `NOT_TESTED`** в текущем окружении. Это не E1-min PASS и не E2.  
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

Проверка записанной геометрии отдельным статическим оракулом: **9 seed (0,1,2,3,7,8,13,31,100), оба обхода доступны; центральный блокирован**. Это не эквивалент запуска Godot, не приёмка E1.2 и не тест когнитивного поведения. Нативные проверки ниже необходимо запустить на Godot **4.7.2**.

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

Перед объявлением **E1.2 PASS** требуются результаты `LifecycleWorldTest.gd` и `world_smoke` на реальном Godot 4.7.2, проектная регрессия прежних P5/P6 и зафиксированные SHA/окружение. До этого — `PARTIAL / NOT_TESTED`, без автоматического перехода к E1.3.
