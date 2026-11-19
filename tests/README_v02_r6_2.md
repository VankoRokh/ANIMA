# ANIMA v0.2 — R6.2 Memory Mutation Integrity

**Статус:** IMPLEMENTED / LOCAL TESTS NOT YET REPORTED.
**Основа:** принятые R6.0 и R6.1; parent `276f43e8621bd293a12ab624b6dc8e445981cf5c`.
**Finding:** независимый H5.5 post-remediation аудит, NEW-03 (P1).

## Дефект

`MemoryProcessor.process_event()` выбирал OPEN Memory во время чтения, а затем отдельной deferred-транзакцией выполнял SQL UPDATE, не перепроверяя статус, актуальность content или зависимости от confirmed Knowledge. Если другая нить между selection и UPDATE выполняла `close → create_candidate → confirm`, прямой processor мог переписать доказательный источник при сохранённом `Knowledge.status=confirmed`.

Изолированный штатный `EventProcessingCoordinator` уже удерживает `BEGIN IMMEDIATE` для всей обработки, но публичный прямой `MemoryProcessor.process_event()` выполнялся без такого writer lock. Одних guards в `MemoryStore.update_memory()` было недостаточно.

## Исправление и контракт

- При `connection=None` прямой `MemoryProcessor.process_event()` теперь применяет результат через `transaction(immediate=True)` и согласует его с писателями `MemoryStore`/`KnowledgeLayer`.
- `MemoryLifecycle.close()` теперь также начинает с `BEGIN IMMEDIATE` **до** чтения статуса, чтобы не возникал deferred read→write lock upgrade в середине параллельного processor update. Это необходимо для стабильного порядка `update → close → confirm` и обратной последовательности.
- `_update_memory_tx()` **внутри транзакции** заново читает Memory, сверяет полную выбранную запись и требует статус `open`, тип `episodic`, домен `user`. Устаревшая, удалённая, закрытая или изменённая Memory вызывает fail-closed `ValueError` **до** composer, UPDATE, INSERT в `memory_sources` и Entity relations.
- Тот же SQL writer вызывает `MemoryStore._require_no_confirmed_knowledge_dependencies()` под lock непосредственно перед composer/UPDATE. Он защищает и прямой путь, и уже существующий путь `connection=...` от Coordinator; не вводится новый независимый предикат.
- При stale selection применяется **отказ**, а не неявная повторная ассоциация/создание другой Memory: повтор выбора и retry остаются обязанностью вызывающего orchestration слоя. Это предотвращает скрытое изменение количества Memory и эффектов при гонке.
- Обычный прямой `process_event()` с неизменной OPEN Memory продолжает обновлять её, сохраняя source Events.
- SQLite schema, Raw EventLog, процессорная версия, event_processing ledger, create/create_related и Knowledge lifecycle публично не меняются.

## Отрицательные испытания

В `tests/test_v02_r6_2_memory_mutation_integrity.py` есть:
1. Положительная прямая update-последовательность без гонки.
2. Детерминированный interleaving: pause после выбора OPEN; вторым потоком `close → create_candidate → confirm`; resume; отказ без изменения Memory, Sources, Knowledge/History/Raw.
3. Lost-update: pause после выбора; другой writer меняет ещё OPEN Memory; resume; отказ без затирки первой записи.
4. Pause-only composer из первоначального аудита: после входа в compositor прямой processor удерживает writer lock, поэтому конкурентный `MemoryLifecycle.close()` завершается только после update; последующий confirm связывается с окончательным содержимым Memory.
5. Legacy-копия с подтверждённым Knowledge и искусственно SQL-открытой Memory: прямой и `connection=` пути отвергают update по R1 dependency guard. Прямой SQL применяется только в `pytest tmp_path` для отрицательного legacy состояния.

`pytest` параметризует пятую проверку, ожидаемо собирая **6** test cases.

## Ограничения

- Некооперативный SQL, прямые low-level записи вне публичного контракта и cross-file atomicity Raw/SQLite не покрываются.
- `MemoryProcessor.process_event(event, connection=...)` считает caller ответственным за передачу настоящего SQLite connection в корректной транзакции. Coordinator уже предоставляет `BEGIN IMMEDIATE`.
- R6.2 не меняет независимый recovery/done owner gate (R6.4), temporal Knowledge evidence (R6.3) и не объявляет весь v0.2 RC READY.
- Отсутствие автоматического retry для stale candidate является осознанным консервативным контрактом; не маскировать отказ новым create.
- Время исполнения, производительность на Pi и power-loss — НЕ ИСПЫТАНЫ.

## Local acceptance

Создать отдельный worktree для точного SHA ветки, выполнять только тесты на временных экземплярах.

```bash
git fetch origin
git rev-parse HEAD
git status --short

PYTHONPATH="$PWD" .venv/bin/python -m pytest -q -rx \
  tests/test_v02_r6_2_memory_mutation_integrity.py \
  tests/test_memory_processor.py \
  tests/test_v02_h55_r1_evidence_lifecycle.py \
  tests/test_v02_h55_r5_standalone_raw_authority.py

ANIMA_PYTHON=.venv/bin/python bash scripts/check.sh
PYTHONPATH="$PWD" .venv/bin/python -m pytest -q -rx
```

Чистый pytest, `scripts/check.sh` и подтверждённый пользователем SHA обязательны для локального R6.2 PASS; независимый H5.6 после R6.4 проверит закрытие NEW-03 вне этих unit tests.
