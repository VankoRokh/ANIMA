# ANIMA v0.2 — R8.2 Temporal Validation Consistency

**Основа:** R8.1 locally verified, commit
`f0cf0032ae00a4e213fac59013a200d0d3e953a7`.
Владелец сообщил `2243 passed`, `scripts/check.sh` PASS,
Python 3.14.4.
**Ветка:** `work/v02-r8-2-temporal-validation-consistency`.
**Задача:** H57-03 (P3), обнаружена независимым аудитом
H5.7 @ `03ec97448d7e805a1dd34729140a47fd31c53774`.
**Статус:** IMPLEMENTED / NOT LOCALLY VERIFIED.

## Причина

R7.3 добавил `_validate_evidence_interval`, который проверяет
все `supports/contradicts` при публикации Knowledge, включая неактивные.
Но в `confirm` сначала вызывается
`_require_effective_memory_evidence`, где
`datetime.fromisoformat(legacy_naive_timestamp) > aware_time`
вызывает **TypeError** ещё до общего валидатора.

Потери данных или ложной публикации не показано: SQLite transaction
откатывается. Нарушается публичная таксономия ошибок и заявленное
правило `ValueError` для повреждённых интервалов.

## Изменение R8.2

`KnowledgeLayer._require_valid_evidence_intervals(connection, knowledge_id)`
проверяет **все** attached `supports/contradicts` строки данного
Knowledge, включая dormant/future/expired, через уже действующий
`_validate_evidence_interval(created_at, valid_until)`.

Read-only preflight выполняется **в той же транзакции SQLite** в начале
каждого изменения состояния Knowledge:
- `confirm` — до duplicate/effective comparisons и возможного INSERT;
- `challenge` — до противоположного Evidence и повторного создания;
- `reject` — до проверки выбранного contradiction и effective Evidence;
- `supersede` — до публикации замещающего Knowledge.

Переиспользуется существующая validation policy: строки должны быть
offset-aware ISO 8601; `valid_until=None` допустимо; finite интервал
строго `created_at < valid_until` по абсолютному времени. Новых
правил Knowledge, Evidence или внешних форматов не вводится.

**Сохранены** R7.3 per-relation проверка перед terminal Raw scan,
Raw existence authority, finite evidence, no opposite overlap,
R8.0 same-instant fresh proof, R7.2 supersedes authority и все старые
lifecycle entrypoints.

### Цена и предел

Добавлен один `SELECT` всего Evidence graph плюс проход validation
перед transition. Existing terminal Raw guard всё ещё валидирует этот
graph при публикации (защита в глубину), поэтому проверка границ может
выполняться дважды. При больших графах возможны дополнительные затраты;
это следует оценить в R8.3/H5.8, а не скрывать под отсутствующим SLO.
Другая граница — семантическая истинность Raw — этим не меняется.

## Тестирование

`tests/test_v02_r8_2_temporal_validation_consistency.py`:
**55 параметризованных test cases**.

На пяти `confirm_implicit`, `confirm_explicit`, `challenge`,
`reject`, `supersede` сценариях:
- 8 способов повреждения **только временной SQLite-фикстуры**:
  inverted, equal, naive start, malformed start, empty start,
  malformed end, naive end, invalid calendar date;
- все 40 отказов должны быть **именно `ValueError`**,
  с неизменными Knowledge, Relations, History, `memory_sources`, Raw;
- 3 корректных типа finite future, offset-equivalent и open-ended
  future Evidence × 5 методов = 15 положительных случаев;
- valid future/finite Evidence не продлеваются и не изменяются;
  статус каждого Knowledge перехода сохраняет прежнюю семантику.

Ранее добавленные R7.3 tests покрывают и H56-05,
Original H5.7 `probes/test_h57_contracts.py` содержит строгий
`test_all_publications_reject_dormant_interval_damage`;
его можно независимо переисполнить из `ANIMA_v0_2_H57_Evidence.zip`
только в новом temp harness после инспекции скрипта.

## Локальная проверка

Работать в отдельном clean worktree точного HEAD. Рекомендуемые команды:

```bash
git rev-parse HEAD
git status --short
PY=~/Projects/ANIMA/.venv/bin/python
PYTHONPATH="$PWD" "$PY" -m pytest -q -rx \
  tests/test_v02_r8_2_temporal_validation_consistency.py \
  tests/test_v02_r8_1_context_adapter_integrity.py \
  tests/test_v02_r8_0_challenged_proof_novelty.py \
  tests/test_v02_r7_3_storage_evidence_validation.py \
  tests/test_v02_r7_4_integration_release_gate.py \
  tests/test_v02_r6_3_temporal_context_contracts.py \
  tests/test_knowledge.py

ANIMA_PYTHON="$PY" bash scripts/check.sh
PYTHONPATH="$PWD" "$PY" -m pytest -q -rx
git status --short
```

**Ожидается** `2243 + 55 = 2298 PASS` при неизменных старых tests.
Это **не утверждение о прогоне**.

R8.2 CLOSED только после фактических PASS всех gates на точном SHA.
Далее R8.3 Integration & Acceptance, затем независимый H5.8.
H5.7 audit branch, исходные Raw и пользовательские данные не изменять.
