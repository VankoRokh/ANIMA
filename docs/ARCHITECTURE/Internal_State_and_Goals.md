# Внутреннее состояние, цели и выбор

**Статус:** детерминированный слой Stage 2 реализован; интеграция с Task/Execution выполнена в Stage 6. Это **регулирующий механизм**, не независимый источник целей или эмоционального сознания.

## Модель

| Переменная | Практический смысл | Что важно |
| --- | --- | --- |
| `fatigue` | накопленная нагрузка | зависит от времени активности и работы; снижение в восстановлении |
| `uncertainty` | недостаток надёжных сведений | не исчезает сама по себе только из-за времени |
| `frustration` | повторение неуспешной стратегии | помогает ограничивать зацикливание |
| `satisfaction` | подтверждённый прогресс | не возникает из неподтверждённой самодекларации |

Значения находятся в ограниченном диапазоне `0.0..1.0`. События-сигналы проходят через `TransitionEngine` с сохранением `before/delta/after`, правила, причины, времени и источника. `TimeDynamics` применяется лениво с явным временем — частые перезапуски не должны искусственно ускорять затухание.

## Goal и Candidate не одно и то же

```text
Источник/оператор → GoalStore → active / blocked / completed / cancelled
                                        ↓
                             проверенные Candidates
                                        ↓
                           ChoiceEngine + State modifiers
                                        ↓
                             выбранный допустимый вариант
```

Цель хранит критерий, приоритет, причину и lifecycle. `GoalArbitrator` решает порядок рассмотрения, но не выдаёт исполнительные capabilities. `ChoiceEngine` принимает **уже проверенный** набор вариантов и корректирует оценку ограниченными modifiers. Internal State не порождает новую Goal, не подменяет Candidate и не разрешает Tool.

`ExpressionAdapter` формирует read-only отображение состояния; оно не является скрытым механизмом обратной записи. В Stage 6 `Task` стал самостоятельной единицей работы; связи Goal/Task описаны в [исполнительном контуре](Execution_and_Verification.md).

## Реализация

[Goals](../../anima/internal_state/goals.py), [Goal arbitration](../../anima/internal_state/goal_arbitration.py), [Transition Engine](../../anima/internal_state/transition_engine.py), [Time Dynamics](../../anima/internal_state/time_dynamics.py), [Choice](../../anima/internal_state/choice_engine.py), [Expression](../../anima/internal_state/expression_adapter.py), [хранилище](../../anima/internal_state/store.py).

**История:** [Stage 2](../STAGES/02_Internal_State.md). **Доказательства:** [TV-0017](../TESTING/Results/TV-0017.md), [TV-0016](../TESTING/Results/TV-0016.md). **Основание:** [ADR-006](../DECISIONS/README.md#adr-006).

## Ограничения

Принципы влияния на Choice проверены на ограниченных кандидато-наборах. Это не доказательство полезности произвольной новой переменной или способность системе сама выбирать жизненные цели. Источники и policy должны оставаться system-owned.
