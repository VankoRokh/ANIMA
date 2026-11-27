# ANIMA v0.2 — R9.4.5b Targeted Remediation

Baseline `b3ce10767405b395541ea723116233ea8017a863`, branch `work/v02-e26-r9-remediation`. Основания: [R9.4.5a](e2-6-r945a-targeted-root-cause-v02.md), [R9.4.4](e2-6-r944-controlled-evaluation-v02.md), [R9 register](e2-6-r9-remediation-v02.md). A/B/D одобрены для opt-in laboratory implementation; C и verification I/O optimization отложены. R944-F01/F02 OPEN, r943/0.1 не stable.

## 1. Diagnostic design — до runtime changes

[Runner](../../labs/virtual_anima_lab/python/lifecycle/e26_r945_diagnostic.py) использует existing Q/I typed mapping/signatures и no-dispatch transport. Source proposal: `/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r945a-2f0f5e6/diagnostic-proposal-NOT-RUN.json`; frozen request: R944 control-7-C03-00-A/wire/01-exchange.json#/request. Source SHA, payload hashes всех four cells, mapping/inverse validation и order заморожены до inference.

Cells: 0 old strategy/original ID; 1 new strategy/original ID; 2 new strategy/renamed ID; 3 old strategy/renamed ID. Native ID complete BIJECTIVE_RENAME; Event/Sample/source IDs неизменны. Existing strategy strings — единственный non-ID factor; остальные fields/bytes доказуемо восстанавливаются к original. N=20 counterbalanced blocks: even [0,1,2,3], odd [3,2,1,0], maximum80 calls, serial, один outstanding request. Generation settings/endpoint/model/backend preflight frozen до run; UNKNOWN fields не объявляются matched.

Analysis: within-block strategy effect при fixed ID (0/1 и 3/2), ID effect при fixed strategy (0/3 и 1/2). Tool/typed args, text stop, terminal, raw response hashes, usage и latency отдельно. Нет tool dispatch, retries, selective reruns или archived-response substitution. Transport/backend/config mismatch останавливает trial, failures остаются в planned denominator80; length/invalid terminals сохраняются. Один frozen context не превращается в20 independent scenarios; no full trajectory/generalized causal effect claim.

Evidence root `/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r945b-b3ce107/`: diagnostic/, synthetic/, validation/ раздельны. Diagnostic design и synthetic checks фиксируются отдельным commit до inference; results/conclusions фиксируются до A/B/D changes. Full T-fresh не запускается в этом этапе.


### Diagnostic results — зафиксированы до runtime

Clean diagnostic implementation `868ec81b33e60b430818807ab3ec1260747ba975`; frozen manifest SHA-256 `7b49545beabd09d50e9dd2480c9193baf5e1dd27d32285917b206c8f07db5f08`. 80 planned/attempted/received, 0 failed; no dispatch/retry/rerun. Cell0 old/original: 19 lookup_raw_evidence +1 text stop. Cells1/2/3: по20 lookup. Typed operations/arguments equality: strategy-original-ID19/20, strategy-renamed-ID20/20; ID-old-strategy19/20, ID-new-strategy20/20. Text/terminal/raw/usage сохранены в отдельных sample/exchange records; decoder проверил tool schema/typed args, не выполняя операции.

Вывод: устойчивое ухудшение от new strategy в этом фиксированном request **не воспроизведено**; это не доказывает безвредность representation/IDs вообще, не устанавливает trajectory effect и не закрывает F01. Все80 сохранены, single stop не исключён. Cache/warm/slot state UNKNOWN; один context, никакого scenario-level significance/generalization. Backend executable/argv/model/PID/start/template pre/post matched в пределах сохранённых checks, environment/peer attestation отсутствует. `diagnostic/results-before-runtime.json` хранит результаты и ограничения до A/B/D.


## 2. A — Stable model-visible representation

Новый explicit opt-in profile **r945/0.1** в существующем coordinator. Defaults/baseline/r942/0.1/r942/0.2/r943/0.1 сохранены. Ranking остаётся R943; [representation contract](../../labs/virtual_anima_lab/python/cognition/retrieval_representation.py) не сортирует и не меняет records, scope или provenance. Перед native broker reply host-only profile binding заменяет technical strategy на стабильное правдивое `ranked_lexical_not_semantic_retrieval`. При fixed native IDs и одинаковых records/order/scope tool replies/следующий request совпадают с соответствующим legacy lexical view. Реальные ranking/data differences не скрываются.

Trusted journal result сохраняет actual strategy `r943/0.1_lexical_coverage_opaque_id_tiebreak`. Вне model-facing tool result outcome дополнен `retrieval_metadata` (`anima.lab.retrieval_metadata/0.1`): algorithm=r943/0.1, family, original query, candidate/returned/truncated counts, returned-candidate explain и stable model description. Это не новые fields tool schema. Verifier recomputes metadata для r945, противоречивый algorithm/explain отвергается. Метаданные расходуют существующий outcome byte ceiling, потолок не повышается; особо крупный journal может быть rejected этим лимитом.

