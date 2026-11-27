# ANIMA v0.2 — R9.4.4 Controlled Evaluation

Дата: 27 ноября 2026. Baseline: `15be9a55f7d18eec289d177d2008f4eccb190079`, branch `work/v02-e26-r9-remediation`.

Основания: [R9 register](e2-6-r9-remediation-v02.md), [protocol R9.4.0 §5](e2-6-r940-characterization-v02.md), [R9.4.1a](e2-6-r941a-observable-v02.md), [R9.4.1b](e2-6-r941b-baseline-model-experiments-v02.md), [R9.4.2](e2-6-r942-cognitive-control-v02.md), [R9.4.3](e2-6-r943-retrieval-efficiency-v02.md).

## 1. Frozen design before inference

Основные arms: A=baseline, B=r943/0.1; оценивается совместный эффект existing control + Retrieval. Diagnostic r942/0.2 не выбран. Все 28 compatibility contexts из существующих plan-control-v2/plan-host-v2: original seven templates × seeds 7/8 × Control/Host. N=20 paired repetitions **на каждый context**, serial execution, одна pending request. Order pair 0 AB, 1 BA, alternating до 19; 560 pairs, 1120 trajectories, максимум **4480 model calls**, включая optional existing claim projection. Existing ResourceLimits: 4 calls, 8192 reported input tokens, 1024 output tokens, 60000 ms; Research Native request max_tokens=256, temperature=0, parallel_tool_calls=false, enable_thinking=false; generation seed NOT_SET_IN_PROFILE. Generation, prompts и tool permissions не меняются.

Manifest и Evidence root: `/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r944-15be9a5/`. `preparation/design/manifest.json` содержит exact scenarios/tasks, approved requirement mapping, frozen Raw/case/request/manifest hashes и AB/BA order. Evaluator labels не загружаются runner и не попадают в completion hints/model context. Sources восстанавливаются независимо для каждого arm/repetition, original Event/Sample identities и Context сохраняются. Event-log ingestion timestamps создаются заново; их byte equality **между** restorations не утверждается. Внутри каждого arm event log/Knowledge/execution/Context должны оставаться неизменными.

Held-out H01–H06 содержат frozen query/top_k/availability, но не frozen task/CompletionRequirement/full trajectory. H07/H08 — fault scopes. До inference объявлены **UNSUPPORTED для fresh trajectory**; supported отдельно: offline lexical evaluation и synthetic fault/source-policy controls. Новые prompts/requirements из evaluator answers не создаются. Held-out conclusions не смешиваются с compatibility; prior R943 metrics и Q/I R941b evidence сохраняются.

## 2. Runner and safety contracts

[T-fresh runner](../../labs/virtual_anima_lab/python/lifecycle/e26_r944_fresh.py) — отдельный experimental runner существующих NativeLabAdapter/E25 coordinator. Initial generated request в обоих arms обязан точно совпасть с frozen request **до dispatch**. Backend responses исключительно fresh: archived replies не используются транспортом. ID policy FRESH_ACCEPT_AND_PROPAGATE делегирована unchanged NativeToolSession; native IDs и все wire bytes сохраняются. Есть exact response prefix и decision/request prefix; response metadata/IDs сами по себе не объявляются cognitive decision difference. После divergence дальнейшая exact equality не утверждается.

Каждая trajectory сохраняет initial-state, requests/responses/exchanges/hashes/monotonic timing, backend failures, adapter calls, checked journal/outcomes, budget, original/common completion, Hybrid Cognitive Result, observable prefix ledger и verification cost по фазам. Received response сохраняется до post-response backend check. No retries/selective reruns. Transport/config change, unsafe source/read-only violation или harness defect останавливает series, сохраняет failure/invalid pair и все planned denominators. Terminal rejection/incomplete/budget exhaustion — сохраняемые outcomes, не основание удалить пару или повторить генерацию.

Preflight: clean committed implementation, verified frozen inputs/owner inventory, PID/start marker/executable/argv/model SHA. Model SHA проверяется перед series; model stat (device/inode/size/mtime/ctime) и process identity — на каждой call boundary; final model hash проверяется после. Hashing model на каждом request не добавляется к elapsed budget. Backend не перезапускается. Endpoint↔process/environment/dynamic libraries attestation отсутствует. Cache, warm state, slot reuse, template/default fields UNKNOWN явно; latency exploratory.

