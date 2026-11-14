# Когнитивная обработка: детерминированный resolver, FAST и DEEP

**Статус:** системные контракты Stage 5–6 реализованы. При этом **стандартный v0.1 headless-профиль не требует LLM**. Наличие сменяемых backend не означает, что каждый релиз обязан выполнять inference.

## Основной принцип

ANIMA — не языковая модель с подключённой базой. Постоянные владельцы Identity/Memory/Goals/Task/Policy работают независимо от FAST/DEEP; модели вызываются для ограниченной интерпретации, когда формальные правила не решают задачу.

```text
Вход → CanonicalTask / IR
          ↓
  Детерминированный resolver
     ├─ точное решение
     ├─ недостаточно данных
     └─ когнитивный остаток
                ↓
         CognitiveRouter
             ├─ FAST
             ├─ DEEP
             └─ CHOICE (системное решение)
                ↓
         CognitiveProposal
                ↓
       системная валидация
```

## Что делает каждый механизм

**Canonical IR** нормализует задачу и отделяет её контракт от текста промпта. **Resolver** сначала проверяет разрешимость без модели: допустимые операции, ограничения и точные вычисления; `unknown`, `insufficient`, `rejected` и отсутствие выбора не должны сливаться в одно «не получилось».

**Projection** формирует bounded запрос и сопровождающий ContextBundle. **FAST** — более оперативный когнитивный consumer; **DEEP** — отдельный более дорогой маршрут. Их общий протокол позволяет заменить backend без переноса системного состояния в модель.

**CognitiveRouter** принимает решение о маршруте **до** вызова модели. В Stage 6 baseline использовал FAST для обычного нерешённого reasoning, DEEP для явно обозначенной конфликтной задачи, CHOICE — для системного выбора из верифицированных кандидатов при зарегистрированной возможности. Предложение модели проходит `CognitiveProposal` validation и не становится готовым `ExecutionAction`.

## Полномочия и границы

- FAST/DEEP не владеют ни Memory, ни Identity, ни Goals, ни executor.
- Успешный ответ модели не равен истинному утверждению или подтверждённому результату действия.
- Смена модели не требует смены личности ANIMA.
- Политика маршрутизации не гарантирует, что DEEP всегда лучше FAST: прежние эксперименты с наивной эскалацией неопределённости не показали убедительной пользы.
- Исторический `LLM Planner` Stage 4 **не** является общим верхним циклом ANIMA.

## Реализация и свидетельства

[ir.py](../../anima/ir.py), [resolution](../../anima/resolution), [pipeline.py](../../anima/cognition/pipeline.py), [coordinator.py](../../anima/cognition/coordinator.py), [routing.py](../../anima/cognition/routing.py), [projection.py](../../anima/cognition/projection.py), [fast_llm.py](../../anima/cognition/fast_llm.py), [deep_llm.py](../../anima/cognition/deep_llm.py), [contracts.py](../../anima/cognition/contracts.py).

**История:** [Stage 4 (остановленный эксперимент)](../STAGES/04_Agent_Experiment.md), [Stage 5](../STAGES/05_FAST_Cognition.md), [Stage 6](../STAGES/06_Core_Integration.md). **Доказательства:** [TV-0043](../TESTING/Results/TV-0043.md), [TV-0045](../TESTING/Results/TV-0045.md), [TV-0051](../TESTING/Results/TV-0051.md), [ADR-009](../DECISIONS/README.md#adr-009).
