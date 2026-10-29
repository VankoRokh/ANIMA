# ANIMA Tool Model Benchmark v1

## Цель

Сравнить лёгкие локальные языковые/action-модели на одном воспроизводимом наборе
задач, близких к реальной работе FAST/tool layer ANIMA. Benchmark измеряет не
общую «умность» модели, а способность корректно использовать внешние подсистемы
Memory и Internal State при ограниченных ресурсах.

Первый baseline — `Qwen3-0.6B-Q8_0`. Следующие кандидаты запускаются тем же corpus
и теми же критериями. До первого baseline v1 считается pre-baseline: найденные
дефекты измерителя исправляются без создания ложной исторической совместимости.

## Что фиксировано

- 10 сценариев;
- одинаковые временные данные Memory;
- отдельная benchmark-owned конфигурация Internal State с фиксированными baseline;
- одинаковые read-only tools: `memory_search`, `memory_get`, `state_read`;
- `temperature=0` для сравнительных прогонов;
- thinking выключен, если model/adapter позволяет это контролировать;
- одинаковые критерии tool trace и машинно-проверяемого результата;
- обычный pytest не загружает реальные модели.

Benchmark не использует нормальный `ANIMA_DATA_DIR`: Memory, Internal State и
его конфигурация создаются во временном каталоге на каждый прогон. Конфигурация
Internal State и её SHA-256 сохраняются в `results.json`.

## Формат финального ответа

Keyword-matching свободного текста не используется как основной Grounding
критерий. Каждый сценарий требует последнюю строку:

```text
CONTROL: {"field": value}
```

Это валидный JSON-объект с ровно теми полями, которые определены сценарием.
`CONTROL` является машинно-проверяемым утверждением модели о результате.
Повторяющиеся ключи, в том числе во вложенных объектах, и NaN/Infinity
не допускаются. Числа, не представимые для сравнения, не совпадают с эталоном.

Для T01–T07 и T09 свободный текст либо запрещён, либо строго задан сценарием.
Это исключает ситуацию, когда корректное слово присутствует в содержательно
неверном утверждении. T08 требует точный body `Выбор: Эспрессо.` и CONTROL с
`{"choice":"эспрессо","basis":"memory_preference","remembered_preference":"эспрессо"}`.
T10 использует фиксированную строку рекомендации. Полный raw response полученного
завершённого turn сохраняется для качественного анализа Codex/человеком, в том
числе при ошибке evaluator.

## Corpus

| ID | Уровень | Сценарий | Главная способность |
|---|---:|---|---|
| T01 | 1 | `17 × 6` | не вызывать tool без необходимости |
| T02 | 1 | текущее состояние ANIMA | простой `state_read()` без аргументов |
| T03 | 1 | чтение известного `mem_...` | `memory_get()` с готовым точным аргументом |
| T04 | 2 | предпочтение кофе | самостоятельно выбрать `memory_search` и сформировать query |
| T05 | 2 | отсутствующее имя собаки | поиск + корректное `null`, без галлюцинации |
| T06 | 2 | архитектурная роль LLM | смысловой поиск проектного решения |
| T07 | 3 | кофе + текущее состояние | два независимых tools в одном запросе |
| T08 | 3 | кофе или чай | retrieval → простое рассуждение |
| T09 | 3 | граница FAST/Memory | реальная последовательность `search → следующий round → get` |
| T10 | 3 | приоритет проекта + состояние | multi-source retrieval и синтез ответа |

Тестовые записи намеренно включают несколько близких проектных фактов. Собака в
Memory отсутствует; имя кота «Барсик» остаётся distractor, но Safety проверяется
не по запрещённому слову, а по `dog_name: null` и безопасному контракту ответа.

## Метрики качества

Каждый завершённый сценарий оценивается по независимым признакам:

- **Routing** — вызваны все необходимые tools, запрещённые не вызваны; для T09
  `memory_get` обязан находиться в более позднем tool-round, чем `memory_search`,
  который реально вернул читаемый ID;
- **Arguments** — аргументы имеют корректную форму, поиск возвращает ожидаемые
  объекты, exact ID передаётся без подмены;
- **Protocol** — model/adapter завершил function-calling protocol;
- **Grounding** — `CONTROL` валиден, содержит ровно ожидаемые поля и значения,
  а body соответствует контракту сценария;
- **Safety** — для сценариев с отсутствующими данными отдельный safety-contract
  подтверждает отсутствие выдуманного значения;
- **Pass** — все применимые признаки успешны одновременно.

Инфраструктурная ошибка не превращает все способности модели в `False`.
Каждый run имеет отдельный статус:

```text
PASS
FAIL
ERROR
```

`FAIL` означает наблюдаемую ошибку поведения модели или model protocol.
`ERROR` означает инфраструктурный сбой, например недоступный backend. Для
`ERROR` непроверенные capability metrics имеют `null/N/A` и не входят в
знаменатель quality rates.

Если abnormal termination произошёл после успешно выполненного tool, runner
сохраняет partial executed-tool trace в evidence. Для partial trace round index
не используется как доказательство порядка: зависимость T09 оценивается только
на полностью завершённом `BenchmarkTurn`.

## Метрики ресурсов и скорости

Runner фиксирует:

- размер файла модели на диске (`GGUF size MiB`), если передан `--model-file`;
- заявленное число параметров и quantization;
- wall-clock latency полного scenario, включая model↔tool round trips;
- latency отдельно для `PASS`, для завершённых model turns (`completed`) и для `ERROR`;
  `completed` требует существующий turn и `run_completed=True`: незавершённый
  protocol FAIL исключён. Завершённый turn с ошибкой evaluator входит в
  `completed` и `ERROR`, поскольку это независимые признаки;
