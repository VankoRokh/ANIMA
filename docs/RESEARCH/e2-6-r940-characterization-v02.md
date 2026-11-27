# ANIMA v0.2 — R9.4.0: управление когнитивными циклами

**Дата:** 27 ноября 2026. **Baseline:** `5448e8ee8b09a3ad8d079896d85367201ed13d5a`.
**Ветка:** `work/v02-e26-r9-remediation`. **Статус:** CHARACTERIZATION / DESIGN ONLY; исправления R9.4.1–R9.4.4 не начаты, независимый аудит не проведён.

Основной [реестр R9](e2-6-r9-remediation-v02.md) сохраняет исторические определения и результаты. Этот документ содержит инвентаризацию, локальные воспроизводители, измерения и проект следующих этапов. PASS characterization означает, что ограничение воспроизведено на неизменённой реализации; это не устранение дефекта и не закрытие R9-Q02/Q03/Q04 или CA-06/R9-E01/E02.

## 1. Исходные данные и граница вывода

Предоставленные владельцем результаты R9.3 Recovery на baseline:

| Контур | Результат владельца |
| --- | --- |
| Historical Evidence | 6/6 VERIFIED; 60 cases, 36 Raw samples, 200 requests |
| Native Control | 10/14 Operation Gate; 47 requests; bundle VERIFIED |
| Native Host | 12/14 Operation Gate; 46 requests; bundle VERIFIED |
| Legacy | 0/4 FAST Quality Gate; 14 calls, 12 valid |
| Choice | 0/4 FAST Quality Gate; 10 calls, 10 valid |
| Canonical Native | 4/8 accepted |
| Canonical Chat | 0/4 accepted |
| Canonical Chat No Thinking | 1/4 accepted |
| Early Diagnostics | 2/2 verified |
| Проверяемые terminal contracts | 0 обнаруженных нарушений |

Это новые восстановительные испытания, а не восстановленные оригинальные трассировки. Здесь не выполнялась независимая проверка этих архивов: пути к recovery bundles и archive SHA-256 не предоставлены в задании. Значения не заменяют предшествующие записи R9.3, привязанные к другим snapshot. Разница 10/14 против 12/14 не устанавливает причинный эффект Host.

Локальные characterization используют terminal-valid синтетические wire replies, действующие NativeLabAdapter, coordinator, SQLite Decision Journal и Core-backed Raw fixtures. Они устанавливают механизм и воспроизводимость ограничений, но не частоту причин в recovery trajectories и не качество реальной LLM. Fresh inference, аппаратный cost, полный frozen trajectory replay и причинные model comparisons в R9.4.0 — NOT_RUN.

## 2. Инвентаризация владельцев и механизмов

Пути в таблице — существующая реализация baseline; ни один из этих модулей не меняется в R9.4.0.