## 3. Metrics and frozen analysis

Primary: common information completeness ratio by predeclared availability (MEMORY_ON, MEMORY_OFF, NO_SERVICE_REQUIREMENT), redundant acquisition rows=same-tool+cross-tool из existing sidecar, post-sufficiency research calls=последующие calls с typed research proposal. All subsequent research model calls и final/presentation calls показаны отдельно. Common evaluator использует existing completion с corrected query key r943/0.1 в обоих arms; original profile verdict сохраняется. Prefixes пересчитываются по reached journal prefix без будущих records. No-service-read violation не игнорируется.

Safety: existing source binding/admission/export verifier, read-only event log/Knowledge/execution, terminal/budget contracts, verified facts, Task completion NOT_ESTABLISHED. Model prose truth и arbitrary consistent archive authenticity не аттестуются. Secondary observable ledger: unique sources, verified fact coverage, continuation gain, premature stop, calls/tokens/latency/verifier costs, accepted final и presentation. RESEARCH_TERMINATED не STOPPED; отсутствие model text не successful generation. Retrieval precision для произвольных adaptive queries и наличие semantic missing-source path — NOT_ASSESSED без frozen relevance/path oracle; frozen offline held-out оценивается отдельно.

Offline-only [evaluator](../../labs/virtual_anima_lab/python/lifecycle/e26_r944_analysis.py): within-context repetition differences → равный вес Control/Host contexts → template×seed cluster means. 14 clusters, contexts не независимые tasks. Paired B−A differences; 10000 cluster bootstrap resamples, RNG 940, 95% percentile CI. Completeness margin=0: lower CI ≥0; upper CI <0 означает observed regression FAIL; снижение redundancy **и** post-sufficiency: upper CI <0 хотя бы в одном заранее заданном availability stratum; median total model calls B≤A. Все strata публикуются. Missing/invalid pairs → INCONCLUSIVE, никаких исключений. Unknown backend/cache/template либо недостаточное разнообразие ограничивают causal/generalization verdict до INCONCLUSIVE; numerical protocol threshold verdicts показываются отдельно. H0/H1 остаётся fixed-journal presentation experiment.

## 4. Preparation validation

Synthetic failures/исправления runner сохраняются отдельно от fresh: append-only duplicate filename исправлен, independent event-log timestamp comparison заменён на source/Context equality и within-arm invariance. Runtime policy не изменялась. Fixed defect corpus использует неизменённые R942 safety assertions на r943/0.1 плюс R943 query/control-marker tests: sufficiency, productive bounded continuation, repeated stop, same/cross-tool/mixed/C14, OFF, stale/forged/digest, incomplete/missing usage/budget, no fabricated final, partial verified facts. Full regression и 28/93 historical replay выполняются на clean implementation snapshot до массовых runs.

Readiness зафиксирован до inference в `preparation/readiness.json`; реализация и runtime contracts оставались неизменными во время series. Новых cognitive возможностей нет; R9.5 и canonical integration не начинались.


## 5. Execution and validation

Clean implementation: **`b533475ba6e0e0c0ed7a31dae34782eea259c24b`**; исходный harness/design commit `7130dbcad96271cad3625b3c2fbdaf618cad2f14`. Manifest SHA-256 **`ad16cb98fdf050d79f875b66ae54f60e1b91fcc0bc9725270b28b2b61f60b61c`**. Final documentation commit записывается в external receipt после commit/push, чтобы избежать самоссылочного SHA.

Preparation и synthetic logs отделены от `fresh/`. Initial synthetic controls: 2 failed/7 passed (append-only filename), затем 1 failed/8 passed (restoration timestamps); исправлены до inference. Дополнительный malformed negative выявил исторический STEP_BUDGET_EXHAUSTED при missing usage — этот verdict сохранён, runtime не исправлялся. Финальные runner controls **14 passed / 2.36 s**; focused runner/R943/R942 **50 passed / 7.40 s**, new-profile fixed defect corpus **24 passed / 4.58 s**. Wide targeted intermediate: 638 passed / 64.86 s. Final full regression на clean implementation: **3195 passed / 248.36 s**. Historical T-recorded: **28/28, 93 exact requests**, journal/result MATCHED, no divergence. Project checks PASS: 209 pages, 1488 links, 468 Python syntax sources, 21 Bash. Полная регрессия после documentation-only изменений не повторяется.

