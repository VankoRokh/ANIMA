# ANIMA v0.2 — H2.1 / Knowledge confirmation authority

**Статус:** ✅ **H2.1 принято**: по результату владельца, `1847 passed, 5 xfailed` за 86,31 с; нарушений полной регрессии не зарегистрировано.

**Ветка:** `work/v02-h2-knowledge-confirmation-guard`. Основана на принятой оптимизированной H1.3: `4376d73a4512753865b9484ef4d15c9a63534780`.

## Основание

R1-S1 N3: `LinkStore.create_knowledge(status="confirmed")` мог создать подтверждённое Knowledge без поддерживающей Memory и без истории жизненного цикла. Это низкоуровневый обход `KnowledgeLayer.create_candidate()/confirm()`.

## Исправление H2.1

- `LinkStore.create_knowledge(status="confirmed")` теперь отклоняет вызов до записи в SQLite: `ValueError("Confirmed Knowledge requires evidence; use KnowledgeLayer.confirm()")`.
- Низкоуровневое создание `provisional` сохранено для совместимости.
- Подтверждение выполняется через `KnowledgeLayer.confirm()`, который записывает соответствующий transition в историю и проверяет наличие support.
- Три фикстуры `test_retrieval.py`, `test_context_builder.py`, `test_provenance.py` больше не создают напрямую `confirmed`: они создают `provisional`, добавляют `supports`, затем используют `KnowledgeLayer.confirm()`.
- H0 тест N3 переведён из `XFAIL` в обычный regression `PASS`.
- `tests/test_v02_h2_1_confirmed_knowledge.py`: шесть проверок прямого отказа, отсутствия побочных записей, работы `provisional`, штатной подтверждённой цепочки, отказа без доказательства, некорректного статуса и `open` источника при создании Candidate.

## Границы исправления

**Это только первая часть N3.** Известные ограничения `KnowledgeLayer.confirm()` при уже существующих отношениях `supports` (в том числе ссылка на `open` или утраченную Memory, противоречия) ещё не исправлены. Нельзя объявлять все гарантии Knowledge Evidence восстановленными по одному N3-тесту.

Также в рамках H2.1 пока допустимо низкоуровневое создание других жизненных статусов `challenged/superseded/rejected`; этот интерфейс требует отдельного согласования lifecycle-границ и изменения фикстур. Не трактовать H2.1 как общий запрет всех обходов history.

Следующий подэтап H2.2 должен закрыть валидацию актуальных `supports`, N4 (осиротевшие отношения при удалении Memory) и политику конкурирующих доказательств без потери истории.

Никаких автоматических изменений существующих пользовательских Knowledge или Memory; миграция БД для H2.1 не нужна.

## Проверки

```bash
PYTHONPATH="$PWD" .venv/bin/python -m pytest -q -rx \
  tests/test_v02_h0_foundation_contracts.py \
  tests/test_v02_h2_1_confirmed_knowledge.py \
  tests/test_retrieval.py tests/test_context_builder.py \
  tests/test_provenance.py tests/test_knowledge.py
```

Ожидаем **5 XFAIL**, остальные PASS; полная регрессия обязательна:

```bash
PYTHONPATH="$PWD" .venv/bin/python -m pytest -q
```

При неизменном остальном наборе тестов ориентировочно ожидается `1847 passed, 5 xfailed` (включая 6 новых H2.1 тестов и N3, переведённый в PASS). Это расчётная оценка, **не исполненный результат**. Любые FAILED/ERROR/XPASS разбираем отдельно; не менять производственные контракты лишь ради косметического PASS.

Raspberry Pi 5 не входит в обязательные проверки.

## Следующий подэтап

H2.2 внесён в отдельную ветку `work/v02-h2-evidence-dependencies`: проверки действительности `supports/contradicts` и запрет удаления Memory с зависимостями. См. `tests/README_v02_h2_2.md`. На момент добавления документации H2.2 **ещё ожидает испытаний**.
