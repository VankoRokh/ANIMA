# Проверки и наблюдение

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

## Реальные локальные модели

Обычный pytest suite проверяет deterministic contracts и fake-LLM сценарии; real-model experiments в него не входят. Они запускаются opt-in через [LLM experiment runner](../../scripts/run_llm_planner_experiment.py) и требуют явно доступных локальных backend и model. Наличие модели или работающего сервера не предполагается; обычные проверки не запускают inference и не загружают модели.

Для сравнения лёгких локальных моделей с tool/function calling используется отдельный [ANIMA Tool Model Benchmark v1](Tool_Model_Benchmark.md): фиксированные 10 рабочих сценариев, одинаковые временные Memory/Internal State fixtures, раздельные quality-метрики и измерения latency/ресурсов. Real-model прогоны benchmark остаются opt-in и не входят в regression pytest suite. Сравнительные прогоны выполняются по зафиксированному [runtime-профилю ANIMA FAST CPU v1](Tool_Model_Runtime_Profile.md), чтобы параметры `llama-server` не менялись между кандидатами. Representative результаты серии сводятся в [таблицу сравнения tool-моделей](Tool_Model_Comparison.md).

Representative saved evidence оформляется отдельным TV report с implementation snapshot, условиями, canonical scenario, измеренными результатами и границами доказанного. Пример — [TV-0042](Results/TV-0042.md): integration Passed отделён от model reliability. Временные captures не заменяют сохраняемый проектный отчёт; каждый диагностический запуск копировать не требуется.

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
в [Research](../ROADMAP/Research.md#exp-001). Список функций не заменяет проверяемый
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