До первого fresh request readiness подтвердил все эти checks, frozen inputs и backend. PID **13301**, start marker **111533**, executable SHA-256 `9060daff0611e6a5fb5338513bf44ddb841214cbe748a4ee413e62ff88193db5`, Qwen3-4B-Q4_K_M model SHA-256 `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`. Executable/argv/model совпали с archived backend profile, PID/start/model сохранились pre/post. Template hash `57f1fd00f0013a2be96aa79b857391f27e23df5b5f847072b524c897e24d0361` совпал pre/post; архивного template hash нет, historical template equality UNKNOWN. Intel i5-10300H, GTX1660 Ti 6144 MiB, driver 580.178.04, server total_slots=4; наш outstanding request максимум 1. Threads/batch/cache/slot reuse/external clients/default sampling fields UNKNOWN. Никакого reset/cold-cache claim нет.

| Count | Planned/max | Attempted | Completed/received | Failed |
| --- | ---: | ---: | ---: | ---: |
| Paired repetitions | 560 | 560 | 560 | 0 |
| Independent trajectories | 1120 | 1120 | 1120 | 0 harness failures |
| Model calls | ≤4480 | 3060 | 3060 | 0 transport failures |

2713 research requests + 347 existing claim-projection requests. Claim projection штатно не содержит tools/parallel_tool_calls; temperature/max_tokens/enable_thinking прежние в обеих фазах. Initial offline wire audit ошибочно требовал research-only parallel field в projection; phase-aware проверка выполнена без изменения implementation и без model rerun, ошибка сохранена в protocol-validation.json. Все 3060 request/response hashes повторно проверены; native ID bindings, serial monotonic intervals, N/order, initial Context/Raw equality проверены на всех 560 парах. Все 1120 stores независимы. Initial model request exact equality: 560/560 pairs.

Terminal outcomes: STOPPED=700, RESEARCH_TERMINATED=400, REJECTED=20. Все 20 rejected — incomplete generation (length), сохранены; это не transport failure и не пропущенная trajectory. Budget-exhausted terminals=0. Fresh held-out: **8 UNSUPPORTED scopes**, ноль attempted; denominator compatibility не уменьшался.

## 6. Paired results and gates

Completeness ниже — common required-unit ratio, не operation success и не accepted final. Original/common satisfied verdicts совпали во всех 1120 trajectories. Среднее A **0.767857**, B **0.732143**; binary fully satisfied A=420/560, B=400/560. Наличие model final A=540/560, B=160/560; у B 400 system-owned research terminations без fabricated model STOP/final. Post-sufficiency **typed research** calls=0 в обоих arms: снижения этого primary endpoint серия не демонстрирует; presentation/model-stop и optional projection не переименовываются в research acquisition.

| Stratum | Pairs / clusters | Δ completeness B−A [95% CI] | Δ redundancy [95% CI] | Δ post-suff research [95% CI] |
| --- | --- | --- | --- | --- |
| ALL_COMPATIBILITY | 560 / 14 | -0.035714 [-0.107143, 0.000000] | -0.142857 [-0.357143, 0.000000] | 0.000000 [0.000000, 0.000000] |
| MEMORY_OFF | 80 / 2 | 0.000000 [0.000000, 0.000000] | -1.000000 [-1.000000, -1.000000] | 0.000000 [0.000000, 0.000000] |
| MEMORY_ON | 400 / 10 | -0.050000 [-0.150000, 0.000000] | 0.000000 [0.000000, 0.000000] | 0.000000 [0.000000, 0.000000] |
| NO_SERVICE_REQUIREMENT | 80 / 2 | 0.000000 [0.000000, 0.000000] | 0.000000 [0.000000, 0.000000] | 0.000000 [0.000000, 0.000000] |

