# ANIMA v0.2 — E2.6 R9: реестр находок и план исправлений

**Дата:** 27 ноября 2026. **Статус:** Research / R9.1–R9.3 owner-validated in documented scope; independent re-audit pending. R9.3 Recovery owner results recorded in R9.4.0 report; independent archive audit pending. R9.4.0 reviewed; R9.4.1a offline observable state/harness implemented; R9.4.1b baseline model experiments recorded; R9.4.2 policy changes not started.
**Исходный baseline реестра:** `508851d458cf759902aa35c9ae140780fb29c4a0`. Рабочая ветка `work/v02-e26-r9-remediation`.
**Источник:** независимый отчёт `ANIMA-E26-R8-Independent-Reaudit-RU.md`, 25 ноября 2026, §§4, 6, 9–15; архив `ANIMA-E26-R8-Independent-Reproduction.zip`. Первичные файлы предоставлены владельцем вне данного snapshot; этот документ не заменяет их.
**Вердикт R8:** CONDITIONAL PASS только для продолжения ограниченной лабораторной работы. Закрытие E2.6, перенос в canonical assembly и расширение model-facing authority — BLOCKED.

## 1. Правила реестра

Исторические ID и определения неизменяемы. Новые локальные ID R9-Q/E/L ниже относятся к остаточным вопросам, а не реконструируют F01–F17. Статус меняется только с указанием SHA, reproducer, результата проверки и границы гарантии. PASS теста, воспроизводящего дефект, не является исправлением. Приоритет этапа отличается от severity аудита.

| ID / severity R8 | Формулировка | Статус R8 | Reproducer / evidence из R8 | План |
| --- | --- | --- | --- | --- |
| CA-01 / High | Cross-wired Goal/Task | CLOSED, single scheduler | A01, L02; R8-17; L02 zero tick/revision delta | R9.5 regression |
| CA-02 / Medium | Direct spatial Executor без Goal/Task/Spec | CLOSED, guarded spatial factory | A02, L01; direct calls rejected; live zero delta | R9.5 |
| CA-03 / Medium | Historical Raw при Memory OFF через alternative adapter | CLOSED, read-only lab | A03/A04; mixed/unknown/sample-as-event rejected | R9.1/R9.5 |
| CA-04 / Low | Старый result для нового call того же tool | CLOSED, correlation only | A15; stale/copy/cross-session handles rejected | R9.5 |
| CA-05 / Medium | Недостающие Raw/точная версия запуска | PARTIAL | R5 export; 4 new bundles checked; R8-N01 | R9.1 |
| CA-06 / Medium | World seed не фиксирует LLM input | PARTIAL | 28 R7 trajectories / 92 exact requests replayed with recorded responses; fresh full-model NOT_RUN | R9.4/R9.5 |
| CA-07 / Low | Потеря известной части usage | CLOSED, reported accounting | A14; missing counters; R8-08/R8-14 | R9.5 |
| R8-N01 / Medium | Неполная проверка внутренней связности export evidence | OPEN | E02/E03, test_r8_evidence_contracts.py: resealed inconsistent proposal IDs, world, admission, Core digest; duplicate seeds | R9.1 P1 |
| R8-N02 / Low | Legacy/Choice принимает незавершённую генерацию | OPEN | R8-15 limit accepted; R8-14 Native rejects length | R9.3 P2 |

### Остаточные вопросы (новые ID)

| ID | Категория / определение | Статус / evidence | Этап |
| --- | --- | --- | --- |
| R9-Q01 | Semantic prose не связан полностью с typed verdicts; empty claims не доказывают correctness | OPEN; R8-18, Q/A-Q/U-Q, C03/8, C06/7, C01/8 | R9.2 P1 |
| R9-Q02 | F04 retrieval ranking и generalization | PARTIAL; ranked lexical; C03_ALT seed 8 не дошёл до Raw | R9.4 |
| R9-Q03 | F05 premature stop и weak continuation | OPEN; missing-information stops 5/4, improvement 0/6 vs 2/6 | R9.4 |
| R9-Q04 | Redundant reads across tools | OPEN; 4 Control + 3 Host cases, repeated_proposals=0 | R9.4 |
| R9-Q05 | Claims construction / temporal / owner semantics | PARTIAL; typed verifier passes bounded tests, model errors persist | R9.2/R9.4 |
| R9-E01 | Host causal effect not isolated; fresh model reproducibility not established | NOT_VERIFIED; R8 §§9–11 | R9.4/R9.5 |
| R9-E02 | Limited corpus: seven templates, two seeds, one quantization; reported accounting not hardware limits | LIMITATION | R9.4/R9.5 |
| R8-L01 | Cancellation after final worker check before dispatch | LIMITATION; live L06, one effect | Future lifecycle; single scheduler retained |
| R9-L01 | Process-local turn budgets/handles; stop-only ID reuse | LIMITATION; R8-12 | Future durable lifecycle |
| R9-L02 | Orphan Task; interrupted admission; no general persistent resume or power-loss matrix | LIMITATION; A07/A08, R8-13 | Future recovery |
| R9-L03 | OS isolation, multiple owners, physical-world guarantees not established | NOT_VERIFIED | Before expanding authority |
| R9-L04 | canonical_baseline_unchanged is not a full persistent fingerprint | LIMITATION; R8 §6 | Stronger independent comparisons in R9.5 |

### F01–F17

