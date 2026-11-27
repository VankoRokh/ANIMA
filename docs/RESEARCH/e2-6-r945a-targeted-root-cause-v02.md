# ANIMA v0.2 — R9.4.5a Targeted Root Cause Analysis

Baseline: `2f0f5e68d1e9485e08f62153bd38389d7fb3f08e`, branch `work/v02-e26-r9-remediation`. Исследование offline; working/runtime profiles, prompts, модель, budgets, catalog/permissions не изменены. r943/0.1 **не принят как stable baseline**. R944-F01/F02 остаются OPEN.

Основания: [R9 register](e2-6-r9-remediation-v02.md), [R9.4.0](e2-6-r940-characterization-v02.md), [R9.4.1a](e2-6-r941a-observable-v02.md), [R9.4.1b](e2-6-r941b-baseline-model-experiments-v02.md), [R9.4.2](e2-6-r942-cognitive-control-v02.md), [R9.4.3](e2-6-r943-retrieval-efficiency-v02.md), [R9.4.4](e2-6-r944-controlled-evaluation-v02.md).

## 1. Evidence, trust boundary and references

Пути для точных references ниже:

- `E=/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r944-15be9a5/` — неизменяемые исходные материалы.
- `R=/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r945a-2f0f5e6/` — новые analysis/reproducers, отдельно от repository и E.
- `P=E/fresh/control-7-C03-{00..19}-{A,B}/` — все 40 trajectories, не только representative pair.

Проверены все **95118 regular-file SHA-256** из E/SHA256SUMS; архив R944 совпал с final receipt: `50c445c0f7633f7f675fc33acff4a59e96332415afc78f86ced6b7bdf3cda200`. Дополнительно проверены hashes R944-F01 reproducer и R944-F02 output, 35 внешних frozen plan/case/Raw files; owner audit подтвердил прежние 7 archives, 8 bundles и 206 Recovery files. Штатный verifier проверил native calls/source bindings и offline reconstruction Hybrid Results всех 40 F01 cases. Для reconstruction использованы только derived in-memory aggregate fields из оригинальных report/calls/result, оригиналы не reseal/overwrite. Проверка означает integrity/internal consistency, не криптографическую аттестацию произвольного согласованного архива.

`R/analyze.py`, `reproduce.py`, `complete_proofs.py`, `summarize.py` — исполняемые offline reproductions. `R/exact-references.json` фиксирует полные payload hashes и JSON pointers. `R/F01-20-pair-analysis.json` содержит каждую пару, first differences, source eligibility, resource counters и B result flags. `R/representative-timeline.json` сохраняет без сокращений все calls/journal/turn/result representative pair 00. Диагностические ошибки первоначального parser/schema assumption сохранены отдельно; вывод о direct lookup в A уточнён по полным 20 trajectories, данные не отбирались.

**Ни одного fresh inference/request к model backend.** Два положительных T-recorded controls и один ожидаемый negative replay используют только RecordedTransport и независимые Raw-restored stores. Offline Raw reads в этом исследовании не добавляются задним числом к acquisition/completeness оригинального B.

## 2. F01: точная последовательность и первое различие

### 2.1. Representative pair 00

Полные wire references: `E/fresh/control-7-C03-00-{A,B}/wire/NN-exchange.json#/request` и `#/response`; requests/responses сохраняются также отдельными envelopes `NN-request.json`, `NN-response.json`. Indices нулевые. Request hashes — canonical payload SHA, не SHA envelope file.

| Arm/call | Request/response decision | Journal/outcome | Input/output tokens |
| --- | --- | --- | --- |
| A/00 | retrieve_memory(query=`crate shortcut`, top_k=2) | journal[0], ADMITTED/COMPLETED | 720/28 |
| A/01 | lookup_raw_evidence([ev_e9a51be5-1f93-4510-ae14-db24548bdba9]) | journal[1], ADMITTED/COMPLETED | 1152/87 |
| A/02 | accepted research text stop | no new operation; STOPPED, information SATISFIED | 1563/85 |
| A/03 | existing claim projection, no tools | separate projection, same shared ResourceBudget | 507/202 |
| B/00 | тот же retrieve_memory | journal[0], ADMITTED/COMPLETED | 720/28 |
| B/01 | text stop | no new operation; CONTINUE, 2 calls remaining | 1159/102 |
| B/02 | text stop | no new operation; NO_CONTINUATION_GAIN, 1 call remaining; STOPPED, INCOMPLETE | 1320/100 |