| Механизм / функции | Реализация и текущая граница |
| --- | --- |
| CompletionRequirement; evaluate_completion | [completion.py](../../labs/virtual_anima_lab/python/cognition/completion.py): четыре вида вопроса; проверяет report/records, admitted completed reads, target entities и temporal prerequisites; model stop, information sufficiency и Task success раздельны. Нет модели availability или incremental gain. `verified_observation` учитывает только `lookup_raw_evidence`; temporal requirement использует оба Raw tools |
| Лабораторный Cognitive Coordinator | [coordinator.py](../../labs/virtual_anima_lab/python/cognition/coordinator.py): `E25LabCognitiveCoordinator.run_turn`, `_record`, `_finalize`, `decision_records`. Frozen Context hash, проверки свежести до/после model/service, pre-admission запись, финализация outcome, integrity checks, source allowlist. Нет policy дедупликации evidence или остановки по gain |
| Canonical Cognitive Coordinator | [anima/cognition/coordinator.py](../../anima/cognition/coordinator.py): `CognitiveCoordinator.process` связывает active Task и CanonicalTask, вызывает authoritative resolver, возвращает FINAL/NEEDS_DATA/ROUTE_COGNITION. Это отдельный контур; не лабораторный multi-tool loop. Дальнейшие routing/dispatch — [pipeline.py](../../anima/cognition/pipeline.py), [routing.py](../../anima/cognition/routing.py) |
| Continuation | В `run_turn`, только ветка `raw is None`: evaluate_completion, один CONTINUE при недостающей информации и оставшихся вызовах; затем CONTINUATION_LIMIT/BUDGET_EXHAUSTED. `no_service_read` не возобновляется. [native_lab.py](../../labs/virtual_anima_lab/python/cognition/native_lab.py): `resume_after_stop` связывает turn/context и передаёт bounded feedback; это не повтор генерации после rejected terminal |
| ResourceBudget | [resource_budget.py](../../labs/virtual_anima_lab/python/cognition/resource_budget.py): `check_next/reserve/settle/snapshot`; default 4 calls, 8192 reported input, 1024 reported output, 60000 ms, output reservation 256. Input/elapsed проверяются на границах, missing usage не обнуляется. Нет оценки полезности следующего вызова; это не hardware ceiling |
| Decision Journal | SQLite `e25_cognitive_trace` в coordinator; содержит Context, typed proposal, admission/outcome и hashes. `decision_records` возвращает ordered checked records; stop/resume сами не service records. Полная история model calls и projection лежит отдельно в adapter/export. Журнал не является криптографической аттестацией произвольного импорта |
| Retrieval в эксперименте | `coordinator._read_only_result`, `_rank_memory_matches`: ASCII `[a-z0-9]{3,}`, OR substring, optional ranking exact-ref / hits / words / lexical ref, затем top_k. [e24_working_memory.py](../../labs/virtual_anima_lab/python/lifecycle/e24_working_memory.py): `world_model`, `context_for_cognition`, `raw_evidence`; проверяет Raw/Core/derived evidence, OFF оставляет latest captured scope. Native adapter дополнительно исключает surface из начальной model projection |
| Production Retrieval | [retrieval.py](../../anima/memory/retrieval.py): `RetrievalEngine.retrieve`, FTS/entity/relation/status scoring; [event_retrieval.py](../../anima/memory/event_retrieval.py): raw Event index с completeness state. Не вызываются лабораторным lexical tool; его ограничения не доказывают дефект этих алгоритмов |
| Source binding / verification | [source_policy.py](../../labs/virtual_anima_lab/python/cognition/source_policy.py): `TurnSourcePolicy` exposed event/sample/scope, Memory OFF запрещает history; [source_binding.py](../../labs/virtual_anima_lab/python/cognition/source_binding.py): `admitted_source_rows`; [claim_verification.py](../../labs/virtual_anima_lab/python/cognition/claim_verification.py): `ObservationClaimVerifier.verify/_load_view`, `_verify_captured_claim`; canonical Raw re-read и digest check, captured-sample scope |
| Hybrid Cognitive Result | [cognitive_result.py](../../labs/virtual_anima_lab/python/cognition/cognitive_result.py): `build_cognitive_result/_bound_records/_project_result`; unique source refs с step_indices, facts/verdicts и information; [result_reasoning.py](../../labs/virtual_anima_lab/python/cognition/result_reasoning.py): `build_reasoning` сохраняет original text и отделяет accepted terminal от verified claims. Дедупликация итогового списка не предотвращает повторные acquisition |
| Host temporal projection | [host_temporal_projection.py](../../labs/virtual_anima_lab/python/cognition/host_temporal_projection.py): `project_temporal_claims` только над уже admitted journal, deterministic historical/latest claims, verifier rereads, zero new model/service calls. Не участвует в выборе research tools |
| Frozen evidence/replay | [e26_reproducibility.py](../../labs/virtual_anima_lab/python/lifecycle/e26_reproducibility.py): `freeze_call/export_case/verify_case/verify_bundle/replay_request`, `normalized_request_sha`, `runtime_manifest/backend_snapshot`; canonical request JSON/hash, response hashes, bounded source integrity. CLI replay — один request без dispatch. Alias hash — строковая диагностика, не exact equivalence и не tool-ID policy |

Существующие архитектурные основания: [инициатива](e2-cognitive-initiative-v02.md), [FAST/DEEP](../ARCHITECTURE/Cognition_FAST_DEEP.md), [Memory/Retrieval](../ARCHITECTURE/Memory_and_Retrieval.md), [Stage 6](../ARCHITECTURE/Stage_6_Cognitive_Integration_Core.md). Deterministic resolver уже существует в canonical path; перенос его результатов в лабораторный context не реализуется здесь и потребует отдельного review области доверия.

## 3. Причины и исполняемые воспроизводители

