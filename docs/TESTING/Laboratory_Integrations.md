# Архив лабораторных проверок интеграции Memory и Core

**Это экспериментальные протоколы**, а не требования к текущему `ANIMA v0.1 Foundation`. В них сохранены исходные ссылки, границы доказательств и команды. Команды могут требовать Godot или отдельную модель; они не выполняются при обычном запуске.

[Вернуться к общим проверкам](README.md) · [Классификация исследований](../RESEARCH/README.md)

## Лаборатория ANIMA — M6-B2 source-isolated Godot execution

[Контракт M6-B2](Memory_v1_Integrated_Godot_Execution_M6B2_Design_v0.md): оригинальный M4 GoalStore и история M5 сохраняются; новая P6/Godot исполнительная цепочка использует отдельные target P2, P3-A, Task и Operation SQLite и собственное одноразовое host-разрешение. Код `labs/virtual_anima_lab/python/m6b2_godot_execution.py`, [offline tests](../../tests/test_memory_v1_godot_execution_gate.py), `labs/virtual_anima_lab/python/core_port.py` (проверка согласованных экземпляра/эпохи/ревизии). Нет P3-C или переноса старого M6-A допуска, нет изменений `anima/`. M6-B2.2 offline + full regression PASS на Python 3.12/3.13/3.14 (CI run `43598096331`, commit `8e003400532a81d52711d751c06a4e4a7d148e2c`); **это не real Godot acceptance**.

Live-runner `labs/virtual_anima_lab/python/m6b2_live_gate.py` проверяет реальный Godot 4.7.2, единичный эффект, отсутствие повторов и две точки `os._exit` между подготовкой операции и получением результата. GitHub Actions job `b2-godot-live` **PASS 10/10** (run `43598961064`, Godot 4.7.2, Python 3.14.10, 2 разрешённых эффекта, 0 дублей; отказ при изменении и восстановлении состояния с другой ревизией, `true_sigkill_tested=false`). [Разбор evidence](Memory_v1_Integrated_Godot_Execution_M6B2_CI_Result_v0.md). **CI не заменяет локальную проверку на ноутбуке**. Локально, из корня репозитория:

```bash
.venv/bin/python -m labs.virtual_anima_lab.python.m6b2_live_gate \\
  --godot "$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64" \\
  --report "/tmp/anima-m6b2-$(date +%s).json"
```

Режим `--case normal` выполняет только положительный сценарий. Мировые воздействия допускаются **только в созданных runner временных Godot-средах**, не в рабочем экземпляре ANIMA. CI live-gate PASS подтверждён; локальный laptop gate и Pi по-прежнему не подтверждены. Не доказаны: реальный SIGKILL/отказ питания, Pi, аутентификация оператора, глобальный production firewall или физический мир.

## Лаборатория ANIMA — M6-B1 real Godot source migration preflight (no executor)

[M6-B1 contract](Memory_v1_Integrated_Godot_Migration_M6B1_v0.md): не переносим старые полномочия M5/M6-A на Godot автоматически. Вместо этого принимаем реальные P6/Godot наблюдения через `VALDoorPort` с исходными `source/producer/clock`, фиксируем `world_instance_id`, `epoch`, `world_revision`, `lab_sample` и их сравнение с исходной M5 lineage. Отдельное явное `APPROVE` в lab-host разрешает **только revalidation mapping**, не действие. Модуль `labs/virtual_anima_lab/python/m6b1_godot_migration.py`, live Godot gate `labs/virtual_anima_lab/python/m6b1_live_gate.py`, [negative tests](../../tests/test_memory_v1_godot_migration_gate.py). B1 не изменяет P2/Core и не создаёт исполнительного интерфейса, B2 — отдельный будущий gate на изоляцию P2 и разрешённый эффект.

## Лаборатория ANIMA — M6-A single-use execution admission (same M5 source)

[M6-A-контракт](Memory_v1_Integrated_Execution_Admission_M6A_v0.md): отдельное host-разрешение на **одну** реальную операцию проверяется до сборки исполнительного Core и повторно в самом Tool handler. Данные исходных M4/M5 Goal/Memory/Belief/ActionSpec валидируются повторно; M6-токен потребляется атомарно до эффекта; отдельный Core sensor Proof подтверждает результат. Экспериментальная сборка без P3-C использует оригинальные `virtual_door` source/producer и `lab_tick` — **не** Godot. Код: `labs/virtual_anima_lab/python/m6_execution_admission.py`, отдельный [M6-runner](../../scripts/run_memory_v1_execution_gate.py), [отрицательные тесты](../../tests/test_memory_v1_execution_gate.py). Прямой `build_core` за пределами этого лабораторного пути остаётся обходом: production firewall не реализован. M6-B Godot потребует нового, явно проверенного контракта migration (`lab_tick`→`lab_sample`, `virtual_door`→`VALDoorPort`). Никаких изменений в production `anima/`.

## Лаборатория ANIMA — M5 separate typed binding admission without executor

[M5-контракт](Memory_v1_Integrated_Binding_Admission_M5_v0.md): подтверждённый M4 Goal может получить **отдельную** типизированную привязку P3-A, только после новой явной host-decision по неизменяемому ActionSpec, registered P2 sensor Belief и exact-source fingerprint. В лабораторном Core **нет исполнительного модуля и P3-C**, поэтому binding не может вызвать Tool. Путь `labs/virtual_anima_lab/python/m5_binding_admission.py`, runner `scripts/run_memory_v1_binding_gate.py`; [отрицательные тесты](../../tests/test_memory_v1_binding_gate.py). Binding в сохранённом Core work DB **может стать исполнимым** при последующей другой сборке: M5 не даёт права переносить данные в конфигурацию с executor без нового допуска. `operator_ref` не аутентифицирует пользователя. Production `anima/` не меняется; Pi и Godot отложены.

