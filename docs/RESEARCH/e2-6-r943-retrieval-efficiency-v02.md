# ANIMA v0.2 — R9.4.3 Retrieval Efficiency

**Дата:** 27 ноября 2026. **Baseline:** `95dd28504b1ed72d77dae4eadee8fce4d45cbd8f`, branch `work/v02-e26-r9-remediation`.

Основания: [реестр](e2-6-r9-remediation-v02.md), [R9.4.0](e2-6-r940-characterization-v02.md), [R9.4.1a](e2-6-r941a-observable-v02.md), [R9.4.1b](e2-6-r941b-baseline-model-experiments-v02.md), [R9.4.2](e2-6-r942-cognitive-control-v02.md), [Memory/Retrieval](../ARCHITECTURE/Memory_and_Retrieval.md).

## 1. Targeted hardening, отдельный commit

`96b6fae` фиксирует R942-R01/R02 отдельно от ranking implementation. RED: 6 failures в `red.log`. R01 подтверждён actual search: ßcrate даёт crate, sscrate не даёт matching rows, хотя old casefold key одинаков. `r942/0.1` сохраняет прежнюю семантику для воспроизводимости. Новый `r942/0.2` использует conservative query key: stripped lower text для exact-ref scoring + sorted unique ASCII terms `[a-z0-9]{3,}`. Equal keys гарантируют одинаковую matching/ranking semantics; ключ намеренно не объединяет все потенциально эквивалентные запросы. Old completion empty-search query semantics не переписываются.

Evidence `verify_case` дополнительно проверяет versioned control metadata. Требование реконструируется как declared question scope; existing completion/state вычисляются по checked records/Context. Полное control state сравнивается, INFORMATION_SUFFICIENT и SOURCE_UNAVAILABLE должны соответствовать termination predicate. REDUNDANT_OPERATION требует последнюю действительно rejected POLICY_NO_GAIN operation и подтверждённую duplicate semantics на предыдущем prefix. Поддержаны профили r942/0.1, r942/0.2, r943/0.1. При пустом journal scope не придумывается: new system termination без checked scope отвергается, non-system terminal допускает только independently checkable completion и отсутствие acquired identities.

Resealed negatives проверяют contradictory INFORMATION_SUFFICIENT при coherent insufficient state, REDUNDANT_OPERATION без denied duplicate, SOURCE_UNAVAILABLE при доступном checked scope, изменённый gain/state. Recomputed checksums не делают их valid. Это **internal consistency**, не криптографическая аутентичность произвольного согласованного импорта; declared requirement и archive provenance не получают внешней аттестации.

## 2. Новый opt-in Retrieval profile

[retrieval_policy.py](../../labs/virtual_anima_lab/python/cognition/retrieval_policy.py) — pure lexical functions `tokens`, `query_key`, `explain`, `rank`. `policy_profile='r943/0.1'` в существующем coordinator включает R942 control с corrected query equivalence и новую сортировку. Defaults и r942/0.1 остаются baseline-compatible; r942/0.2 hardening не включает новое ranking. Model prompts, generation budgets, tool catalog, canonical set normalization и permissions не менялись.

OR candidate universe сохранён, top_k применяется после сортировки. Приоритеты: exact entity reference, число distinct substring terms, число whole-term matches, structural opaque-terminal penalty, stable lexical ref. Opaque penalty применяется только при равенстве предыдущих scores: repeated-character suffix либо hex suffix длиной ≥16 уступает описательному terminal token. Нет словаря entity names, shortcut aliases или expected answers. Это прозрачная lexical heuristic, не semantic relevance proof; категория obstacle сама не определяет intended entity. Generic ties без отличающихся признаков остаются lexical.

Original query сохраняется в proposal/journal; strategy string содержит r943/0.1. `returned`, `possible_matches`, `truncated` раздельны. Explain выводит exact/hit/whole-term/opaque/eligible компоненты; provenance rows не редактируются. Новые поля в model-facing result не вводятся, чтобы сохранить existing tool schema. History/source acquisition reuse унаследован от R9.4.2: no-gain rejection не создаёт fake result; mixed known/new, C14 и обязательные freshness/canonical verification rereads сохраняются.

