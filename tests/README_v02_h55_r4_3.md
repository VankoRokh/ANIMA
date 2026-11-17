# ANIMA v0.2 — H5.5 R4.3 / F-06: Temporal Knowledge Confirmation

**Статус:** R4.3/F-06 принят владельцем: адресные `70 passed` за 1,58 с и полная регрессия `2030 passed` за 88,65 с. Независимый повторный аудит новой ревизии ещё не выполнялся.  
**Ветка:** `work/v02-h55-r4-temporal-confirm` от R4.2 @ `e2ac649c7f8367222bf48d50ce4177ea1a9b7d58`.  
**R4.2 подтверждён владельцем:** адресные `60 passed` за 1,18 с; полный pytest `2017 passed` за 88,09 с.  
**Аудиторский frozen SHA:** `28e8438f8408e85b52e237eaedcf024354a4522a`. **ANIMA v0.2 RC — BLOCKED**.

## Исходный контрпример F-06

Независимый аудитор воспроизвёл `h55_work/independent_probes.py::temporal_future_contradiction` из `ANIMA_v0.2_H5.5_evidence.zip`:

1. `build_core()` проецирует Raw Event в Memory, затем `MemoryLifecycle.close()` и `KnowledgeLayer.create_candidate()` создают `supports` к provisional Knowledge.
2. От той же Memory создаётся `contradicts` с `created_at=2099-01-01T00:00:00+00:00`, `valid_until=NULL`.
3. `confirm(K, source_memory_id=M, confirmed_at=T3)` раньше выдавал `Memory cannot both support and contradict ...`: внутренний `_require_no_opposite_evidence` находил любую **бессрочную** противоположную Relation, даже ещё не начавшуюся.
4. `confirm(K, confirmed_at=T3)` успешно подтверждал то же Knowledge: `_require_effective_memory_evidence` проверял оба начала интервалов в момент `T3`.

**Отличие от первоначального репродуктора:** после R3 публичный `LinkStore.create_relation` уже отклоняет конфликтующие будущие Relations. Поэтому R4.3 воспроизводит **историческое повреждённое состояние** через SQL исключительно на `pytest tmp_path`; обычный writer не ослабляется и не создаёт таких конфликтов.

## Изменения R4.3

Единственный production-модуль — `anima/memory/knowledge.py`:

- `_require_no_opposite_evidence(..., at)` теперь выбирает противоположные Relations и проверяет их активность через **общий** `_relation_active_at(row, at)`, с временным окном `[created_at, valid_until)`; `valid_until=NULL` само по себе **не означает** актуальность.
- `confirm`, `challenge`, `reject` передают точный `confirmed_at`, `challenged_at`, `rejected_at` соответственно; сравнение происходит по offset-aware моментам времени.
- `_insert_relation` (внутренний writer `KnowledgeLayer`, отличный от `LinkStore`) до записи новой бессрочной `supports/contradicts` проверяет **любое** пересечение с противоположными интервалами той же Memory/Knowledge через `_evidence_intervals_overlap`. Это удерживает ограничение R3 не только в публичном LinkStore, но и во внутреннем writer.
- Если исходная активная `supports` **уже существует**, явный `confirm(..., source_memory_id=M)` может переиспользовать её без создания новой Relation; future `contradicts`, ещё не активная на момент подтверждения, не мешает самому переходу. При попытке **создать новую** долгоживущую `supports`, которая пересечётся с будущей `contradicts`, отказ остаётся обязательным.
- Все штатные SQLite транзакции, Raw checks R2, `PROCESSOR_VERSION`, схемы и Knowledge History сохраняются. Исторические конфликтные Relations не исправляются автоматически.

**Ограничение:** R4.3 устраняет асимметрию по времени для равноценных подтверждений, а не объявляет любые будущие противоположные Evidence безвредными. Попытка нового overlapping relation запрещается независимо от будущего момента его начала; это отдельная структурная гарантия R3.

## Регрессии

`tests/test_v02_h55_r4_3_temporal_confirmation.py`: **10 функций / 13 pytest cases**, включая три двойные параметризации (`source_memory_id` указан / не указан):

1–2. Исходный F-06: будущая `contradicts` не блокирует подтверждение при обоих эквивалентных вызовах; не создаётся новая Relation.
3–4. Действующая противоположная `contradicts` отклоняется обеими формами, Knowledge/History/SQLite без изменений.
5–6. Истёкшая `contradicts` разрешает обе формы.
7. Точная граница начала `contradicts`: до момента разрешено, начиная с момента — отказ.
8. Часовой пояс `+03:00` эквивалентен UTC-моменту, без лексических ошибок.
9. `LinkStore` R3 по-прежнему не позволяет штатно добавить будущую противоположную Relation.
10. Внутренний writer не позволяет добавить новую `supports`, пересекающуюся с будущей `contradicts`.
11. Новая `supports` после завершения старой `contradicts` разрешена.
12. `challenge` не создаёт новую конфликтующую Relation, если существующая future `supports` начала бы перекрываться с ней.
13. `reject` может переиспользовать существующую `contradicts`, не отвергая ещё не активную future `supports` при терминальном переходе.

**Получено от владельца:** адресные `70 passed` / 1,58 с, полная регрессия `2030 passed` / 88,65 с. Это подтверждает реализацию F-06 на тестовом окружении владельца; независимый H5.5 для нового SHA ещё требуется.

```bash
git status --short
git rev-parse HEAD

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q -rx \
  tests/test_v02_h55_r4_3_temporal_confirmation.py \
  tests/test_v02_h55_r4_2_temporal_merge.py \
  tests/test_v02_h55_r3_evidence_consistency.py \
  tests/test_v02_h55_r2_raw_provenance.py \
  tests/test_v02_h2_2_evidence.py \
  tests/test_knowledge_evidence.py \
  tests/test_v02_h3_1_temporal_relations.py

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q
```

**Приёмка:** старые F-06 последовательности теперь дают одинаковый результат при равноценных данных, но новые конфликтные Relations не создаются; старые H0–H5 и R1–R4.2 не регрессируют. После этого R4.4/F-07 ([Context coverage](README_v02_h55_r4_4.md), кандидат), R4.5/F-08 (WAL/SHM contract) и review R2 unbound остаются открыты. Перед присвоением RC нужен новый независимый H5.5 на новом фиксированном SHA.
