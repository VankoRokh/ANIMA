# Canonical IR, Resolver и FAST/DEEP

**Назначение:** отделить формальное разрешение задачи от вероятностной интерпретации. Никакой когнитивный backend не является владельцем Identity, памяти, полномочий, Goal или окончательного proof.

## Маршруты

```text
текст / typed task → Canonical IR → Resolver
    ├─ формальное решение (без LLM)
    ├─ rejected / unknown / insufficient / no result
    └─ нерешённый остаток → Projection + bounded Context
                             → CognitiveCoordinator / Router
                             ├─ FAST backend
                             ├─ DEEP backend
                             └─ CHOICE (системный выбор)
                                      ↓
                              CognitiveProposal
                                      ↓
                              системная валидация
```

`Canonical IR` фиксирует нормализованное представление задач. `Resolver` применяет типы, ограничения и точные вычисления до вызова модели. `unknown` не равен пустому значению, `rejected` не равен отсутствию ответа. `Projection` ограничивает данные на вход модели; `ContextBundle` должен сохранять отсылки к первичным источникам.

`FAST` — более дешёвый и быстрый путь интерпретации; `DEEP` — отдельно подключаемый дорогостоящий вариант. `CognitiveRouter` выбирает маршрут согласно контракту, а не по заявленной самой моделью «уверенности». Полученный `CognitiveProposal` не становится `ExecutionAction` без отдельного допуска.

## История контракта

**Stage 5**: результат FAST назывался `FastResult`, вместе с Canonical IR, resolver и projection. **Stage 6**: добавлены system-owned `CognitiveProposal`, Coordinator/Router, Task/Goal-интеграция и независимая Verification. **Stage 4**: верховный `LLM Planner` остановлен как архитектурное направление; полезные исполнительные механизмы сохранены.

## Что используется в v0.1

Штатный `anima.release_v01` **не создаёт и не вызывает** FAST/DEEP backend. `context` строит Memory-only проекцию для consumer `FAST`, но не производит model inference. Отдельные тесты Stage 5–6 подтверждают свои маршруты; они не служат приёмкой LLM в базовой сборке.

## Ограничения и ссылки

DEEP не гарантированно лучше FAST, а успешный benchmark не удостоверяет истинность модельного утверждения. Открытый semantic residual Stage 7 не даёт права автоматически обновлять Knowledge. Оценка качества модели и воспроизводимость её конфигурации отделены от Core.

**Код:** [ir.py](../../anima/ir.py), [resolution](../../anima/resolution), [pipeline.py](../../anima/cognition/pipeline.py), [coordinator.py](../../anima/cognition/coordinator.py), [routing.py](../../anima/cognition/routing.py), [projection.py](../../anima/cognition/projection.py), [fast_llm.py](../../anima/cognition/fast_llm.py), [deep_llm.py](../../anima/cognition/deep_llm.py). **Проверки:** [test_resolution.py](../../tests/test_resolution.py), [test_cognitive_routing.py](../../tests/test_cognitive_routing.py), [TV-0043](../TESTING/Results/TV-0043.md), [TV-0045](../TESTING/Results/TV-0045.md), [TV-0051](../TESTING/Results/TV-0051.md).