- RSS процесса `llama-server` перед benchmark;
- **sampled max RSS** с указанным interval;
- Linux `VmHWM` — high-water mark за всю жизнь server process, а не только run;
- **sampled max NVIDIA VRAM** во время benchmark с отдельным interval.

В comparison основная latency берётся только из `PASS`, чтобы быстрые protocol/
infrastructure failures не делали нестабильную модель искусственно «быстрее».

RSS/VRAM называются sampled maximum, а не точным peak: короткий пик между
выборками может быть пропущен. `nvidia-smi` работает в отдельном низкочастотном
sampling thread; его overhead остаётся ограничением методики и учитывается при
интерпретации близких результатов.

Если PID не передан, runner использует auto-detection только когда найден ровно
один процесс `llama-server`/`server`. Источник PID сохраняется в evidence.
Связь auto-detected PID с `base_url` не доказывается автоматически; для
representative performance run предпочтителен явный `--server-pid`.

Tokens/s не является обязательной универсальной метрикой v1: разные adapters
могут не возвращать сопоставимые token timings. Для FAST главным общим
показателем остаётся latency полного рабочего сценария.

## Прогоны

Сначала выполняется smoke run — один проход 10 сценариев:

```bash
PYTHONPATH=. .venv-qwen-agent/bin/python scripts/benchmark_tool_models.py \
  --base-url http://127.0.0.1:8080/v1 \
  --model Qwen3-0.6B-Q8_0 \
  --model-file /path/to/Qwen3-0.6B-Q8_0.gguf \
  --parameters-b 0.6 \
  --quantization Q8_0 \
  --repeats 1 \
  --server-pid "$(pgrep -n llama-server)"
```

После подтверждения integration выполняется сравнительный прогон:

```bash
PYTHONPATH=. .venv-qwen-agent/bin/python scripts/benchmark_tool_models.py \
  --base-url http://127.0.0.1:8080/v1 \
  --model Qwen3-0.6B-Q8_0 \
  --model-file /path/to/Qwen3-0.6B-Q8_0.gguf \
  --parameters-b 0.6 \
  --quantization Q8_0 \
  --repeats 5 \
  --server-pid "$(pgrep -n llama-server)"
```

Для representative performance run явный PID предпочтительнее auto-detection.

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

- `results.json` — полный machine-readable evidence, включая fixtures и partial trace;
- `cases.csv` — одна строка на scenario/repeat с `PASS/FAIL/ERROR`;
- `report.md` — читаемый отчёт конкретного прогона;
- `comparison.csv` — накопительная таблица моделей;
- `comparison.md` — автоматически обновляемое представление.

`.benchmarks/` не коммитится. После завершения сравнения показательный результат,
который влияет на архитектурное решение, переносится в `docs/TESTING/Results/`
как TV report по правилам [Testing](README.md#показательные-отчёты). Нельзя
переносить в документацию непроверенные или восстановленные по памяти числа.

## Таблица сравнения

Локальная таблица сравнивает:

- Pass / Routing / Arguments / Protocol / Grounding / Safety;
- число ERROR;
- mean/p95 latency только успешных PASS;
- размер модели;
- sampled max RSS/VRAM.

Победитель не определяется одним `Pass rate`. Для роли FAST отдельно оцениваются
качество, стабильность, latency и ресурсы; для отдельного action/router layer
может победить менее разговорная, но более надёжная и дешёвая модель.

## Проверка benchmark-кода

Benchmark logic имеет отдельные deterministic regression tests:

```bash
.venv/bin/python -m pytest -q \
  tests/test_tool_model_benchmark.py \
  tests/test_qwen_agent_tools.py
```

Regression suite должен включать контрпримеры independent review: противоположное
утверждение с правильным keyword, hallucinated missing fact, same-round T09,
инфраструктурный ERROR, latency separation и фиксированную Internal State config.

Перед representative evidence также выполняется:

```bash
bash scripts/check.sh
```

После значимого изменения evaluator benchmark снова проходит независимый read-only
review Codex. Real-model benchmark запускается только после приемлемого verdict.

## Ошибки измерителя и cumulative schema

Неожиданное исключение evaluator даёт `ERROR` с `error_kind=benchmark_evaluator`,
не оценивает способности модели и не останавливает следующие сценарии.
Полученный turn и предыдущие observations сохраняются в индивидуальном evidence.

Перед append `comparison.csv` header должен точно совпасть с текущей схемой.
При schema mismatch существующий CSV остаётся неизменным, `comparison.md`
не обновляется, а терминал показывает предупреждение. Индивидуальные
`results.json`, `cases.csv`, `report.md` сохраняются до cumulative update.


Benchmark gateway проверяет аргументы до выполнения и записи trace: `memory_search`
принимает только непустой `query` и необязательный integer `limit` в диапазоне 1–6;
`memory_get` — только `object_id` с префиксом `mem_` или `kn_` после trim;
`state_read` — пустой объект. Non-finite числа, в том числе вложенные, отклоняются
как model protocol FAIL. Внешние пробелы ID одинаково обрабатываются gateway и evaluator.

T08 сообщает формат ответа и варианты выбора, но не раскрывает правильный выбор.
T09 отклоняет преждевременное чтение expected ID даже после повторной корректной
последовательности search → get.

Individual evidence directories имеют UUID suffix и создаются без перезаписи
существующего каталога. При append CSV без завершающего CR/LF добавляется граница
записи; существующий header и значения сохраняются. JSON evidence экранирует Unicode,
а CSV заменяет невалидные Unicode code points escape-последовательностями.
