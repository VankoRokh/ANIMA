# ANIMA v0.2 — R9.4.1a: Observable Cognitive State

**Дата:** 27 ноября 2026. **Baseline:** `0cde809a9d0f5495d93706a25a9dbe404cc48515`.
**Ветка:** `work/v02-e26-r9-remediation`. **Граница:** измерения и isolated experimental harness; R9.4.2/R9.4.3 и массовые fresh inference не выполняются.

Основания: принятый [R9.4.0 characterization/protocol](e2-6-r940-characterization-v02.md), [реестр R9](e2-6-r9-remediation-v02.md), [когнитивная инициатива](e2-cognitive-initiative-v02.md), [FAST/DEEP](../ARCHITECTURE/Cognition_FAST_DEEP.md), [Memory/Retrieval](../ARCHITECTURE/Memory_and_Retrieval.md). R9-Q02/Q03/Q04, CA-06 и R9-E01/E02 сохраняют прежние статусы. Наблюдаемые proxies не устанавливают семантическую полезность, истинность всего ответа или Task success.

## 1. Архитектура и область доверия

[observable.py](../../labs/virtual_anima_lab/python/cognition/observable.py) — отдельный offline consumer. `measure_turn` получает точный in-process `E25LabCognitiveCoordinator`, report, ordered native calls и CompletionRequirement. `_bound_records` получает journal через проверяющий hashes `decision_records`; совпадение turn/context/step/outcome проверяется повторно. Произвольный JSON journal не получает этот API как новую authority. Для импортированного snapshot experimental harness сначала выполняет штатные `verify_bundle`/`verify_case`/`verify_raw`, затем восстанавливает **новые изолированные** stores и заново получает проверенный journal.

Контракт sidecar — `anima.lab.observable_cognitive_state/0.1`: baseline SHA, case/turn/context identity, отдельные SHA-256 context/report/journal/calls и ссылки `record_indices`/`call_indices`. Sidecar не меняет schema frozen bundles, старые completion verdicts или `repeated_proposals`. Он не импортируется coordinator/adapters/canonical policy. Новые API не передают measurements, evaluator labels или hidden world state в model requests.

`TurnSourcePolicy`, `admitted_source_rows`, `evaluate_completion` и существующий observation verifier переиспользуются. Для каждого prefix `_verify_captured_claim` получает **только records этого prefix**, с canonical Raw loader существующего verifier. Финальный Cognitive Result и последующие verdicts не используются для восстановления прошлого. Frozen Context берётся из совпадающего checked context либо явно переданного `frozen_context` с проверкой `ctx_` hash. Без него и без journal context остаётся UNKNOWN.

Prefix 0 соответствует состоянию до первого вызова; дальше сохраняются call boundaries, в том числе stops, и соответствующие operation prefixes. Stop может иметь тот же step_index, что будущий read; привязка требует совпадения typed proposal, поэтому будущий read не попадает в stop prefix. Если ordered calls не переданы, доступны operation prefixes, а call costs/boundaries остаются UNKNOWN. Полнота research/projection call sequence сверяется с report, в том числе stop-only turns; неполный переданный trace отвергается, отсутствующий trace остаётся UNKNOWN. Final report status и final budget хранятся отдельно от промежуточных completion prerequisites; промежуточный `model_stopped` не фабрикуется.

### Контракты измерений