- F03: Sample ID вместо Event ID. Runtime rejects invalid reference; model selection not universally corrected.
- F04: Недостаточное retrieval ranking; unranked OR/top_k выбирает неверный obstacle. PARTIAL (R9-Q02).
- F05: Преждевременное завершение. OPEN (R9-Q03).
- F01, F02, F06, F07, F08, F09, F10, F11, F12, F13, F14, F15, F16, F17: HISTORICAL_DEFINITION_UNAVAILABLE; closure not assessed. Do not mix with H5.5 F-01–F-08.

## 2. Согласованная архитектура итогового результата

Решение владельца от 26 ноября: hybrid — deterministic mechanisms own checked facts, source bindings, completion, policy and persistence; LLM owns interpretation, hypothesis/proposal generation, cognitive initiative and linguistic presentation. Preserve natural-language output separately from verified typed results. Hypothesis is not established Knowledge; model stop is not Task success. No claim of universal prose verification. No new permissions, training, background goals, or canonical integration in R9. Concrete data contracts are pending R9.2 review.

Существующие контракты: [Cognitive initiative](e2-cognitive-initiative-v02.md), [FAST/DEEP](../ARCHITECTURE/Cognition_FAST_DEEP.md), [Memory and Retrieval](../ARCHITECTURE/Memory_and_Retrieval.md), [Stage 6](../ARCHITECTURE/Stage_6_Cognitive_Integration_Core.md).

## 3. Этапы и exit criteria

| Stage | Deliverable / acceptance criterion |
| --- | --- |
| R9.0 | Registry, frozen baseline, scope and criteria recorded; documentation check pending |
| R9.1 | R8-N01 all resealed inconsistent fixtures rejected; same unchanged R7 inputs verified; CA-03 regression; no backend/physical attestation claim |
| R9.2 | Separate operation, information completion, typed claim validity/coverage, prose authority. Wrong/free prose and empty claims cannot imply semantic PASS. Preserve original output and Host origin/scope. No new Knowledge writes |
| R9.3 | Explicit per-wire terminal mapping; incomplete/unknown status rejected or explicitly outside supported profile; parity negatives; unchanged prompts/budgets |
| R9.4 | Paired Host on/off on same journal; separate acquisition, unique source events, redundancy, completeness, continuation and cost; exact-request repeats, ID-only variants, full replay with declared tool-call-ID handling; record order/cache/backend settings |
| R9.5 | Targeted negatives, full regression, project checks, unchanged R7 frozen replay; fresh local inference separately; independent audit of new clean snapshot. Unexecuted tests marked NOT_RUN. No automatic E2.6 closure |

## 4. R9.1 design / next step

Current verifier checks checksums, Raw/Core pointer fields and selected completed source rows, but not the entire authority chain. Read-only offline verification is not an authentication or backend attestation mechanism.

Existing code to inspect/reuse:
- [Export verifier](../../labs/virtual_anima_lab/python/lifecycle/e26_reproducibility.py) and [tests](../../tests/test_e26_reproducibility.py).
- [Core ingress](../../anima/core/ingress.py): canonical validated event and content fingerprint.
- [Lab coordinator](../../labs/virtual_anima_lab/python/cognition/coordinator.py): frozen Context, turn-local source exposure, admission, outcome and decision record checks.
- [Proposal contract](../../labs/virtual_anima_lab/python/cognition/contracts.py) and [source binding](../../labs/virtual_anima_lab/python/cognition/source_binding.py).
- [Provenance resolver](../../anima/memory/provenance.py): canonical memory provenance; assess applicability, do not treat synthetic Core pointers as canonical Memory IDs.

Implementation sequence: (1) reproduce independent R8 negatives on baseline; (2) map shared canonical invariants without executing services or replaying LLM; (3) reuse/extract pure validation as appropriate, do not duplicate trusted policy; (4) verify Core content fingerprint, Context hash and scope, proposal/turn/step/outcome/admission identity, requested/exposed sources and Memory OFF, phase/request/proposal correspondence, manifest uniqueness; (5) reject resealed inconsistent copies, verify unchanged valid archives and frozen trajectories; (6) regression/project checks. Check actual archive compatibility before deciding any schema migration. No rewriting historical evidence to obtain PASS.

Acceptance does not require signatures, external attestation or new authority. No production changes or dependency additions without review of their necessity. The preceding paragraph describes the original R9.1 design gate; see the dated validation record below.


## 5. R9.1 — локальная валидация, 26 ноября 2026

**Проверенный implementation snapshot:** `4d2e3c8739f58848cc636979be3078bf5c8b8125`. Рабочая ветка R9, не новый релиз. **Статус:** OWNER_VALIDATED / READY_FOR_INDEPENDENT_REAUDIT. R8-N01 не объявляется независимо закрытым; CA-05 сохраняет исходные ограничения, CA-06 не переоценивается.

| Шаг | Snapshot | Owner evidence |
| --- | --- | --- |
| R9.0 | `7ebcb9dfec814fba89e8686004086b4bb4651090` | Project checks PASS |
| RED-1 | `a254eed4aba4a7cf74f96673a7d4e694593bbc48` | 7 expected DID NOT RAISE, 9 passed |
| GREEN-1 | `b79c9c1fbcd61226434e7f5636d9aac32a28a841` | 16 passed |
| RED-2 | `5ffd3689e5c8062cbfc3acb5cf2a12cff1466b57` | 7 expected DID NOT RAISE, 21 passed |
| GREEN-2 | `736a4a9f85a60c8773b188e5e721d585a4333027` | 28 targeted, 228 cognitive regression passed |
| Shared contracts | `97c2a1a3e99da2b5ea739dcf0442baafbb5db23b` | 230 cognitive regression passed; project checks PASS (203 pages, 1400 links); historical bundle verification below |
| Full regression, initial | `97c2a1a3e99da2b5ea739dcf0442baafbb5db23b` | 6 documentation failures, 2742 passed; bounded source snapshot omitted four documented VAL link targets |
| Full regression, corrected | `4d2e3c8739f58848cc636979be3078bf5c8b8125` | 2749 passed in 107.29s, Python 3.14.4; source snapshot allowlist corrected and exclusion regression added |

