# Сравнение tool-моделей

Краткая сводка representative-прогонов [ANIMA Tool Model Benchmark v1](Tool_Model_Benchmark.md).
Все строки ниже получены на одном [runtime-профиле ANIMA FAST CPU v1](Tool_Model_Runtime_Profile.md), если явно не указано иное. Таблица хранит сырые измерения representative-прогонов; выводы общего аудита приведены ниже и учитывают ограничения backend/adapter compatibility.

## Таблица

| Модель | Параметры | Quant | GGUF MiB | Pass | Routing | Arguments | Protocol | Grounding | Safety | ERROR | PASS mean / p95, ms | RSS before / max, MiB |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen3-0.6B-Q8_0 | 0.596B | Q8_0 | 609.824 | 10.00% | 22.22% | 44.44% | 90.00% | 22.22% | 88.89% | 0 | 4699.2 / 4762.9 | 1150.016 / 1150.480 |
| xLAM-2-1B-fc-r-Q8_0 | 1.54B | Q8_0 | 1570.294 | 20.00% | 22.22% | 33.33% | 90.00% | 22.22% | 88.89% | 0 | 22114.6 / 31946.0 | 1723.516 / 1815.566 |
| Hammer2.1-0.5B-Q8_0 | 0.5B | Q8_0 | 506.215 | 0.00% | 10.00% | 30.00% | 100.00% | 0.00% | 90.00% | 0 | — / — | 614.703 / 656.129 |
| FunctionGemma-270M-Q8_0 | 0.27B | Q8_0 | 278.051 | 0.00% | 10.00% | 30.00% | 100.00% | 0.00% | 90.00% | 0 | — / — | 362.340 / 405.766 |
| Granite-4.0-H-350M-Q8_0 | 0.35B | Q8_0 | 349.231 | 20.00% | 60.00% | 40.00% | 100.00% | 20.00% | 90.00% | 0 | 7521.5 / 11186.5 | 345.426 / 553.273 |
| Granite-4.0-H-1B-Q8_0 | 1.5B | Q8_0 | 1486.708 | 0.00% | — | — | 0.00% | — | — | 0 | — / — | 1517.000 / 1841.852 |
| Arch-Agent-1.5B-Q8_0 | 1.5B | Q8_0 | 1570.292 | 10.00% | 100.00% | 100.00% | 10.00% | 100.00% | 100.00% | 0 | 37663.6 / 38869.1 | 1416.418 / 1816.051 |
| SmolLM3-3B-Q8_0 | 3.0B | Q8_0 | 3123.831 | 37.50%* | 62.50% | 75.00% | 100.00% | 50.00% | 87.50% | 10 | 93228.2 / 141218.1 | 2507.527 / 3546.625 |

\* Для SmolLM3 агрегат `Pass=37.50%` рассчитан benchmark только по 40 не-ERROR наблюдениям. Фактически полностью успешны 15 из 50 запусков (30.00%). Десять ERROR требуют отдельной интерпретации ниже.

## Qwen3-0.6B-Q8_0

**Дата:** 2026-10-30  
**Benchmark:** `tool-model-benchmark-v1`, 10 сценариев × 5 повторов = 50 наблюдений  
**Snapshot:** `6598bb5e69f7608b8839cdff43f7f6bc226f05ca`  
**Runtime:** `ANIMA FAST CPU v1`, llama.cpp `0.7.0-dev`, build `11943`, commit `a91917994`  
**Evidence:** `.benchmarks/tool-models/20261029T204535Z-Qwen3-0.6B-Q8_0-c6a99c82950944c798f9fa47db76b390`

Результат: 5 PASS, 45 FAIL, 0 ERROR. T01 прошёл 5/5; T02–T10 — 0/5. T09 во всех пяти повторах дошёл до `memory_search`, после чего завершился model-protocol FAIL на аргументах `memory_get`.

Прогон показал высокую повторяемость результата на фиксированном runtime-профиле и используется как исходный baseline серии.

