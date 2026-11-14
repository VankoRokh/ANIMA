# Stage 6 — Интеграция когнитивного ядра

**Исторический статус:** завершено (`Complete`). **Назначение:** собрать ранее отдельные сервисы в один системный цикл без передачи LLM полномочий на состояние, память или инструменты.

## Какие механизмы объединили

- **Goals и persistent Tasks:** цель задаёт критерий, задача фиксирует единицу работы; `TaskStore` хранит переходы, Goal не равен Task.
- **`CognitiveCoordinator` / `CognitiveRouter`:** сначала выполняется детерминированное разрешение, затем маршрутизация между FAST, DEEP или системным CHOICE в пределах допусков.
- **`CognitiveProposal` / `ActionChoiceCoordinator`:** предложения модели остаются неполномочными; `InternalState` только корректирует оценку уже допустимых Candidates.
- **Исполнение:** отдельные `ExecutionAction` и `VerificationSpec`; исполнительный receipt не равен успеху цели.
- **Независимая проверка:** после выполнения необходимы наблюдение и `VerificationResult`, а не самозаявление модели или исполнителя.
- **SLEEP и recovery:** задача сохраняется через переходы сна, checkpoint и restart; неопределённые операции согласуются отдельно.
- **UnifiedTrace:** в отдельном журнале отображаются причина маршрутизации, состояние цели, действие, наблюдение, проверка и восстановление.

## Подтверждение

[TV-0044–TV-0050](../TESTING/Results/README.md) описывают отдельные части; [TV-0051](../TESTING/Results/TV-0051.md) — финальную системную проверку. Она включает FAST/DEEP/CHOICE, Sleep, keyed файловую запись с контролируемым crash point, восстановление `executing → uncertain`, reconciliation без повторного эффекта и независимую verification до завершения Goal.

## Ограничения

Официальное завершение **Stage 6** не означает доказанную production-safe автономность всех будущих модулей. Отдельный Core v0.1 впоследствии проходил независимый аудит и специальные тесты. Семантический write/revision Knowledge (Stage 7) тогда не был включён; реальный Godot, Pi и произвольные сенсоры не являются частью подтверждения Stage 6.

**Код:** [Coordinator](../../anima/cognition/coordinator.py), [Tasks](../../anima/tasks/store.py), [Execution](../../anima/execution/coordinator.py), [Recovery](../../anima/cognition/recovery.py).  
**Подробная архитектура:** [Stage 6 — Cognitive Integration Core](../ARCHITECTURE/Stage_6_Cognitive_Integration_Core.md), [исполнительный контур](../ARCHITECTURE/Execution_and_Verification.md).