Все ID ниже локальны для R9.4.0, не переопределяют F01–F17. [Новые characterization tests](../../tests/test_e26_r940_cycle_characterization.py) проверяют нынешнее поведение положительными assertions без xfail. Имена в таблице приведены без общего префикса `test_r940_`.

| ID / проявление | Причина по коду; измеренное воспроизведение | Test suffix / граница |
| --- | --- | --- |
| C01: premature finish | Continuation только после stop, максимум один возврат, без проверки recoverability. search → stop → stop: STOPPED, incomplete, 3/4 calls, один ещё доступен, CONTINUATION_LIMIT | `second_stop_leaves_missing_evidence_with_budget_remaining`; STOPPED корректно не объявляется Task success; произвольное увеличение retry не обосновано |
| C02: no-gain continuation и расход после достаточности | После completed read цикл продолжает без evaluate_completion/gain check. Четыре lookup одного event: уже после первого SATISFIED, unique sources 1, ещё три чтения, 4 calls/16 synthetic reported output tokens, STEP_BUDGET_EXHAUSTED | `repeated_reads_consume_budget_after_sufficiency`; отсутствие финального текста не означает утрату полученных фактов; stop/presentation policy ещё предстоит спроектировать |
| C03: cross-tool redundancy | Latest и explicit Raw идут разными operation signatures, но в тот же `raw_evidence`. past → latest → explicit latest → stop: 3 acquisition source rows, 2 unique, `assess.repeated_proposals=0`; third read не меняет completeness | `cross_tool_same_source_is_not_repeated_proposal`; показывает слепую зону старой метрики, не нарушение provenance |
| C04: Memory OFF и bounded empty | evaluate_completion(empty_search) учитывает returned/possible_matches/truncated/query, но не availability; при OFF crate search пуст и SATISFIED, хотя history существует вне разрешённого scope | `memory_off_empty_search_is_satisfied_without_availability_verdict`; existing Cognitive Result правильно маркирует BOUNDED_MEMORY_SEARCH_NOT_WORLD_ABSENCE и не верифицирует всю прозу |
| C05: продолжение при недоступном history | Continuation не различает insufficient-retrievable и out-of-scope. При OFF: empty search → stop → такой же empty search → stop; 4 calls, нулевые Raw sources и completeness gain | `memory_off_continuation_repeats_unproductive_search`; не предлагает обход Memory OFF |
| C06: retrieval vocabulary | ASCII tokenization, minimum length 3, нет alias/translation: crate → 1, box/ящик/cr → 0 при существующем crate | `lexical_retrieval_has_no_alias_language_or_short_token_recall` (4 cases); только lexical lab path |
| C07: ranking/top_k | OR/category tie разрешается lexical ref; obstacle возвращает aaa раньше shortcut при top_k=1. Exact ref выбирает shortcut | `ranked_or_tie_and_top_k_can_omit_requested_entity`; проверка pure ranking, не реальная recovery C03_ALT trajectory |
| C08: retrieval не обязательно acquisition | Source crate уже exposed из frozen context; search возвращает 1 row, exposed bindings до/после одинаковы | `retrieval_can_return_only_already_exposed_source`; metadata может быть полезна, zero new IDs не равно zero semantic gain |
| C09: verifier work смешивается с acquisition | На одном и том же журнале past/latest/stop: build_cognitive_result делает 2 Raw rereads, Host ещё 2; повтор Host ещё 2, journal/requests/report неизменны; Host new_service_reads=0 | `host_on_off_same_journal_changes_no_acquisition_but_rereads_raw`; это необходимые integrity reads, не повод их удалить |
| C10: input identity | Изменение только native tool-call ID меняет следующий request SHA; event aliasing это не нормализует. Согласованная замена assistant id и tool_call_id восстанавливает равенство | `tool_call_id_only_difference_changes_subsequent_exact_request`; не проверяет model sensitivity |
| C11: replay boundary | Два replay_request посылают одинаковый request, новый tool ответ не исполняется; bundle bytes неизменны | `frozen_replay_repeats_one_request_without_dispatching_new_tool`; не full trajectory replay |
| C12: cost boundary | reserve допускает первый call, settle(8193 input) превышает default 8192 и запрещает следующий | `input_limit_is_post_call_reported_boundary_not_inflight_ceiling`; документированная граница reported accounting, не новый дефект terminal contract |
| C13: service unavailable до контекста | context_for_cognition вне model-call error handler. Controlled E24MemoryError из world_model выходит без report/result, calls=0, journal пуст | `unavailable_memory_before_context_has_no_turn_result`; fault injection показывает границу, не утверждает факт backend outage в Recovery |
| C14: requirement/tool asymmetry | verified_observation не считает inspect_latest_observation, хотя admitted Raw row содержит entity; latest → stop → stop остаётся incomplete | `latest_tool_does_not_satisfy_lookup_only_requirement`; намеренный существующий контракт, не менять его молча |