## Лаборатория ANIMA — M4 explicit approval and unbound Core Goal

[M4-контракт](Memory_v1_Integrated_Approval_M4_v0.md): только после source-backed `REVIEW_REQUIRED` и отдельного явного operator-test-host решения по неизменяемому fingerprint допускается создание ровно одной **непривязанной** Goal через существующий GoalStore. Журнал подтверждений изолирован от Core, резервирует Goal ID и start-transition ID для безопасного replay при обрыве между подтверждением и созданием. Лабораторный путь `labs/virtual_anima_lab/python/m4_approval_bridge.py`; runner `scripts/run_memory_v1_approval_gate.py`; [отрицательные тесты](../../tests/test_memory_v1_approval_gate.py). Host `operator_ref` **не подтверждает реальную личность**. Нет Task, Tool, Belief, Knowledge и автоматического Goal binding. No production `anima/` code or Stage 6 validator changes.

## Лаборатория ANIMA — M3 review-only Goal proposal from historical Memory

[M3-контракт](Memory_v1_Integrated_Proposal_M3_v0.md): проверяемое по первичным Events историческое воспоминание может стать **только предложением для рассмотрения**, но не Goal/Task/Tool. Экспериментальная реализация изолирована в `labs/virtual_anima_lab/python/m3_goal_preview.py`, исполняемый gate `scripts/run_memory_v1_goal_proposal_gate.py`, [отрицательные тесты](../../tests/test_memory_v1_goal_proposal_gate.py). Frozen Stage 6 `ProposalValidator` не расширен; противоречивые свидетельства блокируют автоматический переход, неподтверждённые идентификаторы и ложные полномочия отклоняются. Никакого LLM/автономной постановки целей или нового Stage.

## Лаборатория ANIMA — M2 Memory + live Godot VAL + Core recovery

[M2-контракт](Memory_v1_Integrated_External_VAL_M2_v0.md): реальная Godot 4.7.2 `p6_door` через существующий `VALDoorPort`, историческая Memory/Provenance, ограниченный FAST-context, Core Goal/Task/допущенный инструмент и независимое сенсорное подтверждение после перезапуска. `before`/`after` hard-exit перед receipt — отдельные отрицательные проверки, это не настоящие SIGKILL или сбой питания. M2 lab runner: `labs/virtual_anima_lab/python/m2_integrated_gate.py`, [offline tests](../../tests/test_m2_external_val_memory.py). Внешний порт только `127.0.0.1`; Pi отложен. M2 **не** даёт Memory полномочий на Goal/Tool.

## Лаборатория ANIMA — M1 Core-owned typed decision acceptance

[Критерии M1](Memory_v1_Integrated_Decision_M1_v0.md): исторический Memory-контекст читается **до** сохранения текущего вопроса, но только как справочная информация для FAST. Исполняемый typed Goal по-прежнему создаёт и связывает исключительно тестовый оператор, а Core P3-B принимает действия лишь по зарегистрированному датчику и собственному Verification. Негативные случаи: ложный user report, недоступность сенсора и unbound Goal. Headless VirtualDoorWorld, не Godot. [M1 runner](../../scripts/run_memory_v1_integrated_decision_gate.py); [M1 tests](../../tests/test_memory_v1_integrated_decision_gate.py). CI PASS не означает завершение Stage 7, production Memory→Core planning или тесты Pi.

## Лаборатория ANIMA — M0 read-path acceptance

[Критерии M0](Memory_v1_Integrated_Read_Path_M0_v0.md): первая сквозная проверка уже существующих Core Runtime → raw Event → Memory source links → Event Retrieval → Provenance/Context → детерминированный FAST, с **двумя отдельными Python-процессами** и обязательными отрицательными случаями. [Standalone runner](../../scripts/run_memory_v1_integrated_read_gate.py) и [регрессионные тесты](../../tests/test_memory_v1_integrated_read_gate.py). M0 не подтверждает автономный исполнительный контур, Stage 7 или работу на Pi до отдельных прогонов.

## E4 — завершающие SIGKILL/scale проверки перед интеграцией

[Изолированный контракт и воспроизводимый маршрут](Memory_E4_Crash_Scale_Exit_Gate_v0.md): [реальный SIGKILL в отдельном процессе](../../tests/test_memory_e4_process_kill.py) и [измерение 100/1000/10000 синтетических узлов](../../labs/exp009/e4_scale_probe.py). Результаты относятся только к E4 laboratory journal; **не** закрывают Memory v1.0, Core Integration, Pi performance или production-авторизацию. Статус каждой новой проверки уточняется после измеренного CI/локального запуска.

## E4 — изолированная проверка полномочий отзыва

[Зафиксированный контракт](Memory_E4_Source_Authority_Gate_v0.md) и [тесты](../../tests/test_memory_e4_source_authority_gate.py) проверяют привязку определения и его отзыва к синтетически допущенному принципалу с атомарным SQLite-решением. Настоящая аутентификация, внедрение в Core/Memory и автономный L2 **не подтверждены**.

## E4 исследование: полномочия отзыва и граф зависимостей

[Предварительно зафиксированный adversarial gate](Memory_E4_PostAlias_Authority_Graph_Gate_v0.md) отделяет подтверждение источника от синтаксической метки `source="user"`; [новые проверки](../../tests/test_memory_e4_postalias_authority_graph.py) характеризуют известную уязвимость лаборатории и независимо вычисляют ожидаемый набор графовых инвалидизаций. Это **не разрешение на production Memory или L2**.

