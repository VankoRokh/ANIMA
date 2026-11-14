# Проверки и наблюдение

## ANIMA v0.1 Integrated — M6-B2 source-isolated Godot execution

[Контракт M6-B2](Memory_v1_Integrated_Godot_Execution_M6B2_Design_v0.md): оригинальный M4 GoalStore и история M5 сохраняются; новая P6/Godot исполнительная цепочка использует отдельные target P2, P3-A, Task и Operation SQLite и собственное одноразовое host-разрешение. Код `labs/virtual_anima_lab/python/m6b2_godot_execution.py`, [offline tests](../../tests/test_memory_v1_godot_execution_gate.py), `labs/virtual_anima_lab/python/core_port.py` (проверка согласованных экземпляра/эпохи/ревизии). Нет P3-C или переноса старого M6-A допуска, нет изменений `anima/`. M6-B2.2 offline + full regression PASS на Python 3.12/3.13/3.14 (CI run `43598096331`, commit `8e003400532a81d52711d751c06a4e4a7d148e2c`); **это не real Godot acceptance**.

Новый live-runner `labs/virtual_anima_lab/python/m6b2_live_gate.py` — **отдельный незавершённый M6-B2.3 gate**. Он изолирует мир каждого сценария, проверяет реальный Godot 4.7.2, единичный эффект, отсутствие повторов и две точки `os._exit` между подготовкой операции и получением результата. В CI предусмотрен отдельный job `b2-godot-live` с официальным бинарником и проверкой контрольной суммы. Локально, из корня репозитория:

```bash
.venv/bin/python -m labs.virtual_anima_lab.python.m6b2_live_gate \\
  --godot "$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64" \\
  --report "/tmp/anima-m6b2-$(date +%s).json"
```

Режим `--case normal` выполняет только положительный сценарий. Мировые воздействия допускаются **только в созданных runner временных Godot-средах**, не в рабочем экземпляре ANIMA. До подтверждённого live PASS не считать M6-B2.3 закрытым. Не подтверждены: реальный SIGKILL/отказ питания, Pi, аутентификация оператора, глобальный production firewall или физический мир.

## ANIMA v0.1 Integrated — M6-B1 real Godot source migration preflight (no executor)

[M6-B1 contract](Memory_v1_Integrated_Godot_Migration_M6B1_v0.md): не переносим старые полномочия M5/M6-A на Godot автоматически. Вместо этого принимаем реальные P6/Godot наблюдения через `VALDoorPort` с исходными `source/producer/clock`, фиксируем `world_instance_id`, `epoch`, `world_revision`, `lab_sample` и их сравнение с исходной M5 lineage. Отдельное явное `APPROVE` в lab-host разрешает **только revalidation mapping**, не действие. Модуль `labs/virtual_anima_lab/python/m6b1_godot_migration.py`, live Godot gate `labs/virtual_anima_lab/python/m6b1_live_gate.py`, [negative tests](../../tests/test_memory_v1_godot_migration_gate.py). B1 не изменяет P2/Core и не создаёт исполнительного интерфейса, B2 — отдельный будущий gate на изоляцию P2 и разрешённый эффект.

## ANIMA v0.1 Integrated — M6-A single-use execution admission (same M5 source)

[M6-A-контракт](Memory_v1_Integrated_Execution_Admission_M6A_v0.md): отдельное host-разрешение на **одну** реальную операцию проверяется до сборки исполнительного Core и повторно в самом Tool handler. Данные исходных M4/M5 Goal/Memory/Belief/ActionSpec валидируются повторно; M6-токен потребляется атомарно до эффекта; отдельный Core sensor Proof подтверждает результат. Экспериментальная сборка без P3-C использует оригинальные `virtual_door` source/producer и `lab_tick` — **не** Godot. Код: `labs/virtual_anima_lab/python/m6_execution_admission.py`, отдельный [M6-runner](../../scripts/run_memory_v1_execution_gate.py), [отрицательные тесты](../../tests/test_memory_v1_execution_gate.py). Прямой `build_core` за пределами этого лабораторного пути остаётся обходом: production firewall не реализован. M6-B Godot потребует нового, явно проверенного контракта migration (`lab_tick`→`lab_sample`, `virtual_door`→`VALDoorPort`). Никаких изменений в production `anima/`.

## ANIMA v0.1 Integrated — M5 separate typed binding admission without executor

