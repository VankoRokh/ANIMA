# ANIMA v0.2 — H3 / Temporal Relations & Retrieval Eligibility

**Статус:** реализация внесена в GitHub; ещё не подтверждена исполнением pytest в окружении владельца.

**База:** принятый H2 (`1870 passed, 4 xfailed` в полной регрессии, по результатам владельца).

**Промежуточная ветка H3.1:** `work/v02-h3-temporal-relations` — исправление N5.  
**Рабочая ветка H3.2:** `work/v02-h3-retrieval-eligibility` — наследует H3.1, исправляет N8.

## H3.1 — N5: единая временная семантика Relations

Дефект R1-S1 N5: Retrieval мог использовать истёкшее `about`, а `KnowledgeLayer.describe` исключал все конечные `valid_until`, включая ещё действующие.

Принят контракт интервала **`[created_at, valid_until)`**:
- `created_at` включено;
- `valid_until` исключено, `NULL` означает отсутствие конечной границы;
- сравниваются абсолютные моменты по aware ISO-8601 timestamp, независимо от UTC-смещения;
- Relation, которая ещё не началась, не считается текущей.

Изменения:
- `LinkStore.relations_for(..., active_at=<aware ISO 8601>)`: дополнительно фильтрует текущие на заданную дату связи. **Без `active_at` сохраняется прежний исторический список**, включая истёкшие отношения.
- `RetrievalEngine.retrieve()`: на один запрос фиксируется одно `active_at` по текущему UTC; entity-фильтрация и одношаговый graph hop используют только активные Relations. `get_relation()` не изменён.
- `KnowledgeLayer.describe()`: проекция источников строится по тем же временным правилам, а не только по `valid_until IS NULL`.
- H0 N5 переведён из XFAIL в обязательный PASS.
- `tests/test_v02_h3_1_temporal_relations.py`: 8 адресных проверок границ, часовых смещений, entity/one-hop retrieval, актуального/будущего/исторического свидетельства и невалидного `active_at`.

**Границы:** Исторические Relationships не удаляются. Нет отдельной высокоуровневой функции запросов «срез памяти на дату»: для аудита используется прежний низкоуровневый API `relations_for` без `active_at`. Работа со сломанными legacy timestamps остаётся fail-closed. Это текущая временная проекция, не пересмотр автоматического срока жизни Knowledge или самих Memory.

## H3.2 — N8: допустимые кандидаты до FTS LIMIT

Дефект R1-S1 N8: `LIMIT 25` в FTS выполнялся до проверки статуса, поэтому 25 `merged` Memory могли скрыть `open` Memory.

Изменения:
- `RetrievalEngine._fts_records()` применяет **domain, memory_type, memory_status / knowledge_status прямо в SQL WHERE перед LIMIT**; default-статусы также применяются до отбора.
- `_filter_records()` аналогично применяет default-статусы до ограничения при структурированной фильтрации, а не после неё в Python.
- В обоих путях выполняется выборка до `FTS_SEED_LIMIT + 1`, но в candidate pool попадает не более `FTS_SEED_LIMIT=25` записей каждого типа.
- `stats["fts_truncated"]` и `stats["filters_truncated"]` показывают, если кандидатное окно ограничило число **допустимых** совпадений.
- Явные запросы к `merged` / `rejected` остаются допустимыми с явным status-фильтром.
- H0 N8 переведён из XFAIL в обязательный PASS.
- `tests/test_v02_h3_2_retrieval_eligibility.py`: 8 новых сценариев, включая 25 `merged`, 25 `rejected`, структурированные и доменные фильтры, явные terminal-статусы, правдивую truncation-диагностику и приоритет точного ID.

**Границы:** Условие `fts_truncated=False` означает только отсутствие усечения окна **допустимых FTS-кандидатов** для соответствующего запроса; это не доказательство полноты графового или общего Retrieval. `fts_truncated=True` значит, что существует хотя бы один дополнительный подходящий FTS seed за пределами 25. Пользователь может уточнить запрос. Изменений SQLite-схемы нет.

## Запуск на ноутбуке

Из корня ANIMA:

```bash
git status --short
git rev-parse HEAD
PYTHONPATH="$PWD" .venv/bin/python -m pytest -q -rx \
  tests/test_v02_h0_foundation_contracts.py \
  tests/test_v02_h3_1_temporal_relations.py \
  tests/test_v02_h3_2_retrieval_eligibility.py \
  tests/test_retrieval.py \
  tests/test_context_builder.py \
  tests/test_knowledge.py
```

Ожидаемый адресный результат: **2 XFAIL** (N1/N2) и остальные PASS.

Обязательная полная регрессия:

```bash
PYTHONPATH="$PWD" .venv/bin/python -m pytest -q
```

**Расчётное значение:** `1888 passed, 2 xfailed` (1870 прежних PASS + 16 новых H3 PASS + 2 N5/N8 PASS). Это не результат исполнения.

Проверки должны выполняться на ноутбуке x86_64 в установленном окружении. Raspberry Pi 5 не является обязательным release gate.

## Критерии приёмки H3

- H0 N5 и N8 теперь PASS, N1 и N2 остаются XFAIL.
- 16 новых тестов H3 PASS.
- Полный pytest без новых FAILED, ERROR или неожиданных XPASS.
- Исторический доступ к Relations не исчез и нормальные запросы `RetrievalEngine` сохраняют корректные приоритеты.
- При любых новых отказах разбирать первопричину, а не подгонять тест под ожидаемый счётчик.

Следующий этап после приёмки: **H4 — Identity Association (N1/N2)**, без добавления LLM или нового Memory Engine.
