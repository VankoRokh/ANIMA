# ANIMA v0.2 — E2.5b Visual Decision Lab: первый замкнутый цикл решений

**Статус:** `PASS_LAB_DETERMINISTIC_CLOSED_LOOP` — **исследовательская лаборатория**, не новый релиз Core, не настоящий FAST, не нативный Stage6 Admission.  
**Дата фиксации:** 24 ноября 2026.  
**Проверенный кодовый snapshot:** `ed97ddb9393b702988fc48be1293a8df7b2a4c7e`, ветка `work/v02-visual-decision-runner`.  
**Первичные доказательства:** [CI #45266885580](https://github.com/VankoRokh/ANIMA/actions/runs/45266885580) — **4/4 SUCCESS**, Python 3.12/3.13/3.14 **2486 PASS** на каждой версии, официальный Godot 4.7.2, seed 7/8, полный прежний E1.2–E2.5a live gate.  
**Архитектурная база:** [E2.4a](e2-4-working-memory-acceptance-v02.md), [E2.4b](e2-4b-relative-pose-acceptance-v02.md), [E2.5a](e2-5a-cognitive-initiative-acceptance-v02.md), [решение об инициативе FAST/DEEP](e2-cognitive-initiative-v02.md).

## 1. Цель

Не «обучить навигации в игре», а впервые собрать **непрерывный доказательный цикл**:

```text
Godot egocentric sensor 90° (no absolute x/y)
    → E24WorkingMemory: full sealed Raw + cursor / CoreIngress digest event
    → работающая детерминированная политика на текущем наблюдении
    → typed EgocentricAction proposal
    → LAB_ADMITTED (отдельный durable decision record ДО эффекта)
    → Godot executor credential выполняет world.turn / world.step
    → E24PoseTrail проверяет Godot operation_status для полного action
    → новое Core-backed Raw / verified relative movement
    → durable decision outcome ПОСЛЕ наблюдения
    → следующий цикл / bounded stop
```

Первый ограниченный критерий: **увидеть ящик непосредственно, затем выполнить один подтверждённый forward step в его направлении, если текущий сенсор показывает выравнивание**. Это не доставка ящика и не доказательство успешного достижения невидимой цели. Прогресс по сценариям Godot хранится в лабораторном следе, без подмены подтверждённого Knowledge.

## 2. Компоненты

- `labs/virtual_anima_lab/python/lifecycle/visual_runner.py`: Python-процесс запускает Godot GUI (или headless для CI), формирует один disposable `CoreAssembly` + `E24WorkingMemory` + `E24PoseTrail`. `CrateInvestigationPolicy` выбирает `world.turn(left/right)` либо `world.step(forward)` по **реальным** E2.3 показаниям и допустимым локальным воспоминаниям. В памяти присутствуют пометки `not_observed`, `last_seen_sample`; старые bearings могут использоваться только как **неподтверждённые гипотезы**, не как текущая видимость.
- `visual_decisions`: отдельная лабораторная SQLite-таблица с начальным sample ID, Core event ID, digest bounded Context, оригинальным предложением, `LAB_ADMITTED`, reason. **COMMIT до отправки `act`**. Затем при успешном readback и новом Raw **отдельный COMMIT** verified outcome. При неопределённости — `BLOCKED_UNVERIFIED`, остановка, нет слепого replay.
- `VisualControlService`: HTTP JSON на `127.0.0.1` и случайном порту, отдельный непередаваемый агенту bearer key, очередь команд, сериализованный worker и bounded run cadence. `GET /state`, `POST /step`, `/run`, `/pause`, `/memory`. UI не получает executor key и никогда не обращается к operator inspect.
- `labs/virtual_anima_lab/godot/VisualControlHUD.gd`: человек нажимает STEP, RUN, PAUSE, TOGGLE MEMORY; HUD только опрашивает телеметрию Python. Состояние цели, решения, admissibility, verified action и относительная позиция отображаются рядом с существующим операторским обзором. **Не отдавать операторские координаты в Context ANIMA.**
- `scripts/run_visual_decision_lab.sh`: один локальный запуск Godot GUI + Python/ANIMA. Данные изолированы во временном каталоге с явным путём в консоли, не в домашнем Core профиле.
- `tests/test_visual_decision_policy.py` и `visual_runner_live_gate.py`: модульная политика и настоящие HTTP STEP/RUN контракты, впервые с внешним управлением реальными действиями, выбранными на основании сенсора.

## 3. Что именно проверено

| Проверка | Результат |
| --- | --- |
| Python 3.12/3.13/3.14 | **2486 PASS** на каждой версии, включая прежние E2.3–E2.5a |
| Real Godot 4.7.2, seed 7/8 | **`E2_5B_VISUAL_DECISION_GATE_PASS`** |
| После открытия UI, до нажатия STEP | **0** новых Raw, UI polling не вызывает сенсор |
| Один STEP | ANIMA получает первый Core-backed Raw, **сама выбирает** `world.turn(right)`, action readback и новое Raw подтверждают поворот; ящик после него видим |
| RUN после STEP | Детерминированная политика выбирает `world.step(forward)` исходя из **новой видимости ящика**; квитанция и следующая запись Raw подтверждают переход; цель лабораторного сценария завершена |
| На seed | 3 Core-backed Raw, 2 самостоятельно выбранных мировых действия, 2 проверенных перехода, 2 durable decision records, автоматическая остановка |
| Неверная роль/токен | `GET /state` и `POST /step` без правильного control key отклоняются |
| Недопустимое тело API | Отклоняется; произвольный payload не становится программным API |
| Включение/выключение памяти | Не совершает эффекта; переключает исторический доступ для последующих решений |
| Статус FAST/DEEP и прав | **Явно не подключены**; `LAB_ONLY_NOT_STAGE6` |
| Старые gates E1.2–E2.5a | **PASS**, Python/Godot |
| GUI компоновка и работа кнопок на ноутбуке | **Требуется ручная визуальная проверка**. Headless CI доказал RPC и отсутствие crash, не качество расположения элементов в окне. |

**Отладочный инцидент:** первый Godot старт не прошёл из-за синтаксической ошибки в строке HUD; после исправления живой сценарий обнаружил **незафиксированные SQLite решения** (отсутствовал `COMMIT`). Исправлены обе транзакции и заново проверены на итоговом указанном SHA. Не скрывать эти отрицательные испытания при ревью: без второго исправления действительное действие могло не оставить доказанного решения.

## 4. Архитектурные ограничения и аудит

**E25B-R1 / лабораторный допуск НЕ Core Stage6 (HIGH).** `EgocentricAction` и `visual_decisions` проверяются локальной политикой `VisualDecisionSession`, затем executor key напрямую передаётся доверенному runtime. **CoreIngress** — канонический источник Raw digest и runtime continuity, но **не** CoreGoalDecision/Task/Execution для новых мировых действий. Не выдавать это за завершённую интеграцию Core Action Admission.

**E25B-R2 / нет реальной LLM (HIGH).** `CrateInvestigationPolicy` — явный детерминированный baseline. Нет `FAST` transport, self-generated goals, интроспекции или автономной мыслительной жизни. Первое подключение модели должно сравнивать `DETERMINISTIC / STUB / FAST` на одинаковых агентских данных, а не обучать скрытой карте.

**E25B-R3 / независимость Verification (HIGH).** Godot `operation_status` возвращает readback подтверждённого действия, проверенный следующими Core-backed Raw/логическими часами; это **не** отдельный физический сенсор и не полное независимое proof достижения произвольной цели. Цель в E2.5b ограничена проверенным приближающим шагом.

**E25B-R4 / lifecycle и восстанавливаемость (HIGH).** `visual_decisions` и E24 Raw находятся в sidecar, canonical Core — в другом SQLite. Нет общей power-loss/backup транзакции. После аварии между admission и outcome цикл намеренно `BLOCKED_UNVERIFIED`, **нет** безопасного restart/reconciliation текущего world instance. E4 остаётся открытым. Повторный запуск создаёт новую disposable instance, не делает произвольный replay.

**E25B-R5 / доверие OS и GUI.** Control API слушает только loopback и требует случайный token. Но same-UID компрометация ключа, инъекция input, операторская truth на экране и отсутствие реальной OS sandbox остаются. Пользовательский screenshot нельзя давать FAST как сенсорный input с включённым операторским HUD.

**E25B-R6 / ограниченность измерений.** 2 seed, простая комната, фиксированная цель, до 32 действий, нет сложности open-world. Нет эксперимента о качествах FAST, статистики generalization, долговременного «сознания» и замыкания пространственных петель.

## 5. Следующие исследования

1. **Visual acceptance на ноутбуке:** пользователь проверяет реальный Godot UI, наблюдение, STEP/RUN/PAUSE, журнал и режим memory toggle. Если окно неудобно — исправить GUI, не менять семантику Core.
2. **Core-native world-action admission**: отдельный проверяемый тип Goal/Task/Execution/Verification для действий `turn/step`, не второй собственник Core. Провести независимый аудит trust boundary и crash cuts прежде чем давать их FAST.
3. **FAST cognitive adapter:** использовать сменный `LlamaCppTransport` и строгую схему предложений; реальные model calls, отчёт о latency, token budget, invalid proposals, сравнении с baseline.
4. **Расширить сценарии:** неизвестная область, закрытый обзор, перенесённый предмет, неполная/противоречивая память, сохранение после reset/отказ при epoch drift. Измерять качество решений и полезность памяти, **не** число пройденных клеток.

**Вердикт:** `PASS_LAB_DETERMINISTIC_CLOSED_LOOP`, реализация годится для дальнейших **ограниченных** визуальных исследований. Независимый архитектурный аудит и новый release acceptance не проводились. Публичный `v0.2.0-rc.1` и пользовательские данные не изменены.

## 6. Запуск на ноутбуке

```bash
cd ~/Projects/ANIMA
git fetch origin work/v02-visual-decision-runner
git worktree add --detach ../ANIMA-visual-decisions origin/work/v02-visual-decision-runner
cd ~/Projects/ANIMA-visual-decisions
bash scripts/run_visual_decision_lab.sh

# При необходимости:
# PYTHON_BIN=~/Projects/ANIMA/.venv/bin/python bash scripts/run_visual_decision_lab.sh
# bash scripts/run_visual_decision_lab.sh --seed 8 --step-interval 2
```

Закрой другие LifecycleWorld на портах до запуска. На экране появится отдельная панель управления. **Сначала нажми STEP** и проверь, что повернувшийся зелёный агент обнаружил ящик; затем RUN для проверенного forward step; PAUSE останавливает дальнейшее планирование **после текущего атомарного лабораторного шага**. Чтобы начать новый эксперимент — закрой окно и запусти скрипт заново. Точный путь evidence будет напечатан в терминале.
