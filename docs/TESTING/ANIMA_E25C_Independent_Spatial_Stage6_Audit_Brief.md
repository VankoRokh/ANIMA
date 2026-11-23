# ANIMA v0.2 / E2.5c — Independent Stage2/Stage6 Spatial Action Reaudit Brief

**Статус:** задание для независимого ревью, **сам аудит не проведён**.  
**Ветка:** `work/v02-e25c-core-spatial-execution`.  
**Исходный подтверждённый snapshot реализации:** `a60cf73666eac0e5b1cfe8ca659b3341c48a4353`, [CI #45281261375](https://github.com/VankoRokh/ANIMA/actions/runs/45281261375).  
**Связанная запись:** [E2.5c acceptance](../RESEARCH/e2-5c-stage6-spatial-acceptance-v02.md).

## Цель

Независимо проверить, что новая маршрутизация world.turn/world.step действительно использует **канонические** GoalStore, TaskStore, ExecutionStore и SandboxExecutor, не позволяет выполнить эффект до подтверждённой Core/source admission, и не вводит второй источник полномочий.

**Не** принимать 2496 PASS, согласованные Godot receipt/revision/tick или визуальный успех seed 7/8 за доказательство отсутствия архитектурных ошибок. Подвергнуть сомнению сами контракты и сценарии отрицательных тестов.

## Аудиторские области

1. **Registry и привязка полномочий:** exact source/producer, получение/подмена Raw digest, актуальность Core Belief и forwarded event, текущий epoch, forged `SpatialSourceProof`. Попытки вызвать `prepare/execute_once/finish_verified` напрямую с чужим Goal/Task/Action/VerificationSpec; альтернативные public API, в том числе непосредственный `SandboxExecutor.execute`.
2. **Stage2 Goal и Stage6 Task:** immutable Goal/source ID, допустимые переходы, условия успешного завершения, любые обходы `GoalProgressEngine`; гарантия «один Task/эффект за одну признанную операцию», наличие/отсутствие формального `CoreGoalDecision` в новой цепочке. Не подменяет ли опциональный gateway существующий `CoreDoorExecution`.
3. **ExecutionStore atomicity:** Action и VerificationSpec создаются вместе, готовятся до эффекта; нет ли пути без Spec, повторных `operation_id`, повторного/параллельного Task или принятия `succeeded` без исполнения.
4. **World effect boundary:** `ToolRegistry`, input/output schemas, keyed operation identity в Godot, корректность parent/child `SandboxExecutor`, timeout/error_code/effect_possible, отсутствие credentials в LLM, DecisionRecord и Core arguments. Отдельно проверить, что same-UID access остаётся угрозой.
5. **Verification и доказательства:** сравнить исходный Core-backed Raw, Stage6 receipt, Godot readback и новый Raw; оценить возможность создать ложный success при согласованных clocks, но непроверенном физическом эффекте. Отделить `Task verified attempt` от `Goal physically achieved`; не выдавать `GoalObservation(CONFIRMED_RESULT)` за независимый датчик.
6. **Crash/recovery cuts (обязательные):** после Goal creation, после Task creation, после Stage6 prepared, перед эффектом, после сетевого эффекта, до readback, после readback, после нового Raw, до Task completed, после Task completed и до Goal success. Для каждого состояния: можно ли продолжать, верифицировать, блокировать, повторить без дубля? Прерывать исключительно временные экземпляры.
7. **Негативные мировые сценарии:** смена epoch и world instance, уничтоженный Godot ledger, отсутствие reply после фактического эффекта, чужая роль, rejected/blocked step, stale revision, concurrent operators, malformed receipt/output и Context contamination.
8. **Regression и comparison:** отдельный E2.5b lab-only mode должен оставаться исправным, полная Python-регрессия и Godot seed 7/8; дополнительные собственные seeds, немонотонные clocks, отсутствие видимого target. Сохраняются ли запреты на операторские абсолютные координаты и на FAST direct action.

## Требуемые материалы отчёта

- Перечень отдельных находок `CRITICAL/HIGH/MEDIUM/LOW` с конкретными файлами, воспроизводимыми шагами и причинным механизмом; разделение новых дефектов от известных E2.4/E4 ограничений.
- Матрица **Goal → Task → ExecutionAction → VerificationSpec → world effect → new Raw → Verification/Goal** со статусом фактического владения каждым переходом.
- Аварийная матрица: `no effect`, `effect certainly happened`, `unknown` — где разрешён replay, где он запрещён, где требуется операторское восстановление.
- Отдельный вердикт о том, допустимо ли подключать реальную FAST **только как propositional client** и какие блокеры нужно устранить.
- Не изменять релиз, GitHub repo, реальные данные пользователя; отрицательные тесты проводить только на временной изолированной копии. Если окружение недоступно, явно указать непроверенное.

## Существующие доказательства и команды

```bash
python -m pytest -q -p no:cacheprovider tests/test_core_spatial_action_gate.py
bash scripts/run_stage6_visual_gate.sh /path/to/Godot_v4.7.2-stable_linux.x86_64
```

Эти проверки являются **начальными фактами**, а не основанием игнорировать новые пути обхода. Вердикт E2.5c: `PASS_LAB_STAGE2_STAGE6_SPATIAL` — ограничен лабораторией и не означает production readiness.
