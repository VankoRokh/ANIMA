# ANIMA — Memory v1.0 / Integrated Read Path M0 (acceptance contract)

**Status:** MEASURED M0 INTEGRATED READ-PATH PASS (GitHub Linux x86-64); PC/PI HARDWARE GATE OPEN; NOT FULL ANIMA v0.1.
**Research branch:** `experiment/core-memory-information-baseline`.
**Baseline:** `89b536bdacdf0d41223314cb3f110fb303fbc65d`.
**Goal:** begin **ANIMA v0.1 Integrated** using existing Core and Memory interfaces; stop adding E4 research features. This is **M0 read-side acceptance**, not a new Stage, Stage 7 closure or full autonomous agent.

## Problem solved

The current components exist separately (Core Runtime, MemoryProcessor/MemoryStore, Event Retrieval FTS5, RetrievalEngine, ContextBuilder and FAST), but a *single reproducible instance* using all of them and surviving a process restart is not yet independently demonstrated. An isolated alias lab PASS does not prove working retrieval in Core.

## Minimum execution path

```text
CoreAssembly / Runtime.user_input
    -> immutable EventLog (legacy JSONL)
    -> EventProcessingCoordinator -> MemoryStore source links
    -> opt-in EventRetrieval.sync (SQLite FTS5, derived)
    -> exact raw Event retrieval + ProvenanceResolver (source IDs)
    -> RetrievalEngine + bounded ContextBuilder
    -> FastCognition with a deterministic, zero-LLM mock backend
```

Run `seed` and `verify` in **different Python processes** sharing an isolated temporary workdir. No external calls, no real tools or action effects. The test's second process calls `build_core` again; no fake in-memory store or manually created Memory rows. Use seeded reports with deliberately different values for one subject, so evidence is preserved even when legacy encoding merges episodes.

## Gate: required observations

1. **Write/link (A):** `Runtime.user_input` produces two real `conversation.user` source Events; both appear as source links in persisted Memory, without manually injecting a Memory row.
2. **Strict coverage (D):** after new raw Events, opt-in Event Retrieval reports `partial`; a complete-required search **must reject**, not silently claim absence. After `sync`, status is `complete`.
3. **Raw detail (C):** exact earlier numeric values from *both* conflicting reports are retrievable by Event IDs from source-verified raw bytes, irrespective of whether composed Memory text kept those values.
4. **Conflict/authority (E):** both reports remain individually addressable; neither is silently selected as `confirmed Knowledge`. A report is **not** a fact about the world and a `source="user"` label is **not** authentication.
5. **Process restart (B/G, baseline):** a new Python process reloads the same durable stores, executes normal `Runtime.wake`/recovery, re-syncs the derived index, and retrieves both original Events, without duplicating their IDs or source links. This is normal restart, **not SIGKILL**.
6. **FAST boundary:** `RetrievalEngine` and `ContextBuilder` construct a bounded `consumer=FAST` ContextBundle; a replaceable test FAST backend receives it. FAST has no production authorization and does not write Memory or Knowledge.
7. **No-match:** after complete sync, a unique absent marker has zero Event search results and empty Memory search, not a fabricated answer; on partial index, no-match cannot be inferred.
8. **Cross-platform:** script runs with standard Python on Linux x86-64 / ARM64, can write a machine-readable result with OS, architecture, Python, event/source counts, selected Memory IDs, budgets, and gate verdict. Identical fixture and code on PC and Pi, no real-world user data.

**Do not** automatically enable Event Retrieval in production, modify `anima/`, alter `docs/project.json`, integrate the untrusted E4 alias gate, add embeddings/LLM/sensors/SLEEP features or issue Goal/Task/Tool actions for this read-only milestone.

## Evidence and interpretation

- `scripts/run_memory_v1_integrated_read_gate.py` is the standalone opt-in repeatable runner.
- `tests/test_memory_v1_integrated_read_gate.py` proves real child-process restart and negative/fail-closed cases.
- GitHub CI Python 3.12/3.13/3.14: all tests plus the new gate runner must PASS; a CI PASS is not Raspberry Pi validation.
- User's local PC/Pi tests: run the same frozen command and preserve both JSON reports with platform metadata. Distinct hardware/OS/storage/Python configurations are reported, not conflated.
- This M0 gate is **insufficient** for v0.1 Integrated overall: trusted Core ingress, typed decisions, independent verification, true power-loss, p95 scaling, and Stage 7 read-only Claim/Evidence policy must be admitted separately. Next M1 integrates only a *proven* safe Core-owned decision route and VAL adapter with the existing boundary.