| Данные | Определение и граница |
| --- | --- |
| Exposure | initial/full host bindings, candidate references, completed-result exposures; native-visible typed IDs из host user/tool messages соответствующего request отдельно. Assistant proposals не расширяют exposure. Без projection boundary — UNKNOWN |
| Acquisition | typed proposed research operations, admitted completed service reads, rejected отдельно, counts по kind. Generated proposals, остановленные budget до journal admission, учитываются как attempts с `admission=NOT_RECORDED`; `journaled_attempts` и ссылки на unrecorded proposals отдельно. Admission/outcome для них не фабрикуются. Stops/resume/Host/result/verifier не acquisition |
| Verified identities | `(world, epoch, source_ref, event_id, sample_id, raw_sha256)`, canonical re-verification до публикации. Event/sample/content-hash cardinalities раздельны; одинаковый hash не сливает события |
| Redundancy | eligible Raw acquisition row occurrences минус unique identity count. Duplicate при уже встречавшемся tool — same-tool, иначе cross-tool; каждый occurrence ровно в одной категории. Denominator — все eligible rows; при нуле ratio не определено. Retrieval metadata/verifier rereads исключены |
| Fact gain | deterministic requirement-directed facts и opt-in typed model candidates по явно заданному `claim_phase`; все existing predicates проверяются existing verifier. Key содержит entity/predicate/value/event/sample/scope, origins отдельно, одинаковый fact не удваивается. Model candidate проверяется только на boundary появления; unsupported early claim не верифицируется поздним read ретроспективно. Новое свойство прежнего source даёт fact gain при ΔEvent IDs=0. Без model claim phase — NOT_ASSESSED для этого origin; prose usefulness — NOT_ASSESSED |
| Coverage | отдельные historical units по entities и один bound latest sample для temporal; lookup-only observation units для прежнего observation contract; empty-search/no-read binary prerequisite. Required/covered/missing/ratio и оригинальный completion verdict раздельны. Нет requirement — NOT_ASSESSED |
| Search outcome | normalized query + frozen scope + availability + полный result digest, включая truncation. Повторный одинаковый outcome даёт delta 0. Новые search metadata могут давать gain при zero new Event IDs |
| Gain vector | изменения exposure, identities, verified facts, covered units, search outcomes, availability. Availability сравнивается с непосредственно предыдущим prefix. `no_gain_candidate` — ограниченный proxy, без policy effect |
| Continuation | исходные решения/reasons/remaining calls, stop attempts, opportunities; последующий coverage gain, calls до него и metadata gain отдельно. Recoverability недостающих units — UNKNOWN без наблюдаемого разрешённого пути; не выводится из evaluator answers |
| Resources | model calls и известные token/latency subtotals по research/model_claim_projection/host_projection/result_construction/verification; missing counters отдельно. Старое имя `claim_projection` отображается в measurement phase без изменения входа. Timing/usage не оцениваются догадкой |
| Verification cost | measurement-only binding checks, actual Raw rereads/bytes, failed rereads, claim candidates/verdicts по origin/status/reason; source validation checks отдельно. Prefix measurements сами выполняют повторные проверки; это **новая стоимость измерителя**, не реконструкция исторического verifier I/O |
| Sufficiency/excess | первый satisfying prefix; последующие typed research acquisitions, все research model calls, terminal text calls и completed service reads отдельно. Финальный text call не считается новым acquisition. Для no-service-read начальная достаточность может быть утрачена после forbidden read; `remained_satisfied` сохраняет нарушение |

`verification.status=NOT_ASSESSED` при отсутствии claim candidates. Неинструментированные historical context integrity I/O и hardware cost обозначаются явно. В H harness вложенные context checks и непосредственные Raw rereads имеют разные роли; `raw_rows_checked` и `raw_rereads` нельзя складывать как независимые acquisitions или суммировать как непересекающиеся физические bytes.

### Availability и ошибки

| State | Проверяемое основание / scope |
| --- | --- |
| AVAILABLE_IN_SCOPE | admitted bounded service read; empty search при memory enabled + untruncated означает доступный поиск без matching rows. Scope ограничен frozen world/epoch/source/latest/memory mode, `world_absence=false` |
| DISABLED_BY_POLICY | frozen Context.memory_enabled=false; history запрещена, latest-only scope сохраняется. Это не отсутствие физической памяти |
| PARTIAL_OR_TRUNCATED | completed search с `truncated=true`; bounded top_k reason |
| SERVICE_UNAVAILABLE | только явно типизированный `ControlledServiceUnavailable(service, reason_code, scope)` на диагностической границе |
| INTEGRITY_REJECTED | `E24MemoryError` как нарушение Raw/provenance/derived memory в pre-context diagnostic; inconsistent source measurements fail closed, facts не публикуются |
| UNKNOWN | нет достаточного наблюдения; historical `SERVICE_REJECTED` объединяет несколько причин и **не** переклассифицируется в outage |