Completeness non-regression: MEMORY_ON и ALL_COMPATIBILITY **INCONCLUSIVE** (lower CI <0 при margin 0); OFF/no-service имеют observed numeric non-regression, но только по 2 clusters. Gate одновременного снижения redundancy и post-sufficiency research в хотя бы одном объявленном stratum — **INCONCLUSIVE / не продемонстрирован**: второй endpoint не имеет headroom (0→0). Median total calls A=3, B=2; Δ mean calls −1.178571, CI [−1.535714, −0.785714], numeric cost threshold пройден. Это не компенсирует непрохождение completeness gate. **Общий benefit/generalization verdict: INCONCLUSIVE, не PASS**; неизвестные cache/backend defaults и 14 clusters дополнительно ограничивают причинный вывод. Численные improvements не объявляются доказательством generalized policy benefit.

Per-context means (20 paired repetitions каждый; полные vectors по pair/seed/context и confidence intervals в analysis.json):

| Frozen context | Completeness A→B | Redundant rows A→B | Total calls A→B |
| --- | --- | --- | --- |
| control-7-C01 | 0→0 | 0→0 | 3→3 |
| control-7-C02 | 1→1 | 0→0 | 3→1 |
| control-7-C02_OFF | 0→0 | 1→0 | 4→2 |
| control-7-C03 | 1→0 | 0→0 | 4→3 |
| control-7-C03_ALT | 1→1 | 0→0 | 3→1 |
| control-7-C06 | 0.5→0.5 | 0→0 | 3→3 |
| control-7-C09 | 1→1 | 0→0 | 2→2 |
| control-8-C01 | 1→1 | 0→0 | 4→3 |
| control-8-C02 | 1→1 | 0→0 | 3→1 |
| control-8-C02_OFF | 0→0 | 1→0 | 4→2 |
| control-8-C03 | 1→1 | 0→0 | 4→2 |
| control-8-C03_ALT | 0→0 | 0→0 | 3→3 |
| control-8-C06 | 1→1 | 0→0 | 4→3 |
| control-8-C09 | 1→1 | 0→0 | 2→2 |
| host-7-C01 | 1→1 | 0→0 | 4→3 |
| host-7-C02 | 1→1 | 0→0 | 3→1 |
| host-7-C02_OFF | 0→0 | 1→0 | 4→2 |
| host-7-C03 | 1→1 | 0→0 | 4→3 |
| host-7-C03_ALT | 1→1 | 0→0 | 3→1 |
| host-7-C06 | 1→1 | 0→0 | 3→2 |
| host-7-C09 | 1→1 | 0→0 | 2→2 |
| host-8-C01 | 1→1 | 0→0 | 4→3 |
| host-8-C02 | 1→1 | 0→0 | 3→1 |
| host-8-C02_OFF | 0→0 | 1→0 | 3→2 |
| host-8-C03 | 1→1 | 0→0 | 4→2 |
| host-8-C03_ALT | 1→1 | 0→0 | 4→2 |
| host-8-C06 | 1→1 | 0→0 | 4→3 |
| host-8-C09 | 1→1 | 0→0 | 2→2 |

## 7. Open findings, safety and resources

**R944-F01:** control-7-C03, 20/20 A complete против 0/20 B complete. A retrieve→Raw lookup→accepted final; B retrieve→stop→bounded CONTINUE→repeated stop, NO_CONTINUATION_GAIN, один call ещё доступен, required Raw не приобретён. First journal difference включает versioned Retrieval strategy metadata; без diagnostic arm нельзя приписать потерю одному ranking или continuation. Existing code не исправлялся. `findings/R944-F01-reproducer.json` фиксирует hashes уже полученных requests/responses/journals и representative pair 00; это reproducer из сохранённого материала, не rerun. Generalized R9-Q02/F04 остаётся PARTIAL.

**R944-F02:** representative B prose утверждает verification после одного retrieve и трактует not_observed как отсутствие в environment. Checked journal не подтверждает ни Raw verification, ни world absence. Это qualitative unverified-prose finding, не post-hoc semantic score. System facts из этих фраз не создавались; whole_answer_verified=false. Отсутствие unsafe **admitted** facts не означает истинность model prose. Исправление требует отдельного согласованного remediation; R9.5 не начинался.

