# ANIMA v0.2 — E2.4a: рабочая память наблюдений и их связей

**Статус:** **`PASS_LAB_ASSOCIATIVE_MEMORY`** — **частичная приёмка E2.4**: лабораторный поток эгоцентрических Raw, подтверждение Core, производная ассоциативная память, ablation, ограниченный Context. **Не полная топологическая карта, не Cognitive Loop, не FAST и не долгосрочный релиз.**  
**Дата фиксации:** 23 ноября 2026 года.  
**Проверенный snapshot кода:** `114d936eab442619025e2fbad9067a3571670390`, ветка `work/v02-e24-observation-memory`.  
**Primary evidence:** [GitHub Actions #45245551015](https://github.com/VankoRokh/ANIMA/actions/runs/45245551015), **4/4 SUCCESS**, `anima-e24-memory-evidence` и логи, Godot 4.7.2, Python 3.12–3.14.  
**Основной замысел:** [Cognitive Initiative E2.3–E3](e2-cognitive-initiative-v02.md), [E2.3 sensor baseline](e2-3-perception-acceptance-v02.md).

## 1. Что именно реализовано

### Состав

- `labs/virtual_anima_lab/python/lifecycle/e24_working_memory.py`: лабораторная `E24WorkingMemory` поверх существующих `CoreAssembly/CoreIngress/CoreEventDispatcher`, без отдельного владельца Identity/Goal/Task/Execution.
- Источник `lab.sensor.anima.vision` зарегистрирован явно через `vision_source_registration()`, Core-правило `view_digest` — через `vision_digest_rule()`. Core получает **ссылку SHA-256**, а не весь Raw.
- Полный immutable `EgocentricView` JSON хранится в `e24_working_memory.db/e24_raw`; `e24_binding` фиксирует Core identity, зарегистрированный source/producer, world identity, epoch, monotonic sample_seq, revision и tick. **Raw + cursor сохраняются одной SQLite-транзакцией**.
- После сохранения Raw — `CoreIngress.admit` с детерминированным occurrence ID, Core `ALREADY_SEEN` при replay, связь `sample_id → Core event ID`, стандартный Core dispatcher/EventLog. Только после подтверждения `forwarded` материализуются наблюдения.
- Производные `e24_processed`, `e24_mentions`, `e24_co_seen`: записи объектов, наблюдавшиеся свойства (например owner), bearing/range только **в контексте конкретного взгляда**, ассоциации `co_observed` и их исходные Core event IDs.
- `world_model(memory_enabled=True/False)` извлекает сохранённые записи, перепроверив полноту/совпадение производных таблиц с **каждым каноническим Raw** и Core event/receipt; `raw_evidence(sample_id)` возвращает неизменённый sealed Raw.
- `context_for_cognition(focus_refs, max_entities, max_relations, memory_enabled)` возвращает **ограниченный** источникопроверяемый рабочий контекст, `truncated`, `unresolved_focus_refs`, `coverage_scope=captured_view_history_only`. **Он ещё не подключён к продуктовому ContextBuilder или FAST.**

### Семантические ограничения

- `current_observation=observed` — объект виден в **последнем** Raw.
- `current_observation=not_observed` — объект присутствует в исторической памяти, но **не был замечен в последнем взгляде**. Это **не** `absent` и не `unknown` как утверждение о самом объекте.
- `last_seen_view` содержит относительное положение **на момент старого наблюдения**; `current_relative_geometry_verified=false` для старой записи.
- `co_observed` — одновременное сенсорное восприятие, **не** доказательство проходимости, соседства комнат или общего глобального положения. `relative_frame=same_observer_view_not_global`.
- `observed_revisions` фиксирует различие наблюдаемых свойств, например `owner absent → known`, со ссылками на обе серии доказательств. **Это ещё не Knowledge revision, не истинное изменение физического объекта и не автоматическое подтверждение гипотезы.**
- Никаких готовых абсолютных координат Godot, глобального направления взгляда, изменения подтверждённого Knowledge или прямого мирового эффекта от модели.

## 2. Реальные результаты приёмки

| Gate | Результат |
| --- | --- |
| Python 3.12, 3.13, 3.14 — **полная** регрессия | **2452 PASS** на каждой версии, точный кодовый snapshot выше |
| E2.4 unit | **17 PASS**: memory-on/off, bounded context, observed owner revision, 4 crash cuts, forged Raw/Core/derived, epoch/source gate |
| Docs/syntax до добавления этого отчёта | **195 страниц / 1365 локальных ссылок**, Python syntax 430 файлов, Bash 10 файлов, **PASS** |
| Live Godot 4.7.2 | `E2_4_MEMORY_GATE_PASS` на **seed 7 и 8** |
| Эгоцентрические снимки и Core события | **3 исходных Raw + 3 Core pointer events / seed** |
| Эффект памяти | Ящик обнаружен при повороте и впоследствии `not_observed`; в `memory_enabled=True` есть ссылка на прошлое наблюдение, при `False` ящика в контексте нет |
| Возобновление памяти | Core reopened while Godot alive; точный Raw, ссылки, материализованные связи и EventLog сохранены, no duplicate effects |
| Злоупотребления | Изменение Raw JSON/hash, Core event ID, derived proof/mention/relation, чужая эпоха и неверный источник — отказ |
| Crash cuts | После Raw commit, Core admission, Core link и projection commit — восстановление без второго EventLog события |
| Защитные границы | Внешний lab harness совершает **ровно 2 поворота/seed**; `E24WorkingMemory` сама не выдаёт world effects; `CoreExecution/FAST` **не** используются |
| Регрессия E1.2–E2.3 | **PASS** внутри real Godot job |

### Что доказывает ablation — и чего не доказывает

Контроль использует **один и тот же поток Raw** и переключает только исторический доступ `memory_enabled`. Это доказывает, что `E24WorkingMemory` способна извлекать **предыдущий сенсорный опыт**, даже когда объект не виден прямо сейчас.

Однако это **не** две независимые долговременные биографии, **не** независимый поведенческий эксперимент и **не** сравнение качества планирования. Исполнитель поворотов — внешний тестовый harness, а не когнитивная система ANIMA. Следующий E2.5 должен измерять, меняет ли найденная память выбор действий.

## 3. Открытые ограничения

1. **E24-R1 HIGH / split durable Raw:** Core хранит `view_digest`, полный Raw и курсор — в отдельной лабораторной SQLite. Нет общей транзакции между этой БД и `core_state.db`, согласованного backup/restore или реального power-loss gate. Replay исследован на четырёх программных точках.
2. **E24-R2 / не полная топологическая карта:** граф `co_observed` и локальная относительная геометрия — только начальная **ассоциативная пространственная память**. Нет проверки визуальной локализации агента, сопоставления одинаковых комнат, пространственных переходов и замыкания петель. Это нельзя называть восстановленной картой местности.
3. **E24-R3 / отделена от production Memory:** Core event/Raw pointer прошли свои входные границы, но существующий `MemoryProcessor` **не** создаёт из этих данных эпизодические Memory, и `KnowledgeLayer` не подтверждает выводы. `E24WorkingMemory` — изолированный исследовательский адаптер/projection, а не новый канонический слой воспоминаний.
4. **E24-R4 / нет действий Core:** `world.turn/step` в Godot пока доступны только лабораторному executor с отдельным ключом; они не привязаны к типизированным Goal/Task/Stage6/Verification. Никаких скрытых прав FAST/DEEP.
5. **E24-R5 / нет исполняемого CognitiveCoordinator:** `context_for_cognition` валиден и bounded, но фактических когнитивных циклов, генерации гипотез и выбора действий с/без модели пока не было.
6. **E24-R6 / потолки и производительность:** `MAX_HISTORY=256`, `MAX_PENDING=64`, `world_model` перепроверяет ограниченный журнал и материализованные отношения целиком. Это сознательная цена строгой проверки в малой лаборатории; не доказан SLA непрерывного потока, мультиворкер или долговременная масштабируемость.
7. **E24-R7 / границы доверия:** guarded role keys — не изоляция ОС от same-UID кода. Sensor digest/source name не заменяют удостоверенный физический источник и не доказывают мир вне симуляции.

## 4. Решение и следующий шаг

**Принимаем только `PASS_LAB_ASSOCIATIVE_MEMORY` как E2.4a.** Правдоподобная история Raw, происхождение, материализованные отношения и различие «помню» / «вижу сейчас» проверены. Полный E2.4 нельзя закрывать до настоящей рабочей топологической модели или явного решения изменить критерий.

**E2.4b (следующая исследовательская часть):** привязать эгоцентрические наблюдения к подтверждённым относительным поворотам/шагам и сегментам пространства, проверить неоднозначные ориентиры и пересмотр связей. Главный фокус при этом не идеальная навигация, а способность Memory предоставлять причинно-полезную информацию.

**Параллельно:** разрешено приступить к minimal CognitiveCoordinator: bounded `CognitiveStepProposal → Core admission → verified Outcome → DecisionRecord`, с первым read-only шагом `lookup_raw_evidence` или `inspect_current_belief`. Сравнение deterministic/stub/реальная FAST — после минимального наблюдаемого цикла, **не** после совершенной навигации.

Независимый архитектурный аудит и release acceptance **ещё не выполнены**. Ветка и PR остаются экспериментальными, без merge в опубликованный релиз.

## 5. Повторение в изолированном лабораторном окружении

```bash
# На отдельном чистом checkout указанной ветки и официальном Godot 4.7.2:
GODOT_BIN=/path/to/Godot_v4.7.2-stable_linux.x86_64
python -m pytest -q -p no:cacheprovider tests/test_e24_working_memory.py
bash scripts/run_e24_live_gate.sh "$GODOT_BIN"
```

Реальные первичные логи и evidence artifact: [CI #45245551015](https://github.com/VankoRokh/ANIMA/actions/runs/45245551015). Каждая серия создаёт временный Core/World и не затрагивает личный профиль ANIMA.
