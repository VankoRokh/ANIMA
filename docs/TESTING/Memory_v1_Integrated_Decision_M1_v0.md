# ANIMA v0.1 Integrated — M1 Core-owned Decision / Memory Advisory (headless)

**Status:** CI VERIFIED on GitHub Linux x86-64 / Python 3.12–3.14; physical owner's laptop M1 gate OPEN; not production integration or Godot VAL.  
**Branch:** `work/anima-v01-integrated-m1` from M0 frozen baseline `9df779d14f03ff6d0bd514ecf880547621063678`.  
**Execution platform for today's acceptance:** notebook Linux x86-64; GitHub Linux x86-64 compatibility matrix. **Pi postponed** by explicit owner decision.

## Problem / scope

M0 proved Core → Memory → Retrieval → Context → FAST on persistent data, but not its coexistence with a Core-owned, independently verified world action. M0's test query was persisted *before* FAST retrieval, so the same current query could be represented as a Memory item during its own read.

M1 tests the **smallest safe combined system** without changing production `anima/` code:
- Existing Runtime persists historical user reports, Event Retrieval indexes them and provenance resolves them.
- Build one **historical ContextBundle before processing the current request**; then persist the request via Runtime and send its real Event ID plus the frozen historical context through the existing `FastCognition`. This snapshot bridge is *test-only*: it prevents this request from becoming its own prior testimony, but does not claim to be a general production solution for concurrent writes.
- FAST receives bounded informational **advisory context only**. It cannot make or bind Goals, write Knowledge, modify Core Belief, or authorize Tool actions. A user report is not a registered sensor reading.
- Only the explicit test operator creates/binds a typed Core Goal. Existing Core P3-A/P3-B chooses the permitted door action using a newly admitted sensor observation, runs the narrow sandbox handler if needed, verifies through independent readback, and durably records proof.
- Existing `VirtualDoorWorld` provides an isolated **headless test fixture**, not the external Godot Virtual ANIMA Lab. No actual remote world, LLM or sensor hardware is exercised.

## Frozen acceptance cases

| Case | Historical user report | True door state | Expected Core result |
| --- | --- | --- | --- |
| A | "door closed" | open | One authorized close effect + independent VERIFIED_SUCCESS |
| B | "door open" | closed | NO_EFFECT_REQUIRED, zero effects + independent VERIFIED_SUCCESS |
| C | "door closed" | open + first sensor read raises | No effect while sensor unavailable; Goal remains active. When restored, one effect and VERIFIED_SUCCESS |

For each scenario: operator-unbound Goal must be deferred and cause zero effects; querying memory alone cannot create a Goal or an action. The historical FAST snapshot must contain the real historical source memory but **not** the current query Event ID, even if Runtime later stores that query. Source links remain verifiable through the derived Event Retrieval index; no Knowledge is auto-confirmed. After action, reopen Core in **a second Python interpreter** and verify retained Goal, completed Task, proof associated with registered sensor-source Event, unchanged effect ledger on replay, same historical source Event IDs and complete index after explicit sync.

## Strict boundaries

1. Never read `VirtualDoorWorld.current()` into Core's typed Belief. It is a *test operator oracle*, only used for post-run assertions.
2. Memory content is **never** converted into `CoreIngress.admit` world observations or SourceRegistration. No `source="user"` authority.
3. If `sense()` fails before effect, no action is admitted. Never replace failed sensor evidence with memory.
4. An existing goal is always explicitly operator-created and bound to the frozen `world.property_equals` criterion. FAST does not participate in this step.
5. Do not change `anima/`, Core authority, Memory schema, official Stage statuses, real data, or Git history. No SLEEP, E4 L2, new sensors/embeddings.
6. Pass is **functional proof of safe coexistence and integration sequencing**, not autonomous memory-informed planning, no automatic Goal formation, no Godot adapter validation, no true SIGKILL in this M1 test and no proof that M1 is ready for production routing.

**Artifacts:** `scripts/run_memory_v1_integrated_decision_gate.py` (three isolated cases and two-process restart), `tests/test_memory_v1_integrated_decision_gate.py`, full Python 3.12–3.14 CI regression plus laptop operator report.

## Next gate

After M1 laptop PASS: define a *reviewable read-only cognition/decision interface* if actual memory-conditioned planning is needed; forbid treating Memory as Belief. Then connect the same admitted Core behavior to the existing external Godot VAL adapter and test real recovery. Do not call M1 a full artificial personality.

## Измеренные результаты CI — 2026-11-13

- **Исполняемый snapshot:** `d7593c3ec4c33535cd8eaac19b2945a4a26c477f` (документация с результатами добавлена позднее). [GitHub Actions #43420302372](https://github.com/VankoRokh/ANIMA/actions/runs/43420302372) — **SUCCESS** на GitHub-hosted Linux x86-64.
- **M0+M1 targeted:** **9/9 PASS** на Python 3.12, 3.13, 3.14.
- **Полная регрессия:** **1662/1662 PASS** на каждой из Python 3.12, 3.13, 3.14.
- **M1 runner:** `M1_INTEGRATED_DECISION_PASS` на каждой версии. Содержит три обязательных сценария и повторное открытие тех же хранилищ в отдельных Python-процессах.
- **Случай A:** Memory утверждает `closed`, реальное состояние `open`; ровно **1** эффект закрытия, `VERIFIED_SUCCESS`.
- **Случай B:** Memory утверждает `open`, реальное состояние `closed`; ровно **0** эффектов, `NO_EFFECT_REQUIRED`, Goal verified.
- **Случай C:** сначала отказ зарегистрированного sensor `sense()`, **0** эффектов при сбое; после восстановления сенсора ровно **1** эффект и independent Goal proof.
- **Граница:** `unbound Goal` без действия; никаких автоматических Knowledge, FAST без прав Goal/Task/Tool; отсутствие нынешнего вопроса в historical snapshot перед новым `Runtime.user_input`; replay использует `RECOVERED_VERIFIED_SUCCESS` и не повторяет эффект.
- **Открытые проверки:** реальный ноутбук владельца (Python 3.14.4), физический `SIGKILL` на объединённом маршруте, внешняя Godot VAL, отсутствие самопривязки в полноценном production flow, реальная способность памяти влиять на планирование, Pi (отложен). Ни один из них не подразумевается CI PASS.

### Зафиксированная поправка теста

Первый CI-прогон #43420237814 обнаружил **ошибочное ожидание тестового runner**: при повторном вызове после crash-free restart Core возвращал корректный `RECOVERED_VERIFIED_SUCCESS`, а тест ошибочно требовал `VERIFIED_SUCCESS`. Исправлено только ожидаемое состояние теста в `d7593c3`; `anima/core/door_execution.py` **не менялся**, дубли эффектов не обнаружены. На исправленном snapshot матрица полностью зелёная.

### На ноутбуке

Из отдельного checkout или worktree этой M1-ветки, из корня проекта:

```bash
python --version
python -m scripts.run_memory_v1_integrated_decision_gate --report /tmp/anima-m1-PC.json
```

Если файл отчёта уже существует, указать новое имя: скрипт не перезаписывает результаты. Он создаёт только временные синтетические данные и изолированную headless-world SQLite-фикстуру. Это **не** запуск Godot или Raspberry Pi. Заявлять M1 laptop PASS только по присланному фактическому JSON, не по GitHub CI.
