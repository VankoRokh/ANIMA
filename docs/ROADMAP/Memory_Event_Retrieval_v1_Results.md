# ANIMA — Event Retrieval v1: проверка и C3 PC-baseline

**Дата:** 2026-11-11.  
**Статус:** **PASS — функциональный Event Retrieval v1 на проверенном SHA; PC C3 baseline получен.** Не означает финальной интеграции в ContextBuilder или проверенного Raspberry Pi/power-loss workload.  
**Ветка:** `experiment/core-memory-information-baseline`.  
**Проверенный SHA:** `f27a6428e6b5b6cc26585d299def9305bd6a5e4d`.  
**CI:** [run 43091261376](https://github.com/VankoRokh/ANIMA/actions/runs/43091261376), Ubuntu Linux, Python 3.12.16 / 3.13.18 / 3.14.10.  
**C3 raw:** [artifact 13889016802](https://github.com/VankoRokh/ANIMA/actions/runs/43091261376/artifacts/13889016802), Python 3.14.10, SQLite 3.46.1.  
**Контракт:** [Event Retrieval v1 Brief](Memory_Event_Retrieval_v1_Brief.md).

## 1. Реализованный срез

- `anima/memory/event_retrieval.py`: независимый SQLite FTS5 `event_index.db` поверх legacy `events.jsonl`, без изменения исходных Events; bounded `sync`, commit индекса вместе с курсором, явная incomplete/source_changed семантика, точечный `get(Event ID)`, фильтруемый `search`, `events_for_memory`, `rebuild`.
- `anima/core/assembly.py`: новый сервис подключается через `enable_event_retrieval=True`; по умолчанию `None`. Runtime, FAST, DEEP, policy/Knowledge не маршрутизированы через него автоматически.
- `anima/memory/provenance.py`: `event_retrieval` — необязательный indexed backend в `ProvenanceResolver`. Для существующих Memory/Knowledge provenance views нужен только exact source lookup вместо полного JSONL scan; legacy fallback сохранён.
- `tests/test_event_retrieval.py`: в том числе restart, incremental sync, torn tail, rollback, altered/rotated source, duplicate Event ID, injection, missing source и отказ от полного scan при opt-in provenance.
- `labs/exp009/event_retrieval_c3.py`: отдельный воспроизводимый C3-профиль на коротких synthetic `conversation.user` Events. Никакого write-back Knowledge.

## 2. Регрессия

| Проверка | Python 3.12 | Python 3.13 | Python 3.14 |
| --- | ---: | ---: | ---: |
| Профильный pytest | **79 passed** | **79 passed** | **79 passed** |
| Полный pytest | **1506 passed** | **1506 passed** | **1506 passed** |
| `bash scripts/check.sh` | PASS | PASS | PASS |
| `build_core` import | PASS | PASS | PASS |
| Лабораторный EXP-009 A/B/C/D | PASS | PASS | PASS |

Результаты подтверждены логами GitHub Actions данного SHA, а не только отчётом владельца. Correctness PASS **не** является доказательством физической crash durability на реальном SSD.

## 3. C3 PC metrics

Изолированный сценарий: синтетические короткие сообщения через `EventLog.write`, затем производная SQLite FTS5 индексация партиями до 500 событий, 100 точечных `get` и 100 FTS запросов по уникальным маркерам, перезапуск объекта индекса, добавление ещё одного Event. Параллельная Cognitive нагрузка отсутствует.

| Показатель | 10 000 Events | 100 000 Events |
| --- | ---: | ---: |
| EventLog append, с | 0,9833 | 9,3399 |
| Первичная индексация, с | 0,4391 | 4,6043 |
| Количество партий индексации | 20 | 200 |
| `get(Event ID)` p50, мс | 0,5846 | 1,8688 |
| `get(Event ID)` p95, мс | **0,8750** | **2,0641** |
| `get(Event ID)` p99, мс | 0,9394 | 2,2524 |
| FTS по уникальному маркеру p50, мс | 0,7400 | 2,0638 |
| FTS по уникальному маркеру p95, мс | **1,0846** | **2,2652** |
| FTS по уникальному маркеру p99, мс | 1,2189 | 2,4705 |
| Инкрементальная индексация одного нового Event, мс | 1,9194 | 3,5159 |
| EventLog JSONL, байт | 2 631 739 | 26 315 239 |
| SQLite index, байт | 4 435 968 | 44 130 304 |
| Пиковая RSS процесса, KiB | 27 964 | 63 216 |

**Интерпретация:** при росте 10× объёма время первичной индексации выросло ~10,5×. Размер SQLite около 1,68× размера JSONL в данном corpus. Повторный индексированный read остаётся миллисекундным, однако растёт и его p95; claim о `O(1)` времени обращения **не делается** — используется индексный lookup с ограниченным чтением исходных байтов.

**RSS — весь benchmark-процесс**, включая генератор, EventLog-кэш ID и хеширование исходного файла, а не чистое потребление компонента EventRetrieval. Это не Pi 5 и не ресурсный лимит для всех модулей ANIMA.

## 4. Принятый результат и открытые границы

**Принято:**

1. SQLite FTS5 + raw Event ID/offset/hash — первая production проекция исходной legacy истории.
2. Права владения данными остались за первичным EventLog и, для типизированных Core observations, за `core_state.db`; индекс не имеет права назначать Observation/Knowledge authority.
3. Поиск по Event отделён от текущего Memory/Knowledge retrieval; связь источников вызывается по необходимости, а не форсирует graph hop в каждый ответ.
4. `status=partial` и `status=source_changed` не маскируются под достоверный `no_match`; full-index audit/rebuild является отдельной операцией.
5. Optional `ProvenanceResolver` обслуживает ссылочную идентичность через индекс без повторного обхода всех JSONL Events.

**Не доказано и не объявляется сделанным:**

- Автоматическая синхронизация индекса при каждом цикле Runtime (сейчас `sync` вызывается явно).
- Полная индексация непосредственно авторитетного `core_state.db`; legacy `world.observation` — только проекция Core outbox.
- Масштабируемость всего цикла Event→Memory→Context→Cognition→SLEEP и нагрузка на Raspberry Pi 5.
- Физически аварийная потеря питания, multi-process запись в сам `EventLog`, hostile tampering целого журнала или семантический парафразный поиск.
- Автоматическая публикация Knowledge, SLEEP-derived outputs или самостоятельное формирование эпизодов.

**Вердикт:** **Event Retrieval v1 functional gate — VERIFIED on CI PC**; общий Memory v1.0 и Pi C3 gate остаются OPEN. Следующий рабочий шаг по [roadmap](Memory_Architecture_v1_Roadmap.md) — **Шаг 3: Memory Encoding**: shadow-ассоциация независимо от сжатого `Memory.content`, с проверкой сохранения границ эпизодов и прямых source links.