Связь с recovery остаётся гипотезой по конкретным траекториям: нужны call/journal IDs для attribution каждого fail. Установлены executable причины, которые могут производить наблюдаемые классы проблем. Из агрегированных quality gates нельзя заключить, что каждый провал обусловлен coordinator, retrieval или Host.

## 4. Спецификация измерений для R9.4.1

Измерения вычисляются offline из checked journal + frozen context + ordered calls; не подмешиваются в модель. Новый measurement sidecar должен иметь собственную версию, baseline SHA, case/turn/context IDs, hashes inputs и ссылки на record/call indices. Не изменять schema старых bundles и исторический `repeated_proposals`.

Единица — один turn и его call/operation prefixes. Фазы `research`, `model_claim_projection`, `host_projection`, `result_construction`, `verification` учитываются отдельно. Временные интервалы и роли вложенных чтений исключают double-counting. Проверки свежести/context_for_cognition также могут проверять всю историю; их internal I/O нельзя называть приобретением свидетельств.

| Измерение | Определение / denominator / unknown |
| --- | --- |
| Acquisition attempts / completed | Число предложенных / admitted completed research operations по kind; rejected отдельно. Stop, resume, projection и verifier calls не acquisition |
| Candidate references | Возвращённые retrieval IDs; `new_exposed_ids = exposed_after − exposed_before`, initial source set отдельно. Exposed set брать у соответствующей границы: coordinator full Context и native-visible projection могут отличаться |
| Unique evidence | `E_t` — множество admitted verified source identities `(world, epoch, source_ref, event_id, sample_id, raw_sha256)` к prefix t. Отдельно `unique_event_ids`, `unique_samples`, `unique_content_hashes`: одинаковые bytes разных событий не сливаются в один event. Conflicting binding/digest — integrity error, а не новый факт |
| Acquisition redundancy | Source-row occurrences минус `|E_t|`, cross-tool и same-tool отдельно; ratio делить на все eligible acquisition row occurrences. Exact repeated proposal signatures сохранить отдельной legacy метрикой. Retrieval metadata и verifier rereads сюда не входят |
| Verification | Число Raw re-read calls/bytes, claim candidates и verdicts по origin/status/reason; context integrity отдельно. First verification ранее exposed source имеет полезность даже при zero new IDs. Нет verdict — NOT_ASSESSED |
| Information gain | Вектор `Δexposed_ids`, `ΔE`, `Δverified_fact_keys`, `Δcovered_requirement_units`, `Δsearch_outcomes`, `Δavailability_state`. Fact key включает entity/predicate/value/source/scope. Search outcome key — query normalization + frozen scope + availability + full/truncated result digest; duplicate response имеет delta 0. Это наблюдаемые proxies, не Shannon entropy и не доказательство semantic gain |
| Completeness | `C_t = covered_units / required_units`, missing units и original evaluate_completion verdict отдельно. Temporal units: historical observation на каждую entity + один bound latest sample. Empty-search/no-service-read — отдельная binary prerequisite, а не доказательство истинности ответа. Нет requirement или нулевой denominator — NOT_ASSESSED, не 100% |
| Availability | Proposed sidecar enum: AVAILABLE_IN_SCOPE / DISABLED_BY_POLICY / PARTIAL_OR_TRUNCATED / SERVICE_UNAVAILABLE / INTEGRITY_REJECTED / UNKNOWN, с причиной и scope. OFF не означает физическое отсутствие памяти; empty при доступном bounded поиске не доказывает отсутствие в мире. Возможность получить именно missing unit оценивать отдельно, без скрытого answer key |
| Continuation | stop attempts, eligible opportunities, CONTINUE/declines с reason, remaining calls; subsequent gain, eventual completeness, calls до gain. Productive continuation = положительный Δcovered_units или первое требуемое verified evidence/search outcome при сохранённой integrity. Positive metadata gain без completeness gain хранить отдельно |
| Premature stop | STOPPED + incomplete при явно заданном requirement; recoverable подмножество — только missing units с наблюдаемым разрешённым путём получения в frozen scope. Incomplete при DISABLED не ошибка, требующая retry. Не сливать STOPPED и Task status |
| Cost / excess | Model calls/tokens/latency по фазам, service reads, verifier I/O, elapsed; известные subtotals + missing counters, никаких fabricated zeros. `t_sufficient` — первый checked prefix, satisfying current contract; calls/reads после него считать отдельно как research vs presentation/verification. No-service-read sufficiency немонотонна: forbidden read необратимо нарушает её; prefix metric не разрешает игнорировать нарушение |
| Retrieval effectiveness | Offline evaluator-only relevance labels: precision@k, recall@k, MRR и verification yield, доля relevant verified units на cost. Полный candidate universe/available relevance отдельно от truncated top_k и unavailable; zero relevant denominator = NOT_APPLICABLE. Labels, expected answers и hidden world state никогда не входят в policy/prompt |