22 tests added relative to R8 (21 evidence/contract tests and one documentation snapshot test). All 14 reproduced inconsistent export cases rejected in targeted tests. The four R5/R6/R7 bundles passed the stricter verifier without requiring schema migration, according to owner-provided CLI outputs:

| Bundle | Source snapshot | Cases | Raw | Requests |
| --- | --- | ---: | ---: | ---: |
| R5 | `08efa20ab20e0aaa7fafd0d65cd309b845d8cb5b` | 2 | 6 | 8 |
| R6 | `508851d458cf759902aa35c9ae140780fb29c4a0` | 2 | 6 | 7 |
| R7 Control | `508851d458cf759902aa35c9ae140780fb29c4a0` | 14 | 6 | 45 |
| R7 Host | `508851d458cf759902aa35c9ae140780fb29c4a0` | 14 | 6 | 47 |

Reused pure Core envelope validation, extracted shared TurnSourcePolicy, native catalog argument decoding and journal source binding. Added checks of scope, admission, proposal identity, model-call correspondence and declared bundle membership. No new dependency or model authority. Existing export schema preserved. Reproducers: [R9.1 evidence tests](../../tests/test_e26_r91_evidence_integrity.py), [snapshot tests](../../tests/test_source_tree.py).

**Limitations:** owner outputs, not independent execution by this reviewer; final archive external SHA-256 output not supplied; no fresh inference or complete replay performed in R9.1; verification scope remains `integrity_and_source_binding_not_backend_attestation`. A consistently fabricated archive is not authenticated by these checks. Native call metadata and semantic correctness of prose are separate questions. Final project check on documentation-only snapshot `85266f44eee89be2b467bb387f0fc98ae6099053`: owner PASS, 203 pages / 1402 local links, Python 3.14.4. R9.5 independently tests closure and additional bypasses.


## 6. R9.2.0 — Hybrid Cognitive Result (лабораторный контракт, проект)

Владелец согласовал назначение: результат отдельного когнитивного цикла, пригодный для оценки качества обработки и будущего повторного использования. Это не полный журнал, не Knowledge, не автоматически успешная Task и не новая исполнительная authority. Срез должен существовать и при неполной информации, отказе, исчерпании бюджета. R9.2 не реализует persistence, межцикловую передачу, обучение или самостоятельные цели.

### Разделение ответственности

- Decision Journal хранит ход операций; Cognitive Result содержит смысловое резюме и ссылки на этот журнал; Evaluation отдельно сравнивает результат с требованиями испытания. Не подмешивать скрытые fixture answers в модель или подтверждённые факты.
- Identity: turn_id / context_snapshot_id; при наличии — frozen source scope. Execution: исходный turn status, выполненные/отклонённые операции, существующий resource budget. Не превращать STOPPED или STEP_BUDGET_EXHAUSTED в Task completion.
- Information: существующий CompletionRequirement / evaluate_completion; хранить requirement, observed coverage и missing entities/requirements. Это относительная достаточность для явно заданного вопроса, не глобальная полнота знания. Если требования нет, NOT_ASSESSED, а не PASS.
- Evidence: только проверенные typed claims с origin (MODEL_CANDIDATE_VERIFIED или DETERMINISTIC_HOST), event/sample identity, temporal scope и verdict. Проверенные и отклонённые кандидаты разделены; не удалять отрицательные verdicts. Использовать ObservationClaimVerifier, admitted_source_rows, temporal_claim_coverage и host projection, не копировать их алгоритмы. Host формирует утверждения только из уже допущенных источников; не инициирует новый research read. Повторные canonical integrity reads отдельно от acquisition.
- Reasoning: сохранять точный исходный research final и, если был, projection final, их фазу, turn/context и статус. Любой свободный текст модели имеет authority UNVERIFIED; гипотеза/интерпретация/предложение не становятся fact даже при наличии корректных соседних claims. В первой версии не обещать надёжное извлечение таких категорий из произвольной прозы и не добавлять обязательный inference. Явные структурированные гипотезы — будущий опциональный контракт.
- Presentation: проверенные утверждения доступны отдельно от model prose. Host text только из успешно проверенных утверждений с точным capture scope; не маркировать произвольную прозу VERIFIED. Не маскировать ошибочный ответ модели заменой Host text в model metrics. Никакой verified whole-answer semantic PASS из typed coverage.
- Evaluation: independently report operation gate, information status, typed claim format, verdict status, coverage, and free-text review. Empty claim set = NO_CLAIMS (observation-required case fails coverage) or NOT_APPLICABLE (no observation assertion required); never blanket verified semantics. Empty search proves only bounded search outcome, not nonexistence. A no-service-read case does not prove arithmetic correctness. Existing legacy metrics remain for historical comparisons; new fields explicitly scope their meaning.

### Порядок и критерии

