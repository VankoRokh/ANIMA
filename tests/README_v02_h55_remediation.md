# ANIMA v0.2 — H5.5 remediation / Evidence Lifecycle

**Статус:** R1/F-01 принят (`1975 passed`), R2/F-02 Core-bound принят (`1987 passed`, standalone/unbound остаётся открытым), R3/F-04 принят (`1999 passed`), R4.1/F-03 принят владельцем (адресные `73 passed` / 3,01 с, полный `2007 passed` / 88,16 с). R4.2/F-05 подготовлен, ещё не испытан. F-06/F-07/F-08 остаются; v0.2 RC **BLOCKED**.

## Источник и ревизия

- Независимый аудит проводился на commit `28e8438f8408e85b52e237eaedcf024354a4522a`. Исправления выполняются только в ветке `work/v02-h55-evidence-remediation` от этого SHA; ветка `audit/v02-h5-rc-candidate` не изменялась.
- Предоставленный владельцем `ANIMA_v0.2_H5.5_evidence.zip` проверен по `evidence_manifest.json`: **351/351** файлов совпали по размеру и SHA-256. Изучены `h55_work/independent_probes.py` (точные сценарии `evidence_merge`, `evidence_update`) и `h55_work/independent*.json` с подтверждёнными аудитором контрпримерами. Архив не публикуется в Git и не исполнялся при подготовке R1.
- Отчёт H5.5: **BLOCKED**; три P1 — F-01, F-02, F-04. 1967 PASS на 3.14.4 и 3.12.14 — результаты независимого аудита **исходной**, не исправленной ревизии.

## R1 / F-01 — граница мутаций действующего Evidence

### Дефект

Публичная цепочка `Raw → Memory → close → KnowledgeLayer.confirm` создаёт подтверждённое Knowledge. Следующий `MemoryLifecycle.merge(source,target)` меняет статус source на `merged`, а `MemoryStore.update_memory(source)` допускает открытие либо переписывание того же source. Knowledge остаётся `confirmed`, хотя его Evidence уже недействительно. Аудитор независимо воспроизвёл оба случая на Python 3.14.4 и 3.12.14.

### Исправление

- Общий метод `MemoryStore._require_no_confirmed_knowledge_dependencies(connection, memory_id)` блокирует мутации Memory при `supports/contradicts` Relation к текущему `Knowledge.status=confirmed`.
- `MemoryStore.update_memory()` проверяет зависимость и изменяет запись в одной транзакции `BEGIN IMMEDIATE`. Любой update меняет `updated_at` и потому считается изменением источника доказательств, включая importance.
- `MemoryLifecycle.merge()` под тем же типом writer lock проверяет **source и target** до переноса Raw sources, Relations и изменения статусов.
- Ограничение намеренно консервативно: Relation к `confirmed` защищена независимо от срока `valid_until` (в том числе историческая/будущая). Уточнение допуска возможно лишь после явного механизма Knowledge revision/revocation; автоматического изменения Knowledge или истории нет.
- `provisional` и несвязанные Memory не замораживаются. Не менялись SQL schema, Raw, EventProcessing, `PROCESSOR_VERSION`, release protocol, Knowledge writer.
- Прямые SQL, некооперативные writers, F-02 и F-04 не закрываются этим исправлением.

### Регрессии

`tests/test_v02_h55_r1_evidence_lifecycle.py`: **8 pytest cases**:

1. Отказ `confirm → merge` (точный сценарий F-01) с проверкой исходных source/target/ledger/Knowledge/History/Raw и здорового H5.0 diagnostic.
2. Отказ `confirm → update_memory(content)`, сохранение состояния.
3. Отказ `confirm → update_memory(status='open')`.
4. Отказ `confirm → update_memory(importance)`.
5. Отказ `confirm → update_memory(closed_at)`.
6. Несвязанную Memory можно обновить и слить без влияния на подтверждённый Knowledge.
7. `provisional` candidate не блокирует обычный update.
8. `provisional` candidate не блокирует прежний merge.

Расчёт полного pytest: **1975 passed** (1967 + 8). **Это не исполнявшийся результат.**

Проверить на ноутбуке (из корня репозитория):

```bash
git status --short
git rev-parse HEAD
PYTHONPATH="$PWD" .venv/bin/python -m pytest -q -rx \
  tests/test_v02_h55_r1_evidence_lifecycle.py \
  tests/test_v02_h2_2_evidence.py \
  tests/test_v02_h2_2_memory_dependencies.py \
  tests/test_memory_lifecycle.py \
  tests/test_v02_h5_4_compatibility.py
PYTHONPATH="$PWD" .venv/bin/python -m pytest -q
```

**Критерий приёмки:** каждый отказ произошёл *до* изменения данных; успешен весь pytest и старые N1–N9. Старый аудиторский репродуктор на исправленной ветке ожидаемо перестанет получать свой прежний `contract=FAIL`; это свидетельствует об исправленном поведении, а не о сбое проверки R1. Для принятия используем новые негативные тесты, проверяющие `ValueError` и неизменность состояния.

## R2 / F-02 — Raw Provenance (Core-bound принят)

**Полный контракт и команды:** [README_v02_h55_r2.md](README_v02_h55_r2.md).

