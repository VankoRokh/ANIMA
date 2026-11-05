# ANIMA Core v0.1 — P4-B Recovery Bookkeeping / Repeated-Run Endurance

**Статус:** **P4-B PASS** — локальный прогон владельца, точный snapshot `f6536f32c825897ef96168caa52ac45ece514b75` (2026-11-05). P4-C и Core v0.1 release gate ещё открыты.  
**Дата:** 2026-11-05.  
**Ветка:** `work/core-v0-1-p4b-endurance`, основана на owner-accepted [P4-A](Core_v0_1_P4_Integrated_Acceptance_Draft.md).  
**Исходные контракты:** [P0 System Acceptance](Core_v0_1_P0_Boundary_Draft.md) и [P3-C](Core_v0_1_P3C_Autonomous_Loop_Draft.md).

## 1. Зачем P4-B

В P3-C и P4-A подтверждены ограниченный сценарий one-door и отдельные recovery boundaries. Но при ревизии состояния планировщика обнаружен ещё один конкретный разрыв:

1. P3-B получает независимое свидетельство, записывает durable proof и завершает Goal/Task.
2. Процесс прерывается **после** Goal/Task commit, но **до** того, как P3-C сохраняет завершение записи `core_auto_attempts`.
3. После перезапуска P3-C больше не считает Goal активной; без отдельной сверки запись попытки навсегда осталась бы `started`.

Фактический World эффект уже защищён Stage6 и доказательством P3-B, но журнал scheduler attempts был бы неточным.

**Решение:** перед выбором следующей задачи P3-C сверяет `started`-attempts с terminal Goal и persisted P3-B proof. Порядок важен: P3-C сначала восстанавливает доказанные, но незавершённые Goal/Task переходы, затем сводит журнал попыток, только затем рассматривает новые Goal.

## 2. Границы authority

Изменение в [`anima/core/autonomy.py`](../../anima/core/autonomy.py) — `_reconcile_terminal_attempts`:

| Состояние Goal после рестарта | Core proof | Что записывается в scheduler attempt | Эффект |
|---|---|---|---|
| `completed` | есть | `finished / RECOVERED_VERIFIED_SUCCESS`, ссылка на реальный `event_id` | не повторять |
| `completed` | **нет** (например, Goal завершён оператором через Stage2) | `finished / DEFERRED / COMPLETED_WITHOUT_CORE_PROOF`, без fabricated evidence | не повторять |
| `cancelled` | нет | `finished / DEFERRED / GOAL_NOT_ACTIVE` | не повторять |
| `active` | нет | оставить `started`; при следующих событиях разрешается только обычный P3-B policy/recovery | безопасный driver |

Нет нового владельца Goal или Task, новых разрешённых инструментов, произвольного модели-generated действия или изменения семантической памяти. Прежняя первичная проверка independent readback **не заменяется** состоянием scheduler attempt.

Текущий recovery рассчитан на **однопроцессный** Core. Историю Stage2 Goal нельзя подменять Core-доказательством. External completion с отсутствующим Core proof фиксируется как отсутствие такого доказательства, а не как успешная верификация.

## 3. Измеряемые P4-B сценарии

Новые тесты добавлены в существующий [`tests/test_core_p4_acceptance.py`](../../tests/test_core_p4_acceptance.py), чтобы не создавать второй дублирующий acceptance harness.

| ID | Сценарий | Blocking invariant |
|---|---|---|
| B01 | Crash после доказанного Goal/Task success до `core_auto_attempts.finished` | после restart статус попытки восстановлен как verified, World эффект не дублируется |
| B02 | Crash до действия + operator cancels Goal | попытка становится deferred, ноль World эффектов |
| B03 | Crash до действия + operator manually marks Goal completed | нет fabricated `evidence_event_id`, deferred без Core proof |
| B04 | Двенадцать последовательных Goal при restart каждые 2 эпизода | stable instance identity, в точности шесть World операций, двенадцать Task/Goal completions |
| B05 | Те же двенадцать Goal при restart каждые 4 эпизода | воспроизводимость с другим ритмом рестартов, сохранённый журнал и без повторных эффектов |
| B06 | Между эпизодами вводятся зарегистрированные **но невалидные** шумовые события | они остаются raw journal/audit, но не становятся World Belief и не провоцируют действия |

