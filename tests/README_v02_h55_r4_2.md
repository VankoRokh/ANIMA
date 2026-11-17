# ANIMA v0.2 — H5.5 R4.2 / F-05: Temporal Merge Relations

**Статус:** исправление подготовлено, **ещё не исполнялось**.  
**Рабочая ветка:** `work/v02-h55-r4-temporal-merge` от принятой R4.1 @ `62115c4b6f86248de271908522e627ec9e8fd40f`.  
**Результаты владельца R4.1:** адресные `73 passed` / 3,01 с; полный `2007 passed` / 88,16 с.  
**Frozen audit:** `audit/v02-h5-rc-candidate` @ `28e8438f8408e85b52e237eaedcf024354a4522a`. RC остаётся `BLOCKED`.

## Первичный контрпример

В отчёте `ANIMA_v0.2_H5.5_Independent_Release_Audit.md` находка **F-05 / P2** ссылается на `ANIMA_v0.2_H5.5_evidence.zip`, `h55_work/independent_probes.py::temporal_merge`. Аудитор воспроизвёл следующее:

1. `build_core()` создаёт две несовпадающие Memory, source и target.
2. У source создаётся `Memory → Entity:about` с `created_at=2099-01-01T00:00:00+00:00`, `valid_until=NULL`. До merge текущий Entity Retrieval пуст.
3. `MemoryLifecycle.merge(source,target,merged_at=T4)` в 2020 году выбирал Relation только по условию `valid_until IS NULL` и переносил её с `created_at=merged_at`.
4. Entity Retrieval начинал возвращать target **до наступления 2099 года**. Тем самым последовательность валидных операций изменяла temporal scope исходной атрибуции.

Контрпример поддержан первичным кодом аудита и проверкой `lifecycle.py`. В результате исправления `temporal_merge` должен перестать давать прежний `contract=FAIL`: корректность следует проверять новым assert о границах, а не требовать прежнего итогового значения.

## Контракт исправления

В `anima/memory/lifecycle.py::MemoryLifecycle.merge()` все операции остаются в прежнем `BEGIN IMMEDIATE` и не изменяют Raw EventLog, Knowledge и EventProcessing.

Для каждой source Relation `about` рассчитывается **новый переносимый интервал**:

```text
start = max(source_relation.created_at, merge.merged_at)
end   = source_relation.valid_until
transfer only if end is None or end > start
```

- Timestamp сравниваются как **offset-aware instants**, а не лексически по ISO-тексту. Границы действуют как полуоткрытый интервал `[start,end)`.
- Future source `about` сохраняется как future target `about`. Merge **не делает** будущую связь действующей раньше; воспроизведённый F-05 перестаёт порождать ложную текущую атрибуцию.
- Если исходный `about` уже истёк к моменту merge, он остаётся в source для истории, но **не копируется** на target.
- Если срок конечный и ещё действующий, переносится только оставшаяся часть с **исходным `valid_until`**, без бессрочного продления.
- `source_memory_id` новой Relation сохраняет **исходное происхождение**, а не безосновательно переписывается на target. Original Relation и исходная Memory остаются доступны.
- Перед созданием копии проверяется покрытие её интервала существующими target `about` того же Entity, включая future/finite intervals. Если одна существующая target Relation уже охватывает весь переносимый интервал, новая не создаётся. При частичном пересечении допускается дополнительная Relation ради сохранения периода, который иначе отсутствовал; отдельного объединения/нормализации пересекающихся интервалов эта стадия не выполняет.
- Неправильная `valid_until <= created_at` у затронутого source `about` вызывает отказ с откатом; никакой автоматической коррекции повреждённых legacy Relations нет.
- `about` **не становится доказательством авторизованного Entity identity**: исходные legacy `about` всё ещё требуют H5.4b authority review. Изменяется исключительно temporal projection при явном merge.

## Проверки

Добавлено **10 тестов** в `tests/test_v02_h55_r4_2_temporal_merge.py`:

1. Точный аудит `temporal_merge`: current Entity Retrieval остаётся пустым; переносимый `about` действует начиная с 2099 года, сохраняет provenance.
2. Активное исходное `about` переносится не раньше merge.
3. Конечный `valid_until` сохранён, сам конец исключён.
4. Истёкшее `about` не воскрешается в target.
5. Future Relation с конечным сроком сохраняет обе границы.
6. Полностью покрытая target Relation не дублируется.
7. Future target Relation не скрывает перенос текущего source интервала.
8. Original `source_memory_id` (включая внешний provenance Memory) не подменяется target.
9. UTC offsets сравниваются по инстантам.
10. Инвертированный source interval из disposable legacy SQL — fail closed с откатом Memory/source links.

**Расчёт полного pytest:** `2017 passed` (2007 + 10); **не выполнялся**. Нужен также повторный H3.1 и lifecycle regression.

```bash
git status --short
git rev-parse HEAD

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q -rx \
  tests/test_v02_h55_r4_2_temporal_merge.py \
  tests/test_memory_lifecycle.py \
  tests/test_v02_h3_1_temporal_relations.py \
  tests/test_v02_h55_r4_1_projection_retention.py \
  tests/test_v02_h55_r3_evidence_consistency.py \
  tests/test_v02_h5_legacy_diagnostic.py \
  tests/test_v02_h5_4_compatibility.py

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q
```

## Границы приёмки и дальнейшая работа

Принимать R4.2 только после **полного regression PASS** и проверки отсутствия F-05 на исходной последовательности. Проверки обязаны сохранить идемпотентность, Evidence authority, temporal N5 и Recovery. Копия Relation не должна разрешать `about` раньше `max(original.created_at, merged_at)`.

Остаток R4: **F-06** (проверка future contradiction в Knowledge confirm), **F-07** (Context coverage/truncation) и **F-08** (SQLite WAL/SHM forensic read-only contract). В R2 сохраняется открытая граница standalone/unbound MemoryStore. Новый независимый H5.5 review на новом фиксированном SHA обязателен для решения о RC.