**Stop rule:** if the existing interfaces can deliver the M0 path without a production change, do not invent another intermediary service. If there is a blocker, describe it explicitly and patch only that blocker in a separate reviewed step.

## Фактическая проверка — 2026-11-13

- **Snapshot (code + indexed docs):** `582d2da33dc073158f5fa88874500fbfb4ee259e`. **CI:** [#43416994527](https://github.com/VankoRokh/ANIMA/actions/runs/43416994527), завершён **SUCCESS** в матрице Python 3.12 / 3.13 / 3.14.
- **Регрессия:** 98/98 targeted и **1657/1657 full tests PASS** на каждой версии. Четыре новых M0 теста включены в полный набор, а не в отдельный targeted набор из 98.
- **Реальная сборка:** исходные отчёты попали в `Runtime.user_input` → `EventLog` → `EventProcessingCoordinator` → `MemoryStore`; тест не создавал `Memory` вручную и не подменял хранилище.
- **Межпроцессное восстановление:** `seed` и `verify` запускались как отдельные child OS-процессы, на общем ephemeral каталоге. Все исходные Event IDs и ссылки Memory на источники сохранились. Повтор `recover()` не размножил Memory и Event references.
- **Прямые исходники:** строгое чтение через `EventRetrieval` выявило обе старые точные величины (82 C и 69 C) с собственными исходными ID; отсутствие маркера проверено только после complete sync; до индексации partial strict search заблокирован.
- **Защита от подмены:** отдельный отрицательный тест поменял байты исходного `events.jsonl` при прежней длине. Индекс сообщил `source_changed`, а search/get отказали в прежнем доверенном результате.
- **Context/FAST:** существующие `RetrievalEngine`, `ContextBuilder`, `ProvenanceResolver` передали ограниченный FAST-контекст заменяемому mock backend. Он не вызывал LLM, Goal/Task, Tool, не выполнял действий и не подтверждал Knowledge. На новом наборе автоматически созданных Knowledge — **0**.
- **Смысл PASS:** проверена связность **читающего маршрута**, не корректность трактовки противоречий моделью, не собственные решения Core, не production-наделение полномочиями, не реальный SIGKILL этого M0 пути и не поведение Raspberry Pi.

## Воспроизведение на ноутбуке и Raspberry Pi 5

На **одном и том же коммите** проекта с установленным Python/зависимостями:

```bash
python -m scripts.run_memory_v1_integrated_read_gate --report /tmp/anima-m0-PC.json
# На Raspberry Pi (отдельный checkout того же коммита):
python -m scripts.run_memory_v1_integrated_read_gate --report /tmp/anima-m0-Pi.json
```

Вывод содержит `status=M0_INTEGRATED_READ_PASS` и сведения о версии Python, ОС, архитектуре, сохранённых источниках и границах FAST. Используются только временные синтетические данные. Файл отчёта намеренно не перезаписывается; перед повторным запуском указывайте новый путь. Этот эксперимент **не запускает** ядро в непрерывном режиме.

## Локальный запуск M0 на ноутбуке (результат, сообщённый владельцем)

**Дата сообщения:** 2026-11-13; исполняемый snapshot `9df779d`. Результат получен пользователем локально и передан полным JSON в разговоре; он **не** является независимо снятым CI-логом физического ноутбука.

- **Вердикт:** `M0_INTEGRATED_READ_PASS`.
- **Платформа:** Python `3.14.4`, Linux `7.0.0-42-generic`, `x86_64`.
- **Данные:** 6 raw Events, 2 Memory, 2 исходных `conversation.user` Event; оба исходных сообщения ссылаются на одну объединённую Memory. Это допускается в M0, так как проверяется сохранность исходных Events, а не корректность семантической группировки.
- **FAST:** 2 выбранных Memory и 233 символа контекста. Второй элемент не обязательно является независимым ранним свидетельством: в исходном M0 текущий вопрос сохранялся до FAST retrieval.
- **Восстановление:** `independent_process_reopen=true`; `index_status=complete`; `absent_marker_results=0`.
- **Границы:** `knowledge_count=0`, `actions_executed=false`, `llm_used=false`, `real_sigkill_tested=false`.
- **Аппаратный охват:** только ноутбук; по решению владельца Raspberry Pi отложен. Отсутствие Pi gate **не блокирует** следующий локальный интеграционный шаг M1, но не доказывает переносимость.

**Следующее решение:** M0 ноутбука принят; теперь **M1 — Memory advisory + Core-owned typed decision**, с отдельной headless virtual-door фикстурой. Не выдавать результат M1 за подтверждение Godot VAL или полного ANIMA v0.1 Integrated. Официальный Stage status / `docs/project.json` не изменяются.