Ветка `work/v02-h55-raw-provenance` от принятой R1. В `build_core()` создаётся каноническая привязка `MemoryStore` к `events.jsonl` через сохраняемый `schema_meta` ключ. В `KnowledgeLayer.confirm/reject/supersede` вводится физическая проверка всех declared Raw sources; отсутствующий или оборванный EventLog блокирует запись терминального Knowledge и оставляет исходное состояние без изменения.

Добавлены 12 негативных и положительных тестов в `tests/test_v02_h55_r2_raw_provenance.py`. **Подтверждено владельцем:** адресные `58 passed` за 1,48 с, полная регрессия `1987 passed` за 87,60 с.

**Оставшееся ограничение:** отдельно созданные `MemoryStore` без Core Raw binding сохраняют legacy режим, не обеспечивающий проверку Raw. Это не глобальное устранение F-02 для любого Python API. Перед окончательной приёмкой H5.5 необходимо решить, поддерживать ли такой режим вне тестов или сделать строгую привязку обязательной во всех экземплярах.

## R3 / F-04 — Evidence Consistency (принят владельцем)

**Полный контракт и проверки:** [README_v02_h55_r3.md](README_v02_h55_r3.md).

Ветка `work/v02-h55-evidence-consistency` основана на принятом R2; frozen audit SHA не менялся. `LinkStore.create_relation()` атомарно запрещает пересекающиеся по времени противоположные `Memory → Knowledge:supports/contradicts` для одной и той же Memory. В `labs/v02_h5_legacy_diagnostic.py` добавлен finding `conflicting_active_knowledge_evidence` для офлайновых повреждённых legacy данных; он переводит H5.4b compatibility в `BLOCKED`. Существующие тесты H2.2, намеренно моделировавшие повреждённую Relation через публичный API, теперь вставляют её прямым SQL **строго в `pytest tmp_path`**, чтобы сохранить проверку отрицательного legacy случая.

Добавлены **12 тестов** `tests/test_v02_h55_r3_evidence_consistency.py`. **Подтверждено владельцем:** адресные `68 passed` / 1,51 с, полный pytest `1999 passed` / 88,71 с. F-06 (асимметрия future contradictions в `KnowledgeLayer.confirm`) не входит в R3, как и глобальная версия Raw binding для standalone.

## R4.1 / F-03 — Finalized Projection Retention (принят владельцем)

**Подробный контракт, точный независимый сценарий и команды:** [README_v02_h55_r4_1.md](README_v02_h55_r4_1.md).

В ветке `work/v02-h55-r4-projection-retention` после принятого R3 внесены минимальные изменения:

- `MemoryStore.delete_memory()` под `BEGIN IMMEDIATE` запрещает удалять Memory, если любое связанное `memory_sources.event_id` имеет `event_processing.processor='memory_processor'` со статусом `done` (включая старые версии ledger).
- `EventProcessingCoordinator.recover()` отказывает в восстановлении, если уже имеется `done` без связанных `memory_sources`; проверка проводится **до** `_bootstrap_missing`.
- `EventProcessingCoordinator._replay_result()` отказывает в ложном `already_done` с `memory_id=None`; никакие старые `done` автоматически не перерабатываются.
- `skipped` не требует Memory; standalone/unfinalized Memory остаётся удаляемой, если нет других ссылок.

Добавлено **8 новых тестов** `tests/test_v02_h55_r4_1_projection_retention.py`, в том числе первичный сценарий `projection_delete` из аудиторского архива. **Подтверждено владельцем:** адресные `73 passed` / 3,01 с, полный pytest `2007 passed` / 88,16 с.

**Граница R4.1:** штатные API и выявление уже повреждённых `done`; не решает direct SQL и не вводит протокол tombstones/repair. Старые повреждённые экземпляры требуют отдельной офлайновой диагностики и решения оператора.

## R4.2 / F-05 — Temporal Memory Merge (кандидат)

**Подробный контракт и команды:** [README_v02_h55_r4_2.md](README_v02_h55_r4_2.md).

В `work/v02-h55-r4-temporal-merge`, от принятой R4.1, `MemoryLifecycle.merge()` перестал копировать все source `about` с `valid_until IS NULL` и создавать у target связь задним числом от `merged_at`, игнорируя исходный `created_at`. Новый переносимый период — `[max(source.created_at, merged_at), source.valid_until)`; истёкшие `about` не переносятся, а прежний `source_memory_id` сохраняется для provenance. Существующие target Relations не подавляют нужную передачу только из-за открытого `valid_until` без проверки начала и полного покрытия.

Добавлено **10 тестов** `tests/test_v02_h55_r4_2_temporal_merge.py`, в том числе точный `temporal_merge` аудитора (future 2099 relation), finite/exact-end, expired, offsets, provenance и инвертированный legacy-интервал. Расчётная полная регрессия **`2017 passed` (2007+10)**, **не исполнялась**.

## Оставшиеся блокеры

R2 / F-02 — Core-bound пройден по регрессии владельца; unbound standalone API остаётся отдельной границей, указанной выше.

R3 / F-04 — runtime writer и offline diagnostic прошли регрессию владельца; требуется независимый повторный аудит нового snapshot.

R4 — F-03 принят в пределах штатных API; F-05 подготовлен в R4.2, F-06/F-07/F-08 остаются. Не выполнять молчаливую повторную проекцию `done` или автоправку legacy-данных.

После устранения подтверждённых дефектов — новый фиксированный SHA и независимый аудит. Текущий v0.2 RC не принят.
