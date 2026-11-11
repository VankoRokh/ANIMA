# ANIMA — Memory Encoding E2: unverified relation candidates

**Ветка:** `experiment/core-memory-information-baseline`.  
**Дата:** 2026-11-12.  
**Статус:** лабораторный E2 реализован; **CI/gold gate OPEN** до результатов workflow.  
**E1:** [результаты](Memory_Encoding_E1_Results.md); [brief](Memory_Encoding_Shadow_E1_Brief.md).  
**Файлы:** [shadow](../../anima/memory/shadow_encoding.py), [E2 harness](../../labs/exp009/memory_encoding_e2.py), [negative tests](../../tests/test_memory_encoding_e2.py).

## Что именно проверяем

E1 показал у Shadow точные границы на 20 заранее размеченных событиях, но выявил риск **false split** при продолжении на той же сущности без общего текста. Для этого в E2 вводится отдельный **неавторитетный класс результата**: `possible_related`.

Это **не relation в LinkStore, не Knowledge, не Memory merge, не Evidence vote, не решение Core**. Система сохраняет два эпизода раздельно и сообщает диагностическую гипотезу с `episode_id`, конкретными `source_event_ids`, валидированными общими Entity ID и причиной `shared_entity_without_raw_overlap`. Статус строго `unverified`.

## Условия появления candidates

Должны одновременно выполняться:

1. Оба эпизода относятся к известной одной и той же сессии, одному `source` и интервалу не более 30 минут.
2. Entity ID подтверждены через подключённый `LinkStore.get_entity` и пересекаются. При отсутствии регистра Entity этот сигнал недоступен.
3. Прямое лексическое совпадение недостаточно для `append`; иные запреты `_score` (разные проверенные Entity, late Event, превышенный лимит episode) не преодолеваются.
4. Число слабых кандидатов ограничено пятью, обход ограничен 64 последними эпизодами, порядок детерминирован по недавности.
5. `append` по существующим строгим правилам и `new_episode` не изменяют своих условий. Повтор Event ID не создаёт нового эпизода.

Два сообщения об одной Entity **не обязаны быть об одном эпизоде**. Статус `unverified` не превращается автоматически в `related_to`. Наличие валидного ID означает только идентичность, а не истинность пользовательского сообщения.

## Набор отрицательных испытаний

Отдельный E2 корпус из семи Events. Релевантность связи зафиксирована **до запуска**: `decision → baseline` (одна предметная цепочка, совершенно другие слова). Также включены: отдельная инвентаризационная задача на той же Entity (**заведомо ложный кандидат**), другая Entity с теми же словами, другая сессия, интервал >30 минут и перефраз без Entity. Цель — не максимум accuracy, а **полная наблюдаемость пропусков и ложных предположений**.

Отчёт содержит конкретные candidate pairs, `hits`, `false_candidates`, `missed`, относительную precision/recall на **этой маленькой метке**, полные решения по каждому Event и сохранение исходной Memory. Эти метрики нельзя переносить на произвольный язык, Core observations или масштабные базы.

## Проверка

```bash
python -m pytest -q -p no:cacheprovider tests/test_memory_shadow_encoding.py tests/test_memory_encoding_e2.py
python -m pytest -q -p no:cacheprovider
bash scripts/check.sh

out="$(mktemp -d -t anima-e2-XXXXXX)"
python -m labs.exp009.memory_encoding_e2 --report-dir "$out"
cat "$out/memory_encoding_e2_candidates.json"
```

CI матрица 3.12/3.13/3.14; E2 artifact только из Python 3.14. **До успешного CI не фиксировать численные результаты**.

## Критерий следующего решения

Сначала подтвердить E1 adversarial compression probe и E2 по CI/JSON. Затем расширить корпус на независимые тематики и RU/EN, длинные цепочки, ложные Entity refs и неопределённые границы. Production переход разрешён только после проверки устойчивости к false merges/false splits, recovery, ресурса и полной границы authority.