B04/B05 — **короткая детерминированная нагрузка** по 12 эпизодов, а не «многочасовой soak». Не завышать гарантию до испытания на реальном power loss, повреждённом носителе, нескольких независимых writers или живом оборудовании.

## 4. Отчёт и proof of coverage

Улучшен существующий [`scripts/run_core_acceptance.py`](../../scripts/run_core_acceptance.py):

- `summary.json` содержит точный Git SHA, длительность полного запуска, полный список тестов и per-case results.
- `summary.md` дополнен **Mandatory P4 evidence** со списком обязательных сценариев, а также наблюдаемыми `p95` и пятью самыми долгими тестами.
- Если обязательный тест P4 отсутствует из JUnit, был пропущен или завершился ошибкой, вердикт acceptance runner не может быть `PASS`. Параметризованный 12-эпизодный сценарий должен пройти в обоих вариантах (2 и 4 рестарта).
- Метрики времени — **описательные**, без выдуманного performance-SLA. Они нужны как baseline перед Raspberry Pi validation.
- Полные JUnit XML, pytest.log и transient JSON/MD сохраняются в отдельно указанном пустом каталоге, не в tracked Core instance data.

Отчётность — presentation и acceptance layer; она не принимает решения от имени ANIMA и не выступает дополнительным источником истины.

## 5. Команды локальных проверок

Из корня репозитория после перехода на `work/core-v0-1-p4b-endurance`:

```bash
git rev-parse HEAD
bash scripts/check.sh

.venv/bin/python -m pytest -q \
  tests/test_core_p4_acceptance.py \
  tests/test_core_p4_report.py \
  tests/test_core_p3c_autonomy.py \
  tests/test_core_p3c_demo.py \
  tests/test_core_p3b_execution.py \
  tests/test_core_p3a_goal_decision.py \
  tests/test_core_p2c_runtime.py \
  tests/test_core_p2b_belief.py \
  tests/test_core_p2a_ingress.py \
  tests/test_core_p1_bootstrap.py
```

Полный прогон + читаемый сохраняемый отчёт:

```bash
report_dir="$(mktemp -d)"
.venv/bin/python scripts/run_core_acceptance.py \
  --suite full --output-dir "$report_dir"
sed -n '1,55p' "$report_dir/summary.md"
```

Для одного только нового P4 набора использовать `--suite p4`, для P4 + предыдущих Core модулей `--suite core`.

**P4-B acceptance (owner-local):** получен читаемый вывод `scripts/run_core_acceptance.py --suite full` для `f6536f32c825897ef96168caa52ac45ece514b75` (Python 3.14.4, UTC 2026-11-05T15:06:19.321542+00:00): **1373 PASS, 0 FAIL, 0 SKIP**, exit code 0. Все **12 mandatory P4 evidence** отмечены PASS, включая обе параметризации `test_p4b_multi_episode_cold_restart_and_noise_stay_bounded[2]` и `[4]`. Сумма длительностей test cases **22.620s**, наблюдаемый per-case p95 **0.069s**. Это пользовательский локальный прогон, а не запуск ассистента или CI. `summary.md`, `summary.json`, `junit.xml`, `pytest.log` созданы во временном каталоге; пользователь передал часть `summary.md` и терминальный вывод, не сами файлы. `scripts/check.sh` также сообщил PASS, но его числовой вывод отдельно не предоставлен.

## 6. Следующий P4 gate

После успешного P4-B перейти к финальному **P4-C Core v0.1 Release Candidate**:

- seed-based и продолжительный workload baseline (чётко различать deterministic event count и wall-time soak);
- расширенное failpoint и восстановление нескольких холодных запусков;
- явная матрица T0–T4 из P0 с remaining gaps;
- representative result по существующему формату TV (а не архив каждого исполнения);
- финальное решение о заморозке Core v0.1 с перечислением остающихся ограничений.

Только после acceptance и согласованной заморозки Core имеет смысл переходить от headless door fixture к самостоятельному Virtual ANIMA Lab feasibility (P5).