Canonical RetrievalEngine использует Unicode tokens, casefold, длину ≥2, FTS seed, Memory/Knowledge statuses, entity/relation и lifecycle authority. Его `_tokens` несовместим с сохранённым ASCII lab scope (ß/cr/Unicode), scoring зависит от canonical stores/authority. Перенос этих функций изменил бы контракт; поэтому canonical engine не вызывается и authority не переносится. Common pure serialization и existing source/verifier contracts переиспользуются; lexical normalizer выделен локально.

## 3. Characterization и frozen offline evaluation

Evidence root: `/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r943-95dd285/`. `frozen-evaluation-inputs.json` фиксирует cases/labels/scope до исполнения metrics, `evaluate.py` — отдельный evaluator consumer. Runtime imports labels/held-out files не имеет. Frozen Raw — verified R9.3 Control seed 7; H01–H06 берутся из неизменённого R9.4.1a held-out manifest, label file hash записан отдельно. H07/H08 — availability/integrity fault scopes, не ranking relevance cases, проверяются source-policy regression.

C06/C07/C08 ниже — **локальные characterization IDs**, не historical experiment case IDs. C07 использует заранее описанный tie corpus aaa/shortcut; реальный recovery C03_ALT остаётся отдельной trajectory, его failed Raw selection нельзя объявлять исправленным одним offline ranking. C08 поиск уже exposed source может дать metadata, а не новый source acquisition.

Gate до сравнения: precision@k/recall@k/MRR не ниже baseline на каждом labelled stratum, ≥1 predefined ranking failure исправлен. Candidate universe/normalizer одинаковы, различается tie ranking. Verification yield — relevant verified returned entities / returned entities; offline evidence completeness — verified relevant / relevant units. Raw reread сохраняется для каждого returned candidate, не объявляется acquisition. Для synthetic C07 без Raw binding verification/completeness NOT_ASSESSED. Для unlabeled strata/zero relevant denominator — NOT_APPLICABLE, не 100%.

| Control stratum | baseline → r943 P@k / R@k / MRR |
| --- | --- |
| C06 crate; C08 already exposed; exact-ref | 1/1/1 → 1/1/1 |
| C06 box, ящик, cr | 0/0/0 → 0/0/0 (explicit unsupported) |
| multi crate+shortcut, k=2 | 1/1/1 → 1/1/1 |
| C07 generic category tie, k=1 | **0/0/0 → 1/1/1** |

Held-out **отдельно**: H01/H02/H03 aliases/language/short token остаются 0/0/0; H04 actual frozen obstacle query — 1/1/1 в обоих; H05 truncation и H06 Memory OFF — unlabeled relevance NOT_APPLICABLE. Scope/metadata и source binding проверяются отдельно. Не вводились aliases ради held-out answers. Никакой настройки критериев после metrics не было. Labelled real-Raw positive strata verification yield/completeness сохраняются; search-only redundant acquisition NOT_ASSESSED, чтобы не смешивать retrieval metadata с чтением источника.

Отдельный paired synthetic loop на одинаковом frozen Raw и exact initial request: baseline completed reads=4, unique source=1, redundant acquisition=3; r943 completed reads=1, unique source=1, redundancy=0; information completeness SATISFIED в обоих, accepted model final не фабрикуется. Это унаследованный R942 control effect, не новый causal ranking benefit. Fixture самодостаточен и не зависит от owner Evidence paths.

## 4. Tests, ограничения и граница

[Новые tests](../../tests/test_e26_r943_retrieval.py): R01 actual-search reproducer/version split; R02 resealed semantic negatives; exact-ref/multiple terms/category tie; OFF/provenance/metadata; evaluator isolation; paired frozen acquisition/completeness. Existing R942 safety tests и characterization assertions не переписаны. Intermediate RED/GREEN logs сохраняются. `green-final.log`: 35 passed / 5.18 s до test-only переноса paired fixture на isolated synthetic Raw; final clean snapshot включает этот перенос.

Ограничения: generic opaque-ID heuristic может ошибаться вне проверенных strata; это не synonym/translation/semantic retrieval. Полные показатели/refs/explain per stratum — metrics.json. Малый frozen corpus не обосновывает generalization; recovery C03_ALT model selection и whole-answer quality не переоцениваются без fresh trajectories. UNKNOWN source/service state не превращается в outage или world absence. New profiles opt-in, default unchanged. Никаких embeddings, dependencies, inference calls, Knowledge writes, canonical integration, новых целей, T-fresh или R9.4.4. R9.5 review остаётся отдельным.

Final implementation SHA, regression, baseline replay и checks записываются после clean snapshot; data/receipts хранятся вне repository.
