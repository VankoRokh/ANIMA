# ANIMA v0.2 — R6.3 Temporal & Context Contracts

**Статус:** IMPLEMENTED / LOCAL TESTS NOT YET REPORTED.
**Основа:** локально проверенный R6.2, коммит `43de94b363e449a04fc5393caac213adabb0e633`.
**Основание:** независимый H5.5 post-remediation audit, NEW-04 (P2) и NEW-05 (P2).

## NEW-04 — временная согласованность Knowledge.confirm

### Дефект

При существующем конечном `supports` на интервале `[T2,T5)` и
`contradicts` от `T5` публичная форма `confirm(K, confirmed_at=T3)`
использует активный support и проходит, а `confirm(K, source_memory_id=M, confirmed_at=T3)`
ошибочно ищет только `valid_until IS NULL`, пытается добавить новую
бессрочную Relation и упирается в легальную противоположную связь с `T5`.

### Контракт R6.3

- Для явного `confirm(..., source_memory_id=M)` сначала ищется существующий `supports`, активный **в `confirmed_at`** по полуоткрытому интервалу, независимо от `valid_until`.
- Активная конечная и бессрочная Relation могут быть переиспользованы без INSERT, изменения интервала и повторного Evidence.
- Если активной поддержки нет, действует прежняя логика добавления нового support с защитой от будущих пересечений.
- Для `challenged` сохраняется правило нового подтверждающего Evidence: прежний активный support не принимается как «новый».
- Нельзя одновременно поддерживать и опровергать Knowledge одним Memory в один и тот же момент. Конец интервала исключается; даты с разными UTC offsets сравниваются как инстанты.
- Историческая проекция `KnowledgeLayer.describe()` **не изменена**: она выводит отношения, действующие сейчас. Тесты временного подтверждения смотрят `LinkStore.relations_for(active_at=T3)`.

## NEW-05 — проверяемость покрытия Context

### Дефект

`ContextBuilder` принимал flags и counts от произвольного Retrieval adapter:
`fts_truncated=None`, `filters_truncated=None` и неконсистентные
`stats.candidates/returned` могли породить `retrieval_coverage.complete=True`
при фактически недоказанной полноте.

### Контракт R6.3

- Флаги `fts_truncated` и `filters_truncated` считаются проверенными, только если имеют тип **bool**. Иначе возвращается `None` («неизвестно»).
- Счётчики признаются согласованными, только если они целые (не bool), неотрицательные, `candidates>=returned`, `returned==len(results)`, `returned<=requested_top_k`. Иначе `top_k_truncated=None`.
- `retrieval_coverage.complete=True` только при трёх верифицированных `False`; неизвестное значение заставляет `complete=False` и `bundle.truncated=True`.
- Значение `selection_stats.retrieval_returned` отражает реально полученные результаты, а `retrieval_candidates=None` при несогласованных счетчиках.
- Возвращаемая схема `retrieval_coverage` не расширена: `fts_truncated`, `filters_truncated`, `top_k_truncated`, `complete`. Теперь первые три значения допускают `None` у ненадёжных адаптеров.
- Результат `results` обязан быть списком; нарушение этого контракта — `ValueError`.
- Native `RetrievalEngine` возвращает булевы flags и согласованные counts, его прежние PASS-кейсы должны оставаться без изменений.
- Это проверка **формальной согласованности метаданных**, а не доказательство, что нечестный адаптер не скрывает записи, одновременно сообщая ложные «полные» значения.

## Новые тесты

`tests/test_v02_r6_3_temporal_context_contracts.py` проверяет:
- неявное/явное подтверждение на конечном support при будущей непротиворечивой смене знака;
- эксклюзивность конечной границы и сравнение UTC offsets;
- сохранение Relation IDs и History, отсутствие дополнительных writes;
- валидный полный адаптер, неизвестные или неверные флаги, отсутствующую metadata;
- недопустимые счётчики: `None`, отрицательные, `bool`, строковые, `returned != len(results)`, `candidates < returned`;
- `top_k` truncation отдельно от неизвестного состояния.

Все данные тестов изолированы в `pytest tmp_path`. Продуктовые данные, GitHub audit snapshots и `main` не меняются.

## Локальная приёмка

Создать worktree точного SHA ветки; не изменять рабочий проект.

```bash
git rev-parse HEAD
git status --short
PYTHONPATH="$PWD" ~/Projects/ANIMA/.venv/bin/python -m pytest -q -rx \
  tests/test_v02_r6_3_temporal_context_contracts.py \
  tests/test_v02_h55_r4_3_temporal_confirmation.py \
  tests/test_v02_h55_r4_4_context_coverage.py \
  tests/test_context_builder.py \
  tests/test_retrieval.py

ANIMA_PYTHON=~/Projects/ANIMA/.venv/bin/python bash scripts/check.sh
PYTHONPATH="$PWD" ~/Projects/ANIMA/.venv/bin/python -m pytest -q -rx
```

**PASS:** целевые и полные pytest без ошибок; статические проверки без ошибок;
точный SHA зафиксирован владельцем. Предшествующие `2073 passed`
принадлежат R6.2, а не этой ревизии.

## Вне этапа

- NEW-06 recovery owner integrity: R6.4.
- Все прочие H5.5 audit findings и повторный независимый review: H5.6.
- Не добавляется repair, backfill, автоматическая инвалидизация Knowledge,
  изменение структуры SQLite, миграция либо переоценка смысловой истинности Raw.