[M5-контракт](Memory_v1_Integrated_Binding_Admission_M5_v0.md): подтверждённый M4 Goal может получить **отдельную** типизированную привязку P3-A, только после новой явной host-decision по неизменяемому ActionSpec, registered P2 sensor Belief и exact-source fingerprint. В лабораторном Core **нет исполнительного модуля и P3-C**, поэтому binding не может вызвать Tool. Путь `labs/virtual_anima_lab/python/m5_binding_admission.py`, runner `scripts/run_memory_v1_binding_gate.py`; [отрицательные тесты](../../tests/test_memory_v1_binding_gate.py). Binding в сохранённом Core work DB **может стать исполнимым** при последующей другой сборке: M5 не даёт права переносить данные в конфигурацию с executor без нового допуска. `operator_ref` не аутентифицирует пользователя. Production `anima/` не меняется; Pi и Godot отложены.

## ANIMA v0.1 Integrated — M4 explicit approval and unbound Core Goal

[M4-контракт](Memory_v1_Integrated_Approval_M4_v0.md): только после source-backed `REVIEW_REQUIRED` и отдельного явного operator-test-host решения по неизменяемому fingerprint допускается создание ровно одной **непривязанной** Goal через существующий GoalStore. Журнал подтверждений изолирован от Core, резервирует Goal ID и start-transition ID для безопасного replay при обрыве между подтверждением и созданием. Лабораторный путь `labs/virtual_anima_lab/python/m4_approval_bridge.py`; runner `scripts/run_memory_v1_approval_gate.py`; [отрицательные тесты](../../tests/test_memory_v1_approval_gate.py). Host `operator_ref` **не подтверждает реальную личность**. Нет Task, Tool, Belief, Knowledge и автоматического Goal binding. No production `anima/` code or Stage 6 validator changes.

## ANIMA v0.1 Integrated — M3 review-only Goal proposal from historical Memory

[M3-контракт](Memory_v1_Integrated_Proposal_M3_v0.md): проверяемое по первичным Events историческое воспоминание может стать **только предложением для рассмотрения**, но не Goal/Task/Tool. Экспериментальная реализация изолирована в `labs/virtual_anima_lab/python/m3_goal_preview.py`, исполняемый gate `scripts/run_memory_v1_goal_proposal_gate.py`, [отрицательные тесты](../../tests/test_memory_v1_goal_proposal_gate.py). Frozen Stage 6 `ProposalValidator` не расширен; противоречивые свидетельства блокируют автоматический переход, неподтверждённые идентификаторы и ложные полномочия отклоняются. Никакого LLM/автономной постановки целей или нового Stage.

## ANIMA v0.1 Integrated — M2 Memory + live Godot VAL + Core recovery

[M2-контракт](Memory_v1_Integrated_External_VAL_M2_v0.md): реальная Godot 4.7.2 `p6_door` через существующий `VALDoorPort`, историческая Memory/Provenance, ограниченный FAST-context, Core Goal/Task/допущенный инструмент и независимое сенсорное подтверждение после перезапуска. `before`/`after` hard-exit перед receipt — отдельные отрицательные проверки, это не настоящие SIGKILL или сбой питания. M2 lab runner: `labs/virtual_anima_lab/python/m2_integrated_gate.py`, [offline tests](../../tests/test_m2_external_val_memory.py). Внешний порт только `127.0.0.1`; Pi отложен. M2 **не** даёт Memory полномочий на Goal/Tool.

## ANIMA v0.1 Integrated — M1 Core-owned typed decision acceptance

[Критерии M1](Memory_v1_Integrated_Decision_M1_v0.md): исторический Memory-контекст читается **до** сохранения текущего вопроса, но только как справочная информация для FAST. Исполняемый typed Goal по-прежнему создаёт и связывает исключительно тестовый оператор, а Core P3-B принимает действия лишь по зарегистрированному датчику и собственному Verification. Негативные случаи: ложный user report, недоступность сенсора и unbound Goal. Headless VirtualDoorWorld, не Godot. [M1 runner](../../scripts/run_memory_v1_integrated_decision_gate.py); [M1 tests](../../tests/test_memory_v1_integrated_decision_gate.py). CI PASS не означает завершение Stage 7, production Memory→Core planning или тесты Pi.

## ANIMA v0.1 Integrated — M0 read-path acceptance