Host profile на adapter привязывается до первой session/call, модель его не выбирает. SYSTEM prompt и lab_registry AST идентичны baseline; model/catalog/permissions не меняются. Pure lexical explanations не универсальная semantic relevance оценка.

## 3. B — Requirement-aware bounded feedback

[Feedback contract](../../labs/virtual_anima_lab/python/cognition/requirement_feedback.py), schema `anima.lab.requirement_feedback/0.1`, только r945. Основа — existing trusted requirement, checked completion по reached operation prefix, completed operation kinds, verified source rows, SourcePolicy и пересечение permitted bindings с NativeLabAdapter.allowed_ids. Ни evaluator labels, ни hidden source IDs/answers не загружаются. Missing entities — approved question scope, не expected-world labels/values.

Lookup-only prerequisite явно требует admitted lookup_raw_evidence: successful search metadata или другая operation его не удовлетворяют (C14). Temporal/history/latest, bounded empty search и UNKNOWN различаются. Permitted visible refs не обещают успешную физическую доступность Raw; `source_read_success=NOT_ESTABLISHED_BY_METADATA`. OFF не раскрывает historical sources. Remaining calls/reported input/output budget передаётся как текущий bounded counter; wall time проверяется host на границах calls и не сериализуется как volatile timing в prompt. Full ResourceBudget остаётся в report.

Сохранены 2048-byte feedback ceiling, 4-call/default budgets и Native session continuation bound. Whole-unit/reference truncation явно помечена с исходными totals, omitted units не объявляются covered. Нет auto operations/retry после rejected/incomplete generation; repeated stop без gain ограничен прежней политикой. Decision сохраняет feedback schema/prefix/hash, native requests — полный feedback. Ни последующий Raw, ни финальные facts не используются для прежнего prefix.

Preflight hardening `8b43bc2` обнаружил inherited intermediate completion evaluation без profile marker: ßcrate requirement ошибочно сопоставлялся с empty sscrate перед feedback. Исправлено **только в r945**; legacy intermediate behavior намеренно сохранён и отдельно воспроизведён. Это согласование current-profile coverage, не изменение CompletionRequirement или historical verdicts.

Controlled synthetic F01 sequence (два captured entities, один разрешённый Raw binding): search→stop→новый feedback→model-proposed Raw lookup, sufficiency в3 calls из4, verified facts=2, без accepted model final. Это feasible mechanism test, **не** исправление real F01 на Qwen3. Сам model может снова остановиться; тогда действует прежний bound.

## 4. D — Verified presentation boundary

[Consumer contract](../../labs/virtual_anima_lab/python/cognition/verified_presentation.py), schema `anima.lab.verified_presentation/0.1`, добавляется как `consumer_view` только к r945 checked Hybrid Result. Legacy Hybrid JSON не расширяется. Pure deterministic projection, no I/O/inference/UI/canonical consumer integration.

Отдельные fields: verified bounded facts/source refs и verified typed model candidates; information status/requirement/missing units/reason; limitations; accepted **research protocol** final; generation/projection acceptance/claim-assessment phase; unverified research/projection prose. `NO_ACCEPTED_PROJECTION_FINAL` не маскирует существующий accepted research final. `global_verification` и `task_completion` всегда NOT_ESTABLISHED; prose authority UNVERIFIED, whole_answer_verified=false.

F02 incomplete+accepted final отображается как INCOMPLETE, missing primary units, verified_facts=[], accepted protocol text **UNVERIFIED**, без global knowledge/Task success. INFORMATION_SUFFICIENT/system termination сохраняет facts и явно указывает отсутствие accepted research final; model text не генерируется и не фабрикуется. Partial facts сохраняются после incomplete generation. Scope остаётся captured sample, not_observed не превращается в world absence. Фразы модели могут оставаться ошибочными: universal prose verifier не реализован, correctness внешнего UI не аттестуется.

Exported Hybrid Result, включая consumer_view, реконструируется существующим verifier; подмена global verification отвергается. Exact new-profile recorded trajectory через search/stop/feedback/lookup совпадает 3/3 requests, journal/result. Это replay plumbing, не fresh policy benefit.

## 5. Traceability и validation

| Change | Commit |
| --- | --- |
| Diagnostic harness/design before inference | `868ec81b33e60b430818807ab3ec1260747ba975` |
| Diagnostic results before runtime | `2698de5` |
| A stable view / actual trusted metadata | `4050b51` |
| B requirement feedback | `06408e5` |
| D consumer boundary | `70a6fbf` |
| B current-profile coverage hardening | **`8b43bc2da58122a5c0ef31684067481eb4b366b1`** |

Final clean implementation snapshot — **8b43bc2**; последующий documentation-only commit не меняет реализацию. Separate logs: diagnostic/ (80 fresh single-request calls); synthetic/ (Fake-only unit/contract/replay fixtures); validation/ (targeted/full/replay/immutability/reviews). Intermediate attempts сохранены, acceptance использует окончательный full-final.log.

