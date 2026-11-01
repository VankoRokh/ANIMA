# Stage 5 Benchmark v2 — preliminary / exploratory evidence

Отдельный opt-in [runner](../../scripts/benchmark_stage5_v2.py) сравнивает восемь
моделей из [Benchmark v1 comparison](Tool_Model_Comparison.md) через production
`CognitivePipeline → projection → FastLLMBackend.complete_projected → llama.cpp`.
Benchmark v1, его corpus, evaluator, runtime profile и evidence не меняются.
Никаких Agent/Planner, Tools/Executor, Sleep, DEEP или Internal State decisions.

```bash
.venv/bin/python -m pytest -q tests/test_stage5_benchmark_v2.py
.venv/bin/python scripts/benchmark_stage5_v2.py
```

Без параметров runner ищет GGUF под `~/Projects/models/`, binary под
`~/Projects/llama.cpp/build/bin/` и пишет evidence в ignored
`.benchmarks/stage5-v2/<UTC timestamp>/`. `--help` задаёт paths, dedicated port,
call timeout и output directory. Import и обычный pytest не запускают inference.
Qwen3-1.7B не добавляется: она не входит в восемь моделей исходного v1 inventory.
Unavailable model или startup failure явно сохраняется как setup error.

## Условия

Один bounded pass: восемь сценариев на каждую модель. Это не representative
пятизапусковая baseline v1 и не статистическая оценка reliability.
[CPU runtime profile](Tool_Model_Runtime_Profile.md) сохраняется: device none,
context 4096, parallel 1, threads/batch threads 4, batch 2048, ubatch 512,
f16 KV, cache RAM 0, prompt cache off, flash-attn auto, fit off, continuous batching
off, context shift off, warmup on. Изменяются только GGUF и alias; native GGUF
chat template применяется самим сервером, без model-specific prompt overrides.
Runner занимает dedicated localhost port 8081, не заменяет существующий сервер
и завершает только собственный процесс, включая failure paths.

Temperature=0, max output=256 и top-p=0.8 совпадают с v1 runner. Top-k=40 и min-p=0.05
явно фиксируют defaults доступного llama.cpp build, которые v1 не переопределяет.
Thinking=false передаётся через `chat_template_kwargs.enable_thinking`; шаблон
модели может не поддерживать эту опцию. Template/payload и raw response сохраняются,
поэтому несовместимость остаётся видимой. Нет grammar, constrained decoding,
model-specific tuning, retry, output repair или fallback. Default per-call timeout
120 s, startup readiness deadline 90 s. Polling readiness не является model retry.

## Corpus и evaluator

| Scenario | Ожидаемый route | Проверка |
|---|---|---|
| arithmetic | DETERMINISTIC_RESULT | Exact decimal subtraction даёт `0.000001`; zero backend calls |
| insufficient | INSUFFICIENT_DATA | Structured `pet.color` отсутствует; zero calls |
| infeasible | DETERMINISTIC_RESULT | Known universe полностью отвергнут hard constraint; typed NO_ADMISSIBLE_ACTION; zero calls |
| projected_text | COGNITIVE_REQUIRED | `COBALT47` присутствует в raw и final response, один call |
| candidate_choice | COGNITIVE_REQUIRED | CONTINUE и WAIT допустимы, SHUTDOWN hard-rejected; raw preference требует точный CONTINUE |
| invalid_candidate | COGNITIVE_REQUIRED | После real completion явно injected SHUTDOWN отвергается final validation; один call, без repair |
| grounded_evidence | COGNITIVE_REQUIRED | Temporary MemoryStore → Retrieval → ContextBuilder передаёт bicycle evidence; ответ содержит слово amber |
| ambiguous | COGNITIVE_REQUIRED | Два conflicting structured pet.color facts; без precedence resolver не выбирает winner; модель возвращает AMBER или BLUE |

Free-text evaluator проверяет bounded semantic delivery: `COBALT47.` и `amber.`
допустимы; label-only echo `text`, `candidate`, `output_contract` не подменяет task
content. Grounded check — case-insensitive whole word `amber`, не general semantic
judge. Candidate-mode проверяет точный ID после существующей whitespace normalization:
`CONTINUE.` и `RESULT=CONTINUE` невалидны. Ambiguous case проверяет route/validity,
а не истинность одного из конфликтующих facts.

Memory/event fixtures создаются только в TemporaryDirectory; обычный instance не
используется. Grounded request проходит Event path с authoritative FAST context
budget 6 items / 1200 content chars; остальные — structured process_task без FTS.

## Evidence и метрики

На модель: `01/` … `08/`, `server.log`, `evidence.json` с model hash, server identity,
actual command/PID, GGUF template/properties, generation parameters, source
fingerprints и всеми восемью scenarios. Общие `comparison.json` и `comparison.md`
содержат модельные summaries и historical v1 references. В JSON каждого scenario:

- route, expected_route, resolution, correctness, passed;
- backend_attempts, generation_requests, generation_responses, successful_completions;
- final_result, raw_model_response, model_response, backend_response;
- candidate_validity (null когда неприменимо), invalid_output_rejection;
- latency_ms, input_tokens, output_tokens;
- projected_view, rendered prompts, native HTTP payloads/responses;
- validation error, exception, terminal audit/failure classification.

Attempt фиксируется до invocation, completion — после valid FastResult. Token counts
берутся из raw native response даже при unusable model output; zero-call rows имеют
0, а unavailable measurements — null, не выдуманный ноль. Summary token totals
суммируют только наблюдённые counts; `missing_token_rows` показывает неполноту.
Latency измеряет весь pipeline call, включая retrieval/validation, исключая startup,
model hashing и fixture creation. Mean/max backend latency включают все attempted
cases, в том числе failures, а не только PASS. Counts не выводятся из call_history.

