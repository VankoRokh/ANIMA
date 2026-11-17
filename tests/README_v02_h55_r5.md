# ANIMA v0.2 — H5.5 R5 / F-02: обязательная Raw authority для standalone Knowledge

**Статус:** R5/F-02 **принят владельцем** после устранения регрессии тестовых фикстур: итоговая полная регрессия **`2054 passed` за 88,75 с**. Это не заключение независимого H5.5.  
**Ветка:** `work/v02-h55-r5-raw-authority-enforcement`; основа — принятый R4.5 `da70253491b8e6a941cd0f35b67783de353ae700`.  
**R4.5:** владелец сообщил полную регрессию `2044 passed` / 89,61 с.  
**Исходный H5.5 аудит:** `28e8438f8408e85b52e237eaedcf024354a4522a` (`audit/v02-h5-rc-candidate`), вердикт **BLOCKED**. Нельзя считать исходные 2044 теста независимым подтверждением устранения всех рисков.

## Цель и граница

В R2 `build_core()` привязывал `MemoryStore` к `events.jsonl`, а `KnowledgeLayer.confirm/reject/supersede` требовали все declared Raw Events; политика сохранялась в `schema_meta`. Однако `MemoryStore(tmp_path / "memory.db")`, открытый **без** EventLog и без существующей политики, возвращал `False` из `require_knowledge_raw_sources()`; `KnowledgeLayer` **игнорировал этот результат**. Поэтому самостоятельный публичный Python API мог публиковать `confirmed/rejected` Knowledge без первичных событий — первоначальная F-02 оставалась возможной вне Core-bound окружения.

**R5 делает fail-closed Raw authority обязательной для всех переходов `KnowledgeLayer.confirm/challenge/reject/supersede`**, изменяющих достоверность Knowledge: без canonical Raw EventLog `require_knowledge_raw_sources` выдаёт `ValueError("Knowledge Raw provenance is unbound: ...")`, а не `False`. Нельзя подтвердить Knowledge или оспорить уже подтверждённое знание на основании одного факта существования Memory.

## Что меняется

- **Два production-модуля:** `anima/memory/memory_store.py` и `anima/memory/knowledge.py`. Если в `schema_meta` отсутствует `knowledge_raw_provenance_policy`, переход `confirm/challenge/reject/supersede` отказывается. `KnowledgeLayer.challenge()` дополнительно проверяет физическое Raw для источника нового противоречия до изменения Knowledge. Если metadata неизвестно или некорректно, прежний R2 fail-closed сохраняется. Если политика присутствует, все source Event IDs проверяются физическим `EventLog.load_events()`.
- `KnowledgeLayer` **не получает** новый флаг обхода в тестах и production. `MemoryStore.bind_event_log(EventLog(<sibling>/events.jsonl))` остаётся явной штатной операцией для подготовки standalone к подтверждению. Привязка проверяет канонический путь, сохраняется в БД и **сама по себе не удостоверяет** старые `confirmed` либо целостность источников. Конкретные Raw ID проверяются именно при переходе.
- Стандартное создание Memory, `provisional` Knowledge, `investigate`, чтение `get/describe/history`, диагностика, создание резервной копии, Raw и ledger остаются доступными **без принудительной миграции**. Старые `confirmed` не переводятся в `provisional`, и исторические данные не исправляются.
- `MemoryStore.SCHEMA_VERSION=1`, `EventProcessingCoordinator.PROCESSOR_VERSION=1.0`, `release_v01.PROTOCOL`, SQL schema, SQLite backup, Knowledge API parameters, Recovery и Raw EventLog не изменяются. Новых источников authority, LLM-решений и семантической аттестации текста Memory это не добавляет.
- Строгое доказательство остается **экзистенциальным**: все объявленные ID соответствуют валидным LF-терминированным Raw Events на момент проверки. Семантика Memory, доверенность автора и кросс-файловая атомарность при некооперативных writers не доказаны. Прямой SQL вне официальных API остаётся за границей.

## Совместимость старых тестов

Четыре существующих файла ранее симулировали полноценное Knowledge подтверждение над standalone-хранилищем без привязанного Raw:

- `tests/test_knowledge.py` — EventLog уже существовал: его теперь передают в `MemoryStore(..., event_log=event_log)`.
- `tests/test_knowledge_evidence.py` — аналогично, используется готовый Raw.
- `tests/test_v02_h2_1_confirmed_knowledge.py` и `tests/test_v02_h2_2_evidence.py` — добавлены **реальные синтетические Event** в canonical `events.jsonl` перед созданием соответствующих Memory, включая строгие отрицательные тесты legacy evidence.

Все файлы используют только `pytest tmp_path`; никакого тестового bypass, `PYTEST_CURRENT_TEST` проверки или `.get(..., False)` не вводится.

## Новые негативные и позитивные тесты

Файл `tests/test_v02_h55_r5_standalone_raw_authority.py`: **10 pytest cases**:

