# ANIMA v0.2 — R7.2 Lifecycle Write Authority

**Источник:** независимый H5.6, finding **H56-03 (P2)** на snapshot
`f70d879a88d88f63777646b0a65448765610402d`.
**База:** R7.1 `6a2940c489345a85b55931cb754a48d7401d5ab6`
(локально проверено владельцем: `2124 passed`, `scripts/check.sh` PASS).
**Статус:** IMPLEMENTED / NOT YET LOCALLY VERIFIED.
**Цель:** разделить графовые данные и авторитетный Knowledge lifecycle.

## Нарушенный инвариант

До R7.2 `LinkStore.create_relation(relation_type="supersedes")`
разрешал создать `knowledge_new(provisional) → knowledge_old(confirmed)` без
`KnowledgeLayer.supersede()`, History или Raw evidence. Затем
`KnowledgeLayer.describe(old).superseded_by` представлял такую связь как
настоящую замену, хотя оба Knowledge сохраняли прежние статусы.
`RetrievalEngine` также мог повышать ранг ложного соседа за
`relation:supersedes:1hop:+8`.

`LinkStore.relations_for()` намеренно является интерфейсом сырых графовых
данных для аудита, а не авторитетной проекцией lifecycle. Не смешивать
сырой факт хранения Relation с публикацией результата перехода.

## Контракт реализации

1. **Единственный lifecycle writer.** Публичный
   `LinkStore.create_relation(... relation_type="supersedes")` всегда
   отвергает запрос `ValueError`. Право создавать такие Relation сохраняется
   только за `KnowledgeLayer.supersede()`, где статусы, History и Evidence
   утверждаются внутри одной SQLite-транзакции.
2. **Чтение — проверяемая authority.** Новый чисто читающий предикат
   `is_authorized_supersession(connection, relation)` (в
   `anima/memory/lifecycle_authority.py`) проверяет:
   - `knowledge → knowledge`, `relation_type=supersedes`,
     `valid_until=NULL` (каноническая бессрочная lifecycle-связь),
     существование обоих Knowledge и сохранённый статус old=`superseded`,
     new не `provisional`;
   - существование `source_memory_id` и хотя бы одной записи
     `memory_sources` для него;
   - History старого Knowledge с `operation=supersede`, `source_kind=knowledge`,
     `source_id=new_id` и `changes.supersedes_relation=relation.public_id`,
     `changes.superseded_by=new_id`;
   - History нового Knowledge с `operation=create_superseding`,
     `source_kind=memory`, `source_id=source_memory_id`,
     `changes.supersedes=old_id`;
   - History обеих сторон относится к тому же **абсолютному моменту**
     создания Relation (offset-aware ISO; допускаются разные UTC offsets).
3. **Публичная проекция.** `KnowledgeLayer.describe()` в
   `superseded_by` и `supersedes` включает лишь действующие
   `supersedes` Relation с подтверждённой authority. Неавторитетные старые
   записи **не удаляются** и остаются видны в `LinkStore.relations_for()`.
4. **Retrieval.** Однохоповый графовый обход `RetrievalEngine` не
   использует неавторитетные `supersedes` как соседей и не начисляет им
   relation score. Прямой retrieval по exact ID не запрещён; Knowledge
   может быть найден независимо от сомнительной связи.
5. **Offline gate.** `labs/v02_h5_legacy_diagnostic.py` применяет тот же
   read-only предикат, фиксирует `unauthorized_lifecycle_supersedes`,
   статус `degraded`. H5.4b compatibility должен выдавать `BLOCKED`.
   Никаких auto-repair, удалений или молчаливого импорта.
6. **Ограничения доверия.** Исторический History/SQLite не получает
   криптографической защиты, а read-path не сканирует целиком Raw при каждом
   поиске. Физический Raw проверяется при реальном
   `KnowledgeLayer.supersede()`; отсутствие, порча и семантическая
   недостаточность Raw для legacy должны дополнительно оцениваться
   offline gate. Прямой SQL злонамеренного администратора остаётся за
   пределами безопасности Python API.
7. **Без миграции.** Таблицы, индексы, версии процессора, журналы Raw и
   релизные протоколы неизменны. `supersedes` остаётся известным типом
   Relation для чтения и истории.

## Negative / positive test matrix

`tests/test_v02_r7_2_lifecycle_write_authority.py`:
- generic writer на валидных ID с доступной Memory и настоящим Raw
  отказывает атомарно; Knowledge, History, Relations, Raw не меняются;
- legacy `supersedes` через SQL только в `tmp_path`: сырая Relation
  остаётся доступной для диагностики, но `describe` не сообщает о замене,
  H5.0 выдаёт `unauthorized_lifecycle_supersedes`, H5.4b блокирует;
- Retrieval не использует поддельную Relation как 1-hop и не начисляет bonus;
- корректный `confirm → challenge → KnowledgeLayer.supersede` создаёт
  согласованные old/new statuses, обе History и видимые lifecycle поля;
- корректный авторитетный `supersedes` остаётся доступным как neighbor;
- обычный generic `related_to` по-прежнему доступен; конечная,
  неканоническая legacy `supersedes` скрывается reader и блокируется audit;
- удаление любой стороны History через прямой SQL только в временной БД
  скрывает Relation из lifecycle reader, и диагностический gate её выявляет.

## Приёмка

```bash
git rev-parse HEAD
git status --short
PY=~/Projects/ANIMA/.venv/bin/python

PYTHONPATH="$PWD" "$PY" -m pytest -q -rx \
  tests/test_v02_r7_2_lifecycle_write_authority.py \
  tests/test_knowledge.py \
  tests/test_retrieval.py \
  tests/test_provenance.py \
  tests/test_v02_r6_1_knowledge_write_authority.py

ANIMA_PYTHON="$PY" bash scripts/check.sh
PYTHONPATH="$PWD" "$PY" -m pytest -q -rx
```

Число PASS и исполняемое доказательство фиксируются **после** локального
прогона, а не выводятся из количества функций тестов. R7.2 не является
разрешением RC: далее R7.3 (H56-04/05), затем интеграция R7.4 и H5.7.