| Шаг | Scope |
| --- | --- |
| R9.2.1 | Characterization on unchanged R9.1 implementation: false prose + correct claims, empty claims + false absence, wrong arithmetic + no tools; preserve historical metrics and show their semantic boundary |
| R9.2.2 | Add narrow versioned laboratory result builder, using trusted coordinator/report/journal, no arbitrary imported verdict as authority; typed fact/unknown basis; no additional model calls |
| R9.2.3 | Separate original research/projection text, verification and coverage; model prose never automatically VERIFIED, no vacuous success; keep partial/rejected/budget outcomes distinct |
| R9.2.4 | Reuse host temporal projection and existing model claim evaluation, without changing historic metrics or scoring model as if it produced Host facts; optional projection uses existing budget |
| R9.2.5 | Contract and integration tests: supported/unsupported/contradicted/empty claims, scope errors, false prose, missing evidence, wrong arithmetic, foreign turn/context, stale sources, stop-only, budget/rejection; no writes/no new authority; old bundles remain readable |
| R9.2.6 | Local real-model experiment, project checks and full regression. Report separately what was measured and what remains NOT_VERIFIED |

Concrete first-version field names may follow existing contracts, not a replacement canonical IR. No new Core module, schema migration, universal semantic grader, new prompt or expanded tool list at this step. The model can reason freely, while machine consumers must explicitly select verified data instead of treating all text as evidence.

R9.2.1 reproducer: [characterization tests](../../tests/test_e26_r92_result_characterization.py). A PASS here confirms a known limitation of the old metric, not remediation or semantic correctness. The assertions intentionally describe the historical scoring boundary; they are not tests that expect a new API before implementation.


## 7. R9.2 — локальная валидация, 26 ноября 2026

**Implementation snapshot:** `e15da95a606eb03fa2f0b100a943e7bb90ba2b20`. **OWNER_VALIDATED / READY_FOR_INDEPENDENT_REAUDIT.** Не закрывает E2.6, не предоставляет canonical authority.

| Шаг | Snapshot | Owner evidence |
| --- | --- | --- |
| Design / characterization | `f58089868df165eaa3ad973ece5be01d73eb6cae` | 3 passed; legacy metric limitations reproduced |
| Deterministic result | `126018eb8072a2eca1b553dd1002ee66fc31ef9a` | 16 targeted, 246 cognitive passed |
| Reasoning separation | `22ee023dfef582d959f00b8d331a2aa00883b60d` | 29 targeted, 259 cognitive passed |
| Suite / projection | `65c5034a37b968c6864a69930e235c36e1dadd79` | 38 targeted, 268 cognitive passed |
| Offline reconstruction | `bd5f3f0adc8761f32b12d7b027a784ea050f8fac` | 12 fixture preparation failures (exclusive create), 38 passed |
| Fixture correction / final | `e15da95a606eb03fa2f0b100a943e7bb90ba2b20` | 12 export tests, 50 targeted, 280 cognitive, 2799 full passed (111.55 s); checks PASS, 203 pages / 1403 links, Python 3.14.4 |

50 additional tests relative to R9.1. Shared verification/projection logic reconstructs Cognitive Result from frozen Raw, journal and model-call records. All 11 resealed result mutations rejected; legacy export compatibility confirmed. No model calls or writes added by result construction. Production exclusive-create contract preserved.

### Real model experiment

Qwen3-4B-Q4_K_M / llama.cpp, 4096 context, existing temporal_completion profile, seeds 7 and 8, four-call limit, max output 256, temperature 0. Two separate runs, not paired exact-input experiments. Owner-provided reports `e26b-results(9).json` (Control) and `e26b-results(10).json` (Host).

| Metric | Control | Host |
| --- | ---: | ---: |
| Cognitive Results | 14 | 14 |
| Operation gate / information satisfied | 11 | 9 |
| Host claim coverage complete (8 applicable per profile) | 7 | 5 |
| Host claim coverage incomplete | 1 | 3 |
| Model structured nonempty all-verified cases | 3 | 3 |
| Model verified claims | 5 | 5 |
| Model no accepted final for claim phase | 7 | 7 |
| Model empty claim sets | 4 | 4 |
| Temporal information complete | 1 | 1 |
| Legacy host temporal projection verified | n/a | 1 |
| Frozen requests | 48 | 45 |

Both operation gates FAIL. This does not negate result construction: partial facts, missing requirements and original model text remain separate, whole_answer_verified stays false. Free prose semantics are not established by the typed verifier. C06 seed 7 lacks historical verification despite latest-sample read; C01 has ambiguous owner/absence interpretation. Redundant cross-tool reads, early stop and model selection remain R9.4 questions. No evidence that a fresh Host run is causally superior/inferior. Separate deterministic construction cost not measured.

### Evidence record

Owner CLI output: both R9.2 bundles verified at implementation SHA, 14 cases and 6 Raw each, 48/45 requests. All four historical bundles listed in section 5 reverified (32 cases, 24 Raw, 107 requests). Total 6 bundles, 60 cases, 36 Raw, 200 requests. Archive `ANIMA-E26-R92-Evidence.tar.gz` reported SHA-256 `5a197c471d6604e7e0a929002b467811257b5b7573305938e60a1363478bcfca`. Archive bytes and owner logs not independently verified in this review. Scope remains integrity_and_source_binding_not_backend_attestation. Fresh real inference performed by owner; independent replay and audit pending. R9-Q01 mitigated within typed laboratory boundary, not universal semantic verification; R9-Q05 model behavior remains PARTIAL. No persistence, learning or expanded execution authority.

