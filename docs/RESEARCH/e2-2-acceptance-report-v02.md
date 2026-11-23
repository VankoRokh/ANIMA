# ANIMA v0.2 — E2.2: итоговая приёмка Raw capture и Provenance

**Вердикт:** **`PASS_LAB_RAW_POINTER`** — проверены атомарный захват полного WorldObservation и идемпотентная передача адресуемого доказательства в существующий Core. **Не утверждается**, что Core EventLog самостоятельно содержит полную историю сенсоров или что готов весь E2.  
**Дата:** 23 ноября 2026 года.  
**Проверенная кодовая точка:** `0bd1a6b4de8c40a66b5722926996a4da02601ae0`, ветка `work/v02-e22-raw-provenance-outbox`.  
**Первичные доказательства:** [GitHub Actions #45175700030](https://github.com/VankoRokh/ANIMA/actions/runs/45175700030) — **4/4 SUCCESS**, evidence artifact `anima-e22-raw-provenance-evidence`, 82 KB raw reports/logs.  
**База:** `E2.1 / PASS_LAB_APP_BOUNDARY`, `20e0007d634f284203eac2becb7e4883eb109d2a`.  
**Контракт и ограничения:** [E2.2](e2-raw-provenance-v02.md).

## 1. Что действительно добавлено

1. В **опциональном** `capture_raw=True` режиме gateway сохраняет **полный оригинальный `WorldObservation`**, его `sample_id`, SHA-256 и мир/эпоху/часы в `e22_raw_capture` **атомарно с E2.1 monotonic cursor**. Нельзя commit курсор без полного снимка. Без opt-in прежний E2.1 остаётся read-only.
2. `E22RawCaptureService` использует **существующий** `CoreAssembly → CoreIngress → CoreEventDispatcher → EventLog/EventProcessing`. Новый Core pointer event имеет kind `state.property`, единственный разрешённый subject `lab.actor.anima` и predicate `snapshot_digest`; значение — SHA-256 канонического Raw JSON, а `occurrence_id=e22:<sample_id>`. Core повторно принимает только тот же payload и возвращает исходный `event_id` (`ALREADY_SEEN`).
3. Сервис не экспонирует ещё не завершившую Core dispatch запись как готовое наблюдение. Восстановление pending производится перед новой попыткой наблюдения и **без второго вызова Godot**.
4. Для восстановления проверяются: идентификатор **Core**, `SourceRegistration`/Producer, процесс/эпоха мира, sample/revision/tick, исходные JSON-байты и SHA-256, Core pointer payload и linkage. Изменение или подмена приводят к отказу.
5. Stage6 остаётся единственным предусмотренным владельцем решений. В E2.2 нет новой возможности `act`, Goals/Task, FAST/DEEP, semantic Knowledge или автономного поведения.

## 2. Матрица результатов

| Gate | Первичное evidence / итог |
| --- | --- |
| Python 3.12.16 | **2392 pytest PASS** |
| Python 3.13.18 | **2392 pytest PASS** |
| Python 3.14.10 | **2392 pytest PASS** |
| Godot 4.7.2 job / Python regression | **2392 pytest PASS** |
| Новые unit negative/crash tests E2.2 | **12 PASS** на каждой Python и Godot job |
| Core/EventLog crash boundary | после capture commit, после CoreIngress commit, после sidecar link и после legacy EventLog append — **RECOVERED без дубля** |
| Подмена pending Raw | плохой SHA/JSON, Core instance/source/producer или чужой `event_id` — **FAIL-CLOSED** |
| Core reopen, тот же Godot | **ACCEPTED**, тот же persistent sample cursor |
| World reset, новый epoch | **REJECTED**, отсутствуют ложные Core/Raw события |
| Live Godot на seed 7 и 8 | **4 полных снимка**, **4 Core pointer event**, **4 legacy EventLog event** на каждый seed; model used = false, world effects issued = 0 |
| Полная старая матрица | E1.2–E1.4, independent E1-min, E2.1, P5/P6/P5-C, M2 — **PASS** |
| Documentation до этого отчёта | **192 страницы, 1358 локальных ссылок PASS** |
| **Итог** | **`E2_2_LIVE_GATE_PASS` / 4 из 4 CI jobs SUCCESS** |

Исходные логи запуска, unit тестов, предыдущих gates и два набора временных Core/Raw SQLite доступны в Actions artifact; запуск не использовал пользовательскую память и не менял опубликованный `v0.2.0-rc.1`.

## 3. Отрицательные результаты и история разработки

Ранний CI на промежуточном коммите выявил **только ошибку E2.2 test helper**: legacy EventLog имеет ключ `id`, а тест ошибочно читал `event_id`. Исправлено без изменения исходного Core. При дальнейшем ревью расширены проверки Core identity/source и уже записанных `event_id`, добавлен отдельный тест аварии **после legacy EventLog append**. Итоговый [run #45175700030](https://github.com/VankoRokh/ANIMA/actions/runs/45175700030) подтверждает полную регрессию **после этих исправлений**.

Фальсифицировать `PASS` на раннем неуспешном run, объединять файлы в release или объявлять весь E2 готовым нельзя.

## 4. Оставшиеся риски

**E22-R1 — два хранилища, OPEN/HIGH.** Полный Raw JSON находится в `e21_world_binding.db/e22_raw_capture`, а Core хранит только идентификатор + hash. Потеря sidecar делает Core reference недостаточным для восстановления оригинальной сенсорной истории. Проверок согласованного восстановления резервной копии **обоих** хранилищ и `fsync`-гарантий при отключении питания не было. Для долговременного экземпляра необходима единая consistency boundary или атомарный backup/restore.

**E22-R2 — пока нет полной семантической проекции readings, OPEN.** Core Belief получает только pointer `snapshot_digest`, не всю структуру readings/objects. Нельзя считать этот digest знанием о положении предметов, отношении ownership, состоянии препятствий или мотивами ANIMA. Перед Context/FAST-candidates нужно спроектировать строго типизированное derivation с provenance, uncertainty и SourceRevision, без ошибочных Knowledge assertions.

**E22-R3 — локальная аутентификация и целостность, OPEN/HIGH.** SHA-256 обнаруживает случайную или несанкционированную **без пересчёта** правку Raw. Он не аутентифицирует содержимое при полном доступе к той же SQLite и не защищает bearer keys/host от same-UID malicious process. Этот долг принят из E2.1; нельзя подключать недоверенную модель к raw TCP или environment.

**E22-R4 — восстановление мира, OPEN.** Доказаны повторные Core-open и указанные crash cuts; ledger Godot по-прежнему volatile, identity/epoch reset обязан блокироваться, межпроцессный Godot recovery относится к E4.

**E22-R5 — масштаб и независимость, OPEN.** Проверены отдельные снимки и bounded recovery по 64 pending; массовые потоки, гонки параллельных ingestion workers, оптимизация больших snapshots и независимый security audit не пройдены. Испытания дают ограниченный лабораторный PASS, а не эксплуатационную готовность.

## 5. Решение и дальнейшая работа

**Принять E2.2 только как `PASS_LAB_RAW_POINTER`.** В исследовательской ветке E2.2 уже можно надёжно сохранять доказательства наблюдений, восстанавливать их после отдельных прерываний и проверять origin внутри одного контролируемого Core. Достоверность source по-прежнему опирается на guarded-host и trusted composition.

**Следующий разумный шаг:** отдельная E2.2b/ E2.3-подготовка по typed readings→Core Belief/Context, прежде чем позволять FAST делать кандидаты. Там же определить, должно ли полное `WorldObservation` переехать в единственный canonical Raw EventLog или останется в адресуемом sidecar до E4 с обязательной групповой backup-consistency моделью. Решение требует архитектурного ревью, не автоматического включения новой функции.

## 6. Воспроизведение

```bash
GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
bash scripts/run_e22_live_gate.sh "$GODOT_BIN"
```

Аудиторское evidence: [CI и raw logs](https://github.com/VankoRokh/ANIMA/actions/runs/45175700030). Любое локальное воспроизведение выполнять на временном Core data-dir, не на данных основного экземпляра ANIMA.
