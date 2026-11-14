# VAL / Godot и интеграционные эксперименты M0–M6-B2

**Назначение:** реальная, но ограниченная внешняя среда и тестовый путь Memory → Core. Лаборатория `labs/virtual_anima_lab/` — **подключаемый адаптер**, не часть постоянной Identity и не обязательный runtime `ANIMA v0.1 Foundation`.

## VAL P5/P6

[Изолированный P5-C](../ROADMAP/Virtual_ANIMA_Lab_P5C_Scenario_Replay_Draft.md): P5-A 9/9, P5-B 10/10, P5-C 4/4 сценария с повторяемыми trace в новых процессах Godot. Этот исходный документ **предшествует** интеграции P6, поэтому надпись «Core не подключён» — состояние **P5-C**, а не всех более поздних лабораторий.

После P5 появились `VALDoorPort` и P6 как внешняя конфигурация Core: `build_core` получает `world_port` и `world_handlers` только явно, без переноса старых полномочий. См. [историю Core](../history/core-v0.1.md) и [инструкции лаборатории](../../labs/virtual_anima_lab/README.md).

## M0–M6-B2 — последовательность контрольных разрешений

| Срез | Проверяемая граница | Запрещённый автоматический переход |
| --- | --- | --- |
| [M0](../TESTING/Memory_v1_Integrated_Read_Path_M0_v0.md) | raw Event → Memory → Event Retrieval → provenance/Context, два Python-процесса | Создание Goal/Tool из текста |
| [M1](../TESTING/Memory_v1_Integrated_Decision_M1_v0.md) | Исторический Context до нового вопроса; typed Goal создаёт оператор | Предоставление полномочий Memory |
| [M2](../TESTING/Memory_v1_Integrated_External_VAL_M2_v0.md) | Реальный Godot, отдельное readback и recovery сценарии | Приравнивать `os._exit` к SIGKILL/power-loss |
| [M3](../TESTING/Memory_v1_Integrated_Proposal_M3_v0.md) | Source-backed предложение исторической Goal | `preview` автоматически становится Goal |
| [M4](../TESTING/Memory_v1_Integrated_Approval_M4_v0.md) | Первое явное host-решение создаёт **unbound** Goal | Создание Task, binding или Tool |
| [M5](../TESTING/Memory_v1_Integrated_Binding_Admission_M5_v0.md) | Второй operator decision для typed binding | Исполнение в сборке с executor |
| [M6-A](../TESTING/Memory_v1_Integrated_Execution_Admission_M6A_v0.md) | Отдельное одноразовое разрешение на локальную SQLite-дверь | Перенос допуска в Godot |
| [M6-B1](../TESTING/Memory_v1_Integrated_Godot_Migration_M6B1_v0.md) | Source/producer/clock, epoch, world revision и migration approval | Revalidation mapping = Tool permission |
| [M6-B2](../TESTING/Memory_v1_Integrated_Godot_Execution_M6B2_Design_v0.md) | Новый target P2/P3-A, ограниченный эффект в Godot, независимый proof | Историческая M5 Goal сама становится новым разрешённым action |

Все шаги защищают границу **права предложить → создать Goal → связать Task/ActionSpec → исполнить → подтвердить**. Свободный `Memory`-текст не выдаёт authority.

## M6-B2 — первичное live-доказательство

[CI-отчёт M6-B2](../TESTING/Memory_v1_Integrated_Godot_Execution_M6B2_CI_Result_v0.md), **14 ноября 2026**, head SHA `318bb7f7228dccad07502a21f38de04a9d457afd`, [run 43598961064](https://github.com/VankoRokh/ANIMA/actions/runs/43598961064): **10/10 M6B2_CASE_PASS**, Godot **4.7.2**, Python **3.14.10**, `world_effect_total=2`, повторного эффекта нет. Перед эффектом `os._exit(74)` оставлял неопределённую операцию и 0 эффектов; после эффекта `os._exit(73)` восстановление сохраняло единственный эффект и отдельный sensor proof. Изменённая и затем восстановленная дверь отклонялась по `world_revision`, хотя видимое состояние совпадало.

**Граница:** в опубликованном CI report `operator_authenticated=false`, `production_firewall=false`, `true_sigkill_tested=false`, `pi_tested=false`, `power_loss_tested=false`. Он **явно не подтверждает** результат владельческого ноутбука для этого exact branch — если локальный прогон существует, его надо привязать отдельно к файлу/SHA. Ветка #4 на момент отчёта была draft, а не принятый релиз.

## Не путать со Stage 8 и выпуском

`Stage 8` остаётся историческим `Planned` в [реестре](../history/stages.md#stage-8), хотя отдельные VAL и M-сценарии успешно испытаны. Foundation v0.1 не требует Godot и не включает этот world port по умолчанию. Полные команды, ограничения и архивные решения — в [исходной сводке](../TESTING/Laboratory_Integrations.md).

**Открыто:** реальный authenticated operator, независимый production firewall, перенос Pi, unbounded scheduler, длительные процессы с физическими эффектами, произвольный SIGKILL и отказ питания.
