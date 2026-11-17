# ANIMA v0.2 — H5.5 R3 / Evidence Consistency (F-04)

**Статус:** R3/F-04 принят по отчёту владельца: адресные `68 passed` за 1,51 с и полный `1999 passed` за 88,71 с. RC по-прежнему **BLOCKED** до R4 и независимого повторного review.  
**Ветка:** `work/v02-h55-evidence-consistency`, основана на принятом R2 @ `9010849762454ab7af87bd9902441a5243ae7f7c`.  
**Результат владельца R2:** `58 passed` за 1,48 с (адресные), `1987 passed` за 87,60 с (полная регрессия).

## Первичный дефект F-04

`ANIMA_v0.2_H5.5_evidence.zip`, `h55_work/independent_probes.py::contradictory_current_evidence`:

1. Через `build_core` поступает Raw Event, из него создаётся Memory и переводится в CLOSED.
2. `KnowledgeLayer.create_candidate/confirm` делает Knowledge `confirmed`, создаётся Relation `Memory → Knowledge:supports`.
3. `LinkStore.create_relation` допускал `Memory → Knowledge:contradicts` **той же Memory и Knowledge** при пересечении периодов действия.
4. `KnowledgeLayer.describe` показывал эту Memory одновременно в `supporting_sources` и `contradicting_sources`, но `labs/v02_h5_legacy_diagnostic.audit_snapshot` возвращал `healthy`, а `labs/v02_h5_compatibility.analyze_snapshot` — `NO_ISSUES_DETECTED`.

Сценарий воспроизведён независимым аудитором на frozen SHA `28e8438f8408e85b52e237eaedcf024354a4522a`. Прежний штатный pytest не проверял эту цепочку.

## R3 / механизм защиты

**Runtime writer:** `anima/memory/link_store.py::LinkStore.create_relation` для `source_kind='memory'`, `target_kind='knowledge'`, типа `supports/contradicts`:

- Под `BEGIN IMMEDIATE` читает противоположные Relations той же Memory и Knowledge до INSERT.
- Отказывает при **пересечении** периодов `[created_at, valid_until)`, сравнивая offset-aware timestamps как инстанты; `valid_until=NULL` означает бесконечность.
- Проверяет обе полярности. Неправильный/пустой Evidence-интервал также отвергается.
- Если интервалы не пересекаются (например, первая запись истекла **точно** в момент второй), исторические Relations **разрешены**. Противоположные мнения двух **разных** Memory, или одной Memory о **разных** Knowledge не запрещаются.
- До отказа не создаются записи Relations/Knowledge/History. `EventProcessing`, Raw и схема БД не меняются.

**Offline diagnostic:** `labs/v02_h5_legacy_diagnostic.py` формирует finding `conflicting_active_knowledge_evidence` для одновременно действующих противоположных Relations одной Memory к одному Knowledge. Учитываются только действующие в `as_of` интервалы, не архивные или будущие. Finding по паре не дублируется. Из-за результата `base_diagnostic=degraded` существующий H5.4b `analyze_snapshot` выдаёт `BLOCKED`. Ни один диагностический инструмент не исправляет записи автоматически.

**Область:** фиксируется F-04 для public `LinkStore.create_relation` и чтения H5.0/H5.4b. Прямой SQL может обойти writer — это проверяется специально созданными в `tmp_path` историческими повреждениями. Другие paths, в том числе future-contradiction асимметрия `KnowledgeLayer.confirm` (F-06), остаются для R4.

## Регрессионные тесты

Новый `tests/test_v02_h55_r3_evidence_consistency.py`: **12 тестов**:

1. Первичный контрпример: после подтверждения Knowledge противоположный `LinkStore.create_relation` отклоняется без изменения Raw/DB/History; H5.0 остаётся здоровым.
2. Противоположная Relation не создаётся и при provisional Knowledge.
3. Обратный порядок contradicts→supports тоже блокируется.
4–5. Другой Knowledge и другая Memory допускают самостоятельные полярности.
6. Непересекающиеся интервалы `[T1,T3)`, `[T3,+inf)` разрешены, включая точную границу.
7. UTC offsets сравниваются по реальному времени.
8. Отказ для будущих интервалов, которые пересекутся.
9. Отказ от пустого Evidence-интервала.
10. Внедрённый **только в тестовой БД** конфликт обнаруживают `audit_snapshot` и H5.4b; read-only статус `BLOCKED`, без ремонта `confirmed`.
11–12. Истёкший и будущий конфликт не дают false positive в несовпадающем `as_of`.

**Совместимость старой регрессии:** два существующих теста H2.2 раньше создавали незаконную конфликтующую Relation через `LinkStore` для проверки чтения damaged evidence. Они теперь используют отдельный helper `legacy_opposite_sql`, вставляющий данные прямым SQL **только в disposable fixture**. Само поведение `KnowledgeLayer.confirm` при архивном противоречии остаётся под контролем.

## Локальные команды

```bash
git status --short
git rev-parse HEAD

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q -rx \
  tests/test_v02_h55_r3_evidence_consistency.py \
  tests/test_v02_h55_r2_raw_provenance.py \
  tests/test_v02_h55_r1_evidence_lifecycle.py \
  tests/test_v02_h2_2_evidence.py \
  tests/test_v02_h3_1_temporal_relations.py \
  tests/test_v02_h5_legacy_diagnostic.py \
  tests/test_v02_h5_4_compatibility.py

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q
```

**Фактически сообщено владельцем:** адресные `68 passed` / 1,51 с; полный pytest `1999 passed` / 88,71 с. Это подтверждение R3 на Linux x86_64 / Python 3.14.4, а не независимый повтор H5.5.

## Граница приёмки

- Адресные и полная регрессии PASS; ни один старый сценарий idempotence/Recovery не нарушен.
- Public writer не может создать пересекающиеся противоположные Relations; раздельные временные окна сохраняются.
- H5.0/H5.4b обнаруживают вручную вставленный конфликт, не меняя данные; Knowledge остаётся `confirmed` **только как свидетельство повреждённого наследия**, не как автоматически восстановленная истина.
- Полная регрессия `1999 passed` получена; отдельный независимый аудит межкомпонентных переходов после R1–R4 всё ещё необходим.
- Даже после R3: требуется R4 для F-03/F-05/F-06/F-07/F-08, а глобальная Raw-граница standalone MemoryStore из R2 требует отдельного явного решения. Новый независимый H5.5 review обязателен; RC всё ещё BLOCKED.
