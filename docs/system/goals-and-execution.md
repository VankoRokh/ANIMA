# Internal State, Goals, Tasks и Execution

**Задача:** ограниченный выбор и проверяемое действие без передачи полномочий когнитивной модели. `Goal` выражает критерий; `Task` — долговечную работу; действие и его доказательство живут отдельно.

## Внутреннее состояние и допустимый Choice

`InternalStateRuntime` хранит в `internal_state.db` Goals и четыре ограниченные переменные: `fatigue`, `uncertainty`, `frustration`, `satisfaction` (диапазон `0.0..1.0`). `TransitionEngine` записывает причинные переходы, а `TimeDynamics` управляет временем без искусственного ускорения от повторного запуска. `ChoiceEngine` меняет **оценку уже допустимых** кандидатов, но не создаёт новый Tool, Goal или разрешение.

## Линия исполнения

```text
оператор / системно допущенный инициатор → GoalStore (persistent)
 → GoalCriterion → CoreGoalDecision (binding и предложение)
 → зарегистрированный ActionSpec + Policy
 → ExecutionAction + VerificationSpec (в долговечном журнале)
 → SandboxExecutor / подключённый world port
 → ExecutionReceipt (результат вызова; не proof)
 → независимое новое observation / readback
 → VerificationResult → Goal / Task progress
```

| Сущность | Владелец и граница |
| --- | --- |
| `Goal` | GoalStore, критерий и переходы; текст пользователя не создаёт исполнительное разрешение |
| `Task` | TaskStore; независимая долговечная единица работы |
| `Candidate`/`Choice` | Выбор только среди проверенных вариантов |
| `ActionSpec`/`ExecutionAction` | Реестр инструментов и точные параметры допустимого эффекта |
| `ExecutionReceipt` | Исполнитель подтверждает вызов/ошибку, не истинность конечного состояния |
| `VerificationSpec`/`VerificationResult` | Независимая проверка на свежем наблюдении |
| `CoreAutonomy` | Ограниченный синхронный driver, не свободный LLM Planner |

## Конфигурации

**Базовый v0.1:** созданы `CoreIngress` и `CoreGoalDecision` с пустыми реестрами, но `core_execution=None`, `core_autonomy=None`; ни `report`, ни скрытая модель не получают разрешённых инструментов.

**`--sandbox-door`:** отдельный каталог с зарегистрированными `SourceRegistration`, `PropertyRule`, `ActionSpec`, локальным `VirtualDoorWorld`, `CoreDoorExecution` и `CoreAutonomy`. Команда `ensure_sandbox_door_closed` явно создаёт операторскую Goal и запускает bounded цикл. Это не физическое устройство и не обязательный Godot.

**VAL/P6/M2/M6-B2:** внешний `DoorWorldPort` и обработчики передаются через `build_core`; интеграция в `labs/` остаётся внешним адаптером, а не частью identity/memory ядра.

## Отказы и повтор

Перед исполнением долговечно сохраняются намерение и `VerificationSpec`. При прерывании после внешнего эффекта и до proof операция может быть `uncertain`; нужен reconciliation/readback, **не** слепой повтор. Нельзя считать отменённую Goal причиной забыть уже начатую проверку или потерять накопленный результат. B1–B4 показали ошибки транзакционности намерения, отмены, timestamp proof и parked triggers; последующие исправления имеют собственные регрессии. Профильная идемпотентность не обещает exactly-once для любого физического Tool.

**Код:** [goals.py](../../anima/internal_state/goals.py), [choice_engine.py](../../anima/internal_state/choice_engine.py), [goal_decision.py](../../anima/core/goal_decision.py), [door_execution.py](../../anima/core/door_execution.py), [autonomy.py](../../anima/core/autonomy.py), [store.py](../../anima/execution/store.py), [verification.py](../../anima/execution/verification.py), [testовый world port](../../labs/virtual_anima_lab/python/core_port.py). **Проверки:** [test_release_v01.py](../../tests/test_release_v01.py), [test_core_audit_blockers.py](../../tests/test_core_audit_blockers.py), [TV-0047](../TESTING/Results/TV-0047.md), [TV-0051](../TESTING/Results/TV-0051.md). **История:** [Stage 2](../history/stages.md#stage-2), [Stage 4](../history/stages.md#stage-4), [Stage 6](../history/stages.md#stage-6).