No-gain candidate — delta всех применимых наблюдаемых компонентов равна нулю при стабильном frozen scope. Это консервативный диагностический сигнал, не universal verdict о бесполезности рассуждения. Смена availability и нужная повторная верификация не должны ошибочно блокироваться. Любая proposed policy использует только trusted observable state, а не evaluator labels.

## 5. Контролируемый экспериментальный протокол

Протокол фиксируется до исправлений. Каждому запуску — новый append-only output directory; frozen inputs открываются read-only, результаты и manifests создаются вне bundle. Только зарегистрированные read-only tools, никаких world effects или canonical integration.

### 5.1. Общие входы и блокировка смешений

1. Проверить исходный bundle штатным verify_bundle; записать archive SHA-256, manifest, Raw/case/request hashes, implementation SHA и clean worktree. Recovery bundles перечислить с точными путями/хешами до запуска; при отсутствии — NOT_RUN, не реконструировать оригинал.
2. Зафиксировать один frozen Context, Raw/Core/derived state, journal, requirements и adapter flags. Хэшировать полную host context и model-visible projection отдельно. World seed недостаточен: event IDs, context/turn/proposal IDs и предыдущие tool replies меняют input. Никаких новых observations внутри пары.
3. Сохранить модель/quantization/model SHA, backend executable SHA/version/argv/start marker, chat template и hash, declared wire/endpoint, enable_thinking, все фактические generation fields и значения default с отметкой known/unknown, tool schema/order/permissions, request serialization. Не менять модель, prompts, budgets, permissions, sampling seed или template ради результата. Если inference seed отсутствует, явно оставить NOT_SET_IN_PROFILE.
4. Записать GPU/CPU/offload/threads/batch/context length/parallel slots, backend config files hashes без секретов, concurrency, warmed state, prefix/prompt cache и slot reuse. Existing backend_snapshot не аттестует peer/environment/dynamic libraries. Неизвестную cache policy маркировать UNKNOWN; latency comparison тогда exploratory.
5. Выполнять serial, один outstanding request. Для fresh comparisons минимум 20 paired repetitions на каждый заранее выбранный case/context; order AB/BA чередовать по объявленной таблице до запуска. Не смешивать warm и cold блоки; отдельный cold-cache эксперимент допустим лишь с документированным одинаковым reset между arms и неизменной generation configuration. В каждой записи: block/pair/order/monotonic timestamp/backend start marker/cache state/request hash/status/usage.
6. R9 original seven templates × seeds 7/8 оставить compatibility stratum. До изменений выбрать отдельные held-out vocabulary/ambiguity/truncation/availability cases и опубликовать IDs/input hashes без ответов модели; оценочные labels хранить вне visible context. Repetitions одного контекста не являются 20 независимыми сценариями.

### 5.2. Матрица опытов