| Проверка | Результат / Evidence |
| --- | --- |
| Diagnostic synthetic | 3 PASS; diagnostic/synthetic.log |
| A RED / GREEN | 3 failures →39 PASS; synthetic/A-red.log, A-green-final.log |
| B RED / GREEN | 5 failures →45 PASS; B-red.log, B-green-final.log |
| D RED / GREEN | 4 failures →49 PASS; D-red.log, D-green-final.log |
| B coverage RED | 1 failed /1 legacy passed; B-coverage-red.log |
| Final focused | **79 PASS /14.69 s**, coverage-final.log |
| Final E2.6 targeted | **684 PASS /72.49 s**, validation/targeted-final.log |
| Full clean implementation | **3238 PASS /259.47 s**, validation/full-final.log |
| Historical Control | 14/14, 47 exact requests MATCHED |
| Historical Host | 14/14, 46 exact requests MATCHED |
| New-profile export/Hybrid/consumer replay | MATCHED 3/3, mutation negative PASS |
| Project checks | PASS; final counts/receipt сохранены вне repository |

Durable new-profile tests переиспользуют **24 неизменённых R942 safety assertions** test-local selection нового profile: C14, mixed known/new/native normalization, Memory OFF/latest, repeated stop, UNKNOWN path, forged/foreign/stale/digest/sample/source mutations, incomplete terminal/missing usage/budget exhaustion, no-service-read, no fake final, system termination/export/replay. Historical assertions не переписаны. Отдельно проверены fixed-ID representation equality, actual metadata retention/mutation rejection, feedback prefix/no future coverage, hidden/nonvisible refs, bounded truncation, F02 incomplete accepted prose, partial facts, consumer reconstruction и отсутствие evaluator dependencies.

Protected byte/AST review: `anima/agent/native_tools.py`, ResourceLimits/ResourceBudget, SourcePolicy, R943 retrieval_policy/ranking, historical characterization/R942/R943 tests неизменны; SYSTEM/lab_registry AST IDENTICAL. Mandatory service/policy/fact verification rereads не удалены; sidecar не перенесён в hot path. New feedback/representation/consumer helpers pure и bounded; существующая дополнительная policy verification остаётся.

## 6. Evidence, limitations и R9.4.5c

Owner audit MATCHED:7 archives/8 bundles/206 Recovery files. Все95118 regular R944 files и103 R945a files и оба prior archives сверены с прежними hashes. Frozen historical bundles/manifests/metrics не перезаписаны. Новые Evidence — только вне repository; secret patterns/local instance data/personal settings проверяются перед commit/push.

**R944-F01/F02 остаются OPEN.** Один diagnostic context и controlled synthetic sequence не доказывают real-model trajectory fix, semantic prose truth или stable generalized benefit. r945/0.1 opt-in, default baseline; r943/0.1 не принимается как stable задним числом. Consumer contract не заставляет стороннего клиента корректно показывать flags. Byte ceilings/budgets прежние, обратная совместимость не обещает новые capabilities legacy профилям.

Активный предварительный план: `validation/r945c-plan-v2-NOT-RUN.json` (v1 сохранён как superseded; изменён только final implementation SHA, input/order/N/criteria прежние). A=baseline, B=r945/0.1, original28 compatibility contexts, N20 paired repetitions,560 pairs/1120 independent trajectories, max4480 combined calls. Serial AB/BA; FRESH_ACCEPT_AND_PROPAGATE; exact initial requests и независимые Raw-restored stores. Control/Host nested в14 template-seed clusters, равный вес scenarios,10000 bootstrap/seed940/95% percentile. Completeness margin0, прежние redundancy/post-sufficiency/cost gates **не ослаблены** даже при zero headroom. Accepted final, research tool/text, projection, verifier I/O и presentation отдельно. Held-out H01–H08 full fresh UNSUPPORTED без approved frozen tasks/requirements, offline/synthetic strata отдельно. Missing pairs/config/transport failures сохраняются, no retries/selective reruns. Future readiness требует reviewed registration r945 в experimental T-fresh runner и synthetic isolation/exact-prefix tests; исторический R944 harness/manifests не менялись.

**R9.4.5c full fresh НЕ запускался**, R941b/R944 matrices не повторялись; fresh calls в этом этапе ровно80 diagnostic. C deterministic host-origin operations, verification-I/O optimization, Knowledge writes, semantic retrieval, новые model/tool/execution authority, persistent lifecycle и R9.5 не реализованы.

Archive: `/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/ANIMA-R945b-b3ce107-Evidence.tar.gz`, SHA-256 **5be6d6ff99759527cdd0d8d93b5fe7f1a06819f77db7d4f1ebce28ac00120818**. Per-file checksums внутри snapshot, original raw requests/responses/hashes/mapping retained. Final receipt отдельно: `/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r945b-validation-receipt.json` с implementation/documentation SHAs, archive/report hashes, gates, remote equality/clean worktree. Остановка до R9.4.5c/R9.5.