[Критерии M0](Memory_v1_Integrated_Read_Path_M0_v0.md): первая сквозная проверка уже существующих Core Runtime → raw Event → Memory source links → Event Retrieval → Provenance/Context → детерминированный FAST, с **двумя отдельными Python-процессами** и обязательными отрицательными случаями. [Standalone runner](../../scripts/run_memory_v1_integrated_read_gate.py) и [регрессионные тесты](../../tests/test_memory_v1_integrated_read_gate.py). M0 не подтверждает автономный исполнительный контур, Stage 7 или работу на Pi до отдельных прогонов.

## E4 — завершающие SIGKILL/scale проверки перед интеграцией

[Изолированный контракт и воспроизводимый маршрут](Memory_E4_Crash_Scale_Exit_Gate_v0.md): [реальный SIGKILL в отдельном процессе](../../tests/test_memory_e4_process_kill.py) и [измерение 100/1000/10000 синтетических узлов](../../labs/exp009/e4_scale_probe.py). Результаты относятся только к E4 laboratory journal; **не** закрывают Memory v1.0, Core Integration, Pi performance или production-авторизацию. Статус каждой новой проверки уточняется после измеренного CI/локального запуска.

## E4 Source Authority Gate — изолированный допуск отзыва

[Зафиксированный контракт](Memory_E4_Source_Authority_Gate_v0.md) и [тесты](../../tests/test_memory_e4_source_authority_gate.py) проверяют привязку определения и его отзыва к синтетически допущенному принципалу с атомарным SQLite-решением. Настоящая аутентификация, внедрение в Core/Memory и автономный L2 **не подтверждены**.

## E4 исследование: полномочия отзыва и граф зависимостей

[Предварительно зафиксированный adversarial gate](Memory_E4_PostAlias_Authority_Graph_Gate_v0.md) отделяет подтверждение источника от синтаксической метки `source="user"`; [новые проверки](../../tests/test_memory_e4_postalias_authority_graph.py) характеризуют известную уязвимость лаборатории и независимо вычисляют ожидаемый набор графовых инвалидизаций. Это **не разрешение на production Memory или L2**.

Тест доказывает заранее выбранное свойство; эксперимент сравнивает гипотезы.
Число тестов и длительность текущего прогона вычисляет pytest. Они не копируются
в статус или Roadmap. Исторические измерения остаются в отдельных отчётах.

## Команды

