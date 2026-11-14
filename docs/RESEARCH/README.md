# Исследования и экспериментальные ветки ANIMA

Этот раздел — **навигация по исследованиям, а не релизный Roadmap**. Статус `PASS` относится к конкретной гипотезе, test fixture и commit. Он не подтверждает включение алгоритма в рабочую ANIMA.

**Что входит в текущую версию:** [ANIMA v0.1 — контракт](../RELEASES/ANIMA_v0_1_Release_Contract.md) и [фактическая архитектура](../ARCHITECTURE/README.md).  
**Реестр исследовательских вопросов:** [исторический Research Track](../ROADMAP/Research.md).

## Отдельные направления

| Направление | Источник | Статус относительно ANIMA v0.1 |
| --- | --- | --- |
| Event Retrieval, эксперимент EXP-009 | [Memory Architecture v1 Roadmap](../ROADMAP/Memory_Architecture_v1_Roadmap.md) | Подтверждённый opt-in Event Retrieval используется в release-профиле; дальнейшее исследование отдельно |
| Memory Encoding E1–E4 | [Результаты E1](../ROADMAP/Memory_Encoding_E1_Results.md) и [план Memory](../ROADMAP/Memory_Architecture_v1_Roadmap.md) | Shadow / lab; новая production-ассоциация **не** принята автоматически |
| M0–M6-B2 интеграционные лаборатории | [M0](../TESTING/Memory_v1_Integrated_Read_Path_M0_v0.md), [M6-B2](../TESTING/Memory_v1_Integrated_Godot_Execution_M6B2_CI_Result_v0.md) | Источники проверенных сценариев; **не** обязательный Godot runtime релиза |
| Virtual ANIMA / Godot | [Сводка полигона](../ROADMAP/Virtual_ANIMA_Lab_P5C_Scenario_Replay_Draft.md) | Отдельная проверочная среда; не обязательна для v0.1 |
| Stage 7 semantic lifecycle | [Принятая read-only граница](../ROADMAP/Stage_7_Semantic_Boundary_v0.md) | Будущий сложный Knowledge lifecycle; не часть минимального релиза |
| Hardware Pi / performance | [TV-0054](../TESTING/Results/TV-0054.md) | Предыдущие Core-пробы; перенос на Pi не обязателен для v0.1 |
| FAST/DEEP/SLEEP refinement и meta-memory | [Research Track](../ROADMAP/Research.md) | Будущее развитие; контракты существующих систем не удаляются |

## Иерархия

1. **Implemented:** модуль используется в основном коде и отражён в архитектуре.
2. **Release-accepted:** реализованное поведение прошло release gate на точном снимке.
3. **Validated lab:** отдельный эксперимент подтвердил заявленные сценарии, но релизный путь не изменён.
4. **Research:** гипотеза или предложение, нуждающееся в исследовании.
5. **Historical / archived:** завершённая или отвергнутая линия, сохранённая ради воспроизводимости.

Это **категории**, а не обязательные стадии. Для каждой ветки решение о переносе в релиз принимается отдельно, без изменения исходных отчётов.

После окончательного принятия v0.1 можно перемещать устаревшие документы и папки по согласованной карте ссылок. Историю Git и первичные результаты не переписывать.
