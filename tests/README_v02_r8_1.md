# ANIMA v0.2 — R8.1 Context Adapter Integrity

**Исходный аудит:** H5.7 @ `03ec97448d7e805a1dd34729140a47fd31c53774`.
**Новая finding:** **H57-02 (P2)** — unsupported adapter candidate
`kind="entity"` теряется из `ContextBuilder._selection_order` при
`retrieval_coverage.complete=True`, `truncated=False`,
`items_used=0` и `omitted_budget=0`. **BLOCK_RC** для публичного custom
Retrieval adapter API. **Native `RetrievalEngine` не затронут repro.**
**База:** R8.0 locally verified `d9ebf376bd4831f2c74e22a4831ef176c8376eff`
(`2179 passed` и `scripts/check.sh` PASS по отчёту владельца).
**Рабочая ветка:** `work/v02-r8-1-context-adapter-integrity`.
**Статус:** IMPLEMENTED / NOT LOCALLY VERIFIED.

## Контракт

`ContextBuilder.build` принимает Retrieval response `dict` с
`results: list`. Каждый элемент **до** попытки вычисления coverage,
selection, trace или budget должен соответствовать минимальному
представимому контракту Stage 1.9:

| Поле | Ожидаемый тип / инвариант |
| --- | --- |
| Candidate | `dict` |
| `kind` | строго `"memory"` или `"knowledge"` |
| `id` | непустая строка |
| `record` | `dict` с `record["id"] == candidate["id"]` |
| `record["content"]` | строка для `kind="memory"` |
| `record["statement"]` | строка для `kind="knowledge"` |
| `score` | finite `int/float`, исключить `bool` и NaN/Infinity |
| `reasons` | `list[str]`, элементы — непустые строки; `[]` допустим |

Дополнительные поля записи допустимы. Проверка `id` не заменяет Raw
authority, не разрешает несуществующий ID и не вводит новый тип данных.
Внешний адаптер остаётся ответственным за truthfulness своих stats и
записей; `ContextBuilder` отвечает за **структурную представимость**.

Нарушение любого поля в **любом** элементе вызывает `ValueError`
с индексом candidate, без частичного `ContextBundle` и без
ложного `complete=True`. Это строгая fail-closed политика,
**не** tolerant mode, автоматически выбрасывающий неизвестные records.

### Незатронутые свойства

- Native `RetrievalEngine` возвращает допустимые `memory/knowledge`
  records и прежние top-k/filter/exact/graph scores.
- Policy `FAST/DEEP`, knowledge-first, exact-first, relation_hops,
  бюджетирование по item/char и event provenance не меняются.
- `_assess_retrieval_coverage` сохраняет tri-state flags, защиту от
  противоречивых counts, различие `retrieval_coverage.complete`
  (полнота Retrieval) и `truncated` (включая Context budget omission).
- Для корректных `results=[]` с проверенными stats сигнал
  `complete=True` допустим; отсутствие stats остаётся
  `complete=False`.
- Не вводятся `entity` в Context, новая БД, миграция или auto-repair.
  Пользовательские данные и исходный H5.7 target не меняются.

## Изменения

- `anima/memory/context_builder.py`:
  `_validate_retrieval_candidates(candidates)` вызывается сразу после
  проверки типа `results` и **до** оценки coverage/selection.
  Проверяются поля, реально используемые ContextBuilder и вызовами
  ProvenanceResolver. Не меняются existing bundle keys и поля статистики.
- `tests/test_v02_r8_1_context_adapter_integrity.py`:
  **64 параметризованных cases** без файловой БД:
  - original `kind="entity"` и `exact_id:+100` в FAST и DEEP;
  - смешанный list valid + unsupported в обоих порядках;
  - неизвестный/missing/нестроковый kind;
  - не-dict candidate, missing/nonstring/empty ID, mismatched/missing
    record, missing/nonstring content/statement;
  - invalid reasons, nonfinite/boolean/non-numeric score;
  - valid FAST/DEEP memory/knowledge, unmodified items, complete stats,
    корректно пустой response, unknown stats;
  - valid budget omission остаётся `truncated=True` с
    `omitted_budget=1`, а `retrieval_coverage.complete=True`.

## Локальный gate

```bash
git rev-parse HEAD
git status --short
PY=~/Projects/ANIMA/.venv/bin/python

PYTHONPATH="$PWD" "$PY" -m pytest -q -rx \
  tests/test_v02_r8_1_context_adapter_integrity.py \
  tests/test_v02_r8_0_challenged_proof_novelty.py \
  tests/test_v02_r7_4_integration_release_gate.py \
  tests/test_v02_r6_3_temporal_context_contracts.py \
  tests/test_context_builder.py \
  tests/test_retrieval.py \
  tests/test_provenance.py

ANIMA_PYTHON="$PY" bash scripts/check.sh
PYTHONPATH="$PWD" "$PY" -m pytest -q -rx
git status --short
```

**Ожидаемый full pytest:** `2179 + 64 = 2243 passed`,
если прежний состав тестов не меняется. **Это не результат
исполнения**. Для R8.1 closed требуется полный local gate на точном SHA.

В комплекте H5.7 `ANIMA_v0_2_H57_Evidence.zip` имеется
`probes/test_h57_findings.py` с original unsupported adapter
negative repro. При отдельном независимом прогоне требовать
`test_unsupported_candidate_kind_is_not_silently_omitted_as_complete`
для FAST/DEEP. До запуска проверить код внешних probes и выполнять
только на временной копии.

**Следующие этапы:** R8.2 — H57-03 temporal validation consistency;
R8.3 — общий интеграционный gate; независимый H5.8 review.
RC без review не публикуется.
