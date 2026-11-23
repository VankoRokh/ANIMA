# ANIMA v0.2 — E2.2: durable capture и происхождение Raw наблюдений

**Статус:** **`Validated Lab / E2.2 PASS_LAB_RAW_POINTER`**, полный снимок сохраняется в sidecar, Core получает только адресуемый digest event. [Приёмка и ограничения](e2-2-acceptance-report-v02.md).  
**Проверенный кодовый snapshot:** `0bd1a6b4de8c40a66b5722926996a4da02601ae0`; [CI 45175700030](https://github.com/VankoRokh/ANIMA/actions/runs/45175700030), 4/4 SUCCESS.  
**Исходная проверенная база:** `work/v02-e21-core-owned-world-gateway`, `20e0007d634f284203eac2becb7e4883eb109d2a`; `PASS_LAB_APP_BOUNDARY`.  
**Рабочая ветка:** `work/v02-e22-raw-provenance-outbox`. Без изменений `anima/` и опубликованного `v0.2.0-rc.1`.  
**Не E2-full:** нет автономного исполнения, новой цели, FAST, самостоятельного Learning или доказанной безопасности против same-UID malicious code.

## 1. Зачем нужен этот этап

В E2.1 `CoreBoundObservationGateway._pin()` фиксировал `sample_seq`, `revision` и `tick` **до** сохранения полного наблюдения. Обрыв после commit курсора мог навсегда лишить ANIMA исходного сенсорного снимка.

E2.2 решает именно эту проблему: при opt-in `capture_raw=True` запись канонического `WorldObservation` и продвижение курсора выполняются **в одной SQLite-транзакции** `e21_world_binding.db`. Затем отдельный доверенный сервис передаёт ссылку на снимок в **существующий** `CoreIngress` и штатный `CoreEventDispatcher`, не создавая второго обработчика Belief/Goal.

## 2. Хранение и доказательство происхождения

| Уровень | Содержимое | Что доказывает |
| --- | --- | --- |
| `e22_raw_capture` в SQLite gateway | **Полный канонический JSON** `WorldObservation`, SHA-256, `world_instance_id/epoch/sample_id/sample_seq/revision/tick`, nullable `event_id` | Обязательная локальная Raw-копия до возврата наблюдения, восстановление pending после аварии. Хеш проверяет целостность байт, **не** идентичность внешнего недоверенного процесса |
| Существующий `CoreIngress` | Типизированный `core.event/0.1`, kind `state.property`, subject `lab.actor.anima`, predicate `snapshot_digest`, value `{type:string,value:<sha256>}`, `source_revision=sample_seq` | Неподменяемый Core event ID и Registered Source/Producer для **ссылки на Raw-снимок**. Core не хранит весь сенсорный JSON в этом событии |
| Существующий `CoreEventDispatcher` и `EventLog` | Канонический Core reference event и обычный `world.observation` legacy audit/projection | Идемпотентная доставка в старый Raw/EventLog и историю событий; не создаёт Knowledge или полномочия Goal |

**Строгое разграничение:** это **двухкомпонентное доказательство**: полные исходные Raw-байты в sidecar SQLite и Core event с адресуемым hash/ID. Нельзя утверждать, что EventLog самодостаточно содержит полный `WorldObservation`, либо восстановить полный снимок, если sidecar удалён. Для долговременного Core-native хранения всего Raw, независимого бэкапа и полноценных проекций каждого reading понадобятся отдельные контракты. `snapshot_digest` — указатель на источник, **не** подтверждённое семантическое знание о мире.

## 3. Последовательность, recovery и полномочия

```text
guarded Godot.observe / observer bearer
    ↓
WorldObservation full schema + source/epoch/clock checks
    ↓
SQLite BEGIN IMMEDIATE:
  e22_raw_capture[canonical bytes, sha256] + e21_world_binding[cursor]
  COMMIT                   ← единственная точка «Raw capture complete»
    ↓
CoreIngress.admit(core.event state.property snapshot_digest, occurrence_id=e22:<sample_id>)
  native Core event + outbox + Belief pointer atomically
    ↓
captured Raw ←→ Core event_id link
    ↓
CoreEventDispatcher.drain → EventLog/Memory processing → native dispatch receipt
    ↓
Only now observation and event_id returned to trusted caller
```

`E22RawCaptureService.recover()` может работать после перезапуска **только Core**, при живом Godot. Он перечитывает **полный Raw JSON** из capture journal и проверяет каноничность, SHA-256, sample identity, pinned Core/world/epoch, registered `SourceRegistration`, точный Core event payload и projection outcome. `CoreIngress.admit()` возвращает `ALREADY_SEEN` для уже принятого идентичного события, независимо от аварии до sidecar receipt. Затем штатный dispatcher повторяет только недоставленную запись.

`observe_and_record()` перед новым снимком вызывает recovery, после capture вызывает его повторно и **не возвращает наблюдение**, пока у Core EventLog нет `forwarded` receipt. Публичный `capture_snapshot(sample_id)` также **запрещает** читать pending или linked-but-undispatched Raw: он сверяет Core event ID, digest и наличие `forwarded` receipt. Внутренний восстановитель может читать pending только для передачи в Core. При невозможности завершить — fail-closed, pending остаётся в SQLite.

Ограничение одного batch восстановления — 64 pending. Повторный запуск обработки возможен; сложное конкурентное чтение, мультихостовое распределение, как и гарантированная fsync power-loss на всех драйверах — вне проверенного профиля.

## 4. Негативные испытания

- Crash **после атомарного Raw+cursor commit**, до `CoreIngress`: восстановление без нового вызова Godot.
- Crash **после CoreIngress commit**, до ссылки в Raw capture: тот же `event_id`, никакой повторной истории.
- Crash **после sidecar event_id link**, до dispatcher: штатный Core outbox доставляет событие без второго ingest.
- Подмена байтов в pending snapshot, плохой SHA/metadata, чужой `source_ref`, world/epoch mismatch: отклонение без ложного history.
- Core reopen при живом Godot, одно и несколько наблюдений, совпадающие timestamps с различными `sample_seq`, внешнее изменение `revision`: сохранённая последовательность.
- Reset/restart мира, ненадлежащая регистрация Core source и попытка использовать legacy gateway без `capture_raw`: fail-closed.
- Отсутствие `WorldAction`, operator/FAST/Goal и side effects. E2.1/E1-min/P5/P6/M2 regression без изменений старых режимов.

## 5. Команды и правила gate

```bash
# Из изолированной копии рабочей ветки, с официальным Godot 4.7.2
GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
bash scripts/run_e22_live_gate.sh "$GODOT_BIN"
```

CI `.github/workflows/anima-e22-raw-provenance-gate.yml` запускает Python 3.12/3.13/3.14, полную регрессию, старые E1.2–E2.1/P5/P6/M2 и E2.2 live в изолированных временных папках. Полные raw logs сохраняются как evidence.

Вердикт может быть **`PASS_LAB_RAW_POINTER`** только после подтверждения всех ключевых crash/negative сценариев. Даже он не означает самостоятельный непрерывный lifecycle, самодостаточный Core Raw EventLog либо долговременную биографию ANIMA.

## 6. Следующая проверяемая граница

Перед E2.3/E2.4 требуется определить, какой набор typed properties будет извлекаться из полной Raw-среды в Context; их значения должны иметь ссылку на исходные sample/sha256/event, а не становиться Knowledge только из-за доставки в Core. Перед E4/full-recovery — backup и восстановление обоих хранилищ sidecar + Core в одной consistency boundary либо миграция полного Raw в единственный canonical journal.

Принцип не меняется: **одно право решения о действиях — Stage6 Core; FAST только предлагает**.