| Arm | Что фиксировано / единственное различие | Измерения и допустимый вывод |
| --- | --- | --- |
| H0/H1: Host off/on, identical Decision Journal | Один завершённый research report, checked records, Context и calls; H0 строит hybrid result без optional Host temporal presentation, H1 дополнительно вызывает project_temporal_claims на копии того же report. Не запускать research заново, не включать model claim projection в один arm | Acquisition, unique evidence, research calls и model text обязаны совпасть; Host facts/coverage/presentation и verifier cost отдельно. Это causal presentation effect при фиксированном journal, не Host research-quality improvement |
| F0/F1: frozen-context policy comparison | Снимок stores/context и exact initial model request одинаковы; только будущая system policy version различна; полный журнал отклонений и дальнейших requests | После первого различия траектории расходятся; нельзя называть все последующие requests matched. Сравнение end-to-end outcome/cost на frozen starting state |
| Q: identical request repeat | replay_request посылает один canonical payload N=20 раз, включая исходные tool IDs, messages, schemas и order; dispatch выключен | Exact response JSON hash equality, choices equality, отдельно finish classification, parsed operation/arguments/content, latency/usage. Response IDs/timing могут менять hash без semantic divergence; temperature=0 не гарантирует identity |
| I-event / I-turn / I-tool: ID-only variants | По одному классу opaque IDs за arm; биективная замена всех typed occurrences и ссылок, включая JSON внутри message content, без изменения остальных bytes/полей/порядка. Mapping задаёт host offline, не модель; одношаговый replay без dispatch | Проверить diff allowlist и согласованность provenance до inference; exact hashes ожидаемо различны. Сравнить parsed output после обратного mapping; не нормализовать prose как proof equivalence. Event aliases текущего normalized_request_sha недостаточны для tool IDs |
| T-recorded: full recorded-response trajectory | Rebuild isolated lab stores из проверенного Raw snapshot, привязать те же source IDs/Context; transport возвращает archived responses в исходном порядке. Каждый generated request до выдачи ответа обязан иметь исходный exact SHA; replay только read-only services | На первом request/outcome/admission divergence остановить replay и сохранить prefix, не подменять следующий request архивным. Проверить полный journal, budget, result и terminal contracts; latency/elapsed timestamps сравнивать отдельными diagnostics, не требовать их byte equality; это deterministic replay plumbing, не fresh model reproduction |
| T-fresh: full fresh trajectory | Тот же начальный frozen snapshot, fresh NativeLabAdapter/coordinator и backend; model выбирает tools, broker допускает только существующие read-only operations, сохраняет все replies | Не проигрывать архивные ответы после divergence. Матched prefixes и first divergence отдельно от дальнейшего outcome/cost. Failures/rejections/exhaustion сохраняются. Не смешивать с Q или T-recorded |

I-event/I-turn/I-tool изменяют только отдельную копию model-visible request, не Raw/Core stores, journal или archived hashes. Original-to-variant map проверяет ссылки на исходные source bindings; ответ variant не получает admission и не становится verified evidence. Для ID-variant full trajectory потребуется отдельно проверенный mapped broker; в данном протоколе I arms ограничены no-dispatch single-request comparison.

Уже H0 hybrid Cognitive Result содержит deterministic verified facts и COMPLETE typed coverage при достаточном admitted evidence. H1 проверяет добавочное temporal представление и его verification cost, не приписывает эти же факты Host второй раз и не обещает рост information completeness.

Existing `run_cases(host_temporal_projection=...)` не является чистым H0/H1: в Host profile выключается optional model claim projection, а исследования в разных запусках независимы. Числа Operation Gate из Recovery нельзя переименовывать в результат этого эксперимента.

### 5.3. Явная политика native tool-call IDs

- **EXACT_PRESERVE** для Q и T-recorded: каждый assistant tool_calls[].id и соответствующий tool.tool_call_id сохраняется byte-for-byte; порядок/аргументы/result content неизменны. Дубликаты, stale/cross-session binding или mismatch — fail closed действующего session contract.
- **BIJECTIVE_RENAME** только для I-tool: одна mapping на весь transcript выбранного request, каждый ID уникален в исходной scope, все его typed связи заменяются согласованно; map/hash и inverse mapping приложены к sidecar. Нельзя заменить только assistant ID или только tool reply, молча чинить произвольные строки либо использовать mapping для обхода source admission.
- **FRESH_ACCEPT_AND_PROPAGATE** для T-fresh: backend-generated IDs принимаются только действующим validator, соответствующий broker reply использует тот же ID. Для сравнения допустим отдельный diagnostic canonical ordinal по first appearance. Оригинальные bytes всегда сохраняются; canonicalized hash никогда не называется exact request equality.
- ID renaming не меняет provenance authority: Event/Sample binding, world/epoch и digest проверяются независимо. Изменённые fixtures являются новыми экспериментальными производными, а не resealed historical evidence.