## 8. R9.3 — terminal contract investigation

R8-N02: valid structured JSON is not evidence that generation terminated normally. Legacy and Choice decode response.text without checking response.finish_reason. Native chat and separate Claim Projection already require protocol-specific finish reasons. llama.cpp /completion transport preserves stop_type but currently synthesizes stop from stop=true when stop_type is missing; this is ambiguous, not proof of EOS. Keep distinct wire protocols; do not accept a native tool call merely because a text completion is terminal.

Sequence: reproduce R8-N02 through actual lab adapters and coordinator (valid stop and read proposal, incomplete/unknown/missing finish reason); then inspect native completion metadata and existing transport/planner consumers before agreeing explicit mapping. Reuse common typed terminal validation only where contracts agree, retain original reason and reported usage even for rejected outputs. Do not alter prompts, budgets, tool permissions, or historical evidence to obtain parity. Preserve canonical planner compatibility or explicitly scope/document any behavior change after checking existing tests. Unknown/missing reasons must not be silently treated as successful lab termination. Independent assessment remains R9.5.

RED tests: [adapter terminal contract](../../tests/test_e26_r93_terminal_contract.py). Synthetic responses only; successful eos/word controls and negative limit/length/unknown/missing reasons. No new implementation in this commit.


### R9.3 laboratory implementation and owner validation

| Step | Snapshot | Owner evidence |
| --- | --- | --- |
| RED | `dad4d58b8e862ecc975a3bfafc4151d0f48e2035` | 16 expected failures, 8 positive controls passed |
| Shared classifier / Legacy and Choice | `55f57d1eebd79f165e5c440814a0be7708ad1023` | 53 targeted, 333 cognitive, 10 transport tests passed |
| Native / Projection / offline consumers | `9714d1d17b7d00e3a088148b7a01e976dc024fea` | 80 targeted, 360 cognitive passed |
| Resource and error accounting | `dfc7cad95282330afa87150a3bc1a55dce59a6e4` | 31 new, 111 targeted, 391 cognitive passed; project checks PASS (203 pages, 1404 links, 457 Python files, Python 3.14.4) |

R8-N02 mitigated in the tested laboratory profiles; independent closure pending. Termination classification distinguishes native /completion (eos/word, limit/none) from chat/completions (stop/tool_calls, length/content_filter). Unknown/missing reasons fail closed. Diagnostic field is optional for historical archives; resealed contradictory metadata rejected in targeted tests. Existing ResourceBudget preserves known usage, including rejected calls; no budget/prompt/authority changes. Full regression, historical archive recheck and real backend gate still pending.

## 9. R9.3-C — Canonical Generation Contracts (owner-approved 26 November 2026)

Owner decision: every LLM consumer must establish normal generation termination according to an explicit trusted wire contract before accepting a cognitive or action proposal. Rejected/incomplete output may be retained as diagnostic material with reported usage, not as established Knowledge or executable proposal. No automatic retry, continuation, parking, new model authority or canonical Cognitive Result integration in this extension. Preserve existing privacy boundaries for raw text and existing role-specific error contracts; diagnostic retention does not imply permanent raw logging or exposing hidden reasoning.

C1 inspection at `dfc7cad95282330afa87150a3bc1a55dce59a6e4`: `anima/agent/llm_planner.py` and `anima/agent/small_llm.py` record finish_reason then parse a valid JSON decision without checking termination. `anima/cognition/fast_llm.py` and `anima/cognition/deep_llm.py` create FastResult / CognitiveProposal from returned text without checking termination. Two distinct LLMCallResult contracts exist; do not merge them merely because their names match. Native llama.cpp transports synthesize stop from stop=true without stop_type; this does not establish normal native termination. Some historical transport fixtures omit stop_type. Custom transport fixtures frequently use stop. Explicit wire declaration and fixture compatibility must be assessed, not infer protocol from model/provider or finish_reason. AgentLoop and RecoverableAgentLoop create Step before planner.plan; the latter also creates a recovery journal entry. Resulting failure/recovery behavior needs executable characterization; no confirmed runtime state defect yet.

| Step | Acceptance |
| --- | --- |
| C1 | Inventory existing consumers, transport contracts, metadata and failure boundaries |
| C2 | RED via real transport implementations with synthetic wire replies: valid text/JSON plus incomplete/ambiguous terminal reason, positive controls; runtime failure characterization separately |
| C3 | Explicit wire identity at trusted transport boundary; shared classifier; preserve original reason, no ambiguous fallback accepted; document compatibility for custom transports |
| C4 | Planner and SmallModelPlanner reject before parsing/admission; preserve call metadata and existing error type; no implicit cannot_progress |
| C5 | FAST and DEEP reject before producing result/proposal; preserve existing successful-only history contract and assess separate bounded diagnostics without raw reasoning exposure |
| C6 | Verify Runtime/Recovery and cognitive dispatch error paths; no action/effect on rejected proposal; use existing failure transitions where possible. Any required lifecycle redesign needs separate owner review |
| C7 | Targeted and full regression, project checks, historical bundle recheck and real backend gate; independent assessment in R9.5 |

C2 initial reproducer: [canonical terminal contract](../../tests/test_e26_r93_canonical_contract.py). 28 native and 12 chat cases, expected 30 failures and 10 positive controls before remediation. Tests do not execute external actions or real inference. Preserve baseline implementation in this RED commit.


### Canonical validation progress

