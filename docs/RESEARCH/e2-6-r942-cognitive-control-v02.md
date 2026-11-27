# ANIMA v0.2 — R9.4.2 Cognitive Control Policy

**Дата:** 27 ноября 2026. **Baseline:** `2a9cb1b202e3efcabaae0b2621320af3c431e242`. **Ветка:** `work/v02-e26-r9-remediation`.

Основания: [R9.4.0](e2-6-r940-characterization-v02.md), [R9.4.1a](e2-6-r941a-observable-v02.md), [R9.4.1b](e2-6-r941b-baseline-model-experiments-v02.md), [реестр R9](e2-6-r9-remediation-v02.md), [инициатива](e2-cognitive-initiative-v02.md), [FAST/DEEP](../ARCHITECTURE/Cognition_FAST_DEEP.md). Область — существующий read-only laboratory coordinator. Causal fresh policy evaluation остаётся R9.4.4; R9.4.3, T-fresh, canonical integration, Knowledge writes и новые полномочия не реализованы.

## R9.4.2.0: контракт и доверенное состояние

В [coordinator.py](../../labs/virtual_anima_lab/python/cognition/coordinator.py) добавлен host-only constructor parameter `policy_profile`. Default `baseline` сохраняет старый цикл, report bytes/fields и historical replay. Explicit `r942/0.1` требует existing NativeLabAdapter, CompletionRequirement и ResourceBudget. Это opt-in лабораторный профиль, не изменение production/default profiles и не параллельный coordinator.

[control_policy.py](../../labs/virtual_anima_lab/python/cognition/control_policy.py) строит pure bounded runtime view из frozen Context и checked `decision_records`: original completion prerequisites/coverage, completed operations, source identities `(world,epoch,source_ref,event_id,sample_id,raw_sha256)`, completed lookup obligations, normalized search outcomes и gain key `(covered units, unique verified source rows, unique search outcomes)`. Scope задаётся frozen Context hash и SourcePolicy; source rows допускаются existing `admitted_source_rows`. Conflicting same-event rows fail closed. Никаких evaluator labels, expected answers, offline sidecar, hidden world state или model prose в решениях нет.

Coordinator сохраняет existing context freshness checks и budget reserve/settle. Controlled Raw results дополнительно проверяются existing `_verify_captured_claim` и canonical loader перед финализацией. Prospective validation record описывает реально выполненный service read; при integrity failure journal получает REJECTED/SERVICE_REJECTED без result. Успешный result не фабрикуется. Checked prior records читаются до записи pending admission; verifier не читает незавершённый journal. Дополнительные verification candidates учитываются отдельно в control metadata; это runtime verification cost, не acquisition и не стоимость offline prefix measurements. Финальные Cognitive Result/Host verifier rereads сохраняются.

Control metadata `anima.lab.cognitive_control/0.1` содержит profile, reason, runtime view, effective remaining calls и `policy_verification_candidates`. Counter означает число попыток source validation, не физические bytes или гарантированное число disk reads. Runtime state не является универсальной оценкой semantic utility; repeated full-result reads определяются по конкретной deterministic tool semantics/frozen scope, а не только по Event ID.

## R9.4.2.1: sufficiency и termination

После подтверждённого результата и на границе перед следующим research call проверяется existing completion contract. При достаточности acquisition прекращается до нового model call. `no_service_read` исключён из initial sufficiency shortcut: требуется generation; состоявшийся forbidden read необратимо оставляет requirement violated и останавливает последующее research.

[turn_status.py](../../labs/virtual_anima_lab/python/cognition/turn_status.py) вводит `RESEARCH_TERMINATED`, допустимый только с versioned control marker и одним из reasons: INFORMATION_SUFFICIENT, SOURCE_UNAVAILABLE, REDUNDANT_OPERATION, NO_SERVICE_READ_VIOLATION. Это system-owned research termination, не model STOPPED, accepted final или Task success. После valid model stop declined continuation report остаётся STOPPED, поскольку stop действительно получен.

Completion evaluator принимает дополнительный host status, не меняя CompletionRequirement, coverage rules или historical verdicts. Hybrid Result сохраняет partial verified facts, model text attempts и NOT_ESTABLISHED Task completion; accepted model text отсутствует, если research закончила система после tool call. Optional model claim projection не вызывается без accepted research final. Host deterministic presentation остаётся отдельным verified consumer. Observable sidecar использует общий checked-result boundary и признаёт новое состояние без переноса измерителя в hot path.

Evidence export проверяет versioned terminal marker и полный native/journal chain. Recorded trajectory runner принимает explicit `policy_profile` для новых synthetic trajectories; default baseline прежний. Никакие unmatched generated requests не заменяются архивными. Runtime policy metadata JSON-native и сравнивается при replay; elapsed/latency остаются diagnostics.