Exact initial request A/B: `1266cf8dde644e412637a1697ff45c025d36d18b000937b93f06caf40fe274df`. Next request A/01: `856990eac0b6253886411dd7870a450d260bee072a7c1e74d927e7f74281c99d`; B/01: `f3cd51242fc1d979cdd65805731b9dd75f80652d99f73ceec90c254a1abddac3`.

A final budget: reserved_calls=4, input=3942, output=402, elapsed=12248.002 ms, stop_reason=null. B: reserved_calls=3, input=3199, output=230, elapsed=6324.743 ms, stop_reason=null, usage complete, no pending reservation. Остаток B на сохранённой границе: **1 call, 4993 input tokens, 794 output tokens, 53675.257 ms**; reservation требует 256 output tokens. Штатный ResourceBudget.check_next на этих сохранённых counters возвращает None. Это возможность зарезервировать call на этой границе, не гарантия его результата или соблюдения input/elapsed ceiling после генерации.

### 2.2. Все 20 пар, без усреднения sequences

**CONFIRMED:** A complete 20/20, B incomplete 20/20. A pairs 00–02: retrieve→lookup→stop→projection. A pairs 03–19: retrieve→stop→CONTINUE→lookup→stop; 4 research calls, projection уже не помещается. B во всех парах: retrieve→stop→CONTINUE→stop→NO_CONTINUATION_GAIN, всего 3 research calls. Accepted final не тождественен выполнению requirement.

**CONFIRMED:** call 00 operation/typed arguments одинаковы в 20/20, несмотря на разные response/native IDs. Первое model-visible request difference — **call 01** во всех парах. Первое parsed response signature difference (включает точный free text) — call 01 в 20/20. Первое различие tool-vs-stop decision: call 01 в 3 парах; call 02 в 17 парах. Не следует называть различный prose на call 01 различным выбором инструмента в этих 17 парах.

### 2.3. Ranking, representation и IDs

Для каждого journal[0].outcome.result проверены records **с порядком**, entity refs, source/event/sample/digest, temporal/geometry/properties, memory_enabled=true, returned=possible_matches=2, truncated=false. Всё одинаково, **кроме strategy**:

- A / baseline / r942/0.2: `ranked_lexical_not_semantic_retrieval`.
- B / r943/0.1: `r943/0.1_lexical_coverage_opaque_id_tiebreak`.

Records: `[lab.item.crate, lab.obstacle.shortcut]`; оба указывают на один historical event `ev_e9a51be5-1f93-4510-ae14-db24548bdba9`, sample `worldobs:cca1f097de9218ff05588c15cf595bf6:1:2`, Raw digest `aa708a2db3708a71402f8a2fde345630439f65619855b8d630df804402fffceb`. Последний captured sample — sequence 3. Одинаковый hash не используется как единственное доказательство event identity: сравнивается полная binding/scope tuple.

**CONFIRMED:** в request 01 различаются только native assistant tool_calls[].id / matching tool_call_id и JSON result.strategy. Это доказано 20/20: typed BIJECTIVE_RENAME A→B IDs плюс одна локальная замена strategy дают точное равенство copy request B. Оригиналы не менялись; normalized copy не называется исходным exact request и не отправлялась модели. Event/Sample IDs не переименовывались. Первое journal divergence R944 на operation 0 включает strategy metadata, а не different selected operation.

**CONFIRMED:** ranking improvement **не объясняет F01 через другой набор/порядок кандидатов**: на этом query такие изменения отсутствуют. Pure service reproduction на одном восстановленном Raw даёт одинаковые records для baseline/r942/0.2/r943/0.1, только последний profile меняет model-visible tag. Это не отменяет проверенное R943 C07 lexical improvement на другом stratum.

**HYPOTHESIS:** tag/representation sensitivity влияет на следующий model choice. **HYPOTHESIS:** generated native IDs или их interaction с tag влияют на него. Оба фактора одновременно изменены; causal shares не идентифицированы. R941b I-tool characterization не заменяет факторный контроль именно этого request. Нельзя объявить IDs причиной или доказать их безвредность по одной paired trajectory.

### 2.4. Source availability, stop policy и r942/0.2

