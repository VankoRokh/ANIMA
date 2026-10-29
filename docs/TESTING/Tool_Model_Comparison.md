# Сравнение tool-моделей

Краткая сводка representative-прогонов [ANIMA Tool Model Benchmark v1](Tool_Model_Benchmark.md).
Все строки ниже должны быть получены на одном [runtime-профиле ANIMA FAST CPU v1](Tool_Model_Runtime_Profile.md), если явно не указано иное. Подробный общий аудит выполняется после завершения серии моделей; этот документ хранит измерения и короткие наблюдения без ранжирования по одному показателю.

## Таблица

| Модель | Параметры | Quant | GGUF MiB | Pass | Routing | Arguments | Protocol | Grounding | Safety | ERROR | PASS mean / p95, ms | RSS before / max, MiB |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen3-0.6B-Q8_0 | 0.596B | Q8_0 | 609.824 | 10.00% | 22.22% | 44.44% | 90.00% | 22.22% | 88.89% | 0 | 4699.2 / 4762.9 | 1150.016 / 1150.480 |
| xLAM-2-1B-fc-r-Q8_0 | 1.54B | Q8_0 | 1570.294 | 20.00% | 22.22% | 33.33% | 90.00% | 22.22% | 88.89% | 0 | 22114.6 / 31946.0 | 1723.516 / 1815.566 |
| Hammer2.1-0.5B-Q8_0 | 0.5B | Q8_0 | 506.215 | 0.00% | 10.00% | 30.00% | 100.00% | 0.00% | 90.00% | 0 | — / — | 614.703 / 656.129 |
| FunctionGemma-270M-Q8_0 | 0.27B | Q8_0 | 278.051 | 0.00% | 10.00% | 30.00% | 100.00% | 0.00% | 90.00% | 0 | — / — | 362.340 / 405.766 |

## Qwen3-0.6B-Q8_0

**Дата:** 2026-10-30  
**Benchmark:** `tool-model-benchmark-v1`, 10 сценариев × 5 повторов = 50 наблюдений  
**Snapshot:** `6598bb5e69f7608b8839cdff43f7f6bc226f05ca`  
**Runtime:** `ANIMA FAST CPU v1`, llama.cpp `0.7.0-dev`, build `11943`, commit `a91917994`  
**Evidence:** `.benchmarks/tool-models/20261029T204535Z-Qwen3-0.6B-Q8_0-c6a99c82950944c798f9fa47db76b390`

Результат: 5 PASS, 45 FAIL, 0 ERROR. T01 прошёл 5/5; T02–T10 — 0/5. T09 во всех пяти повторах дошёл до `memory_search`, после чего завершился model-protocol FAIL на аргументах `memory_get`. Остальные причины не разбираются здесь подробно и будут сопоставлены с другими моделями в общем аудите.

Прогон показал высокую повторяемость результата на фиксированном runtime-профиле. Этот результат используется как первый официальный baseline серии, а не как окончательный вывод о целевой архитектуре FAST/tool layer.

## xLAM-2-1B-fc-r-Q8_0

**Дата:** 2026-10-30  
**Benchmark:** `tool-model-benchmark-v1`, 10 сценариев × 5 повторов = 50 наблюдений  
**Snapshot:** `6598bb5e69f7608b8839cdff43f7f6bc226f05ca`  
**Runtime:** `ANIMA FAST CPU v1`, llama.cpp `0.7.0-dev`, build `11943`, commit `a91917994`  
**Evidence:** `.benchmarks/tool-models/20261029T213836Z-xLAM-2-1B-fc-r-Q8_0-beb04af95b4b4f4ea122094d2e895255`

Результат: 10 PASS, 40 FAIL, 0 ERROR. T01 и T02 прошли 5/5; T03–T10 — 0/5. В T10 модель во всех пяти повторах вызвала цепочку `state_read → memory_search → memory_get`, после чего завершилась model-protocol FAIL (`Qwen-Agent returned no assistant messages`). Остальные причины будут разбираться только в общем аудите серии.

Результат стабилен между повторами и сохранён как второй официальный baseline для последующего межмодельного сравнения.

## Hammer2.1-0.5B-Q8_0

**Дата:** 2026-10-30  
**Benchmark:** `tool-model-benchmark-v1`, 10 сценариев × 5 повторов = 50 наблюдений  
**Snapshot:** `6598bb5e69f7608b8839cdff43f7f6bc226f05ca`  
**Runtime:** `ANIMA FAST CPU v1`, llama.cpp `0.7.0-dev`, build `11943`, commit `a91917994`  
**Evidence:** `.benchmarks/tool-models/20261029T221721Z-Hammer2.1-0.5B-Q8_0-5eb75e562ec44b00ba21b8712eaf96d4`

Результат: 0 PASS, 50 FAIL, 0 ERROR. Ни один сценарий не прошёл полностью; во всех 50 наблюдениях инструментальные вызовы в trace отсутствовали. Protocol при этом составил 100%, а RSS peak — 656.129 MiB. Детальный разбор поведения откладывается до общего аудита серии.

Результат сохранён как третий официальный baseline для последующего межмодельного сравнения.

## FunctionGemma-270M-Q8_0

**Дата:** 2026-10-30  
**Benchmark:** `tool-model-benchmark-v1`, 10 сценариев × 5 повторов = 50 наблюдений  
**Snapshot:** `6598bb5e69f7608b8839cdff43f7f6bc226f05ca`  
**Runtime:** `ANIMA FAST CPU v1`, llama.cpp `0.7.0-dev`, build `11943`, commit `a91917994`  
**Evidence:** `.benchmarks/tool-models/20261029T222445Z-FunctionGemma-270M-Q8_0-2aba9cd227d842c5ae460fbd4e942f77`

Результат: 0 PASS, 50 FAIL, 0 ERROR. Во всех 50 наблюдениях trace не содержит tool calls. Routing — 10%, Arguments — 30%, Protocol — 100%, Grounding — 0%, Safety — 90%. RSS peak составил 405.766 MiB, размер GGUF — 278.051 MiB. Детальный разбор откладывается до общего аудита серии.

Результат сохранён как четвёртый официальный baseline для последующего межмодельного сравнения.