`diagnose_before_context` вызывается внешней границей после контролируемого отказа **до** Context. Результат имеет `context_status=NOT_FORMED`, ограниченные service/reason/scope и identity; он не содержит Cognitive Result, sources, facts или model calls. Произвольные KeyError/RuntimeError/ValueError не принимаются как service unavailability. Старый coordinator по-прежнему выбрасывает pre-context ошибку; автоматически перехватывающий её production wrapper не добавлен. В частности, произвольный текст E24MemoryError не превращает integrity failure в outage. Для невыясненной причины остаётся UNKNOWN/исходное исключение.

## 2. Experimental harness

[e26_r941_experiments.py](../../labs/virtual_anima_lab/python/lifecycle/e26_r941_experiments.py) реализует отдельные H/Q/I/T-recorded entry points и CLI `prepare`/`run`. Output directories создаются эксклюзивно вне repository и известных frozen bundle roots. Archived originals не перезаписываются. Все ID variants — новые производные requests с original/variant hashes, mapping/inverse mapping/hash и changed paths; они не reseal historical evidence.

- **H0/H1:** один checked journal/report/calls. Дважды одинаковый hybrid result constructor, H1 дополнительно temporal Host presentation; research inputs/model text/acquisition совпадают. Model claim assessment не включается асимметрично. Исторический optional projection, если был, остаётся фиксированной metadata в обоих arms. Измеряются result/Host rereads и отдельно nested context integrity rows/bytes. Это presentation effect при фиксированном research, не улучшение research quality.
- **Q:** canonical payload с исходными tool IDs передаётся N=20 раз без dispatch. Сохраняются request, original response, все новые responses, SHA-256, choices/finish/parsed message, usage, monotonic start/latency и first response divergence. Different response id может менять full hash при равных choices. Ошибка сохраняется, автоматического retry нет.
- **I-event/I-turn/I-tool:** ровно один класс typed IDs; проверенная исходная source/turn scope либо complete native tool binding; disjoint bijection и inverse proof сохранения остальных полей. JSON внутри content/arguments редактируется по leaf spans с сохранением остальных bytes, whitespace и order. Prose не нормализуется. Unknown fields/неполный mapping/duplicate or stale tool links отвергаются. Output сравнивается после inverse typed argument/structured-claim mapping; известный claims JSON проверяется existing `parse_final`, `answer` prose сохраняется точно; произвольный текст не нормализуется. Raw choices/hash и parsed content отдельно. Новые generated tool IDs сохраняются в raw responses и не выдаются за semantic operation differences.
- **T-recorded:** verified three-sample Raw snapshot восстанавливается через existing capture/recovery в новых Core/derived stores. Во время isolated ingress admission локально фиксируется UUID factory для сохранения archived Event IDs; это serial offline restoration, без изменения canonical ingress. Journal не импортируется: его заново формирует coordinator. Transport сверяет каждый **generated** exact request SHA до выдачи archived response. Перед следующим ответом сравнивается уже сформированный journal prefix; final journal, budget (кроме elapsed diagnostic), Cognitive Result и terminal fields проверяются. На первом request/admission/outcome/result mismatch — остановка и сохранение generated prefix/first divergence; архивный request никогда не подставляется вместо generated.

В `run` перед inference обязательны clean implementation SHA, verified unchanged bundle/map hashes, backend executable SHA/argv, локальный model SHA и declared runtime fields. PID/start marker проверяется до/после каждого вызова. Неизвестные cache/warm/template/hardware/threads/batch/slots/external config отмечаются UNKNOWN, выводы о latency остаются exploratory. Это не attestation HTTP peer, GPU state, dynamic libraries или default backend settings.

Evaluator-only `retrieval_metrics` — отдельный pure consumer. Unknown relevance не считается negative label; recall/MRR при неизвестном candidate universe — NOT_ASSESSED, при zero relevant denominator — NOT_APPLICABLE. Runtime measurement/policy API не принимает relevance labels. Canary tests проверяют отсутствие labels в requests, journal и sidecar; дополнительно проверяется отсутствие imports измерителя/evaluator в model adapter и policy coordinators.

## 3. Synthetic acceptance и ожидаемые значения