Из корня проекта после [Setup](../OPERATIONS/README.md#установка):

```bash
bash scripts/check.sh
.venv/bin/python -m pytest -q
```

Check — быстрая проверка метаданных/генерируемых блоков, Markdown-ссылок/якорей,
достижимости, code/test references архитектуры, синтаксиса Python/VS Code JSON/Bash
и отсутствия отслеживаемых персональных данных. Он не заменяет pytest.
Pytest проверяет функции, Foundation/D1, CLI/headless и саму систему документации.
Harness создаёт данные в tmp_path; subprocess-тесты явно задают временный ANIMA_DATA_DIR.

## Stage 7 semantic conformance

Принятый pre-training/read-only semantic boundary проверяется отдельным
[Stage 7 Semantic Conformance v0](Stage7_Conformance_v0.md).

До model training порядок такой:

```text
accepted semantic boundary
→ owner-reviewed semantic root fixtures
→ deterministic evaluator
→ constrained renderer / grammar
→ vanilla model evaluation
→ measure semantic residual
→ only then LoRA/SFT decision
```

Для первого corpus нужно не меньше 30 root situations; целевой диапазон — 40–50.
Все deterministic-decidable reviewed cases должны проходить с backend model call
count = 0. Partial CONTENT/REVISION results, Evidence replay/dependence,
Unknown/Unbounded time, incomplete coverage, protocol failures и adversarial source
text проверяются отдельно. Shape validity не считается semantic accuracy.

Старые FAST/DEEP audit labels остаются historical regression evidence и не являются
новым untouched training/evaluation gold.

## Реальные локальные модели

Обычный pytest suite проверяет deterministic contracts и fake-LLM сценарии; real-model experiments в него не входят. Они запускаются opt-in через [LLM experiment runner](../../scripts/run_llm_planner_experiment.py) и требуют явно доступных локальных backend и model. Наличие модели или работающего сервера не предполагается; обычные проверки не запускают inference и не загружают модели.

Исторический [ANIMA Tool Model Benchmark v1](Tool_Model_Benchmark.md) сохраняет сравнение лёгких моделей на tool/function-calling bridge: фиксированные 10 сценариев, одинаковые временные Memory/Internal State fixtures, раздельные quality-метрики и измерения latency/ресурсов. Этот benchmark относится к исследовательскому pull/tool path и **не является текущим каноническим FAST contract**. Real-model прогоны benchmark остаются opt-in и не входят в regression pytest suite. Сравнительные прогоны выполнялись по зафиксированному [runtime-профилю ANIMA FAST CPU v1](Tool_Model_Runtime_Profile.md), чтобы параметры `llama-server` не менялись между кандидатами. Representative результаты серии сохранены в [таблице сравнения tool-моделей](Tool_Model_Comparison.md).

Representative saved evidence оформляется отдельным TV report с implementation snapshot, условиями, canonical scenario, измеренными результатами и границами доказанного. Пример — [TV-0042](Results/TV-0042.md): integration Passed отделён от model reliability. Временные captures не заменяют сохраняемый проектный отчёт; каждый диагностический запуск копировать не требуется.

Для production pipeline, закрытого в Stage 5, доступен отдельный [Benchmark v2](Stage5_Benchmark_v2.md):
восемь bounded scenarios на том же inventory моделей; Benchmark v1 сохраняется отдельно как исторический эксперимент другого интерфейса.
Завершённый one-pass прогон документирован там только как preliminary / exploratory
evidence архитектурной границы, не как официальный рейтинг, reliability estimate
или решение о preferred FAST backend. До выбора модели нужны repeated runs с
paraphrased/equivalent scenarios; проценты v1/v2 напрямую не сопоставимы.
Raw captures остаются локальными ignored experimental artifacts.

## Opt-in Stage 5 projected smoke

[Runner](../../scripts/run_stage5_smoke.py) проверяет production
`CognitivePipeline → complete_projected → llama.cpp`, отдельно от legacy FAST и
исторических Planner experiments. Обычный pytest не загружает модель и не делает
inference; [runner tests](../../tests/test_stage5_smoke.py) используют fake transport.

```bash
.venv/bin/python -m pytest -q tests/test_stage5_smoke.py
.venv/bin/python scripts/run_stage5_smoke.py
```

По умолчанию используются локальные Qwen3-0.6B-Q8_0 GGUF и llama-server из
`~/Projects/models/qwen3-0.6b/` и `~/Projects/llama.cpp/build/bin/`, endpoint
`http://127.0.0.1:8080`. Пути/endpoint, output и timeout можно задать через `--help`.
Thinking выключен, temperature=0, top-k=1, top-p=1, min-p=0, output limit=32 tokens,
call timeout=30 s, startup timeout=60 s. Неготовый сервер проверяется по readiness;
повторных model calls или output repair нет.

Runner переиспользует готовый сервер с нужной model identity. Если localhost
отклоняет соединение, runner запускает свой сервер по существующему CPU runtime
profile и останавливает только этот child process, включая failure paths. Чужой
сервер не завершается. Instance data создаются только во временном каталоге и
удаляются. Evidence JSON и лог собственного server сохраняются отдельно в
`.benchmarks/stage5-projected-smoke/<UTC timestamp>/` либо по `--output`.

Семь cases: exact arithmetic, missing fact, known infeasible action (zero calls),
один free-text semantic-delivery cognitive request с bounded Memory evidence, constrained action,
явно injected invalid candidate после real completion и controlled transport failure
до HTTP. Это integration smoke, не доказательство независимого memory recall или
model intelligence. Invalid-candidate injection сохраняет исходный real response
отдельно от подставленного backend result; он не выдаётся за ошибку самой модели.

Free-text case проверяет доставку уникального `COBALT47` в реальном projected
request и присутствие marker в raw model response и итоговом ответе при ровно
одном backend attempt / generation / completion, без retry и output repair.
Ответ `COBALT47.` допустим; ответы только `text`, `candidate` или `output_contract`
вместо task content не проходят. Запрос и fixture сохраняются без изменений.
`output_contract="text"` не гарантирует byte-exact форматирование unrestricted
text output. Такая гарантия потребовала бы будущего явного output contract или
constrained decoding и находится вне Stage 5 scope. Candidate-mode
validation остаётся точной: `CONTINUE.` не равен допустимому ID `CONTINUE`.

Evidence содержит model hash/server identity, параметры, projected view, role и
native prompts, raw response, final validation, attempt/completion counts и terminal
failure classification. Backend attempt, generation POST `/completion` и successful
backend completion — разные счётчики; `/apply-template` не считается generation.
В исправном live smoke три real generations; controlled failure даёт 1 backend
attempt / 0 generations / 0 completions. Любой failed case сохраняется и возвращает
nonzero exit status. Smoke сам по себе не определяет stage status; закрытие Stage 5
подтверждено отдельным acceptance report [TV-0043](Results/TV-0043.md).

## Наблюдать процесс

```bash
.venv/bin/python -m pytest -v -s tests/test_d1_validation.py
```

Показываются шаги wake → user_input → sleep, решения memory stored/skipped,
итоговая проверка эквивалентности CLI/headless и timings/CPU/peak RSS.
Остальные проверки удобно смотреть через `-v`; `-s` отключает захват stdout.
Данные trace/snapshot/metrics доступны через Runtime и harness; GUI/TUI —
представления над этим слоем и пока не обязательны. При росте параллельных
состояний потребность в визуальном интерфейсе оценивается отдельно.

## Performance baseline

Stage 1.12 использует отдельный runner, чтобы 100k-набор не входил в обычный
regression suite:

```bash
.venv/bin/python scripts/benchmark_stage1.py
```

По умолчанию каждый размер `1000`, `10000`, `100000` запускается в отдельном
subprocess. Это позволяет независимо измерить peak RSS. Runner фиксирует Event
append throughput, synthetic SQLite seed throughput, Memory create/update,
Entity/Knowledge lookup, FTS, 1-hop Relations, Retrieval, FAST/DEEP Context,
полный EventProcessing batch, CPU, RAM и размеры файлов.

Synthetic SQLite seed нужен только для воспроизводимого наполнения базы и явно
отделён от production `MemoryStore.create_memory()` latency. Результат сохраняется
в `.benchmarks/stage1-performance.json`; каталог локальный и не отслеживается Git.
Для проверки самого benchmark-контура в обычном pytest используется маленький
`tests/test_performance_baseline.py`, а не полный 1k/10k/100k прогон.

## Уровни и критерии

| Уровень | Что проверяет | Когда сохранять результат |
|---|---|---|
| Check | Целостность проекта и документации | Если обнаружена значимая проблема |
| Feature test | Новое поведение, отрицательные/граничные случаи | Первый показательный результат или регрессия |
| Stage validation | Целевое свойство этапа целиком | При закрытии Stage |
| Experiment | Гипотеза против baseline на одинаковых условиях | Если результат влияет на решение, включая Failed/Inconclusive |

До реализации этапа задаются Goal, Observable result, условия старта, Required
work, Test scenarios, Regression scope, Acceptance criteria и Evidence.
Критерии конкретных этапов — в [Roadmap](../ROADMAP/README.md), эксперименты —
в [Research](../ROADMAP/Research.md). Список функций не заменяет проверяемый
результат. Если свойство нельзя наблюдать, сначала создаётся наблюдаемость.

## Показательные отчёты

[Реестр результатов](Results/README.md) генерируется из метаданных `Results/TV-*.md`.
Обычные успешные прогоны остаются в терминале; копировать каждый запуск не нужно.
Сохраняются закрытие этапа, новый механизм, важный аварийный/граничный случай,
существенная регрессия/исправление и сравнение альтернатив.

Новая запись начинается с плоского YAML frontmatter. Значения задаются JSON-строками
в двойных кавычках; это поддерживаемое подмножество YAML без внешнего парсера:

```yaml
---
id: "TV-0004"
title: "Краткое название проверки"
date: "2026-10-24"
stage: "1"
result: "Passed"
snapshot: "полный SHA проверенного commit"
---
```

Имя файла совпадает с id. Допустимы Passed/Failed/Inconclusive; snapshot — commit
или явно `not-recorded` для перенесённого старого результата. После метаданных
нужны разделы «Цель», «Условия», «Сценарий и входные данные», «Ожидаемый результат»,
«Фактический результат», «Метрики», «Доказано», «Не доказано».
Задать команды воспроизведения и связи со Stage/ADR; метрики без измерений
отмечать как отсутствующие. При эксперименте дополнительно фиксируются baseline,
метод и метрики до запуска. Проверка целостности архива не заменяет проверку restore.

После добавления выполнить `python3 scripts/update_docs.py` и Check.
Нельзя дописывать отсутствующий commit, лог или результат по догадке.