| Step | Snapshot | Owner evidence |
| --- | --- | --- |
| C2 RED | `9c80993e608954f30d61d7175a427101be8486ad` | 30 expected failures, 10 passed |
| C3/C4 | `71f7bacd658e8506f43ceb061e821609af97902c` | 46 Planner targeted passed, 14 deselected; 42 Planner/transport regression; 111 laboratory targeted |
| C5 | `29255ace5c8497352c81111cbb83db914aef0f8f` | 82 canonical targeted, 78 FAST/DEEP regression, 193 R9.3 targeted; project checks PASS (203 pages, 1405 links, 458 Python files) |

Trusted transports explicitly declare wire_protocol; unknown declarations fail closed. Planner records terminal metadata before parsing; FAST/DEEP preserve successful-only call_history and retain at most 64 rejected returned-call metadata records without raw text. Missing native stop_type is no longer synthesized as stop. Custom transports must declare their wire and report the actual terminal reason. Earlier exceptions before a call result is available remain outside this rejected-generation history.

### C6 — controlled Planner failure

Existing AgentStore permits planning -> failed and running -> failed and requires terminal steps/operations before terminal Run. No new state or retry/parking policy is required for an ordinary controlled Planner failure. Current AgentLoop and RecoverableAgentLoop call planner.plan before Choice without a handler; source inspection indicates an exception can leave Step planning and Run running. Existing recovery abandons an active pre-selection Step then continues, appropriate for a crash but not an intentionally failed Run. RED: [runtime failure tests](../../tests/test_e26_r93_runtime_failure.py). Eight cases (baseline/recoverable x length/missing reason/invalid JSON/typed transport error) require failed Step and Run, unchanged Goal, no operation, no effect, no synthetic PlannerTurn, no retry on reopened terminal Run. Expected eight failures before implementation. Do not conflate a controlled error with arbitrary programming exceptions or crashes. Atomicity across the two terminal transitions and crash-boundary handling need separate inspection; no claim of general recovery correctness.


C6 owner RED: 8 failed at `4e52dbc180bd97e46a9d6598a9b95c7ce1287499`. Implementation `6e3cc85b92add61d4df69d8f03eb2edd5b171363`, fixture correction `72ef6ed6135268ec6111b63c9344149b7415d2a2`: 12 runtime, 181 agent regression, 205 R9.3 targeted passed; project checks PASS (203 pages, 1406 links, 459 Python files). AgentStore now atomically fails matching running Run and planning Step with no operation, reusing transactional transition checks and both transition journals. Typed LLMPlannerError/LLMTransportError handled before Choice; no Goal mutation, no fabricated PlannerTurn, no retry after committed failure. SQLite abort probe confirms rollback of both transitions; unexpected implementation exceptions retain the crash path. No power-loss or cross-owner atomicity proof. Untyped exceptions, including other validation failures, remain outside this narrow controlled-error boundary.

Cognitive failure boundary inspection: projected FAST already audits and rethrows FastModelOutputError with MODEL_OUTPUT, legacy FAST rethrows, DEEP dispatcher traces and rethrows before proposal validation without alternate role fallback. No new Task transition policy required. [Dispatch failure tests](../../tests/test_e26_r93_dispatch_failure.py) cover these three paths with four rejected reasons each; synthetic replies only, 12 additional tests pending execution. Existing Task ownership is preserved; a persistent active Task is not proof of full autonomous retry/parking support.

C7 remaining: run targeted and full regression, reverify six earlier bundles, exercise existing real-backend gates including both structured lab adapters and canonical text/Planner consumers. Record any research-quality failures separately from terminal-contract correctness. Independent audit remains R9.5.


### C7 full regression compatibility

Owner results at `274d5102f66f9b9cec2aa6d73c0a980bc68a53ea`: 12 dispatch integration and 217 R9.3 targeted passed; checks PASS (203 pages, 1407 links, 460 Python files); full regression 3003 passed, 13 failed (122.36 s). Historical bundles and real backend validation not yet reported for R9.3.

Source inspection: four failures in projected FAST pipeline/projection/audit tests use synthetic successful-call transports without explicit wire_protocol or finish_reason. In particular the empty-text fixture must first pass the termination gate to exercise FastResult content validation as intended. Nine benchmark failures share a native synthetic response fixture with stop=true and no stop_type. Repair only the test fixtures by explicitly declaring the actual synthetic protocol and completed terminal reason; keep original content, expected outcomes, negative content/transport tests, counters and benchmark evaluator unchanged. Add three benchmark-level negative tests for otherwise usable output with limit/none/missing stop_type. Do not synthesize successful termination in production. Expected 3019 full tests after these additions; execution pending.


### C7 — owner validation and early-response diagnostic gap

At `40d0d2ed71a2effbbc6d8eed8e91a5a8327a79a0`: 68 affected tests, 3019 full tests passed (120.53 s), project checks PASS. All six historical bundles verified (60 cases, 36 Raw samples, 200 requests). Legacy/Choice fresh owner traces: 14/10 calls, all eos/TEXT_COMPLETE, 12/10 valid, no terminal classification violations; quality 0/4 each. Native Control/Host evidence verified (14 cases and six Raw samples each, 44/47 requests); operation passes 8/14 and 9/14, not a causal comparison or backend attestation.