[Observable tests](../../tests/test_e26_r941_observable.py) используют те же реальные memory/coordinator/Native adapter механизмы, что неизменённые [R9.4.0 characterization tests](../../tests/test_e26_r940_cycle_characterization.py). [Harness tests](../../tests/test_e26_r941_harness.py) проверяют positive и negative controls. Это отдельные regression tests, исторические assertions не редактируются.

В таблице `A/U/S/X/F` = completed acquisition / unique verified sources / same-tool duplicates / cross-tool duplicates / deterministic requirement-directed facts. `P` — первый sufficient operation prefix; `R+` — typed acquisitions после него, `M` — все research model calls. Проверяется также каждый call prefix, missing coverage и оригинальные completion verdicts.

| Case | Exact synthetic expectation |
| --- | --- |
| C01 | A/U/S/X/F=1/0/0/0/0; P отсутствует; R+=0; M=3; CONTINUE → CONTINUATION_LIMIT; incomplete stop и UNKNOWN recoverability |
| C02 | 4/1/3/0/1; P=1; R+=3; M=4; unique Event/sample/hash=1/1/1; каждый следующий read без нового fact/coverage |
| C03 | 3/2/0/1/2; P=2; R+=1; M=4; после sufficiency ещё 2 model calls, включая terminal text |
| C04 | 1/0/0/0/0; P=1 по прежнему empty-search contract; R+=0; M=2; DISABLED_BY_POLICY, не world absence |
| C05 | 2/0/0/0/0; P отсутствует; M=4; один distinct search outcome, continuation без coverage gain; OFF |
| C06 | crate/box/ящик/cr → returned 1/0/0/0; 0 Raw acquisitions/facts; AVAILABLE_IN_SCOPE; empty results bounded |
| C07 | query lab, top_k=1 → truncated bounded search, PARTIAL_OR_TRUNCATED; 0 verified sources/facts. Не исправляет legacy ranking/tie |
| C08 | search A=1, U=0; new exposed IDs=0; первый search outcome gain=1; subsequent stop prefix gain=0; отсутствие новых IDs не означает отсутствие metadata gain |
| C09 | research 2/2/0/0/2, P=2, R+=0, M=3; H0 result rereads=2; H1 result rereads=2 + Host rereads=2, context integrity rows отдельно; journal/calls неизменны |
| C10 | tool-ID-only variant меняет exact request hash; обе native links изменены согласованно; другие ID classes/prose/order сохраняются |
| C11 | Q synthetic N=2: exact same payload дважды, dispatch=0; response-id-only difference: exact hash differs, choices equal; T full positive и first-request/outcome negative controls |
| C12 | input=8193: model calls=1, generated attempts=1, journaled attempts=0, completed=0, verified sources/facts/rereads=0; NOT_RECORDED proposal и прежний INPUT_USAGE_EXCEEDED. Отдельно missing input counter=1; no requirement → coverage NOT_ASSESSED. Прежний boundary characterization неизменён |
| C13 | explicit controlled diagnostic → SERVICE_UNAVAILABLE; E24 integrity → INTEGRITY_REJECTED; Context NOT_FORMED; без fabricated result/facts/calls; произвольные exceptions отвергаются |
| C14 | 1/1/0/0/0; latest source acquired, lookup-only coverage=0; P отсутствует, M=3; прежняя asymmetry сохранена |

Дополнительные negatives: conflicting digest на повторном source, forged sample/event/source, ложный entities_observed; все отвергаются. Equal-hash/different-event identity тест проверяет раздельный ключ. Stop-before-later-read fixture имеет `(operation_prefix,U)=(0,0),(1,0),(1,0),(2,1),(2,1)`; будущая верификация не заполняет первые prefixes. No-service-read coverage меняется 1 → 0 и не маскируется первым sufficient prefix. Отдельные tests: lookup → новый verified bearing claim даёт facts 0/1/2 при identities 0/1/1; ранний неподкреплённый claim → поздний read даёт facts 0/0/1/1, без ретроспективного model verdict. Optional claim projection увеличивает fact count при неизменном acquisition и имеет отдельный resource phase.

## 4. Evidence владельца и immutability

Постоянный output root этого этапа:

```text
/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r941a-0cde809a/
```