## xLAM-2-1B-fc-r-Q8_0

**Дата:** 2026-10-30  
**Benchmark:** `tool-model-benchmark-v1`, 10 сценариев × 5 повторов = 50 наблюдений  
**Snapshot:** `6598bb5e69f7608b8839cdff43f7f6bc226f05ca`  
**Runtime:** `ANIMA FAST CPU v1`, llama.cpp `0.7.0-dev`, build `11943`, commit `a91917994`  
**Evidence:** `.benchmarks/tool-models/20261029T213836Z-xLAM-2-1B-fc-r-Q8_0-beb04af95b4b4f4ea122094d2e895255`

Результат: 10 PASS, 40 FAIL, 0 ERROR. T01 и T02 прошли 5/5; T03–T10 — 0/5. В T10 модель во всех пяти повторах вызвала цепочку `state_read → memory_search → memory_get`, после чего завершилась model-protocol FAIL (`Qwen-Agent returned no assistant messages`).

Результат стабилен между повторами.

## Hammer2.1-0.5B-Q8_0

**Дата:** 2026-10-30  
**Benchmark:** `tool-model-benchmark-v1`, 10 сценариев × 5 повторов = 50 наблюдений  
**Snapshot:** `6598bb5e69f7608b8839cdff43f7f6bc226f05ca`  
**Runtime:** `ANIMA FAST CPU v1`, llama.cpp `0.7.0-dev`, build `11943`, commit `a91917994`  
**Evidence:** `.benchmarks/tool-models/20261029T221721Z-Hammer2.1-0.5B-Q8_0-5eb75e562ec44b00ba21b8712eaf96d4`

Результат: 0 PASS, 50 FAIL, 0 ERROR. Ни один сценарий не прошёл полностью; во всех 50 наблюдениях инструментальные вызовы в trace отсутствовали. Protocol при этом составил 100%, RSS peak — 656.129 MiB.

Этот результат сохраняется как проверка drop-in совместимости текущего backend, но не считается достаточным доказательством отсутствия function-calling способности модели: Hammer использует собственный формат action/function output.

## FunctionGemma-270M-Q8_0

**Дата:** 2026-10-30  
**Benchmark:** `tool-model-benchmark-v1`, 10 сценариев × 5 повторов = 50 наблюдений  
**Snapshot:** `6598bb5e69f7608b8839cdff43f7f6bc226f05ca`  
**Runtime:** `ANIMA FAST CPU v1`, llama.cpp `0.7.0-dev`, build `11943`, commit `a91917994`  
**Evidence:** `.benchmarks/tool-models/20261029T222445Z-FunctionGemma-270M-Q8_0-2aba9cd227d842c5ae460fbd4e942f77`

Результат: 0 PASS, 50 FAIL, 0 ERROR. Во всех 50 наблюдениях trace не содержит tool calls. Routing — 10%, Arguments — 30%, Protocol — 100%, Grounding — 0%, Safety — 90%. RSS peak — 405.766 MiB, размер GGUF — 278.051 MiB.

Этот результат сохраняется как проверка drop-in совместимости. FunctionGemma требует собственного function-calling формата/триггера и ориентирована прежде всего на компактный action layer, поэтому её intrinsic capability нельзя оценивать только этой строкой.

## Granite-4.0-H-350M-Q8_0

**Дата:** 2026-10-30  
**Benchmark:** `tool-model-benchmark-v1`, 10 сценариев × 5 повторов = 50 наблюдений  
**Snapshot:** `6598bb5e69f7608b8839cdff43f7f6bc226f05ca`  
**Runtime:** `ANIMA FAST CPU v1`, llama.cpp `0.7.0-dev`, build `11943`, commit `a91917994`  
**Evidence:** `.benchmarks/tool-models/20261029T223400Z-Granite-4.0-H-350M-Q8_0-65a544c9032f494db7495239c617d848`