0 source-binding/read-only/terminal-contract/false Task success violations в 1120 checked trajectories, 0 harness failures. Mandatory verification rereads не удалялись. Ни одно imported consistent archive не объявляется криптографически аутентичным. First divergences: JOURNAL_OUTCOME=280 (включает strategy metadata, не автоматически different operation), REQUEST=160 (включает propagated native IDs), RESPONSE_DECISION=2, TRAJECTORY_LENGTH=40, NO_DIVERGENCE=78. Response IDs/timing сами по себе не cognitive decision change; exact response и decision/request prefixes раздельны, после first divergence equality не утверждается.

| Resource / secondary endpoint | A | B |
| --- | ---: | ---: |
| Total model calls | 1860 | 1200 |
| Reported input tokens | 1829063 | 1087744 |
| Reported output tokens | 117619 | 62616 |
| Accepted final / model text available | 540 | 160 |
| CONTINUE decisions / productive | 253 / 133 | 200 / 120 |
| STOPPED + incomplete | 120 | 80 |
| Incomplete with checked observable missing path | 60 | 80 |
| Rejected duplicate + observable missing path | 0 | 0 |
| Mean unique verified sources | 0.750000 | 0.714286 |
| Mean verified fact count | 0.750000 | 0.678571 |
| Native tool IDs / unique | 780 / 780 | 760 / 760 |
| Known wire latency total ms | 3427001.217 | 1802432.614 |
| Median wire latency ms | 1416.050 | 960.497 |
| Runtime service + policy Raw rereads | 500 | 800 |
| Result construction Raw rereads | 574 | 380 |
| Host projection Raw rereads | 80 | 80 |
| Offline measurement Raw rereads | 2475 | 1140 |
| Context integrity row checks | 16098 | 11160 |

Usage полностью backend-reported; неизвестных usage counters=0. Runtime policy verification у B дороже по rereads, несмотря на меньшее число model calls. Nested integrity counts и read phases не суммируются как independent acquisition. Все latency exploratory: UNKNOWN cache/warm/slots/external clients. Missing-path flags — existing pure recoverability по checked scope, не semantic oracle. Whole-answer/presentation quality NOT_ASSESSED; availability показана отдельно. Adaptive-query retrieval relevance NOT_ASSESSED без заранее frozen labels на эти queries.

Held-out offline отдельно подтвердил R943 lexical result: H01/H02/H03 unsupported aliases/language/short token 0→0; H04 1→1; H05/H06 unlabeled N/A, H07/H08 synthetic fault scopes. Synthetic category C07 0→1 остаётся ограниченным lexical tie case, не fresh held-out generalization. Q/I 2640 matrix R941b не повторялась; H0/H1 не переименовывался в research improvement.

## 8. Evidence and stop boundary

Owner inventory после runs совпал: 7 archives, 8 bundles, 206 Recovery files. Frozen manifests/cases/Raw/held-out inputs/label hash неизменны. Архивы R941b и R943 отдельно сверены с final receipts; hashes MATCHED. Новых Evidence/персональных настроек/секретов в tracked paths нет; 7 changed paths — только experimental harness, offline evaluator, tests/source allowlist и 3 Markdown. Working cognitive policy, ranking, prompts, model, budgets, catalog/permissions не изменены.

Archive: `/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/ANIMA-R944-15be9a5-Evidence.tar.gz`, SHA-256 **50c445c0f7633f7f675fc33acff4a59e96332415afc78f86ced6b7bdf3cda200**. SHA256SUMS фиксирует regular files snapshot; symlinks не dereference. Final validation receipt отдельно от archive: `/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r944-validation-receipt.json` (implementation и documentation SHAs, remote equality/clean worktree, report/archive hashes).

Исполненный fresh command (не повторять в этом этапе; output exclusive):

```bash
.venv/bin/python -B -m labs.virtual_anima_lab.python.lifecycle.e26_r944_fresh run /home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r944-15be9a5/preparation/design/manifest.json --output /home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r944-15be9a5/fresh --pid 13301 --preflight /home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r944-15be9a5/preparation/preflight-final.json
```

Этап завершает измерение существующих profiles, а не устраняет R944-F01/F02. Никаких selective reruns, новой policy, semantic Retrieval, Knowledge writes, canonical integration или R9.5. Следующий шаг — отдельное рассмотрение findings/ограничений; remediation не реализована.