`evidence-inventory-before.json` сохраняет полный SHA-256 inventory; `evidence-verified-checksums.json` повторно проверяет bundles, owner checksum listings и byte equality с исходным inventory. Воспроизводитель — [audit_e26_r941_evidence.py](../../scripts/audit_e26_r941_evidence.py). Все оригиналы открываются только для чтения. Результаты не хранятся только в `/tmp`; synthetic stores/requests/responses и логи находятся под постоянным root.

| Archive в `/home/vanko/ANIMA-Evidence/archives/` | SHA-256 |
| --- | --- |
| ANIMA-E26-Audit-Evidence.zip | `2804cbba31db882da46324eace92698dbc73cf4a915a83434dae3625a0b26ed3` |
| ANIMA-E26-Independent-Audit-Reproduction.zip | `bf65bdaf470f703e55b43aaebcd74abb13a54ac841979920804500699326caaa` |
| ANIMA-E26-R1-R6-Evidence.tar.gz | `bab0fbd088250dc74a73e1989e91887c4fa28c299d1851c1b633169fa2739449` |
| ANIMA-E26-R7-Evidence.tar.gz | `28e0a7cb1a26435c53c758e34dbf11bcc56978fe8912b242597adc5683870827` |
| ANIMA-E26-R8-Independent-Reproduction.zip | `e8cd813661834b452d9c9ff2fb39f7c7bac018bb10f8a5930a058dd53a30ef1a` |
| ANIMA-E26-R92-Evidence.tar.gz | `5a197c471d6604e7e0a929002b467811257b5b7573305938e60a1363478bcfca` |
| ANIMA-E26-R93-Recovery-Evidence.tar.gz | `ae9ee91bf619fb029876f0b74ecd04ef60851642b65b3cd91aaccf497dd50385` |

Все 7 archive hashes совпадают с owner checksum listings. Проверены 206 Recovery files, включая вложенные listings. Штатный verify_bundle: historical **6/6** (60 cases, 36 Raw, 200 requests) и Recovery **2/2** (28 cases, 12 Raw, 93 requests). Всего **88 cases, 48 Raw, 293 requests**. Это integrity/source-binding verification; independent R9.5 audit и backend attestation этим не заменяются. Архивы не распаковываются поверх оригиналов; используются уже предоставленные recovered copies.

Для baseline replay пригодны exact request/response JSON, Raw bindings и checked journals двух Recovery bundles. Offline smoke C06/7 Control совпал по 3 generated requests, ordered journal, budget/verdict/result, без inference. На clean snapshot `8616639373b815b8998ecddaede4ff0867a1e368` full T-recorded: Control 14/14, 47 exact requests; Host 14/14, 46 exact requests; journal/budget/result matched, first divergence отсутствует. H0/H1 на 4 temporal journals: 3 VERIFIED, Control C06/7 INFORMATION_INCOMPLETE, оба arms сохраняют одинаковый hybrid result; ещё 24 scenarios NOT_APPLICABLE. Это фиксированный journal/presentation effect, не causal research-quality benefit. После усиления fact-prefix измерений проверки повторяются на окончательном implementation snapshot. Legacy/Choice/canonical logs не объявляются full replay bundles.

## 5. R9.4.1b: замороженный план и команды

Подготовлены `plan-control-v2/run-manifest.json` и `plan-host-v2/run-manifest.json` под постоянным root: по 14 frozen scenarios (7 templates × seeds 7/8), case/Raw/request/map hashes, N=20, serial concurrency=1 и заранее заданный AB/BA order. Исходные `plan-control/plan-host` сохраняются как промежуточные outputs, **не использовать для inference**. В актуальных v2 manifests на каждый bundle: Q=14, I-event=14, I-tool=12 подготовлены; I-tool на 2 arithmetic trajectories и все 14 I-turn — UNSUPPORTED (typed IDs отсутствуют). Новые turn IDs не вставляются в request ради запуска arm.

`r941b-run-index.json` фиксирует SHA двух актуальных plans, `held-out-inputs.json` (H01–H08: vocabulary/ambiguity/truncation/OFF/controlled fault scopes) и отдельного `evaluator-only-labels.json`. Held-out inputs заморожены для будущей validation, не включены в baseline Q/I matrix; labels и canary не читает runtime/policy.

