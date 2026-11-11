# ANIMA — Memory Encoding v1: Stage 3, shadow association E1

**Ветка:** `experiment/core-memory-information-baseline`.  
**Дата:** 2026-11-12.  
**Статус:** экспериментальная read-only реализация, **приёмка OPEN** до проверенного CI и анализа raw отчёта.  
**Roadmap:** [Memory Architecture v1.0/1.1](Memory_Architecture_v1_Roadmap.md).  
**Исходный baseline:** [Event Retrieval v1](Memory_Event_Retrieval_v1_Results.md), `anima/memory/processor.py`, `anima/memory/composer.py`.

## 1. Что проверяем

**Вопрос E1:** могут ли стабильные ссылки на исходные `Events` и их первичные признаки организовывать эпизоды независимо от сжатого `Memory.content`, не нарушая границы независимых случаев?

Нынешний `MemoryProcessor` читает `Memory.content` при `_candidate_memories()` и `_score_candidate()`. Это связывает **ассоциацию** с изменчивой **композицией**. Для исследований эти операции разделены: production `MemoryProcessor` и `MemoryStore` не заменяются и не мигрируются.

## 2. Реализация

- **`anima/memory/shadow_encoding.py`:** `ShadowEpisodeEncoder`, отдельная детерминированная in-memory модель. Обрабатывает только `conversation.user`; source refs — настоящие Event IDs, новые группы имеют локальные `shadow_ep_<event_id>`. Нет Memory write, нет LLM и нет runtime routing.
- **Признаки:** токены **первого и двух последних исходных Events** (не суммарный/сжатый summary), идентичность источника, session boundary, интервалы времени, опциональные **валидированные** Entity IDs. Два значимых пересекающихся токена и отношение overlap ≥ 0.4, только в пределах 30 минут и одной известной сессии. Повтор Event ID идемпотентен, несовпадение payload того же ID отклоняется.
- **Ограничения:** ≤64 последних эпизода-кандидата и ≤128 исходных Events на один shadow episode; новые Events за границами становятся самостоятельными эпизодами. Не утверждать, что этот лексический baseline понимает семантику, причинность или масштабирование без нагрузки.
- **`labs/exp009/memory_encoding_shadow.py`:** E1 сравнивает legacy processor с двумя бюджетами Composer (64/512 символов) и независимый shadow на **одних и тех же 20 фиксированных исходных Events**. Формируется заранее назначенный `gold`, pairwise precision/recall, `false_merge`/`false_split`, per-event решения, связи с источниками и raw JSON отчёт.
- **`tests/test_memory_shadow_encoding.py`:** replay/conflict, unknown Entity, межсессионные и временные границы, интерливинг, разные объекты, пунктуация, сохранение исходных source links, отсутствие записи в Memory.

## 3. Критерии приёмки (не подгонять под тест)

1. Сохранить реальные authoritative Events и действующую Legacy Memory: никакого изменения SQLite/JSONL во время вызовов shadow.
2. **Параллельное сравнение:** legacy-64/legacy-512/shadow получают идентичные Event ID, тексты, timestamp, Session, source и entity refs; реальные memory_sources из legacy не подменяются модельными.
3. Gold задаётся до расчёта. Нельзя объявлять `create_related` тем же эпизодом, что `update`; связи не отменяют границы.
4. В отчёте должны остаться как точные group assignments, так и ошибки границ, не только суммарная F1.
5. Если shadow ошибочно объединяет события другой сессии/Entity или после временной границы — это BLOCKER для его архитектурного использования, даже если средний F1 высок.
6. Даже при PASS E1 нельзя менять production MemoryProcessor: потребуется расширенный корпус (шум, русский/английский язык, длинная история, поздняя доставка, компакция, неверные refs), плюс shadow-сравнение в долговечном runtime и решение о миграции.
7. CI Python 3.12/3.13/3.14 должен проходить профильные тесты, весь pytest, docs check; лаборатория сохраняет JSON-отчёт как artifact.

## 4. Исполняемые проверки

```bash
python -m pytest -q tests/test_memory_shadow_encoding.py
python -m pytest -q
bash scripts/check.sh

out="$(mktemp -d -t anima-shadow-e1-XXXXXX)"
python -m labs.exp009.memory_encoding_shadow --report-dir "$out"
cat "$out/memory_encoding_shadow.json"
```

**Решение после E1:** только если сравнение с legacy воспроизводимо и анализ ошибок полезен, переходить к расширенному E2 corpus и/или структурной ассоциации по подтверждённым ссылкам на Entity. Штатные Memories до этого остаются нетронутыми.
