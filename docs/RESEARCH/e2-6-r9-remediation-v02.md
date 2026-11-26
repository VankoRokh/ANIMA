# ANIMA v0.2 — E2.6 R9: реестр находок и план исправлений

**Дата:** 26 ноября 2026. **Статус:** Research / R9.0 recorded; implementation and acceptance pending.
**Baseline:** `508851d458cf759902aa35c9ae140780fb29c4a0`. Рабочая ветка `work/v02-e26-r9-remediation`.
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

Acceptance does not require signatures, external attestation or new authority. No production changes or dependency additions without review of their necessity. R9.1 is not yet implemented or accepted.