Primary/safety endpoints, clustering unit frozen scenario, bootstrap 10000/seed 940/95% percentile и INCONCLUSIVE при недостаточной основе зафиксированы до fresh runs. Q — 20 single-request repetitions; I — 20 paired repetitions original/variant, order AB/BA. При исполнении обоих планов полностью: Q=560 fresh requests, I-event=1120, I-tool=960, I-turn=0; **2640 fresh requests не запущены в R9.4.1a**. T-recorded и H не выполняют fresh inference. Это baseline tooling, policy comparison/T-fresh здесь не реализованы.

Команды выполняются из repository root существующим `.venv`. Для каждого исполнения нужен новый output directory; имена ниже зарезервированы для R9.4.1b и в этом этапе не используются:

```bash
EVIDENCE=/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r941a-0cde809a
NEXT=/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r941b-run-01
mkdir -p "$NEXT"

# Read-only preflight; exclusive JSON output.
.venv/bin/python -B scripts/audit_e26_r941_evidence.py \
  --output "$NEXT/evidence-before.json" --compare "$EVIDENCE/evidence-inventory-before.json"

# Recorded-response replay and fixed-journal Host pairs: no model backend.
for PROFILE in control host; do
  PLAN="$EVIDENCE/plan-$PROFILE-v2/run-manifest.json"
  .venv/bin/python -B -m labs.virtual_anima_lab.python.lifecycle.e26_r941_experiments \
    run "$PLAN" --arm T-recorded --output "$NEXT/$PROFILE-T-recorded"
  .venv/bin/python -B -m labs.virtual_anima_lab.python.lifecycle.e26_r941_experiments \
    run "$PLAN" --arm H --output "$NEXT/$PROFILE-H"
done
```

Для Q/I перед запуском сохранить текущие operator-observed backend/cache/template/hardware settings в `$NEXT/backend-state.json`. Все поля обязательны; UNKNOWN допустим как отсутствие знания, а не как отрицание cache/config. PID должен быть текущим PID прежнего backend profile, а не архивным числом. Shell использует текущий PID read-only; harness дополнительно проверяет executable/argv/model hash/start marker:

```bash
cat > "$NEXT/backend-state.json" <<'JSON'
{"cache_state":"UNKNOWN","warm_state":"UNKNOWN","slot_reuse":"UNKNOWN","chat_template_sha256":"UNKNOWN","hardware":"UNKNOWN","threads":"UNKNOWN","batch":"UNKNOWN","parallel_slots":"UNKNOWN","external_config_hashes":"UNKNOWN"}
JSON
BACKEND_PID=$(pgrep -f '^/home/vanko/Projects/llama.cpp/build-cuda/bin/llama-server -m /home/vanko/Projects/models/Qwen3-4B-Q4_K_M.gguf --alias Qwen3-4B-Q4_K_M --host 127.0.0.1 --port 8085 --ctx-size 4096 --n-gpu-layers 99 --jinja$')
# Должен быть ровно один PID. Пустой/множественный результат не запускает run.
for PROFILE in control host; do
  PLAN="$EVIDENCE/plan-$PROFILE-v2/run-manifest.json"
  for ARM in Q I-event I-turn I-tool; do
    .venv/bin/python -B -m labs.virtual_anima_lab.python.lifecycle.e26_r941_experiments \
      run "$PLAN" --arm "$ARM" --backend-pid "$BACKEND_PID" \
      --backend-state "$NEXT/backend-state.json" --output "$NEXT/$PROFILE-$ARM"
  done
done
.venv/bin/python -B scripts/audit_e26_r941_evidence.py \
  --output "$NEXT/evidence-after.json" --compare "$EVIDENCE/evidence-inventory-before.json"
```

Backend не перезапускается и generation settings не изменяются этими командами. После failures/terminal rejections нет selective rerun или retry. UNKNOWN cache/config не разрешает заключение о причинном latency effect. Ответы ID arms не получают admission и не становятся verified evidence. Выход H/Q/I/T не объединяется в один quality PASS.

## 6. Ограничения и неподдерживаемые cases