**CONFIRMED:** нужный event уже присутствует в typed **initial model-visible** bindings; Memory ON. TurnSourcePolicy разрешает lookup, проверка его фактического A result против B scope проходит. Pure controlled redundancy check для этого lookup возвращает false: после retrieve нет admitted verified Raw rows. Raw реально существует в frozen snapshot и обслужен A; это не UNKNOWN outage и не новый источник, обнаруженный только дальнейшими шагами. Во время RCA существование дополнительно проверено offline, но оригинальный B verdict не меняется.

Completion для verified_observation требует **lookup_raw_evidence**, retrieve не создаёт admitted_source_rows. После search state gain_key=`[0,0,1]`: covered required entities=0, verified source rows=0, search outcomes=1. Два text stops не создают completed operations/facts/search outcomes, state остаётся тем же. Coordinator сохраняет gain на первом stop; на втором равенство вызывает NO_CONTINUATION_GAIN (`coordinator.py:365–399`, `control_policy.py:19–60`). Budget/availability/duplicate rejection не являются причиной F01 stop.

**CONFIRMED по коду:** baseline на *том же заданном* двух-stop sequence тоже завершился бы после одной CONTINUE, с reason CONTINUATION_LIMIT и одним unused call. Existing baseline expression извлечён AST и выполнен с remaining=1 и одной previous decision; не подставлялись archival responses под unmatched requests. Следовательно, нельзя приписать регрессию только новой NO_CONTINUATION_GAIN ветке: различный reason не доказывает более ранний stop относительно baseline на одинаковом sequence.

В 17 A pairs generic CONTINUE feedback **точно совпадает** с B feedback, включая REQUIRED_SOURCE_NOT_VERIFIED и remaining_model_calls=2; различается antecedent transcript. A затем выполняет lookup, B снова stops. Feedback не объясняет это как самостоятельное treatment difference. Он не различает явно retrieved metadata и невыполненный lookup-only prerequisite; его adequacy для B history — открытая проблема, не доказанный causal fix.

| Profile | Подтверждённое сравнение | Что не известно |
| --- | --- | --- |
| baseline | actual A, старый strategy, one-continuation bound; exact recorded pair00 replay 4/4 MATCHED | результат при изменении только tag/ID |
| r942/0.2 | old strategy/ranking; тот же corrected query key, sufficiency/gain/redundancy code, что r943/0.1; state на B journal совпал | fresh trajectory profile не запускалась в R944 |
| r943/0.1 | actual B; exact recorded pair00 replay 3/3 MATCHED; source available, lookup not redundant | causal shares tag/IDs/policy |

Negative replay B input под r942/0.2 останавливается после одного matched request: JOURNAL_PREFIX_MISMATCH на operation 0 перед response на request 1. Generated request 1 сохранён: с тем же recorded first native ID он отличается от r943 request 1 **только strategy**. Archived response 1 не выдан. Это доказательство plumbing/input boundary, **не** предсказание ответа r942 модели и не failure исторического baseline replay.

## 3. F02: утверждения, proof и presentation

Exact reference: `E/fresh/control-7-C03-00-B/result.json`; исходные ответы — wire/01-exchange.json и 02-exchange.json, `#/response/choices/0/message/content`.

| Утверждение / поле | Contract assessment |
| --- | --- |
| Call 01: not_observed «indicating they are not currently present in the environment» | Unsupported world-absence inference. В Hybrid reasoning/model_text_attempts/0, authority UNVERIFIED, protocol INTERMEDIATE_OR_UNACCEPTED; это **не** selected final model_text |
| Call 02: «previous observations ... have been verified» | Не подтверждено выполнением verification в B: journal содержит только retrieve. reasoning/model_text_attempts/1 и presentation/model_text; protocol ACCEPTED_FINAL, authority UNVERIFIED |
| Historical metadata seq2/event ID | Само metadata совпадает с источником; оно не удовлетворяет lookup-only requirement и не аттестует current world |
| information/status=INCOMPLETE, evidence/facts=[], integrity_status=NO_CLAIMS | Не было false typed verified fact или fake successful lookup |
| execution/task_completion=NOT_ESTABLISHED, whole_answer_verified=false | Нет Task success/whole-answer verification |

Typed verifier принимает ограниченные observation predicates, а не произвольный prose. Reproducer того же positive source-sample claim: B → UNSUPPORTED/SOURCE_NOT_VERIFIED_IN_TURN **без загрузки более позднего Raw**; A после admitted lookup → VERIFIED/MATCHES_CAPTURED_SAMPLE. Historical sample2 claim со scope latest_captured_sample → UNSUPPORTED/HISTORICAL_SOURCE_NOT_LATEST. World-absence predicate не поддержан контрактом. Это source/scope verification, не universal prose verifier.

