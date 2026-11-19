# ANIMA v0.2 — R7.0 Knowledge Temporal Authority

**Режим:** целевое исправление H56-01 (P1) и H56-02 (P2), без добавления новых функций.
**База:** audit H5.6, snapshot `f70d879a88d88f63777646b0a65448765610402d`.
**Этап приёмки:** локальный pytest + `scripts/check.sh` → независимая проверка H5.7 после R7.1–R7.4.
**Авторитетные доказательства:** `ANIMA_v0_2_H56_Evidence.zip`, `probes/test_h56_findings.py`, `probes/h56_live_reconfirm.py`, `ANIMA_v0_2_H56_Independent_Reaudit_RU.md`.

## Архитектурный контракт

1. **Временное основание**: все `supports` / `contradicts` используют один полуоткрытый интервал `[created_at, valid_until)`. `valid_until=None` означает бессрочность. Сравнение — по абсолютному UTC instant (offset-aware ISO), не лексикографически по строкам. Временная граница end исключается, start включается.
2. **Transition-time proof**: `confirm`, `challenge`, `reject` могут указывать в History только на Relation, действующую при `*_at` перехода. Существующая будущая бессрочная Relation не является подтверждением сейчас; `_insert_relation(reject_duplicate=False)` с return created=False **не** доказывает действительности.
3. **Reuse, без неявного продления**: если подходящий source имеет действующую конечную или бессрочную Relation, переход использует её ID без INSERT и без изменения `valid_until`. У этого правила нет исключений для `challenge` и явного `reject`; `confirm` из provisional также сохраняет finite support.
4. **Новый Evidence для `challenged → confirmed`**: неявная форма `confirm(K)` недопустима. Явный `source_memory_id` требует **нового относительно последнего challenge** действующего support: (а) новая Relation, созданная этим confirm в `confirmed_at`, либо (б) заранее подготовленная Relation, которая **начинается строго после `knowledge.updated_at` challenge** и уже действует при `confirmed_at`. Предшествующая действующая Relation не является новой; будущая, ещё не действующая — тоже. Ранее использованный source нельзя просто переобъявить новым без новой версии/свидетельства.
5. **Несогласованная попытка writer**: если после lookup `_insert_relation` возвращает duplicate, который не действует при transition time, обязательно `ValueError` без изменения status/History/Relations. Нельзя заменять этот дефект проверкой «существует какое-нибудь старое support другой Memory».
6. **`challenge` и `reject`**: если уже действующий contradiction B имеется (finite или open-ended), переиспользовать его. Если B отсутствует, создать новый с началом в transition time с прежними проверками пересечений. `reject(K)` без указанной Memory продолжает требовать хотя бы одно действующее contradiction. Не продлевать expired/future без явного контролируемого writer.
7. **Authority/atomicity**: `Memory` должен существовать и быть CLOSED для активного Evidence; provenance — физические канонические Raw, весь graph должен проходить общий published Raw guard. Любой отказ откатывает mutation атомарно; `LinkStore` не получает новое право вставлять поздние support/contradiction в published Knowledge. Никаких SQL data-repair и миграций.
8. **Границы**: `Knowledge.status` является сохранённым результатом последнего lifecycle-перехода; текущая `KnowledgeLayer.describe()` проекция использует «сейчас». Автоматическое aging по истечении finite support, snapshot исторического текста Memory, правдоподобие Evidence и право generic `supersedes` рассматриваются отдельно (H56-03 / R7.2), в R7.0 НЕ реализуются.
9. **Исторический source**: при повторном подтверждении прежняя Memory, уже поддерживавшая K до challenge, сама по себе не становится новым свидетельством от повторной вставки same-polarity Relation. Выделение действительно новой версии этого Memory потребует отдельного revision/source identity контракта; пока fail-closed.

## Обязательные отрицательные тесты

- **H56-01**: `provisional(K)` с valid A → `confirm(A)` → `challenge(B)` → `confirm(C)`, где C содержит только `supports` из 2099; должен быть отказ с идентичными Memory/Knowledge/Relation/History/Raw.
- **H56-01**: попытка `confirm` с предсуществующим active старым A — отказ; с новым C, полученным после challenge — успех, с действующим support, записанным в History; восстановление после restart.
- **NEW-04 control**: уже действующий конечный support на initial `provisional → confirmed` повторно используется и не создаёт новых Relations.
- **H56-02**: finite `contradicts(B,K)=[t4,t8)` → `challenge(B,t5)`, с и без `supports(B,K)` от t8; исходный finite ID и end неизменны, никакого overlap.
- **H56-02**: `reject(K,contradiction_memory_id=B,t5)` vs `reject(K,t5)` одинаково сохраняют интервалы и различаются только намеренной `History.source_kind` семантикой.
- **Boundaries**: t4 включительно, t8 исключительно, future relation, различные UTC offsets, active opposite evidence — отказ/сохранение  R3.
- **Authority**: unknown/missing Raw и current OPEN Memory — атомарный отказ; original F-01–F-08 и NEW-01–NEW-07 regressions.

## Локальная приёмка

```bash
git rev-parse HEAD
git status --short
PY=~/Projects/ANIMA/.venv/bin/python
PYTHONPATH="$PWD" "$PY" -m pytest -q -rx \
  tests/test_v02_r7_0_temporal_authority.py \
  tests/test_v02_r6_3_temporal_context_contracts.py \
  tests/test_v02_h55_r4_3_temporal_confirmation.py \
  tests/test_knowledge.py \
  tests/test_v02_r6_1_knowledge_write_authority.py
ANIMA_PYTHON="$PY" bash scripts/check.sh
PYTHONPATH="$PWD" "$PY" -m pytest -q -rx
```

**Не считать реализованное исправление PASS до фактического исполнения.** Новые release gates в этом документе — цели, не сведения о проверенных результатах.
