# ANIMA — Memory Encoding E3: review of uncertain episode links

**Дата:** 2026-11-12.  
**Ветка:** `experiment/core-memory-information-baseline`.  
**Статус:** лабораторный код и отрицательные тесты добавлены; **CI gate OPEN**, E2 и compaction probe тоже ожидают исполняемую приёмку.  
**Основание:** [E1 Results](Memory_Encoding_E1_Results.md), [E2 Brief](Memory_Encoding_E2_Brief.md), [Stage 7 Semantic Boundary](Stage_7_Semantic_Boundary_v0.md).  
**Реализация:** [E3 triage](../../labs/exp009/episode_link_triage.py), [adversarial runner](../../labs/exp009/memory_encoding_e3.py), [tests](../../tests/test_memory_encoding_e3.py).

## 1. Смысл жизненного цикла

Нужно не разрушать полезные продолжения эпизодов при недостаточном лексическом совпадении, но и не превращать гипотезы в Memory/Knowledge relations.

```text
raw Event → ShadowEpisodeEncoder
    ├─ reliable lexical boundary: append to existing shadow episode
    └─ no safe merge: new shadow episode
           └─ shared validated Entity within same session/time window
                → potential_related (status=unverified)
                     → no additional bridge: review_state=needs_evidence
                     → later raw bridging Event: review_state=review_ready
                          └─ ALWAYS status=unverified
```

`review_ready` **не означает** подтверждение. Это приоритет/триггер для более дорогого независимого анализа. Вердикт о реальной связи, слиянии, Knowledge/Claim admission и authority остаётся **вне** E3. Нет числовой вероятности «истинности», которую невозможно откалибровать на семи синтетических примерах.

## 2. Основания, дедупликация, границы

- У каждого candidate стабильный ID от отсортированной пары episode ID, конкретные исходные Event IDs и известные Entity IDs. Дубли одного и того же неориентированного предложения сводятся к **одной** гипотезе, а не к двум свидетельствам.
- Proposal E2 должен указывать на существующие в замороженном корпусе Event IDs. Фальшивые source references, неподтверждённые Entity IDs и несогласованные episode identities отклоняются.
- Новый `conversation.user` Event может создать **триггер пересмотра**, если он относится к той же сессии и source, имеет известную общую Entity, поступает по временной оси в пределах 30 минут и содержит >=2 значимых общих токена с **каждым** из двух исходных Events. Это **лексический bridge**, а не независимое свидетельство истинности связи.
- Повтор Event ID не создаёт нового bridge, конфликтующий replay отклоняется.
- `MAX_CANDIDATES=256`, `MAX_TRIGGER_EVENTS=256`, `MAX_BRIDGES=8` на candidate; пределы сообщаются явно, не маскируются под отсутствие фактов. При превышении лимита список bridge ID не расширяется и устанавливается `bridge_limit_reached`.
- История рассматривается как производная in-memory проекция; доступен JSON snapshot для разборов, **нет** долговечной production очереди. Системный `received_at` и Source authority не выводятся из пользовательского `Event.timestamp`. Для production потребуется отдельный контракт ingress/clock-domain/recovery.

## 3. Тест с заведомо ложным bridge

E2 даёт три слабых пары, из которых **одна** размечена как действительно тематически связанная, а две — как ошибочные предположения.

E3 использует два новых raw Events:

1. Содержит лексику обоих действительно связанных эпизодов. Это должно повысить **только** соответствующий candidate до `review_ready`.
2. Содержит лексику двух **несвязанных** эпизодов. Оно способно повысить **ложный** candidate до `review_ready`, и это обязано быть видно в raw-отчёте.

После обоих шагов все candidate status по-прежнему `unverified`, ни один исходный эпизод не объединён. Критично: **совпадение слов в одном сообщении не доказывает отношение между двумя событиями**.

Дополнительные negative gates: отсутствие Entity, другой session, время вне окна, повтор bridge Event ID, конфликтный replay, поддельный raw source, дубли симметричных hypotheses и проверка полного отсутствия production writes.

## 4. Исполняемая проверка

```bash
python -m pytest -q -p no:cacheprovider \
  tests/test_memory_encoding_e2.py tests/test_memory_encoding_e3.py
python -m pytest -q -p no:cacheprovider
bash scripts/check.sh

report_dir="$(mktemp -d -t anima-e3-XXXXXX)"
python -m labs.exp009.memory_encoding_e3 --report-dir "$report_dir"
cat "$report_dir/memory_encoding_e3_review.json"
```

CI выполняет Python 3.12/3.13/3.14, полную регрессию и сохраняет E3 JSON artifact на Python 3.14. C3 100k benchmark ранее выполнен и переведён на **ручной запуск** `workflow_dispatch` для сокращения времени обычного CI.

## 5. Gate и следующий шаг

**E3 нельзя объявить PASS до выполнения вышеуказанных тестов и изучения JSON.** Даже при PASS это только лабораторный алгоритм *предложения на пересмотр*, а не production Memory Encoding.

Если E3 подтверждён, следующий содержательный шаг — независимый расширенный корпус (E4) с перефразами RU/EN, длинными цепочками, межсессионными и временными продолжениями, ложными Entity refs и разными уровнями authority. Долговременные гипотезы и пересмотр после SLEEP требуют отдельного durable-source/checkpoint контракта; нельзя просто сохранять `review_ready` в Knowledge и объявлять свойство решённым.