`not_observed` относится к последнему captured view (FOV/range/occlusion), не физическому отсутствию объекта и не непрерывному current-world monitor. Даже допустимое «не наблюдался в latest captured sample» требует соответствующего bound evidence для typed claim; B не выполнял inspect_latest. Историческое наличие reading нельзя превратить в current visibility. Неизвестность/отсутствие необходимого evidence не заменяется отрицательным world fact.

**CONFIRMED:** STOPPED + accepted research final допускается при information INCOMPLETE: protocol acceptance проверяет законченный корректный text, а не semantic truth или requirement satisfaction. В F02 research_final_index=2; projection_status=INFORMATION_INCOMPLETE. model_claims.phase=claim_projection и status=NO_ACCEPTED_FINAL означает отсутствие accepted **projection** для typed claims, а не отсутствие accepted research answer. Это phase-sensitive обозначение нельзя читать вне контекста.

**CONFIRMED:** существующий Hybrid contract сохраняет authority UNVERIFIED, free_text_verified=false и отдельные data paths. Consumer, который показывает только presentation.model_text или трактует STOPPED/ACCEPTED_FINAL/NO_CLAIMS как глобальный success, может скрыть ограничения. **HYPOTHESIS/risk:** phase names и соседство verified facts/prose способствуют такой ошибке отображения. **NOT_ASSESSED:** конкретный внешний consumer действительно неверно маркирует текст; в исследованных exporters такого повышения authority не обнаружено. Реальный consumer/UI experiment не проводился.

System-owned termination отдельно: у B 400 RESEARCH_TERMINATED и **нет accepted model final**. Из них 320 INFORMATION_SUFFICIENT (240 с verified facts, 80 satisfied empty-search без facts) и 80 REDUNDANT_OPERATION/INCOMPLETE без facts. Существующие facts не исчезают из-за отсутствия prose, но отсутствие текста не становится успешной генерацией. Результаты/исходы/model final не фабрикуются.

## 4. Откуда efficiency и дополнительные rereads

Разложение проверено по **всем 1120 trajectories**, не только F01; `R/efficiency-decomposition.json` и `accounting-proofs.json`. Model calls не тождественны admitted service operations.

| Call category | A | B | A−B |
| --- | ---: | ---: | ---: |
| Research tool proposals (включая отклонённые) | 780 | 760 | 20 |
| Research text-stop attempts | 793 | 360 | 433 |
| Other rejected/incomplete research calls | 20 | 0 | 20 |
| Claim projection | 267 | 80 | 187 |
| Total | 1860 | 1200 | **660** |

433 text-stop savings = **380 fewer accepted finals** (540→160) + 53 fewer continued stop attempts (253→200). Final text + projection дают 567/660 = **85.91%** savings; это descriptive accounting, не causal attribution или evidence качества research. Net 20 fewer tool proposals соответствуют потерянным required F01 Raw lookups. Нельзя считать их полезным research improvement.

Terminal transition accounting: A STOPPED→B RESEARCH_TERMINATED: 380 pairs, 620 saved calls; A REJECTED→B RESEARCH_TERMINATED: 20 pairs, 20 saved; A STOPPED→B STOPPED: 160 pairs, 20 saved. Поэтому 400 новых system terminations означают 380 fewer previously accepted finals плюс 20 previously rejected trajectories, а не 400 lost accepted finals.

Completed service calls: search 280→280; lookup 360→260; inspect_latest 140→140; B дополнительно отклоняет 80 duplicate lookup proposals без fake service result. Raw service reads 500→400 = **80 OFF duplicate reads avoided + 20 required F01 reads lost**. Все четыре OFF contexts дают по 20 avoided reads, но completeness в OFF не выросла.

Runtime service/policy Raw rereads:

| Component | A | B |
| --- | ---: | ---: |
| Service Raw load (one per returned admitted Raw row) | 500 | 400 |
| Additional pre-finalize policy verification reread | 0 | 400 |
| Total | **500** | **800** |

Net +300 = −100 service +400 policy. Gain/state functions pure и сами Raw не читают. Controlled coordinator после service load/source check выполняет `_verify_captured_claim` с ObservationClaimVerifier._load_view перед finalize (`coordinator.py:505–526`): отдельный re-read проверяет Event↔Sample, Raw digest, source/scope/contents. Эти 400 checks **обязательны по текущему профилю**, их удаление ради метрики не предлагается.

