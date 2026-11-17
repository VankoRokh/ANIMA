# ANIMA v0.2 — H5.5 R4.4 / F-07: Context Retrieval Coverage

**Статус:** R4.4/F-07 принят владельцем после повторной полной регрессии: **`2038 passed` за 88,34 с**. Начальные 3 ошибки Stage 6 исправлены обновлением только тестового Retrieval-адаптера; production-контракт не ослаблялся.  
**Рабочая ветка:** `work/v02-h55-r4-context-coverage`, создана от принятой R4.3 @ `3c017013855fe196520f4b9a80ce10d6ede90124`.  
**R4.3 подтверждён владельцем:** адресные `70 passed` за 1,58 с; полная регрессия `2030 passed` за 88,65 с.  
**Оригинальный независимый H5.5 snapshot:** `audit/v02-h5-rc-candidate` @ `28e8438f8408e85b52e237eaedcf024354a4522a`. **v0.2 RC = BLOCKED**.

## F-07 — проблема

`RetrievalEngine.retrieve()` формирует `stats.fts_truncated`, `stats.filters_truncated`, а также `stats.candidates` и `stats.returned`. Поиск FTS/structured filters до R4.4 ограничивал внутреннее окно кандидатов `FTS_SEED_LIMIT=25` (второй `LIMIT` запрашивает 26-й элемент как сигнал усечения).

Сценарий: имеется **30 подходящих Memory**, Retrieval возвращает **25 результатов** при `top_k=100`; `candidates=returned=25`, но `fts_truncated=True`. `ContextBuilder` до исправления проверял только `candidates > len(results)`, устанавливая `ContextBundle.truncated=False` при достаточном бюджете. Для FAST/DEEP это выглядит как полный найденный контекст, хотя остальные подходящие Memory остались за границей FTS.

## Изменение

Единственный производственный модуль: `anima/memory/context_builder.py`.

В выходной `ContextBundle` добавлено **аддитивное** поле `retrieval_coverage`:

```json
{
  "retrieval_coverage": {
    "fts_truncated": true,
    "filters_truncated": false,
    "top_k_truncated": false,
    "complete": false
  },
  "truncated": true
}
```

- `fts_truncated` и `filters_truncated` **передаются напрямую** из `RetrievalEngine.stats`, а не выводятся из длины списка. Отсутствие обязательных флагов — нарушение контракта, а не разрешение заявить полноту.
- `top_k_truncated = stats.candidates > len(results)` сохраняет прежнюю проверку, но теперь называет её источник.
- `complete` означает **нет ни одного из трёх известных ограничений Retrieval** в данном запросе и его заявленных фильтрах/сканировании. Это **не** доказательство полноты всех знаний ANIMA, не оценка качества поиска и не гарантия неограниченного обзора Raw.
- `ContextBundle.truncated` — агрегированный сигнал: `not retrieval_coverage.complete` **ИЛИ** ограничение бюджета Context. Прежние `selection_stats.omitted_budget` и `budget.max_items/max_chars` позволяют отдельно увидеть локальное исключение по бюджету.
- `ContextBuilder._trace_bundle` теперь выводит `retrieval_complete`, `retrieval_fts_truncated`, `retrieval_filters_truncated`, `retrieval_top_k_truncated`, сохраняя прежний `truncated`.
- Не меняются FTS LIMIT, eligibility, scoring, ranking, Provenance, состав выбранных Memory/Knowledge/Events, Raw, schema или release protocol.

**Контракт совместимости:** существующее поле `truncated` остаётся boolean, а при ранее скрытом seed-limit усечении меняет значение **с ложного на правильное true**. Потребители, которые ожидали `truncated=False` при `candidates==returned`, должны использовать новый `retrieval_coverage`. Это намеренное исправление семантики, а не смена release protocol.

## Тесты

`tests/test_v02_h55_r4_4_context_coverage.py` — **8 новых pytest cases** (реальные SQLite Memory/FTS, EventLog, RetrievalEngine, ProvenanceResolver; disposable `tmp_path`):

1. Основной F-07: 30 FTS matches, 25 seeds, `candidates=returned=25`, бюджет не исчерпан, но `retrieval_coverage.fts_truncated=True`, агрегированный `truncated=True`.
2. Аналогичная потеря `filters_truncated` при структурированном `domain`.
3. Одновременное FTS и filter усечение: обе причины сохранены.
4. Отдельная причина `top_k_truncated`, без seed-limit.
5. Только локальный budget-limit: Retrieval `complete=True`, но общий Context `truncated=True`, `omitted_budget>0`.
6. Полная малая выборка: `retrieval_coverage.complete=True` и общий `truncated=False`.
7. DEEP: Provenance Events добавляются и дедуплицируются без потери upstream FTS усечения.
8. DiagnosticTrace: причины Retrieval не сворачиваются в один безымянный `truncated`.

**Расчёт полного pytest — `2038 passed` (2030 + 8). Это НЕ исполненный результат.**

## Регрессионный отказ Stage 6 и исправление фикстуры

Первый полный прогон владельца завершился **`2035 passed, 3 failed` за 88,18 с**. Все три падения — `tests/test_stage6_experiments.py::test_request_more_context_*`: тестовый `FixtureRetrieval.retrieve()` возвращал `stats={candidates:1,returned:1}` без полей `fts_truncated` и `filters_truncated`, а `ContextBuilder` по контракту F-07 требует эти флаги.

Исправлен **только тестовый адаптер** `tests/test_stage6_experiments.py`: он явно возвращает оба поля со значением `False`. Это достоверно для фиксированного синтетического адаптера с одним заранее известным результатом и без поиска в FTS/фильтрах. Production `ContextBuilder` и `RetrievalEngine` не изменены, **не** используются `.get(..., False)` или молчаливые значения по умолчанию. Отсутствие данных о покрытии по-прежнему вызывает отказ, а не ложное `retrieval_coverage.complete=True`.

Количество pytest cases **не изменилось**. После обновления фикстуры владелец сообщил повторную **полную регрессию `2038 passed` за 88,34 с**. Отдельный адресный повтор не сообщён; общий pytest включает новые 8 тестов и Stage 6.

## Команды на ноутбуке владельца

```bash
git status --short
git rev-parse HEAD

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q -rx \
  tests/test_v02_h55_r4_4_context_coverage.py \
  tests/test_context_builder.py \
  tests/test_stage6_experiments.py \
  tests/test_v02_h3_2_retrieval_eligibility.py \
  tests/test_v02_h55_r4_3_temporal_confirmation.py \
  tests/test_v02_h55_r4_2_temporal_merge.py \
  tests/test_release_v01.py

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q
```

**Gate R4.4:** новые и существующие регрессии PASS; при seed-limit нельзя выдавать `truncated=False`; бюджет и неполнота Retrieval различаются; FAST и DEEP сохраняют те же выбранные records; выпуск RC не разрешён.

## Следующие gate

**R4.5 / F-08:** [WAL/SHM contract correction](README_v02_h55_r4_5.md) — кандидат, проверяет правильность логического SQLite backup и снимает недостоверную forensic byte-read-only гарантию для исходных sidecars. **R2 standalone/unbound:** не давать неподключённому `MemoryStore` неявного статуса Raw-verified Core. До нового независимого аудита нового фиксированного SHA RC остаётся `BLOCKED`.
