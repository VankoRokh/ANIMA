# Цели, задачи, допуск, исполнение и независимая проверка

**Статус:** типизированный исполнительный контур Core/Stage 6 реализован и испытан в ограниченных сценариях. В **базовом** профиле v0.1 реальных исполнительных capabilities **нет**; локальный тестовый sandbox подключается явно.

## Разделение ответственности

| Тип | За что отвечает | Не отвечает за |
| --- | --- | --- |
| Goal | Желаемый результат и критерий успеха | Конкретную операцию или подтверждение само по себе |
| Task | Долговечную единицу работы | Автоматическое владение Goal |
| Candidate / Choice | Проверенные варианты и выбор по правилам | Самовольное создание инструментов |
| ExecutionAction | Точные параметры разрешённой операции | Достоверность конечного результата |
| ExecutionReceipt | Факт выполнения/отказа исполнителя | Завершение Goal без наблюдения |
| Observation | Сведения от зарегистрированного источника | Универсальную правдивость любого текста |
| VerificationResult | Независимое сопоставление эффекта с критерием | Изменение первичной истории задним числом |

```text
Goal (persistent)
    ↓
TaskStore → CanonicalTask / resolver
    ↓
Candidate/Policy → validated ActionSpec
    ↓
ExecutionAction + VerificationSpec (durable)
    ↓
SandboxExecutor / зарегистрированный adapter
    ↓
ExecutionReceipt
    ↓
Новая независимая Observation
    ↓
VerificationResult → Goal / Task transition
```

## Trusted Core Event / Belief

`CoreIngress` принимает typed события только от **явно зарегистрированного** адаптера (`SourceRegistration` + разрешённые kinds). `BeliefProjection` применяет типы, разрешённые источники, ревизии и временные правила. Поле `source="user"` в обычном raw Event и текст «я сенсор» **не являются** аутентификацией. Registry без доверенной транспортной границы также не доказывает удалённую идентичность отправителя.

`GoalCriterion` допускает только поддерживаемый известный критерий; `CoreGoalDecision` связывает его с существующей допустимой Goal и подходящим Action. `CoreAutonomy` — ограниченный, сохраняемый driver; он не является свободным LLM-планировщиком, и его срабатывание зависит от явной регистрации источников и capabilities.

## Ошибки, повтор и восстановление

`ExecutionStore` сохраняет действие и `VerificationSpec` в журнале операций. Если процесс завершился между внешним эффектом и фиксацией результата, операция становится `uncertain`; возможны reconciliation/readback, но **не безусловный повтор**. Keyed idempotency допустима только при поддержанном адаптером контракте. `ExecutionReceipt` не завершает Goal без независимой `VerificationResult`.

В Stage 6 и последующих Core-тестах появились отрицательные проверки отмены Goal, конкуренции, восстановленных доказательств, планировщика и реального `SIGKILL`. Ни одна из них не доказывает exactly-once для **произвольного** физического устройства или злонамеренного процесса.

## Реализация

[CoreIngress](../../anima/core/ingress.py), [Belief](../../anima/core/belief.py), [GoalDecision](../../anima/core/goal_decision.py), [CoreAutonomy](../../anima/core/autonomy.py), [TaskStore](../../anima/tasks/store.py), [ExecutionStore](../../anima/execution/store.py), [SandboxExecutor](../../anima/execution/sandbox.py), [Verification](../../anima/execution/verification.py).

**История:** [Stage 4](../STAGES/04_Agent_Experiment.md), [Stage 6](../STAGES/06_Core_Integration.md), [подробная Stage 6](Stage_6_Cognitive_Integration_Core.md). **Проверки:** [TV-0047](../TESTING/Results/TV-0047.md), [TV-0051](../TESTING/Results/TV-0051.md), [TV-0054](../TESTING/Results/TV-0054.md), [релизный контракт](../RELEASES/ANIMA_v0_1_Release_Contract.md).
