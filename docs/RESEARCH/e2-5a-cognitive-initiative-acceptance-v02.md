# ANIMA v0.2 — E2.5a: ограниченная когнитивная инициатива без LLM

**Вердикт:** `PASS_LAB_READ_ONLY_INITIATION` — **частичная приёмка E2.5**, не полная CognitiveCoordinator/Core Admission, не реальная FAST и не автономные цели.  
**Проверенный кодовый snapshot:** `e4d26213b4c155cdad24a752f7980dab263b0d10`.  
**Доказательства:** [CI #45251798046](https://github.com/VankoRokh/ANIMA/actions/runs/45251798046), **4/4 SUCCESS**: Python 3.12/3.13/3.14 — **2481 PASS** на каждой версии; Godot 4.7.2 seed 7 и 8; регрессия E1.2–E2.4b PASS.  
**База:** [E2.4a](e2-4-working-memory-acceptance-v02.md), [E2.4b](e2-4b-relative-pose-acceptance-v02.md), [решение о когнитивной инициативе](e2-cognitive-initiative-v02.md).  
**Цель:** не научить ANIMA играть в Godot, а изучать роль памяти и LLM при выборе следующих шагов анализа.

## 1. Что именно реализовано

`labs/virtual_anima_lab/python/cognition/coordinator.py` содержит экспериментальный `E25LabCognitiveCoordinator`. Это **исследовательский оркестратор на ограниченной локальной политике**, не второй Core, не изменение `anima/core` и пока **не нативный Core Admission**.

Операции проходят последовательность:

```text
Core-backed Raw + E2.4 Working Memory
   -> bounded world context (source refs, stale/not_observed, truncation)
   -> adapter.propose(context, предыдущие проверенные outcomes)
   -> strict CognitiveStepProposal schema + ID/context/budget validation
   -> лабораторный read-only admission (до исполнения)
   -> доверенная зарегистрированная операция чтения
   -> verified service result + durable DecisionRecord
   -> адаптер может предложить следующий шаг / stop / budget exhaustion
```

Допустимые операции этой версии:
- `retrieve_memory`: только ограниченный **строковый** поиск по E2.4 working-world memory. **Не** production EpisodicMemory и не семантический Retrieval; стратегия явно обозначена `substring_baseline_not_semantic_retrieval`.
- `lookup_raw_evidence`: проверяемые чтения оригинальных E2.4 Raw по известным Core event ID; произвольные файлы/SQL не принимаются.
- `inspect_current_belief`: только явно зарегистрированная Core property `lab.actor.anima/view_digest` из существующего `CoreIngress.read_belief`.
- `inspect_goal_status`: в `CognitiveStepProposal` присутствует как возможное направление, но здесь **отклоняется `OPERATION_UNAVAILABLE`**, поскольку доверенный GoalDecision в данном лабораторном экземпляре отсутствует.

Недоступны `world.turn/step`, `propose_world_action`, `delete_memory`, `Knowledge` mutation, произвольные инструменты ОС и произвольное расширение реестра операций моделью.

`DecisionRecord` хранится в `e25_cognitive_trace` внутри временной E2.4 лабораторной БД: `turn_id`, `step_index`, входной ограниченный Context, SHA-256, типизированное предложение, результат admission с причиной, фактический outcome и его SHA-256. Admission commit выполняется **до** вызова read-only handler. Операции не запускаются повторно при повторном `turn_id`; незавершённый результат не выдаётся за успешный. Контекст перепроверяется **до и после** вызова адаптера/операции.

Ограничения: `max_steps<=6`, ограничение Context 32 KiB, outcome 16 KiB, существующий proposal budget 4096 bytes; остановка и отказ при недействительном/устаревшем Context, недопустимой операции или ошибке провайдера.

## 2. Сравнение с памятью / без памяти

Три направленных Raw-наблюдения: сперва ящик не виден, затем виден, затем оказывается вне нового поля зрения. Сравнивается **тот же** набор исходных наблюдений, но меняется доступ к прошлому через `memory_enabled`.

| Условие | Достоверно проверенный результат |
| --- | --- |
| Память включена | Шаг 1: bounded working-memory retrieval обнаруживает прошлый ящик (`not_observed`). Шаг 2: `TwoStepEvidenceStub` на основании полученного `last_seen_event_id` инициирует `lookup_raw_evidence` и получает verified source Raw. |
| Память выключена | Шаг 1 возвращает пустой список для ящика; дополнительного запроса по несуществующему доказательству не появляется. |
| Злонамеренное предложение `world.step` | Отвергнуто схемой / lab policy; Godot operator truth не изменён. |
| Повторное открытие Core | DecisionRecord и Core-linked Raw сохранены, без повторных world effects. |

**Эксперимент на Godot seed 7 и 8:** по 3 исходных Raw, 3 Core event pointer, **2 когнитивных шага с памятью**, **1 без**, 0 world effects от CognitiveCoordinator, 0 FAST/LLM calls, 0 Stage6 world actions. Отдельно проверены предложенная запрещённая операция и одинаковое независимое состояние Godot до/после когнитивного цикла.

**Что это доказывает:** API поддерживает инициативное продолжение анализа на основе проверенного результата предыдущего шага, строго отделяет данные от разрешений, и доступ к прошлому наблюдению меняет **информационную последовательность**.

**Чего это не доказывает:** адаптер — предопределённый `TwoStepEvidenceStub`. Никакая LLM ещё не продемонстрировала инициативы, обучения, эффективного планирования, улучшения успешности целей или самостоятельного жизненного цикла. Нет независимого behavioural A/B и статистики качества решений.

## 3. Проверка негативных условий

Python unit: **15 новых тестов** E2.5a (см. CI), в том числе: stale/forged context ID, чужой turn, недопустимые world/Memory-команды, пустой/недостоверный Raw, несуществующий Goal, resource exhaustion, повторный turn ID, adapter failure, подмена DecisionRecord context/outcome, изменение сенсорного Context внутри вызова адаптера. Любое из этих событий не превращается в разрешение на action.

По крайней мере две дополнительные области остаются OPEN:
- Изменённые локально SHA и таблицы сами по себе **не обеспечивают криптографической подлинности** при полном контроле БД или same-UID процесса. Это readback/consistency защита малой лаборатории.
- Обработка аварии между сохранением `ADMITTED` и записью `outcome` пока **fail-closed** (`outcome unknown`), без полного продолжения незавершённого когнитивного turn. Это отдельный тест/проектный этап.

## 4. Границы архитектуры

1. **LAB admission ≠ Core-native admission / Stage6.** Нельзя называть E2.5a полноценным внедрением CognitiveCoordinator в Core без дополнительного контракта прав доступа, идентичности и lifecycle.
2. **Никакого FAST/DEEP пока нет.** Имеющиеся `FastLLMBackend` и `DeepLLMBackend` обслуживают другие интерфейсы Stage 5/6, не схему `CognitiveStepProposal`. Для реальной модели нужен сменный проверяемый адаптер к общему `llm_transport`, а не передача модели прямого SQL или Goal/Executor.
3. **Working-world memory остаётся экспериментальной E2.4 проекцией**, а не подтверждённым Knowledge или канонической episodic памятью.
4. **Не полная пространственная модель:** E2.4b сохраняет относительные переходы, но не доказана полноценная топологическая локализация и устранение неоднозначности ориентиров.
5. **Raw/Core sidecar всё ещё разделены**, power-loss и консистентный backup не тестировались; нет OS sandbox. Все run делались на disposable instances.
6. **Метрика пока информационная**, не поведенческая: результат «две операции вместо одной» сам по себе не означает лучшего мышления. Нужны blind tasks, multi-seed, повторения и контроль стоимости/ошибок LLM.

## 5. Решение и следующий шаг

**Принять `PASS_LAB_READ_ONLY_INITIATION` только как E2.5a.** Следующий приоритет, соответствующий цели ANIMA, — **E2.5b / First Real FAST Cognitive Adapter**:

- использовать существующий provider-neutral `llm_transport`, новый строго типизированный role adapter для `CognitiveStepProposal`, без вмешательства в прежний `FastLLMBackend`;
- одинаковый агентский Context и read-only операции для stub и FAST, фиксированный бюджет, воспроизводимая temperature=0 для базового теста;
- измерить долю валидных предложений, уместность следующего Retrieval, число недопустимых операций, качество выбора при ложных/противоречивых следах, стоимость и задержку;
- сравнить `deterministic / stub / live FAST`; отдельно отметить, что synthetic replay/stub PASS **не** является реальным FAST PASS;
- параллельно подготовить перевод lab admission в доверенную Core-собственную политику и E2.4c — ограниченную топологическую гипотезу без попытки сделать полноценную навигационную игру.

Публикации релиза не было, PR остаётся draft, независимый архитектурный аудит E2.4b/E2.5a ещё не выполнен.

## 6. Воспроизведение

```bash
# Только из временного checkout соответствующего snapshot:
python -m pytest -q -p no:cacheprovider tests/test_e25a_cognition.py
bash scripts/run_e25a_cognition_gate.sh /path/to/Godot_v4.7.2-stable_linux.x86_64
```

Первичный отчет: [CI #45251798046](https://github.com/VankoRokh/ANIMA/actions/runs/45251798046). Вердикт относится к указанной проверенной ревизии кода. Изменения только документации, добавленные позже, должны проходить свой CI отдельно.