Потенциальный redundancy candidate — непосредственная повторная загрузка уже проверенного того же Raw внутри одной bounded service/verification transaction. Только отдельный design мог бы передавать immutable verified view в pure predicate verification при сохранении independent binding/digest/scope/freshness checks. Достаточность такой замены **NOT_ASSESSED**; cache по одному Event ID/hash, меж-turn cache или отмена обязательного reread недопустимы без нового контракта. Entity-level result/model-claim verification также может повторно загружать один sample; batch verification общей checked view — отдельная гипотеза, не разрешение снизить integrity.

Result construction rereads 574→380, Host projection 80→80, offline measurement 2475→1140; context integrity row checks 16098→11160. Эти phases не объединяются с acquisition или 500→800 runtime счётчиком. Input/output token и latency reductions R944 не переинтерпретируются: cache/backend UNKNOWN, accepted presentation и verified coverage снизились.

## 5. Варианты remediation для отдельного review

Ни один вариант ниже не реализован. Versioned opt-in profile обязателен; baseline/r942/0.2/r943/0.1 и их exact archived requests/replayers сохраняются. Принятие r943 как stable не предлагается.

| Вариант | Причина и минимальный контракт | Риски | Expected acceptance / historical reproducibility |
| --- | --- | --- | --- |
| **A. Stable model-visible Retrieval metadata** | Устранить version-tag treatment при одинаковых results. Общий точный lexical strategy description в model result; actual algorithm/version/explain остаются host-owned measurement/provenance. Никаких aliases, новых tool fields или ranking changes | Может скрыть реальное изменение semantics, если общий tag неточен; само по себе не доказано как causal fix F01 | На C03 fixed IDs/query/records give equal tool reply/request bytes; ranking действительно изменённых cases не маскируется. C07/exact-ref/multi-term regression сохранена. Старые profiles обязаны по-прежнему выдавать старые strings; old T-recorded 28/93 |
| **B. Requirement-aware continuation feedback** | Явно различить metadata search и missing lookup-only prerequisite; только approved requirement + checked observed scope/previous operations. Допустимы уже model-visible/admitted references, без evaluator labels/hidden answers, без обещания физической availability до проверки | Новая подсказка может менять choices/стоимость, overfit C03, случайно раскрыть запрещённый historical scope. Успех произвольной модели не гарантирован | Один existing bounded CONTINUE, прежние budgets; no retry после incomplete/rejected generation. C14 lookup asymmetry, mixed known/new, OFF/latest, UNKNOWN, forged/stale/digest negatives. Synthetic permitted missing path должен получаться в старом бюджете; repeated stop всё ещё bounded. Fresh benefit проверяется отдельно, archived feedback не переписывается |
| **C. Deterministic resolution of an unambiguous gap** | Отдельное архитектурное предложение: host может распознать единственный разрешённый lookup binding для approved missing units. Для host-origin service operation нужны явные origin/journal/admission/budget contracts; нельзя выдать его за model proposal/response | Меняет host initiative/operation scheduling, возможен новый authority boundary и TOCTOU; неоднозначные/missing/foreign источники нельзя угадывать. Не входит в минимальную реализацию без отдельного review | Те же SourcePolicy, Memory OFF, digest/provenance, resource/operation limits; no-service-read не разрешает skip generation; unknown/ambiguous abstain. Ноль fabricated model calls/outcomes/Task success. Old profiles/replay сохранены. **DEFER**, сейчас не реализовать |
| **D. Separate verified facts, limits and prose** | Consumer/presentation contract: показывать typed facts со scope/source, information completeness/missing units, accepted research final, projection status и unverified prose отдельными секциями. Phase-qualified display NO_ACCEPTED_FINAL; actual Hybrid authority не повышается | UI может скрыть partial facts, выдать host summary за model final или трактовать protocol acceptance как truth. Не предотвращает все hallucinations модели | F02 incomplete + accepted unverified prose не показывает global verified/success; system termination показывает facts и отсутствие model final. Partial facts сохраняются. No new model call/prose verifier/Task gate; original JSON/statuses не нормализуются задним числом |

