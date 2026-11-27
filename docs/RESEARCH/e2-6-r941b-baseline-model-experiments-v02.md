# ANIMA v0.2 — R9.4.1b Baseline Model Experiments

**Дата:** 27 ноября 2026. **Execution baseline:** `d34b472e51cdddf6f8700f0d521d4df65e8b4216`, ветка `work/v02-e26-r9-remediation`. **Статус:** COMPLETED, BASELINE EXPERIMENTS ONLY.

Протокол: [R9.4.1a, §5](e2-6-r941a-observable-v02.md#5-r941b-замороженный-план-и-команды). [Реестр R9](e2-6-r9-remediation-v02.md) сохраняет прежние finding IDs и quality gates. Реализация, модель, prompts, budgets, permissions, Retrieval и continuation policy не менялись. T-fresh, R9.4.2/R9.4.3 и повторная полная регрессия не запускались.

## 1. Preflight и исполнение

Clean HEAD/worktree проверены до испытаний. SHA актуальных `plan-control-v2`, `plan-host-v2`, held-out inputs, evaluator-only labels и run index совпали с R9.4.1a. Поля baseline старых manifests не переписывались: их исторический measurement baseline — 0cde809a; фактический execution SHA во всех run-inputs — d34b472.

Постоянный output root: `/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r941b-run-01/`. Все новые requests/responses, mappings, hashes, intermediate/final analysis и replay stores находятся вне repository и owner originals. Реальные испытания выполнялись существующим `.venv` и неизменённым R9.4.1a harness. Внешние analysis/validation scripts — только offline consumers, не изменения реализации.

Backend PID **13301**, start marker **111533**; executable/argv/model SHA совпали с архивным profile и сохранились до конца. Backend не перезапускался, config/cache не менялись. Loopback models endpoint доступен, alias Qwen3-4B-Q4_K_M. GPU NVIDIA GTX 1660 Ti, VRAM capacity 6144 MiB, driver 580.178.04; CPU Intel i5-10300H, 8 logical CPUs. Из argv известны ctx-size=4096, n-gpu-layers=99, --jinja; это declared settings, не утверждение о числе фактически offloaded layers. Cache/warm/slot reuse, effective template hash, generation threads/batch/parallel slots, external config/dynamic-library state — **UNKNOWN**. Inference seed не задан existing profile. HTTP peer/model-in-memory attestation не выполнялась.

Executable SHA-256: `9060daff0611e6a5fb5338513bf44ddb841214cbe748a4ee413e62ff88193db5`. Model SHA-256: `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`.

## 2. Planned / attempted / received / failed / unsupported

| Arm, оба profiles | Planned requests | Attempted | Received | Failed | Unsupported contexts |
| --- | --- | --- | --- | --- | --- |
| Q | 560 | 560 | 560 | 0 | 0 |
| I-event | 1120 | 1120 | 1120 | 0 | 0 |
| I-tool | 960 | 960 | 960 | 0 | 4 (7/C09, 8/C09 в каждом profile) |
| I-turn | 0 | 0 | 0 | 0 | 28 (typed turn IDs отсутствуют) |
| Всего fresh | **2640** | **2640** | **2640** | **0** | 32 context-arm exclusions, не failed requests |

N=20 соблюдён: Q — 20 repetitions/context; I — 20 original/variant pairs/context. AB/BA order, exact frozen request bodies и response hashes проверены offline. Monotonic timestamps подтверждают serial execution без overlap. Tool dispatch в Q/I отсутствует. INVALID_PAIR, transport failures, selective reruns и retries — 0; неисполненных prepared requests — 0. Terminal rejection не подменялся повторной генерацией. Дефект harness, остановивший испытание, не обнаружен.

H: 4 eligible fixed-journal pairs выполнены, 24 non-temporal contexts NOT_APPLICABLE. T-recorded: 28 trajectories / 93 generated exact requests MATCHED, first divergence отсутствует. Эти replay requests не входят в 2640 fresh model requests.

## 3. Q/I endpoints раздельно

Q сравнивается с archived response того же request; I — original A против inverse-mapped variant B. Denominator — responses для Q и pairs для I. Операции/аргументы включают пустой список при text stop; terminal status оценивается отдельно. Raw choices сохраняют новые tool IDs. Parsed operation signature исключает новые opaque tool IDs, но не меняет имена/аргументы/их порядок; known typed claims JSON разбирается existing parser, answer prose сравнивается точно. Arbitrary prose не нормализуется и не получает verified статуса.

| Profile/arm | Attempted / received / failed | Full response equality | Choices equality | Operations/typed args | Exact answer prose | Terminal classification |
| --- | --- | --- | --- | --- | --- | --- |
| control-Q | 280 / 280 / 0 | 0/280 | 40/280 | 280/280 | 280/280 | 280/280 |
| control-I-event | 560 / 560 / 0 | 0/280 | 40/280 | 220/280 | 280/280 | 280/280 |
| control-I-tool | 480 / 480 / 0 | 0/240 | 158/240 | 240/240 | 238/240 | 240/240 |
| host-Q | 280 / 280 / 0 | 0/280 | 40/280 | 280/280 | 280/280 | 280/280 |
| host-I-event | 560 / 560 / 0 | 0/280 | 40/280 | 220/280 | 280/280 | 280/280 |
| host-I-tool | 480 / 480 / 0 | 0/240 | 117/240 | 240/240 | 237/240 | 240/240 |

Q: 560/560 parsed decision signatures совпали с архивными; full hashes 0/560, choices 80/560. Внутри каждого Q context относительно первой fresh response есть 19 нетривиальных сравнений: **532/532** decision signatures совпали, full hashes **0/532**, choices **76/532**. Исходные analysis counters также включают 28 self-anchor comparisons; они не считаются независимыми совпадениями в этих 532.

I-event: **440/560** pairs имеют одинаковые операции/аргументы. В remaining 120 pairs меняется именно tool choice: 7/C01, 7/C06, 8/C06, по 20 pairs в каждом profile. Примеры Control: 7/C01 retrieve_memory(crate,1) → lookup_raw_evidence(mapped historical source); 7/C06 inspect_latest_observation → lookup_raw_evidence; 8/C06 lookup_raw_evidence → retrieve_memory(crate,1). Внутри каждого A и B на этих contexts — одна decision signature на 20 repetitions. Это наблюдаемая чувствительность к выбранным opaque ID variants в данном corpus; строки/длины/tokenization IDs также меняются. Нет вывода о более правильном tool choice или causal effect будущей policy: dispatch/outcome/verification отсутствуют.

I-tool: **480/480** pairs совпали по операциям/аргументам, **475/480** по точному prose. Пять prose mismatches: Control 7/C06, 8/C03_ALT; Host 7/C01, 7/C03_ALT, 8/C01. В каждом из них original A сам имеет две decision signatures при неизменном request; B — одну. Поэтому эти mismatches нельзя уверенно приписать rename. Это также ограничивает перенос Q stability с initial requests на later-history requests.

Все 1840 новых tool-call IDs уникальны (1840); все 2640 response IDs уникальны (2640). Empty-ID comparisons при text stop не доказывают стабильность generated tool IDs. Различие response ID/timing metadata или нового tool ID само по себе не означает различия когнитивного решения.

Terminal totals: **1840 tool_calls / TOOL_CALL_COMPLETE**, **800 stop / TEXT_COMPLETE**. INCOMPLETE/UNKNOWN и missing usage — 0. Это wire classifications, не admission, verified facts или Task success.

## 4. Результаты по scenario/context

Context — префикс context_snapshot_id; полные context/request hashes и selected request indices находятся в `protocol-validation.json`. Q и I могут выбирать разные recorded request indices; они не объявляются matched между arms. Ячейки Q: index; matching operations/args из 20 responses. I: index; matching operations/args из 20 pairs; затем exact prose из 20 pairs. NA — unsupported.

| Profile | Seed/case | Context hash prefix | Q: i; ops | I-event: i; ops; prose | I-tool: i; ops; prose |
| --- | --- | --- | --- | --- | --- |
| control | 7-C01 | `ctx_d417e801e504` | 0; 20/20 | 0; 0/20; 20/20 | 1; 20/20; 20/20 |
| control | 7-C02 | `ctx_d417e801e504` | 0; 20/20 | 0; 20/20; 20/20 | 1; 20/20; 20/20 |
| control | 7-C02_OFF | `ctx_14514156ce92` | 0; 20/20 | 1; 20/20; 20/20 | 1; 20/20; 20/20 |
| control | 7-C03 | `ctx_d417e801e504` | 0; 20/20 | 0; 20/20; 20/20 | 1; 20/20; 20/20 |
| control | 7-C03_ALT | `ctx_d417e801e504` | 0; 20/20 | 0; 20/20; 20/20 | 1; 20/20; 20/20 |
| control | 7-C06 | `ctx_d417e801e504` | 0; 20/20 | 0; 0/20; 20/20 | 1; 20/20; 19/20 |
| control | 7-C09 | `ctx_d417e801e504` | 0; 20/20 | 0; 20/20; 20/20 | NA |
| control | 8-C01 | `ctx_c73b1cd56389` | 0; 20/20 | 0; 20/20; 20/20 | 1; 20/20; 20/20 |
| control | 8-C02 | `ctx_c73b1cd56389` | 0; 20/20 | 0; 20/20; 20/20 | 1; 20/20; 20/20 |
| control | 8-C02_OFF | `ctx_a3128759d578` | 0; 20/20 | 1; 20/20; 20/20 | 1; 20/20; 20/20 |
| control | 8-C03 | `ctx_c73b1cd56389` | 0; 20/20 | 0; 20/20; 20/20 | 1; 20/20; 20/20 |
| control | 8-C03_ALT | `ctx_c73b1cd56389` | 0; 20/20 | 0; 20/20; 20/20 | 1; 20/20; 19/20 |
| control | 8-C06 | `ctx_c73b1cd56389` | 0; 20/20 | 0; 0/20; 20/20 | 1; 20/20; 20/20 |
| control | 8-C09 | `ctx_c73b1cd56389` | 0; 20/20 | 0; 20/20; 20/20 | NA |
| host | 7-C01 | `ctx_ed8dbd965fb4` | 0; 20/20 | 0; 0/20; 20/20 | 1; 20/20; 19/20 |
| host | 7-C02 | `ctx_ed8dbd965fb4` | 0; 20/20 | 0; 20/20; 20/20 | 1; 20/20; 20/20 |
| host | 7-C02_OFF | `ctx_02a1e4caa3cf` | 0; 20/20 | 1; 20/20; 20/20 | 1; 20/20; 20/20 |
| host | 7-C03 | `ctx_ed8dbd965fb4` | 0; 20/20 | 0; 20/20; 20/20 | 1; 20/20; 20/20 |
| host | 7-C03_ALT | `ctx_ed8dbd965fb4` | 0; 20/20 | 0; 20/20; 20/20 | 1; 20/20; 19/20 |
| host | 7-C06 | `ctx_ed8dbd965fb4` | 0; 20/20 | 0; 0/20; 20/20 | 1; 20/20; 20/20 |
| host | 7-C09 | `ctx_ed8dbd965fb4` | 0; 20/20 | 0; 20/20; 20/20 | NA |
| host | 8-C01 | `ctx_b794cac809d7` | 0; 20/20 | 0; 20/20; 20/20 | 1; 20/20; 19/20 |
| host | 8-C02 | `ctx_b794cac809d7` | 0; 20/20 | 0; 20/20; 20/20 | 1; 20/20; 20/20 |
| host | 8-C02_OFF | `ctx_f8e4951bb19d` | 0; 20/20 | 1; 20/20; 20/20 | 1; 20/20; 20/20 |
| host | 8-C03 | `ctx_b794cac809d7` | 0; 20/20 | 0; 20/20; 20/20 | 1; 20/20; 20/20 |
| host | 8-C03_ALT | `ctx_b794cac809d7` | 0; 20/20 | 0; 20/20; 20/20 | 1; 20/20; 20/20 |
| host | 8-C06 | `ctx_b794cac809d7` | 0; 20/20 | 0; 0/20; 20/20 | 1; 20/20; 20/20 |
| host | 8-C09 | `ctx_b794cac809d7` | 0; 20/20 | 0; 20/20; 20/20 | NA |

## 5. H и T-recorded

T-recorded: Control 14/14, 47 exact requests; Host 14/14, 46 exact requests. Full ordered journal/admission/outcome, reported budget и Cognitive Result совпали; elapsed/latency оставлены diagnostics. Не является fresh full trajectory reproduction.

H0/H1 получены на одном checked journal для каждой пары. Acquisition operations, research model calls, model text и source bindings одинаковы. Hybrid result equality — 4/4. Host presentation VERIFIED: Control C06/8, Host C06/7, Host C06/8; Control C06/7 сохраняет INFORMATION_INCOMPLETE. Для трёх достаточных journals оба result constructors делают по 2 canonical Raw rereads; H1 дополнительно 2 Host rereads и 6 nested context integrity row checks. Для incomplete case result construction — 1 reread, Host не добавляет evidence. Verifier I/O не считается acquisition и nested bytes не суммируются как независимые физические reads. H не доказывает улучшения research quality.

## 6. Resource consumption

Backend-reported tokens — known subtotals, не hardware cost. Latency — wall time harness, включая backend pin checks (executable hashing до/после HTTP), response serialization и persistence; не чистое GPU inference time. P95 — inclusive percentile. Cache/prefix reuse UNKNOWN, поэтому сравнения latency exploratory; profile/source corpus и selected request histories различаются.

| Profile/arm | Input tokens | Output tokens | Median ms | P95 ms | Known latency sum, s |
| --- | --- | --- | --- | --- | --- |
| control-Q | 208400 | 9320 | 475.76 | 945.01 | 165.19 |
| control-I-event | 433780 | 18420 | 988.90 | 1712.77 | 531.68 |
| control-I-tool | 505080 | 39654 | 1436.60 | 1930.32 | 635.48 |
| host-Q | 207680 | 8500 | 426.64 | 847.50 | 134.45 |
| host-I-event | 433480 | 18120 | 914.70 | 1811.43 | 522.19 |
| host-I-tool | 504080 | 34152 | 1049.59 | 1883.78 | 559.66 |

Всего reported input **2292500**, output **128166**; known latency sum **2548.66 s**, first-start → last-end window **2598.95 s**. Per-member A/B resource subtotals — `resources-supplement.json`. Нельзя считать разницу token counts после ID rename эффектом policy или аппаратной экономией.

## 7. Evidence / ограничения / предложения R9.4.2

Owner evidence после испытаний: MATCHED_BEFORE_INVENTORY — 7 archives, 8 bundles, 206 Recovery files; 88 cases / 48 Raw / 293 historical requests неизменны. Frozen v2 plans/run index/held-out inputs/labels SHA совпали. Held-out corpus не исполнялся и labels не входили в запросы; exact frozen request equality подтверждена. Реализация и generation configuration не менялись; повторная полная регрессия не требуется и не запускалась.

Ограничения: два world seeds, семь templates, один model/quantization/device; repetitions не независимые scenarios. I-turn unsupported; I-tool excludes arithmetic histories. UNKNOWN cache/template/default backend state ограничивает latency и attribution; отсутствие I-tool effect не доказывает, что template передаёт ID в model tokens. No dispatch: acquisition/completeness/redundancy после этих fresh proposals не измерены как реальные outcomes. Whole-answer semantics, T-fresh и causal policy effect — NOT_ASSESSED/NOT_RUN. Bootstrap policy gates не применяются к этому single-request baseline как к policy A/B test. R9.5 independent audit не заменён этими испытаниями.

Предложения для отдельного review R9.4.2:

1. Сохранить данные как baseline до policy changes; оценивать будущую policy на отдельных frozen-start trajectories с declared matched prefixes/first divergence, не на этих single-request outputs как на outcome доказательстве.
2. Использовать host-owned verified identities/requirement coverage/availability для review sufficient-information и continuation decisions. Учитывать повторный Raw proposal на уже admitted source независимо от tool name и ID spelling; source allowlist/verifier не ослаблять.
3. Разделить прекращение research acquisition и получение presentation: не фабриковать model final/Task success. Сохранить no-service-read non-monotonicity, Memory OFF boundary и прежние budgets/terminal contracts; без автоматических retries.
4. Включить ID variants и поздние exact-request repetitions в будущие regression strata: observed tool-choice sensitivity и exact-request prose variability требуют проверки, но не разрешают hidden aliases, Knowledge writes или новые полномочия.
5. Retrieval ranking и vocabulary changes оставить отдельному R9.4.3. До causal latency conclusions отдельно зафиксировать effective template/cache/backend state.

Данные и report snapshot архивируются отдельно от originals. Archive SHA-256 и итоговая receipt публикуются снаружи архива, чтобы избежать самоссылочного hash. Конкретные файлы: `analysis-final.json`, `diversity-final.json`, `resources-supplement.json`, `protocol-validation.json`, `evidence-before.json`, `evidence-after.json`, `backend-after.json`, исходные arm directories. Boundary — R9.4.1b; R9.4.2/R9.4.3 не реализованы.

## 8. Archive и итоговая receipt

Archive: `/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/ANIMA-E26-R941b-Baseline-Experiments-run-01.tar.gz`.

**SHA-256:** `4552ecfc74f22174182b451e6087f9187073ada9dd35faac1d46a4fffd0c81c2`.

Индекс `/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r941b-run-01/checksums.json` покрывает 11364 files; text checksum list дополнительно включает JSON index. Archive members проверены чтением без extraction. Raw dataset и pre-archive REPORT snapshot входят в архив; эта запись SHA и итоговая receipt находятся снаружи во избежание self-reference. Итоговая receipt: `/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r941b-run-01-validation-final-v2.json`.

Исходный execution HEAD d34b472 сохранён; результаты добавлены только в project documentation. Full regression не запускалась, поскольку реализация не менялась.

Итоговые checks: documentation/source snapshots **39 passed / 6.57 s**; project checks **PASS** (206 pages, 1456 links, 465 Python files, 21 Bash files). Offline wire audit: **1840/1840** tool calls декодируются existing NativeToolCatalog с frozen-profile `canonical_sets`; wire schema errors=0. В 160 responses (C03, seeds 7/8, оба profiles, I-tool A/B) raw event_ids содержит один и тот же ID дважды. Existing native set normalization удаляет duplicate до internal registry validation. Более строгий pre-normalization registry audit даёт 160 rejects; это не wire/admission failures и не изменение harness. Raw arguments сохранены и сравнивались без deduplication; tool dispatch не выполнялся. Execution HEAD не менялся; project diff — только три Markdown documentation files, новых commits/push нет.