Результат: 10 PASS, 40 FAIL, 0 ERROR. T01 и T02 прошли 5/5; T03–T10 — 0/5. Инструментальные вызовы устойчиво наблюдались в T02–T05, T08 и T09; в T09 все пять повторов выполнили цепочку `memory_search → memory_get`. Routing составил 60%, Protocol — 100%.

Среди моделей, которые реально вошли в tool loop через текущий backend, этот прогон даёт наиболее сильное сочетание компактности, корректного routing и низкой задержки.

## Granite-4.0-H-1B-Q8_0

**Дата:** 2026-10-30  
**Benchmark:** `tool-model-benchmark-v1`, 10 сценариев × 5 повторов = 50 наблюдений  
**Snapshot:** `6598bb5e69f7608b8839cdff43f7f6bc226f05ca`  
**Runtime:** `ANIMA FAST CPU v1`, llama.cpp `0.7.0-dev`, build `11943`, commit `a91917994`  
**Evidence:** `.benchmarks/tool-models/20261029T225200Z-Granite-4.0-H-1B-Q8_0-1eaafed5770c4a3a884c7b6bd0e6fac5`

Результат: 0 PASS, 50 FAIL, 0 ERROR. Все 50 наблюдений завершились model-protocol FAIL с одинаковой ошибкой `Function arguments must decode to an object`; Routing, Arguments, Grounding и Safety поэтому не имеют наблюдений, Protocol — 0%. RSS peak — 1841.852 MiB, размер GGUF — 1486.708 MiB.

Так как модель официально поддерживает tool calling, этот результат рассматривается прежде всего как сигнал несовместимости текущей связки parser/template/backend, а не как содержательный capability result.

## Arch-Agent-1.5B-Q8_0

**Дата:** 2026-10-30  
**Benchmark:** `tool-model-benchmark-v1`, 10 сценариев × 5 повторов = 50 наблюдений  
**Snapshot:** `6598bb5e69f7608b8839cdff43f7f6bc226f05ca`  
**Runtime:** `ANIMA FAST CPU v1`, llama.cpp `0.7.0-dev`, build `11943`, commit `a91917994`  
**Evidence:** `.benchmarks/tool-models/20261030T001532Z-Arch-Agent-1.5B-Q8_0-5cca6e9905f6432cab9cd69f32a76b2e`

Результат: 5 PASS, 45 FAIL, 0 ERROR. Только T02 прошёл 5/5. В остальных сценариях модель преимущественно продолжала вызывать инструменты до превышения лимита tool-call rounds; T01 стабильно выполнял `state_read → memory_search → state_read → memory_search`, T09 — `memory_search → memory_get → memory_get → memory_get`. Protocol составил 10%; Routing, Arguments, Grounding и Safety равны 100% только по пяти полностью завершившимся наблюдениям и не должны интерпретироваться без metric counts.

RSS peak — 1816.051 MiB, размер GGUF — 1570.292 MiB.

## SmolLM3-3B-Q8_0

**Дата:** 2026-10-30  
**Benchmark:** `tool-model-benchmark-v1`, 10 сценариев × 5 повторов = 50 наблюдений  
**Snapshot:** `6598bb5e69f7608b8839cdff43f7f6bc226f05ca`  
**Runtime:** `ANIMA FAST CPU v1`, llama.cpp `0.7.0-dev`, build `11943`, commit `a91917994`  
**Evidence:** `.benchmarks/tool-models/20261030T010914Z-SmolLM3-3B-Q8_0-e0fdeedaaf60495ca01e55ca1b3ee199`

Результат: 15 PASS, 25 FAIL, 10 ERROR. T02, T06 и T07 прошли 5/5; T01, T03–T05 и T10 — 0/5. T08 и T09 дали по 5 ERROR после `memory_search`: модель попыталась использовать синтетические ID `mem_coffee_preference` и `mem_12345`, которые прошли поверхностную benchmark-проверку префикса, но были отвергнуты RetrievalEngine как невалидные public IDs.

