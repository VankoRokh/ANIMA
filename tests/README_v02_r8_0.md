# ANIMA v0.2 — R8.0 Knowledge Proof Novelty

**Исходный аудит:** H5.7, `audit/v02-h57-r7-post-integration-candidate`
@ `03ec97448d7e805a1dd34729140a47fd31c53774`, conclusion
`BLOCKED / BLOCK_RC`. Finding **H57-01 (P2)**.

**Основа R8.0:** зафиксированный H5.7 SHA.
**Рабочая ветка:** `work/v02-r8-0-challenged-proof-novelty`.
**Статус:** IMPLEMENTED / NOT LOCALLY VERIFIED.
**Цель:** исправить ложный отказ genuinely new proof при одинаковом
`challenge_at == confirm_at`. Запретить возврат прежнего H56-01.

## Контракт до и после R8.0

`KnowledgeLayer.confirm(K, source_memory_id=C)` из challenged:
- требует CLOSED Memory C и канонического физического Raw (R5);
- отказывает при повторном использовании старого support для C, а также
  при future/expired proof;
- разрешает новый effective Raw-backed C, доказательство которого
  **создано самим текущим confirm**, даже если timestamp Relation
  равен `challenged_at`. Фактический порядок находится в транзакции,
  а не извлекается из секундной отметки времени;
- разрешает уже подготовленную Relation с началом строго после
  challenge при условии, что для C не было старой support;
- отвергает **старую, заранее подготовленную Relation**, начинающуюся
  в точности в момент challenge (включая offset-equivalent instant);
- при неуспехе не оставляет новых History/status/Relation/Raw effects.

### Причина H57-01

В `_require_challenged_support_novelty` запрос `old_source`
исполнялся **после** `_effective_or_create_evidence`.
Если новый support был INSERTed в текущем вызове, запрос считал
его уже существовавшим и блокировал `created_at <= challenged_at`.
На нормальном default clock обе метки могут иметь точность до секунды.

### Минимальная реализация

Запрашивать `public_id, created_at` всех supports того же C и K.
При `created=True` исключать из проверки старых support **ровно**
`row.public_id == relation.id`. Другие Relation, в том числе
предварительно созданные и совпадающие по времени, проверяются как
раньше; при `created=False` нельзя ничего исключать.

**Недопустимые способы «исправления»:** менять `<=` на `<`,
отключать novelty целиком, считать физическое наличие `memory_sources`
доказательством Raw, сбрасывать History или принудительно задерживать
вызов `confirm` до следующей секунды.

Изменяется только `anima/memory/knowledge.py`, без schema migration,
других production API или новых функций. `ContextBuilder` H57-02
остаётся отдельным шагом R8.1; H57-03 — R8.2.

## Испытания

`tests/test_v02_r8_0_challenged_proof_novelty.py`, **13 cases**:
- новая Relation при identical second и offset-equivalent instant;
- default-parameter `challenge()` и `confirm()` в одном
  детерминированном clock second, с физическим Raw appended после challenge
  и новой Memory CLOSED до confirm;
- старый support A не может повторно подтвердить K ни на равной метке,
  ни позднее;
- support C, подготовленный **до** challenge на ту же секунду,
  отказывается как старый, включая эквивалентный UTC offset;
- valid staged support C с `start > challenged_at` подтверждается
  без создания второй Relation и без продления конечного `valid_until`;
- future (2099) и expired support C нельзя молча повторно открыть;
- отсутствие физического Raw для C даже после успешного novelty check
  откатывает вставку support/status/history;
- challenged confirm без указания нового источника остаётся запрещён.

Вся фикстура живёт под `pytest tmp_path`. Нет SQL damage или
пользовательских файлов. Отдельный raw-loss case изменяет только
синтетический временный `events.jsonl`.

## Независимые проверки, требующие сохранения

Перезапустить регрессии R7.0–R7.4, R6.1/R6.3 и `tests/test_knowledge.py`.
По возможности переисполнить H57 original independent
`probes/test_h57_findings.py -k new_proof_created_by_confirm_is_not_itself_old_evidence`
из предоставленного `ANIMA_v0_2_H57_Evidence.zip` в отдельном
sandbox и его `probes/live_same_second_reconfirm.py` (при совпадении
времени ожидается exit 0; exit 3 означает, что в трёх попытках не
попали в ту же секунду — это **не** доказательство PASS/FAIL).

Для этих scripts нужен `h56_support.py` из
`original_probes/`, а также review сторонних scripts перед исполнением.

## Локальный gate

```bash
git rev-parse HEAD
git status --short
PY=~/Projects/ANIMA/.venv/bin/python

PYTHONPATH="$PWD" "$PY" -m pytest -q -rx \
  tests/test_v02_r8_0_challenged_proof_novelty.py \
  tests/test_v02_r7_0_temporal_authority.py \
  tests/test_v02_r7_1_memory_source_integrity.py \
  tests/test_v02_r7_2_lifecycle_write_authority.py \
  tests/test_v02_r7_3_storage_evidence_validation.py \
  tests/test_v02_r7_4_integration_release_gate.py \
  tests/test_v02_r6_1_knowledge_write_authority.py \
  tests/test_v02_r6_3_temporal_context_contracts.py \
  tests/test_knowledge.py

ANIMA_PYTHON="$PY" bash scripts/check.sh
PYTHONPATH="$PWD" "$PY" -m pytest -q -rx
git status --short
```

При неизменном числе прежних случаев **ожидается 2179 PASS**
(`2166 + 13`), но это не результат фактического исполнения.

**R8.0 CLOSED / LOCALLY VERIFIED** только после полного успешного gate
на точном SHA. Затем R8.1 Context Adapter Integrity, R8.2 Temporal
Validation Consistency, R8.3 integration acceptance. H5.7 audit
branch/target остаются неизменными. Решение по RC только после H5.8.