### 5.4. Analysis / stopping rules

До model runs заморозить primary endpoints: information completeness (separately by availability), redundant acquisition rows и model calls после sufficiency; safety endpoints — source integrity, read-only invariants, terminal contracts. Secondary: typed/model/Host coverage, gain vector, retrieval quality, tokens/latency. Не объединять их в один PASS.

Показывать raw paired numerators/denominators, per-template/per-seed и held-out results, median/quantiles cost. До запуска определить clustering unit как frozen scenario (template, seed, Context hash), с равным весом scenario. Для primary paired differences использовать cluster bootstrap: 10000 resamples scenario с replacement, все repetitions scenario сохраняются вместе, 95% percentile interval; offline analysis RNG seed=940, не generation seed. Для заключения о росте lower bound completeness delta должен быть >0; для non-regression — ≥0 (margin 0), для снижения cost/redundancy upper bound delta должен быть <0. Если interval пересекает порог, gate INCONCLUSIVE; raw point improvement не заменяет его. Низкое разнообразие исходных 14 scenarios ограничивает generalization даже при узком interval. Binary differences — paired discordant counts; uncertainty — paired interval с clustering по frozen scenario, repeated draws не независимые cases. При недостатке сценариев или неизвестном cache/backend state вывод INCONCLUSIVE, а не significance claim. Missing usage исключает total-token claim, но сохраняет known subtotal. Model prose review отдельно, с evaluator rubric до запуска и без присвоения verified whole-answer статуса.

Остановить конкретную пару при integrity/context/backend/config mismatch и маркировать INVALID_PAIR, сохранить обе попытки; не делать selective rerun только плохого arm. При terminal rejection сохранить reported usage и diagnostic; автоматического retry нет. При одинаковых inputs, но расходящихся responses — зарегистрировать nondeterminism, не исправлять frozen context. Нулевые нарушения typed contracts обязательны; недостаточная model quality не оправдывает их ослабление.

## 6. Последовательный план и критерии R9.4.1–R9.4.4

Начало реализации возможно только после рассмотрения characterization и протокола. Следующие типы/названия — проект, не существующий API. Сначала фиксируются measurement/availability semantics, затем policy, retrieval и end-to-end evaluation; никакой canonical integration.

| Этап | Изменение архитектуры в read-only lab | Измеримый acceptance gate |
| --- | --- | --- |
| R9.4.1 — observable state | Versioned offline measurement sidecar и host-owned evidence/requirement/availability view; переиспользовать admitted_source_rows/evaluate_completion/verifier, не копировать provenance policy. Отличать source exposure, acquisition и verification; предусмотреть unavailable-before-context diagnostic без fabrication result/facts | На всех C01–C14 fixtures exact expected counts, prefix completeness и availability; same-tool/cross-tool duplicate видны, verifier не увеличивает acquisition; UNKNOWN при отсутствующих данных. 100% inconsistent-source negatives rejected; historical metric values/bundle bytes неизменны. Никакого policy-effect изменения |
| R9.4.2 — sufficient-information and continuation policy | Явное system-owned решение до следующего research call и после outcome; учитывать missing units, availability, bounded gain history и remaining existing budget. Лимиты не повышать, generation/prompt/tool catalog не менять. Отделить прекращение acquisition от accepted model final/presentation; не фабриковать STOPPED или response. Contract changes лаборатории требуют явного review, а не добавления через characterization | На fixed repeated-read case после первого достаточного evidence — 0 дополнительных дублирующих acquisition; на OFF/impossible history — 0 бесполезных повторных retrieval. На recoverable missing-evidence fixture — получить разрешённый missing source в прежних 4 calls; не вызывать retry после incomplete terminal. Forced system finish сохраняет partial/no-final semantics hybrid result; 0 false Task success, 0 unsafe admissions, 0 bypasses verifier. No-service-read violation не «чинится» продолжением |
| R9.4.3 — retrieval efficiency | Исследовать query normalization/ranking и выбор доступных source references, затем отдельное согласованное изменение deterministic lab Retrieval. Не добавлять LLM tools, model authority, extra prompt или скрытые aliases из answer keys. Reuse already admitted evidence keyed by scope/digest только при сохранении проверки свежести; integrity rereads не удалять ради cost | На frozen ambiguity/exact-ref corpus precision@k/recall@k/MRR не хуже baseline по каждому контрольному stratum; минимум один заранее заданный ranking failure исправлен. На held-out cases положительный verification yield без роста false source binding; 0 source-policy regressions. Language/alias cases могут остаться explicit unsupported; не объявлять semantic retrieval без его проверки. Все generation fields прежние |
| R9.4.4 — controlled validation | Реализовать/проверить Q/I/T harness отдельно от production; затем запустить матрицу на reviewed frozen inputs. Hybrid result и R9.3 terminal diagnostics остаются обязательны; deterministic resolver reuse только для явно доступного trusted результата с собственной границей review | T-recorded: 100% exact request hashes и ordered journal/outcome equivalence на выбранных compatible trajectories; INVALID/unsupported отдельно. Q/I: N=20, declared ID maps, все order/cache/backend fields known или explicit unknown. H0/H1: 0 изменений research inputs/reads/calls, Host output только verified admitted sources. На fixed defect corpus: 100% R9.4.2 policy criteria; fresh paired primary completeness не хуже baseline, redundancy и post-sufficiency research calls ниже baseline хотя бы в одном заранее заданном stratum, median total model calls не выше baseline. Малый/неубедительный fresh corpus — INCONCLUSIVE, не PASS causal benefit |