Сырые агрегаты benchmark показывают Pass 37.50% по 40 не-ERROR наблюдениям; фактическая доля полностью успешных запусков от всех 50 составляет 30.00%. RSS peak — 3546.625 MiB, размер GGUF — 3123.831 MiB. Модель показала наиболее широкий набор полностью пройденных сценариев, но с существенно большей задержкой и памятью.

## Общий аудит серии v1

### Что серия действительно измерила

Все модели прошли один corpus, evaluator и CPU runtime profile. Однако backend не является полностью model-neutral: текущий экспериментальный bridge создаёт модели через Qwen-Agent и фиксирует `fncall_prompt_type="nous"`. Поэтому серия надёжно сравнивает **drop-in поведение кандидатов в текущем ANIMA/Qwen-Agent bridge**, но не является чистым сравнением intrinsic function-calling capability моделей с их нативными adapters/templates.

### Основные выводы

1. **Granite-4.0-H-350M — сильнейший текущий FAST-кандидат по балансу.** Он дал 20% полного PASS, 60% routing, 100% protocol, устойчиво строил `memory_search → memory_get`, при RSS peak около 553 MiB. Для edge/CPU FAST это существенно выгоднее xLAM, Arch-Agent и SmolLM3.
2. **SmolLM3 показала самый широкий функциональный результат, но не лучший FAST-профиль.** 15/50 запусков полностью успешны, включая semantic project retrieval и multi-tool Memory+State. Цена — около 3.55 GiB peak RSS и очень высокая CPU latency. Это скорее кандидат на более тяжёлый cognitive/DEEP слой или контрольный upper bound, чем на компактный FAST.
3. **xLAM работает, но текущая связка раскрывает её слабо.** При 20% PASS она потребляет около 1.8 GiB RSS и показывает слабый routing в текущем bridge. У модели есть собственный tool-call parser/формат, поэтому перед окончательным исключением нужен один нативный compatibility check.
4. **Arch-Agent умеет инициировать tools, но в текущем bridge не умеет устойчиво остановиться.** Повторные вызовы до лимита раундов делают её непригодной как drop-in FAST без model-specific prompt/parser work.
5. **Hammer и FunctionGemma нельзя честно ранжировать по их 0% как intrinsic action models.** Оба кандидата используют специализированные function formats; FunctionGemma дополнительно ориентирована на single-turn/parallel calls и собственный developer trigger. Их текущие результаты означают «не drop-in совместимы с Qwen-Agent/Nous bridge», а не «не умеют tools».
6. **Granite-4.0-H-1B требует отдельной проверки parser/template.** Сто процентов запусков сломались одним и тем же способом до содержательной оценки, несмотря на заявленную tool-calling поддержку семейства.
7. **В benchmark найден реальный classification defect.** `memory_get` допускает любую строку с `mem_`/`kn_` на benchmark validation layer, а RetrievalEngine требует валидный public ID. Из-за этого модельные ошибки SmolLM3 попали в `ERROR/infrastructure`. Это нужно исправить перед следующей серией, но не требует повторять все уже валидные прогоны.

### Решение по кандидатам после v1

Для следующего шага приоритет разумно задать так:

- **Primary FAST candidate:** Granite-4.0-H-350M.
- **Reference / heavier candidate:** SmolLM3-3B.
- **Compatibility retest:** Granite-4.0-H-1B и xLAM-2-1B с корректным model-specific parser/template.
- **Separate action-router track:** FunctionGemma-270M и Hammer2.1-0.5B; оценивать их отдельным router/action benchmark без требования выполнять роль полноценного когнитивного ответа.
- **Low priority:** Arch-Agent-1.5B, если model-specific adapter не устраняет повторные tool loops без роста сложности системы.

Таким образом, v1 выполнил свою задачу: он не выбрал окончательную модель одним числом, а отделил компактный практичный FAST-кандидат от тяжёлых моделей, adapter-sensitive action models и кандидатов с protocol incompatibility.