Canonical Native owner probe: all four roles accepted eos at 256-token budget, rejected limit at one-token budget with typed errors and reported usage; no executor. Canonical Chat default-template probe: all four responses length, two empty contents at 256 tokens rejected before call record construction (1883 input, 512 output tokens not represented in Planner history). Explicit enable_thinking=false probe: all four had nonempty content and zero reported reasoning characters; three length responses rejected by termination gate; SmallPlanner stop with 160 output tokens rejected for missing rationale_summary. No accepted real Chat Planner turn yet; no contract violation observed. Synthetic positive Chat coverage remains valid. Do not infer that default-template reasoning was confirmed from the original probe, which did not record reasoning length. Do not change production prompts, budgets or schema for a model-quality result.

C7 diagnostic RED: [early-response diagnostics tests](../../tests/test_e26_r93_early_response_diagnostics.py) exercise six canonical role/wire combinations, empty/whitespace/null output and completed-but-empty output, plus unfinished inline reasoning on FAST/DEEP. Existing typed error boundaries and success histories must remain unchanged. Preserve only reported resource and terminal metadata, character counts and role/provider/model identity in a bounded per-transport rejected_response_history; propagate the corresponding metadata on the typed exception (generation_diagnostic). No synthetic LLMCallResult, text retention, automatic retry, durable memory, or resource-budget authority. A response without a usable envelope or before generation is not an observed completed call; missing metadata must not be fabricated. RED expected 26 failures; pending owner execution. Boundedness, malformed usage and no-generation controls to be tested before closing. Independent audit remains R9.5.


### R9.3 — итог локальной валидации, 27 ноября 2026

**Проверенный snapshot:** `cadd7888bdf0d29badc4f99149e37b3be7c7f30c`. **Статус:** OWNER_VALIDATED в пределах проверенных контрактов; independent closure R8-N02 pending R9.5. Это не новый релиз, не закрытие E2.6 и не разрешение на расширение model-facing authority.

| Проверка | Результат владельца |
| --- | --- |
| Early Response Diagnostics RED, `cdba6a34cc6ee24eec25ed4cd99459a69e659343` | 26 failed (0.56 s), expected |
| Early Response Diagnostics GREEN | 59 passed (0.35 s) |
| R9.3 targeted | 276 passed (5.40 s) |
| Transport regression | 85 passed (0.76 s) |
| Full regression | 3078 passed (118.88 s), +279 relative to R9.2 |
| Project checks | PASS, 203 pages, 1408 links, 461 Python files, Python 3.14.4 |
| Real early rejection — Planner / SmallPlanner | 2/2, zero diagnostic failures |

The shared diagnostic helper resides in generation_termination.py. Generic and compact Chat Planner transports reuse the same response decoder. Native Planner and shared FAST/DEEP text transport retain metadata before propagating existing typed content errors. The bounded per-transport history retains up to 64 entries; exception diagnostics are detached copies. Invalid token counters are unknown, not zero. Pre-generation failures do not manufacture records. The new diagnostics do not store raw response or reasoning text fields, do not synthesize an accepted call, and do not introduce retry or memory writes.

Real final probe: Qwen3-4B-Q4_K_M, loopback llama.cpp, default template, 256-token limit. Planner: length / INCOMPLETE, 1160 input and 256 output tokens, zero content characters, 1084 reasoning characters, latency 8215.02 ms. SmallPlanner: length / INCOMPLETE, 727 input and 256 output tokens, zero content characters, 1045 reasoning characters, latency 4227.40 ms. Both raised LLMTransportError; call history empty; exactly one rejected response record each, matching exception metadata and observed backend counters. This confirms thinking-only output in the final default-template probe, not the unrecorded reasoning field of every earlier call. No accepted proposal or executor use. Reported counters are not independently measured resource usage.

Earlier owner evidence at `40d0d2ed71a2effbbc6d8eed8e91a5a8327a79a0` remains bound to that snapshot: six historical bundles (60 cases, 36 Raw samples, 200 requests) and two new native bundles (28 cases, 12 Raw samples, 91 requests) verified. Legacy/Choice 24 real calls; Canonical Native 8 calls, four accepted and four rejected; Canonical Chat two probes of four calls each, all rejected. These are distinct experiments, not a single final-snapshot end-to-end validation. No positive canonical Chat Planner result on Qwen3 was demonstrated. The final snapshot full regression supplies synthetic positive coverage and regression evidence, not a new full real-backend replay.

**Residual scope:** process-local diagnostic history, no durable/global resource accounting, malformed or unavailable response envelopes may lack counters, no guarantees against malicious backend metadata, no independent execution or backend attestation. The final-snapshot archive recheck and packaging are pending; source logs under owner's `/tmp/anima-r93-BKi2Gj` have not been independently inspected or archived by this reviewer. Preserve original artifacts, including failures; do not replace them with summaries or claim hashes not yet computed. Prior unresolved R9-Q/E/L findings remain open. Independent assessment should probe inconsistent terminal flags, alternative response paths and diagnostic coverage beyond tested content failures.

**Resume point — R9.4:** package local R9.3 evidence and verify the existing bundles under the final tested code, record archive SHA-256; then plan causal evaluation before new implementation. Priorities: information sufficiency, repeated operations, incremental information gain, retrieval quality, reuse of deterministic resolution, and matched-input evaluation (CA-06 and R9-E01/E02). Preserve R9.2 hybrid result and R9.3 terminal contracts, existing roadmap and read-only lab authority. No new development started in R9.4. R9.5 independent re-audit remains mandatory.


## 10. R9.4.0 — characterization и экспериментальный протокол, 27 ноября 2026