`invalid_candidate` — labelled fault injection после настоящей generation, не
model mistake и не model quality success. Raw model response сохранён отдельно.
Total PASS/8 содержит три model-independent cases и этот negative validation case.
Отдельный positive_model_passes/4 использует только projected text, constrained
choice, grounding и ambiguity. Нельзя ранжировать модели по scaffold checks.
Benchmark process exit code сообщает setup errors; scenario quality FAIL остаются
результатами измерения и отражаются явно в JSON/Markdown.

## Предварительный exploratory прогон

Завершённый прогон охватил Stage 5 deterministic-resolution / projected-FAST
architecture на всех восьми моделях, ранее доступных в Benchmark v1, с одним
проходом на модель. Следующая таблица сохраняет предварительные наблюдения
в исходном inventory order; это не официальный рейтинг моделей.

| Модель (Q8_0) | Preliminary PASS / 8 | Positive checks / 4 | Mean backend latency, ms |
|---|---:|---:|---:|
| Qwen3-0.6B | 8/8 | 4/4 | 2054 |
| xLAM-2-1B | 7/8 | 3/4 | 6029 |
| Hammer2.1-0.5B | 6/8 | 2/4 | 1737 |
| FunctionGemma-270M | 5/8 | 1/4 | 1028 |
| Granite-350M | 8/8 | 4/4 | 1796 |
| Granite-1B | 8/8 | 4/4 | 7495 |
| Arch-Agent-1.5B | 8/8 | 4/4 | 5647 |
| SmolLM3-3B | 8/8 | 4/4 | 12753 |

Всего 58/64 scenario checks и 26/32 positive model checks. На каждой модели
arithmetic, missing-data и known-infeasibility требовали ноль model calls;
остальные пять scenarios дали по одному backend attempt / generation / successful
completion. Итого 40 / 40 / 40, 15794 input tokens, 418 output tokens,
192.69 s суммарного pipeline latency; setup/transport failures не наблюдались.
Три model-independent scenarios и injected negative case входят в PASS/8,
поэтому этот общий счётчик не является оценкой качества LLM.

Наблюдения этого единственного прогона:

- Несколько моделей с плохими историческими v1 tool-protocol results успешно
  обработали prepared Stage 5 projections: Granite-1B и Arch-Agent прошли все
  четыре positive checks. Это другой workload, а не измеренный процент улучшения.
- xLAM вернул tool-call wrapper `[{"name": "CONTINUE", "arguments": {}}]` вместо ID;
  Hammer вернул fenced IDs для CONTINUE и AMBER. Strict candidate validation
  корректно отвергла эти structurally invalid/non-exact outputs без repair/retry.
- FunctionGemma echo structured input и не прошла grounding/candidate checks.
  Её marker-containing echo, как и echo инструкции у Granite-350M, прошёл bounded
  semantic-delivery check. Это не clean-answer success и не доказательство
  instruction-following reliability; evaluator проверяет доставку task content.
- Qwen3-0.6B и Granite-350M особенно интересны для будущей FAST evaluation благодаря
  наблюдённому balance результатов и latency. Это исследовательское наблюдение,
  а не выбор backend или архитектурное решение.

Прогон даёт полезное архитектурное evidence: Stage 5 решает formal rules и routing
до модели и передаёт ей prepared projection, уменьшая объём protocol/routing work,
делегированного LLM. Результаты согласуются с этой границей ответственности;
это не controlled causal comparison качества моделей между v1 и v2.

Полные raw captures остаются только local experimental evidence в ignored
`.benchmarks/stage5-v2/20261101T191219Z/`: `01/` … `08/` содержат
`evidence.json` и server logs; `comparison.json` / `comparison.md` — aggregates;
`scenario-results.csv` / `scenario-results.md` — derived views всех 64 scenarios,
сохранённые после прогона без дополнительного inference. Это локальные artifacts,
не публикуемый официальный model leaderboard и не Stage acceptance evidence.

## Ограничения и последующая проверка

Этот результат preliminary / exploratory: использован только один pass на модель.
Он не устанавливает model reliability, definitive ranking или preferred FAST
backend. В частности, он не доказывает предпочтительность Granite-350M,
Qwen3-0.6B или любой другой модели. Нет прямого percentage improvement над
Benchmark v1: v1 и v2 проверяют разные workloads, corpus и interfaces.

До model-selection decisions нужны последующие repeated runs с
paraphrased/equivalent scenarios, явным отделением semantic delivery от clean-answer
качества и сохранением одинаковых runtime условий. Такая проверка — будущая
experimental work, не принятое решение о backend и не изменение Stage scope/status.

## Сравнение с v1

Общие оси: inventory, CPU/runtime, temperature, token limit, transport compatibility
и факт successful/failed completion. Corpus, интерфейс, evaluator и call counts
различаются. V1 измеряет multi-round function-calling и самостоятельный поиск через
Tools; v2 получает уже подготовленную projection и не выполняет Tools. Поэтому
PASS rates, routing accuracy и latency нельзя трактовать как прямой improvement
или speedup. V1 PASS-only mean latency не равен v2 all-attempt mean.

V1 reference берётся read-only из `.benchmarks/tool-models/comparison.csv`, только
representative rows с total_runs=50. Для SmolLM3 raw numerator/denominator — 15/50,
а не conditional 15/40 после исключения errors. Historical evidence не перезаписывается.
Полные raw payloads/results следует сохранять вместе с comparison для проверки
необычных ответов, template errors и token-limit failures.
