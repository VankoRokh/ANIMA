# ANIMA Tool Model Benchmark v1

## Цель

Сравнить лёгкие локальные языковые/action-модели на одном воспроизводимом наборе
задач, близких к реальной работе FAST/tool layer ANIMA. Benchmark измеряет не
общую «умность» модели, а способность корректно использовать внешние подсистемы
Memory и Internal State при ограниченных ресурсах.

Первый baseline — `Qwen3-0.6B-Q8_0`. Следующие кандидаты запускаются тем же corpus
и теми же критериями; изменение сценариев после начала сравнения требует новой
версии benchmark.

## Что фиксировано

- 10 сценариев;
- одинаковые временные данные Memory/Internal State;
- одинаковые read-only tools: `memory_search`, `memory_get`, `state_read`;
- `temperature=0` для сравнительных прогонов;
- thinking выключен, если model/adapter позволяет это контролировать;
- одинаковые критерии проверки ответа и tool trace;
- обычный pytest не загружает реальные модели.

Benchmark не использует нормальный `ANIMA_DATA_DIR`: Memory и Internal State
создаются во временном каталоге на каждый прогон.

## Corpus

| ID | Уровень | Сценарий | Главная способность |
|---|---:|---|---|
| T01 | 1 | `17 × 6` | не вызывать tool без необходимости |
| T02 | 1 | текущее состояние ANIMA | простой `state_read()` без аргументов |
| T03 | 1 | чтение известного `mem_...` | `memory_get()` с готовым точным аргументом |
| T04 | 2 | предпочтение кофе | самостоятельно выбрать `memory_search` и сформировать query |
| T05 | 2 | отсутствующее имя собаки | поиск + отказ от галлюцинации |
| T06 | 2 | архитектурная роль LLM | смысловой поиск проектного решения |
| T07 | 3 | кофе + текущее состояние | два независимых tools в одном запросе |
| T08 | 3 | кофе или чай | retrieval → простое рассуждение |
| T09 | 3 | граница FAST/Memory | последовательность `memory_search → memory_get` |
| T10 | 3 | приоритет проекта + состояние | multi-source retrieval и синтез ответа |

Тестовые записи намеренно включают несколько близких проектных фактов. Собака в
Memory отсутствует; имя кота «Барсик» служит ловушкой для неверного переноса
факта или галлюцинации.

## Метрики качества

Каждый запуск сценария оценивается по независимым признакам:

- **Routing** — вызваны все необходимые tools, запрещённые не вызваны, а для T09
  соблюдён требуемый порядок;
- **Arguments** — аргументы имеют корректную форму и приводят к ожидаемым объектам
  Memory; точный ID должен передаваться без подмены;
- **Protocol** — model/adapter завершил ход без malformed function call или другой
  ошибки tool protocol;
- **Grounding** — итоговый текст содержит проверяемые данные, полученные из
  требуемого источника;
- **Safety** — отсутствующие данные не выдуманы, запрещённые факты не перенесены;
- **Pass** — все пять признаков успешны одновременно.

Итоговые rates считаются отдельно. Это позволяет отличить, например, правильный
выбор подсистемы от неправильной сериализации tool call.

## Метрики ресурсов и скорости

Runner фиксирует:

- размер файла модели на диске (`GGUF size MiB`), если передан `--model-file`;
- заявленное число параметров и quantization;
- wall-clock latency полного сценария, включая все model↔tool round trips;
- mean / median / p95 / min / max latency;
- RSS процесса `llama-server` перед benchmark;
- максимальный наблюдаемый RSS во время benchmark;
- Linux `VmHWM` процесса;
- NVIDIA VRAM процесса через `nvidia-smi`, если доступно.

Если PID не передан, runner пытается определить единственный процесс
`llama-server`. При неоднозначности memory/VRAM остаются `not measured`, а
результат качества всё равно валиден.

Tokens/s не является обязательной универсальной метрикой v1: разные adapters
могут не возвращать сопоставимые token timings. Для FAST главным общим показателем
скорости является latency полного рабочего сценария. Backend-specific token
throughput можно добавить отдельным полем без изменения corpus.

## Прогоны

Сначала выполняется smoke run — один проход 10 сценариев. Он проверяет integration
и chat/tool template конкретной модели:

```bash
PYTHONPATH=. .venv-qwen-agent/bin/python scripts/benchmark_tool_models.py \
  --base-url http://127.0.0.1:8080/v1 \
  --model Qwen3-0.6B-Q8_0 \
  --model-file /path/to/Qwen3-0.6B-Q8_0.gguf \
  --parameters-b 0.6 \
  --quantization Q8_0 \
  --repeats 1
```

После подтверждения корректной integration выполняется сравнительный прогон:

```bash
PYTHONPATH=. .venv-qwen-agent/bin/python scripts/benchmark_tool_models.py \
  --base-url http://127.0.0.1:8080/v1 \
  --model Qwen3-0.6B-Q8_0 \
  --model-file /path/to/Qwen3-0.6B-Q8_0.gguf \
  --parameters-b 0.6 \
  --quantization Q8_0 \
  --repeats 5
```

Если auto-detection не нашёл server process, добавить:

```bash
--server-pid "$(pgrep -n llama-server)"
```

## Артефакты

Результаты пишутся в локальный, игнорируемый Git каталог:

```text
.benchmarks/tool-models/
├── comparison.csv
├── comparison.md
└── <run-id>/
    ├── results.json
    ├── cases.csv
    └── report.md
```

- `results.json` — полный machine-readable evidence;
- `cases.csv` — одна строка на scenario/repeat;
- `report.md` — читаемый отчёт конкретного прогона;
- `comparison.csv` — накопительная таблица всех моделей;
- `comparison.md` — автоматически обновляемое представление таблицы.

`.benchmarks/` не коммитится. После завершения сравнения показательный результат,
который влияет на архитектурное решение, переносится в `docs/TESTING/Results/`
как TV report по правилам [Testing](README.md#показательные-отчёты). Нельзя
переносить в документацию непроверенные или восстановленные по памяти числа.

## Таблица сравнения

Локальная `comparison.md` содержит одинаковые колонки для всех кандидатов:

| Model | Params | Quant | Size | Pass | Routing | Args | Protocol | Grounding | Safety | Mean latency | P95 | Peak RSS | Peak VRAM |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen3-0.6B | — | — | — | — | — | — | — | — | — | — | — | — | — |
| Hammer 2.1 0.5B | — | — | — | — | — | — | — | — | — | — | — | — | — |
| xLAM-2-1B-fc-r | — | — | — | — | — | — | — | — | — | — | — | — | — |
| FunctionGemma 270M | — | — | — | — | — | — | — | — | — | — | — | — | — |
| Granite small | — | — | — | — | — | — | — | — | — | — | — | — | — |
| Arch-Agent / SmolLM candidate | — | — | — | — | — | — | — | — | — | — | — | — | — |

Победитель не определяется одним `Pass rate`. Для роли FAST отдельно оцениваются
качество, стабильность, latency и ресурсы; для отдельного action/router layer
может победить менее разговорная, но более надёжная и дешёвая модель.

## Проверка benchmark-кода

Benchmark logic имеет отдельные deterministic unit tests и не требует модели:

```bash
.venv/bin/python -m pytest -q tests/test_tool_model_benchmark.py
```

Перед сохранением representative evidence также выполняются обычные project
checks. Real-model benchmark остаётся opt-in experiment и не входит в regression
pytest suite.