1. Unbound `confirm(K)` отказывает, оставляет `provisional`, History/Memory/Raw/метаданные неизменными.
2. Unbound `confirm(K, source_memory_id=M2)` откатывает даже предварительно вставленную Relation.
3. `MemoryStore`, повторно открытый из unbound DB, не обходит защиту.
4. `bind_event_log` без самих Raw Events не разрешает подтверждение. После появления физического Raw с точным ID подтверждение успешно; политика сохраняется.
5–6. У ранее `challenged` Knowledge после удаления policy в **исключительно тестовой** SQLite unbound `reject()` и `supersede()` отказывают до изменений.
7. Standalone unbound позволяет `provisional`, `get/describe/history`; никакой автоматической записи Raw policy.
8. Composed `build_core()` по-прежнему подтверждает Knowledge с настоящим Raw.
9. Unbound legacy `confirmed` не может перейти в `challenged` по Memory без зарегистрированного Raw; никаких Relation и History при отказе.
10. Даже в Core-bound системе новое противоречие без физического Raw не переводит ранее подтверждённый Knowledge в `challenged`.

**Фактический результат владельца:** полная регрессия `2054 passed` за 88,75 с (2044 + 10 новых pytest cases). Результат относится к исправленной ветке R5; не переносить его на Python 3.12/aarch64 или реальные legacy-экземпляры без испытаний.

## Регрессия R5: старые тестовые фикстуры

Первый полный прогон владельца завершился **`2022 passed, 32 failed` за 89,22 с**. Все 32 ошибки имели общий тип `ValueError: Knowledge Raw provenance is unbound` в прежних фабриках Context, Retrieval, Provenance, Sleep, Stage 1 и H5 legacy diagnostic. Это был **недостаток адаптации тестового окружения к новой обязательной Raw authority**, а не основание отключать проверку в production.

Исправлено **9 существующих тестовых файлов**:

- `tests/test_context_builder.py` — передача уже существующего `EventLog` в `MemoryStore`.
- `tests/test_retrieval.py` — создание канонического EventLog и четырёх настоящих синтетических Event IDs перед Memory / confirmed Knowledge.
- `tests/test_provenance.py` — локальная фикстура `test_relations_validate_direction_and_provenance` теперь пишет Event и привязывает его к MemoryStore; другие независимые тесты не меняются.
- `tests/test_sleep_contracts.py`, `tests/test_sleep_derived_results.py`, `tests/test_sleep_stage_validation.py`, `tests/test_sleep_text_consolidation.py` — привязка уже создаваемого физического EventLog в соответствующих фабриках.
- `tests/test_stage1_validation.py` — явная Raw-привязка при сборке тестового Stage 1 стека.
- `tests/test_v02_h5_legacy_diagnostic.py` — исходная фикстура становится корректной; специальная SQL/Raw инъекция legacy повреждения и проверка `audit_snapshot` сохраняются.

**Production-код R5 не изменялся** при исправлении этих 32 сбоев: `require_knowledge_raw_sources()` по-прежнему fail closed при unbound, `challenge()` требует реального Raw. Никаких `pytest`-исключений, скрытого автоматического Raw binding, `except ValueError` или обхода политика не добавлено. Изменилось только создание synthetic fixtures.

**Общее число тестов не изменилось. Повторная полная регрессия подтверждена владельцем: `2054 passed` / 88,75 с.** Fail-closed политика осталась неизменной; независимая повторная проверка всех public Knowledge writers ещё не проводилась.

### Команды

```bash
git status --short
git rev-parse HEAD

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q -rx \
  tests/test_v02_h55_r5_standalone_raw_authority.py \
  tests/test_v02_h55_r2_raw_provenance.py \
  tests/test_knowledge.py \
  tests/test_knowledge_evidence.py \
  tests/test_v02_h2_1_confirmed_knowledge.py \
  tests/test_v02_h2_2_evidence.py \
  tests/test_context_builder.py \
  tests/test_retrieval.py \
  tests/test_provenance.py \
  tests/test_sleep_contracts.py \
  tests/test_sleep_derived_results.py \
  tests/test_sleep_stage_validation.py \
  tests/test_sleep_text_consolidation.py \
  tests/test_stage1_validation.py \
  tests/test_v02_h5_legacy_diagnostic.py \
  tests/test_v02_h55_r4_5_wal_scope.py

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q
```

**Критерий приёмки:** все 10 новых сценариев PASS, полная регрессия PASS, `confirm/challenge/reject/supersede` не используют Memory с unbound/отсутствующим Raw, отказ не изменяет SQLite/History/Raw. Новая привязка без соответствующего Raw не обходит guard, а корректный Raw позволяет подтверждение. Старые `provisional` и исторический read-only доступ не блокируются.

## После R5 — не объявлять RC автоматически

- Независимый повтор H5.5 на **новом зафиксированном SHA**, по [техническому заданию повторного аудита](../docs/TESTING/ANIMA_v0_2_H5_5_Independent_Reaudit_Brief.md), включающий прогоны на Python 3.12.14 и 3.14.4, сбойные сценарии, SQLite WAL/SHM и недоверенные публичные API.
- Не подменять реальную legacy-проверку тестовыми фикстурами: оператор выбирает согласованную офлайновую копию, H5.4b выдаёт `NO_ISSUES_DETECTED/REVIEW_REQUIRED/BLOCKED`; никакого автоматического исправления подтверждённого Knowledge.
- Portability Pi/aarch64, эксплуатационные SLO и решения об области RC остаются отдельными gate.