- Только bounded lab three-sample Raw format; canonical integration, произвольная база production, иной Event-ID import format, world actions и изменяющие memory tools не поддерживаются.
- CLI восстановление профиля поддерживает verified `temporal_completion` bundles; старые R1–R7 profiles могут проверяться штатным verify/replay_request, но не объявляются поддержанными этим full-trajectory runner.
- Missing Raw/Core binding, missing responses, malformed tool chain, unknown typed ID locations, отсутствующий в request ID class, archived elapsed-dependent stop, изменённый task/schema/prompt/backend/config дают divergence/unsupported, не подстановку payload, synthetic timing или новый исторический bundle.
- T-recorded сравнивает reported budgets и terminal contracts; реальные latency/elapsed diagnostics сохраняются, но byte equality timing не требуется. Elapsed-dependent trajectories не эмулируются замороженными часами.
- Live mid-turn observer, callback/session migration, non-default focus_refs и нестандартные budgets требуют отдельного reviewed reconstruction profile; CLI их не угадывает. Function-level runner принимает явные существующие ResourceLimits, без повышения бюджетов.
- Общий detector semantic usefulness, free-prose verifier, автоматическое восстановление missing units, semantic Retrieval, statistical significance engine и T-fresh не реализованы. Evaluator labels не входят в policy. No-gain proxy не управляет остановкой.
- Pre-context diagnostic — opt-in external consumer, не новый report/status coordinator. Existing errors и historical verdicts сохраняются.
- Full replay/instrumentation serial-only: isolated UUID restoration и временные memory method wrappers не предназначены для concurrent production use. Новых model-facing/execution полномочий нет.

## 7. RED/GREEN и проверки

Результаты и изолированные fixtures сохраняются под постоянным evidence root. `red-observable.log`/`red-harness.log` — ожидаемые initial collection failures отсутствующих новых модулей. Промежуточные GREEN attempts и исправления harness semantics сохранены, historical characterization assertions не менялись. `green-5.log`: **41 passed / 5.72 s**; после него добавлен cross-class-ID regression test. `targeted-1.log`: **621 passed / 50.29 s** до последующих negative/control tests. `synthetic-final-2.log`: **44 passed / 6.16 s** на текущей реализации, включая Fake-only проверку подготовленного Q runner и отказ при backend restart. Первый clean full regression на `8616639373b815b8998ecddaede4ff0867a1e368`: **3139 passed / 248.16 s**, project checks PASS (205 pages, 1452 links, 465 Python files, 21 Bash files). Затем расширен только offline measurement ledger для typed model fact gain и усилены trace-count guards: `red-prefix-facts.log` — 3 failed / 27 passed; `synthetic-final-3.log` — **48 passed / 6.52 s**. Historical cycle/policy code не менялся. На clean `f9f6a87e27724f0bc166b56ea0865ee31549e99d`: **3143 passed / 262.51 s**, targeted **628 passed / 66.10 s**, project checks PASS; T-recorded 28/28 и H 4 journals повторно без divergence. Затем добавлены C12 generated-before-journal accounting и structured-claim inverse mapping controls: `red-c12-and-structured.log` — 2 failed / 48 passed; `synthetic-final-4.log` — **50 passed / 6.80 s**. Окончательные snapshot/full regression, повторный inventory и clean commit записываются ниже после исполнения.

Повторяемые команды (новый basetemp/output для каждого прогона):

```bash
.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  --basetemp="$EVIDENCE/synthetic-final" tests/test_e26_r941_observable.py tests/test_e26_r941_harness.py
.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  --basetemp="$EVIDENCE/targeted-final" tests/test_e26*.py tests/test_e25a_cognition.py tests/test_cognitive_coordinator.py
bash scripts/check.sh
.venv/bin/python -B -m pytest -q -p no:cacheprovider --basetemp="$EVIDENCE/full-final"
git diff --check
```

Implementation commit определяется `git log -1 --format=%H -- labs/virtual_anima_lab/python/cognition/observable.py labs/virtual_anima_lab/python/lifecycle/e26_r941_experiments.py`. Финальный documentation result commit определяется `git log -1 --format=%H -- docs/RESEARCH/e2-6-r941a-observable-v02.md`; самоссылочный hash в текст не подставляется. Остановка — R9.4.1a; новые реальные model experiments и policy changes остаются следующими отдельными этапами.