## R9.4.2.2: availability-aware continuation

Memory OFF запрещает historical scope, но сохраняет latest scope. Для temporal requirement историческая часть при OFF недоступна; для lookup-only requirement разрешённый путь к entity в latest Context остаётся AVAILABLE. Missing entities вне наблюдаемого scope при Memory ON имеют UNKNOWN recoverability, а не объявленное отсутствие. Empty search остаётся bounded outcome, не world absence. Generic service rejection не классифицируется как временный outage и не возобновляется.

Continuation допускается только после valid model stop, при remaining existing budget и recoverability AVAILABLE/UNKNOWN. Первый UNKNOWN получает одну ограниченную возможность; повторный stop без наблюдаемого gain отклоняется NO_CONTINUATION_GAIN. После progress возможен следующий bounded continuation в пределах прежнего max_steps/ResourceBudget. Gain — coverage/source/search proxies, не proof semantic usefulness. Недоступная history и повторная deterministic пустая retrieval не вызывают futile повторных acquisition. Feedback text и prompts не менялись: используется прежний bounded CONTINUE payload. Controlled profile не возобновляет rejected native generations, в том числе прежний optional error-feedback branch; baseline profile сохраняет его прежнее поведение.

## R9.4.2.3: redundancy

Решение принимается после existing typed proposal/turn/context/source permission checks. Полностью известный lookup не исполняется повторно, если тот же verified row/digest/frozen scope не может закрыть новое требование. Inspect-latest после уже acquired latest — cross-tool duplicate. Повторный normalized query с тем же top_k на frozen deterministic search scope — duplicate. Другой top_k/query не блокируется как semantic equivalent.

C14: lookup после inspect-latest на том же Event ID разрешается, если впервые закрывает lookup-only requirement. Mixed known/new requests исполняются целиком с прежним admission, canonical set normalization и verification, без pruning старых sources. Belief tools не блокируются на основании совпадения source ID: их predicates/semantics могут отличаться. При duplicate journal сохраняет реальную rejected proposal, POLICY_NO_GAIN и execution_performed=false; report RESEARCH_TERMINATED/REDUNDANT_OPERATION, без успешного service result. Research завершён, а не молча заменён архивным ответом или model final.

## R9.4.2.4: validation и границы

[Новые tests](../../tests/test_e26_r942_policy.py) отдельно от неизменённых historical characterization assertions. Evidence root:

```text
/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r942-2a9cb1b/
```

RED: `red.log` — 12 failed до появления profile. Intermediate `green1/green2` сохраняют fixture exposure и JSON tuple/list replay failures; originals не переписаны. GREEN `green4.log`: **24 passed / 3.80 s**, включая actual Hybrid Result export/reconstruction и controlled recorded replay. Целевая regression `targeted.log`: **654 passed / 50.19 s** (до последнего test-only усиления Hybrid aggregate). Baseline historical behavior включает прежние C01–C14 characterization. Source/metadata tests: sufficiency после первого Raw — 1 acquisition, 1 model call, 0 post-sufficiency calls; OFF history — 1 search и 0 повторов; controlled search → stop → permitted Raw — 3 model calls с продуктивным completion; repeated stop без gain — 2 calls. Это synthetic sequences, не обещание успеха arbitrary real model.

Дополнительно: same/cross-tool denial без fabricated result; mixed known/new и native duplicate-array normalization; C14 same-ID new requirement fact и latest scope при OFF; no-service generation/violation; forged/foreign IDs; corrupted digest/source/sample; stale context; incomplete terminal/missing usage/input budget overrun; max call exhaustion; versioned status negatives; Hybrid partial facts и absent accepted final; export/verifier/replay совместимость. Канонические safety/terminal tests выполняются также в целевой и полной regression.

Limitations: profile не выбирает tools за модель и не гарантирует recoverability при UNKNOWN; фиксированная deterministic tool semantics не является semantic retrieval. При достаточности нет нового model final — presentation может быть partial/absent. Новые predicate requirements не вводятся. Per-turn state непостоянен, source scope не расширяется; default baseline сохраняется до отдельного выбора профиля trusted composition root. Fresh inference/2640-request rerun и causal claims о реальной модели — NOT_RUN. R9.5 independent review остаётся отдельным этапом.

Implementation snapshot/full regression, historical T-recorded и final checks фиксируются ниже после clean commit. SHA реализации определяется `git log -1 --format=%H -- labs/virtual_anima_lab/python/cognition/control_policy.py`; последующий documentation-only commit записывает результаты без изменения tested code.