**Baseline этапа:** `5448e8ee8b09a3ad8d079896d85367201ed13d5a`, ветка `work/v02-e26-r9-remediation`. **Статус:** CHARACTERIZATION / DESIGN ONLY. Новые owner Recovery результаты, инвентаризация файлов/функций, C01–C14 воспроизводители, определения метрик, controlled experiment matrix и критерии R9.4.1–R9.4.4 зафиксированы в [техническом отчёте R9.4.0](e2-6-r940-characterization-v02.md). [Characterization tests](../../tests/test_e26_r940_cycle_characterization.py) исполняют неизменённую baseline реализацию через synthetic terminal-valid responses; PASS означает воспроизведение ограничения, а не исправление.

Подтверждённые механизмы: один возврат после model stop без оценки recoverability; отсутствие проверки sufficiency/gain после completed research read; cross-tool повтор одного event невидим для repeated_proposals; bounded empty search не имеет отдельного availability verdict; lexical lab Retrieval не выполняет semantic/alias matching. До получения Context недоступный working model может оставить вызов без turn result. Existing hybrid result уже отделяет stop/information/claims/prose и не утверждает Task success; provenance и R9.3 terminal checks сохраняются.

Host projection не инициирует acquisition; повторные Raw reads для integrity нужно считать отдельно. Пары Native Control/Host из Recovery не являются matched-input causal experiment. Existing replay_request повторяет один exact request без service dispatch; full recorded/fresh trajectory replay остаётся отдельным запланированным опытом. Нужны explicit tool-call-ID policy, request order, cache и backend configuration.

R9-Q02/Q03/Q04, CA-06 и R9-E01/E02 остаются открыты в прежней области; критерии не смягчены. Historical metrics и frozen evidence не изменены. No model/prompt/budget/tool permission changes, Knowledge writes или canonical integration. **Resume point:** рассмотреть результаты characterization и протокол; только затем начинать R9.4.1. Граница этой работы — R9.4.0, исправления не реализованы. Проверки текущего этапа и их граница записаны в §7 отчёта; independent re-audit остаётся R9.5.


## 11. R9.4.1a — Observable Cognitive State, 27 ноября 2026

На baseline `0cde809a9d0f5495d93706a25a9dbe404cc48515` реализованы offline versioned measurement sidecar, host-owned prefix coverage/availability view и isolated H/Q/I/T-recorded harness. Контракты, exact C01–C14 expectations, RED/GREEN/regression, archive SHA-256 и команды R9.4.1b находятся в [отчёте этапа](e2-6-r941a-observable-v02.md). Owner originals и historical completion/metrics сохраняются; измеритель не входит в policy/model context.

R9-Q02/Q03/Q04, CA-06 и R9-E01/E02 не закрываются измерениями. Continuation/stop/Retrieval/prompts/model/budgets/tool permissions, R9.2 Hybrid Result и R9.3 terminal contracts не изменены. **Resume point:** R9.4.1b — controlled baseline H/Q/I/T experiments по замороженному manifest; массовые fresh inference в R9.4.1a не запускаются. R9.4.2/R9.4.3 не реализованы; independent re-audit остаётся R9.5.


## 12. R9.4.1b — Baseline Model Experiments, 27 ноября 2026

На execution baseline `d34b472e51cdddf6f8700f0d521d4df65e8b4216` выполнены serial Q/I matrix: 2640 planned/attempted/received, 0 failed, no dispatch/retries. T-recorded 28/28, 93 exact requests; H0/H1 4 fixed journals, acquisition/research text/source bindings неизменны. В [техническом отчёте](e2-6-r941b-baseline-model-experiments-v02.md) находятся per-context results, hashes/choices/typed arguments/prose/terminal endpoints, resource costs, immutability, archive SHA и предложения R9.4.2.

I-event: 120/560 pairs меняют tool choice; I-tool: 480/480 operations/arguments совпали, 5 prose differences также наблюдаются внутри exact original repetitions. I-turn остаётся UNSUPPORTED. Это single-request baseline, не T-fresh и не causal policy benefit; прежние finding/quality gate statuses не закрываются. Реализация, model/prompts/budgets/permissions/Retrieval/continuation не менялись; R9.4.2/R9.4.3 не реализованы. Owner originals неизменны, independent R9.5 audit остаётся отдельным этапом.


## 13. R9.4.2 — Cognitive Control Policy

[Отчёт R9.4.2](e2-6-r942-cognitive-control-v02.md) фиксирует opt-in r942/0.1 в существующем lab coordinator: information sufficiency, availability-aware bounded continuation и source/tool-aware redundancy. Baseline-compatible default сохранён; historical assertions и scoring не изменены. New system termination не model stop/Task success. R9.4.3/T-fresh/canonical integration не реализованы; causal fresh policy evaluation остаётся R9.4.4. Новых prompts, generation budgets, tool permissions или Knowledge writes нет. Scope synthetic/recorded validation не закрывает generalized model-quality findings или R9.5 independent audit.


## 14. R9.4.3 — Retrieval Efficiency

[Отчёт](e2-6-r943-retrieval-efficiency-v02.md) фиксирует separate R942-R01/R02 hardening и r943/0.1 lexical retrieval: corrected query equivalence, semantic control-marker verification, explainable structural tie-break. Прежние profiles/evidence/metrics сохраняются. Offline control/held-out metrics не объявляются устранением recovery model-selection failure или causal fresh policy benefit. R9.4.4/T-fresh и canonical authority integration не реализованы.
