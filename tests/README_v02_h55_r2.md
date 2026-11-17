# ANIMA v0.2 — H5.5 R2 / Raw Provenance (F-02)

**Статус:** реализовано в `work/v02-h55-raw-provenance`, **не исполнено и не принято**.  
**Frozen H5.5 audit:** `28e8438f8408e85b52e237eaedcf024354a4522a`.  
**Исходный R1:** `work/v02-h55-evidence-remediation` @ `73aba4ad4b143a50f1bb5ab1c70c7ea950a30b4b`; R1 подтвердил владелец: `44 passed` (0,92 с), полная регрессия `1975 passed` (86,13 с).

## Обнаруженный контрпример F-02

В архиве независимого аудитора `ANIMA_v0.2_H5.5_evidence.zip`, `h55_work/independent_probes.py::missing_raw_confirmation`: через `build_core(tmp)` создаётся CLOSED Memory с `source_event_id=ev_...`, которого **нет** в `events.jsonl`. Затем `KnowledgeLayer.create_candidate()/confirm()` раньше возвращали `confirmed`. `ProvenanceResolver.knowledge()` падал с `Missing source event`, а `EventProcessingCoordinator.recover()` не замечал ссылку, поскольку соответствующий Event отсутствовал в его ledger. Воспроизведено независимым аудитором на Python 3.14.4 и 3.12.14.

## Контракт R2 (первая граница, scoped to composed Core)

1. `build_core()` привязывает `MemoryStore` к **единственному каноническому** `events.jsonl` в том же каталоге, что `memory.db`. Привязка сохраняется как `schema_meta.knowledge_raw_provenance_policy=canonical_events_jsonl_v1`; номер SQLite `SCHEMA_VERSION=1` **не меняется**, существующие таблицы не преобразуются.
2. `KnowledgeLayer.confirm()` сначала требует обычное активное CLOSED Memory evidence, затем вызывает `MemoryStore.require_knowledge_raw_sources()` **внутри той же SQLite-транзакции**. Для каждого Memory источника нужны `memory_sources` и **каждый объявленный** Raw Event ID.
3. Физический `EventLog.load_events()` перечитывает весь журнал, проверяя LF, JSON/Event format и уникальность идентификаторов. Нет доверия к кешу `EventLog._known_ids` или только к совпадению формально валидного `ev_UUID`.
4. Тот же Raw gate действует перед терминальными переходами `reject()` (противоречащий источник) и `supersede()` (публикация нового `confirmed` без обычного `confirm()`). При отказе вся операция и создаваемые ею Relations/History откатываются.
5. Привязка **постоянна для данной БД**: повторный `MemoryStore(memory.db)` без передачи `EventLog` все равно прочитает политику из `schema_meta`. Нельзя перепривязать Core DB к постороннему файлу через штатный `bind_event_log()`.
6. `MemoryStore`, созданный отдельно **без** `build_core` и без явной Raw-привязки, остаётся в legacy storage-only mode ради совместимости самостоятельных старых unit-тестов, не создающих реальный EventLog. Его `KnowledgeLayer` **не дает гарантии R2**. Не считать такой DB ANIMA Core instance или безопасной для RC. Отдельная миграция legacy/unbound stores и более строгая унификация Python API потребуют отдельного решения (см. ограничения).

## Ограничения

- Доказывается только **существование** Raw Event IDs в полностью валидном JSONL на момент подтверждения, но не семантическое соответствие Memory контенту Event, не легитимность автора и не авторизованность Entity claims. Для строгой привязки содержания нужен отдельный provenance контракт.
- Raw и Memory — разные файлы, поэтому общий физический COMMIT отсутствует. Некооперативный writer может изменить Raw после проверки; `fsync`/power-loss здесь не добавлены.
- Чтение всех Raw записей при каждом подтверждении имеет стоимость O(bytes) и может стать performance bottleneck. Оптимизация допускается **только с проверяемой инвалидацией и без ослабления Raw authority**.
- При первом `build_core` на прежней `memory.db` добавляется один ключ в `schema_meta`. Это **не** проверка/ремонт старых `confirmed` и не автоматическая миграция их provenance; H5.0/H5.4b и независимая проверка offline copy остаются обязательными.
- Direct SQL, неподконтрольные внешние писатели и новая standalone DB без binding остаются вне гарантии R2. Прежде чем считать F-02 **глобально закрытым** для всех Python API, независимый reviewer должен оценить необходимость fail-closed политики для unbound stores.

## Проверки

`tests/test_v02_h55_r2_raw_provenance.py`: **12 новых тестов**:
- аудиторская последовательность `missing_raw_confirmation` теперь блокируется;
- настоящее событие `Raw → Coordinator → CLOSED Memory → confirmed` успешно проходит и ProvenanceResolver возвращает исходный ID;
- отсутствие `memory_sources`, одна пропавшая ссылка из нескольких и оборванный Raw tail вызывают отказ без изменения Knowledge;
- новый независимый объект `MemoryStore` из bound DB наследует политику;
- чужой EventLog не может заменить канонический;
- isolated legacy DB не переписывается автоматически;
- отвергаются LF-терминированный JSONL с недействительным Event и неизвестная версия сохранённой Raw-политики;
- `supersede()` и `reject()` не завершаются при отсутствующих Raw для новых доказательств.

**Расчётная полная регрессия: `1987 passed` (1975 + 12). Это не результат исполнения.**

```bash
git status --short
git rev-parse HEAD

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q -rx \
  tests/test_v02_h55_r2_raw_provenance.py \
  tests/test_v02_h55_r1_evidence_lifecycle.py \
  tests/test_v02_h2_2_evidence.py \
  tests/test_v02_h2_1_confirmed_knowledge.py \
  tests/test_v02_h5_4_compatibility.py \
  tests/test_v02_h5_4_snapshot_restore.py

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q
```

**Критерий принятия:** все существующие H0–H5/R1 PASS; отказ F-02 на composed Core; только полный Raw обеспечивает подтверждение; состояние Knowledge, links, History, Raw и ledger не меняется после отказа. Вердикт `R2 CORE-BOUND GATE PASS` допустим после тестов, но `GLOBAL F-02 CLOSED` и `v0.2 RC READY` пока недопустимы.