Каждый этап: targeted negatives, appropriate regression и project checks, clean commit, сохранённые failures и evidence hashes. Full regression и historical frozen verification повторить на финальном implementation snapshot; независимый аудит остаётся R9.5. Ни один этап не разрешает Knowledge writes, дополнительные tool permissions, canonical Cognitive Result integration или переход к E2.6 closure.

## 7. Локальная проверка R9.4.0

Команды из корня репозитория (Python из существующего `.venv`, без новых зависимостей):

```bash
.venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_e26_r940_cycle_characterization.py
.venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_e26*.py tests/test_e25a_cognition.py tests/test_cognitive_coordinator.py
bash scripts/check.sh
.venv/bin/python -B -m pytest -q -p no:cacheprovider
```

Локальное исполнение: CPython 3.14.4, существующий `.venv`, без новых зависимостей.

| Проверка | Результат |
| --- | --- |
| Новые characterization | 17 passed / 0.99 s; PASS = ограничения воспроизведены |
| E2.6 + E2.5a + canonical coordinator | 580 passed / 16.47 s |
| Documentation/source snapshot + characterization после исправления fixture allowlist | 56 passed / 6.13 s |
| Project checks | PASS: 204 pages, 1438 local links, 462 Python files, 21 Bash files |
| Первый полный прогон до фиксации snapshot | 3084 passed, 11 failed / 100.52 s: 6 documentation fixture failures из-за отсутствующих linked lab sources и 5 release evidence gates, требующих clean Git tree |
| Полный прогон на clean commit | PENDING: выполняется после commit; clean-tree guards не отключаются |

Для исправления documentation fixtures расширен только точный `_VAL_DOC_SOURCES` allowlist в [source_tree.py](../../tests/source_tree.py) на девять файлов, указанных в инвентаризации; существующая [проверка bounded snapshot](../../tests/test_source_tree.py) покрывает их копирование и исключение unreferenced/private/log files. General labs tree по-прежнему не копируется. Это test infrastructure, не изменение lab behavior. Первые 11 failures сохраняются как результаты промежуточного прогона, не как обнаруженные когнитивные дефекты.

Scope: четыре research документа и три test/test-infrastructure файла; `anima/`, `labs/`, `scripts/`, config, model/prompt/generation budgets/tool permissions не изменены. Исходные frozen evidence и исторические результаты не переписывались. Новые тесты обращаются к synthetic temporary bundles, а не к Recovery archives.

Эти команды не запускают fresh LLM/Godot gate. Synthetic tests создают только изолированные временные stores. Не считать их повторным выполнением R9.3 Recovery. Fresh Q/I/T experiments и independent archive verification — NOT_RUN в этом этапе; протокол подготовлен до исправлений. Остановиться на R9.4.0.