**Минимальный план R9.4.5b:** сначала review A/D contracts и сохраняющих baseline negative tests. Для выбора behavioral исправления провести только отдельно разрешённый ограниченный diagnostic ниже; нельзя обещать, что A достаточен для F01. B — после review конкретного feedback contract, с прежним bound; A и B не объединять в один treatment без attribution, если требуется причинный вывод. C вынести за этот минимальный объём. Integrity optimization не является необходимой частью F01/F02 исправления: сначала сохранить её checks и исправить наблюдаемые semantics/presentation границы.

### Proposed diagnostic — NOT RUN

`R/diagnostic-proposal-NOT-RUN.json`: один frozen A request 01, 2×2 factors **old/new strategy × original/bijectively-renamed native tool ID**, 20 counterbalanced blocks ×4 cells = **80 single-request calls maximum**. Полные typed ID declarations/replies согласованно переименовываются, Event/Sample/Raw scope неизменны. Serial, no tool dispatch, no archived-response substitution, no retries/selective reruns, unchanged model/settings; backend/config change останавливает trial. Next tool/typed args/text stop отдельно от exact/prose hashes; один frozen context не становится 20 независимыми scenarios. Это не T-fresh и не 2640 Q/I matrix; не устанавливает эффект continuation policy или generalization. Requests не отправлялись, ответы не синтезировались. Перед inference нужны отдельное разрешение и frozen hashes/order/backend preflight по принятому протоколу.

## 6. Итог уверенности и validation

| Статус | Вывод |
| --- | --- |
| **CONFIRMED** | F01 не изменяет retrieved candidates/order; first request difference — strategy+IDs. Required Raw binding доступен/допустим, не redundant; state не меняется после двух stops; ResourceBudget не исчерпан. Baseline на тех же двух stops тоже ограничен одной continuation |
| **CONFIRMED** | F02 prose не получает verified authority. World-absence inference выходит за bounded observation. Accepted research final и completeness/accepted projection независимы. Наблюдается consumer-risk boundary, а не доказанное повышение authority в exporters |
| **CONFIRMED** | 660-call savings и +300 Raw rereads разложены; presentation reduction — основная доля savings; 20 required Raw lookups потеряны |
| **HYPOTHESIS** | Sensitivity к strategy/ID и interaction; более явный feedback поможет B; verified-view batching снизит I/O при прежней integrity |
| **NOT_ASSESSED** | Отдельный causal effect каждого фактора; fresh r942/0.2 trajectory; успех предложенных исправлений/четвёртого call; реальные внешние consumer mislabelling; универсальная semantic truth/prose utility |

Offline positive controls: baseline A 4 requests и r943 B 3 requests exact MATCHED, journal/result matched. Negative r942 derivative: expected early divergence, unmatched response не выдан. Typed verification guards, production baseline-stop expression и source eligibility assertions PASS. Полная регрессия и fresh matrices не повторялись: repository changes только Markdown, runtime не менялся. Project checks **PASS**: 210 pages, 1497 links, 468 Python syntax sources, 21 Bash. Изменены только три Markdown-файла; implementation остаётся на baseline. SHA/clean worktree и archive integrity фиксируются в итоговой receipt.

Новые материалы архивируются вне repository: `/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/ANIMA-R945a-2f0f5e6-Evidence.tar.gz`, SHA-256 **1773b00b2761e8f832dab570bc95ceab4314fc85aa263490c3aff0579f94af74**. Receipt с final documentation SHA — `/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r945a-validation-receipt.json`. R944-F01/F02 не закрыты, benefit остаётся INCONCLUSIVE. Остановка **до** реализации remediation и любого fresh diagnostic.


Offline reproduction из repository root на указанном baseline/runtime, в **новый sibling directory** (существующие outputs exclusive; не перезаписывать исходный RCA):

```bash
RCA_COPY=/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r945a-reproduce-01
mkdir "$RCA_COPY"
cp /home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r945a-2f0f5e6/{analyze,reproduce,complete_proofs,summarize}.py "$RCA_COPY/"
.venv/bin/python -B "$RCA_COPY/analyze.py"
.venv/bin/python -B "$RCA_COPY/reproduce.py"
.venv/bin/python -B "$RCA_COPY/complete_proofs.py"
.venv/bin/python -B "$RCA_COPY/summarize.py"
```

Команды не запускают предложенный diagnostic или model transport. Original root/archives должны сохраняться по указанным путям и hashes. Текущее исследование завершено; эти команды приведены для отдельного offline воспроизведения, не для rerun fresh matrix.
