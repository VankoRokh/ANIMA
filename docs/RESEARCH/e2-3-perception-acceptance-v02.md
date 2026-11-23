# ANIMA v0.2 — E2.3: направленное восприятие и когнитивные proposals

**Вердикт:** **`PASS_LAB_SENSOR_ONLY`** — проверено агентское эгоцентрическое наблюдение Godot и отдельный read-only CognitiveStepProposal *validator*. **Это не E2-full, не cognitive lifecycle и не production/release acceptance.**  
**Дата:** 23 ноября 2026 г.  
**Проверенный кодовый snapshot:** `fc28548ffdf0e2aa8ac4b23a720c23396f594476` на ветке `work/v02-e23-egocentric-perception`.  
**Первичное evidence:** [CI 45200287800](https://github.com/VankoRokh/ANIMA/actions/runs/45200287800), **4/4 SUCCESS**, artifact `anima-e23-view-evidence`, полные Godot и Python логи.  
**База:** `work/v02-e23-cognitive-initiative-design`, `b93f5915e8461da9da740597cf8fb50aa2427a53`, [решение о когнитивной инициативе](e2-cognitive-initiative-v02.md). Предыдущая реальная реализация E2.2 — `PASS_LAB_RAW_POINTER`.  
**Цель:** виртуальный мир — стенд для будущих экспериментов памяти, представлений, выбора действий и роли FAST/DEEP; навигационная эффективность сама по себе **не** конечная цель.

## 1. Что изменилось

1. `LifecycleWorld.gd`: отдельный запуск `--lifecycle-egocentric` **только с `--lifecycle-guarded`**. Новое наблюдение `observe_view` имеет схему `anima.lifecycle.egocentric_observation/0.1`, сектор 90° относительно текущего взгляда, проверку окклюзии и **нет искусственного ограничения дальности** в небольшой комнате.
2. `self_position`, `reading.cell`, `grid_cell`, глобальное направление и прочие координаты отсутствуют в агентском DTO. Вместо них — `bearing_mdeg` и `range_milli_cells` относительно агента. Идентификаторы стен и временных препятствий — случайные стабильные в рамках эпохи `lab.surface.<opaque>` / `lab.obstacle.<opaque>`, а **не** координатные `lab.wall.x.y`. Новый сенсор имеет отдельный `source_ref=lab.sensor.anima.vision`.
3. Прежний `observe` при включённом E2.3 **не доступен** агенту; operator `inspect` сохраняет скрытую истину только для независимого oracle. Observer credential не имеет права `act/inspect`; executor credential не имеет `observe_view`. Старые E1/E2.2 режимы работают без флага и не меняют схемы.
4. Относительные команды `world.turn(direction=left/right)` и `world.step(direction=forward)` используют **отдельный** `anima.lifecycle.egocentric_action/0.1`, старый E1.4 operation ledger и обязательные `observation_id`, `expected_revision`, epoch, operation ID. Изменение направления увеличивает world revision/tick, replay не меняет эффект второй раз; старая compass-команда `world.move(N/S/E/W)` в режиме E2.3 отвергается. Команды отправляются **только тестовым executor harness**, не Core Stage6 и не FAST.
5. Python `EgocentricView`, `EgocentricAction`, `E23ObserverPort`: immutable и strict-schema DTO, проверка источника, связности world/epoch/sample, монотонных sample/revision/tick; старый observer port fail-closed при reset.
6. Минимальный лабораторный `CognitiveStepProposal`: immutable, exact schema, bounded query/event-IDs и **только** `retrieve_memory`, `lookup_raw_evidence`, `inspect_current_belief`, `inspect_goal_status`. Это **только валидация недоверенного предложения**, без оператора, реестра реальных handlers, Core Admission, выполнения, LLM и записи Memory/Knowledge/Goal.

## 2. Результаты

| Gate | Итог и ограничения |
| --- | --- |
| Python 3.12, 3.13, 3.14 — полная регрессия | **2435 PASS** на каждом |
| Новый E2.3 набор сенсора и cognition proposals | **43 PASS** в Godot job; 27 PASS повторно в старом gate |
| Документация до этого отчёта | **194 страницы, 1363 локальные ссылки PASS** |
| Godot official 4.7.2, seed 7 и 8 | **`E2_3_VIEW_GATE_PASS`**, опорные hidden coordinates используются **только** test oracle |
| Наблюдения на каждый seed | **5**, из четырёх направлений + начальное повторение направления, `sample_seq=1..5` |
| Исполнительные тесты | **4 поворота**, **4 идемпотентных replay**, **1 успешный forward step** для каждого seed |
| Режим координат / источник | **0 обнаруженных утечек** абсолютных клеток, `lab.sensor.anima.vision`; старый `observe` и compass move в новом режиме запрещены |
| Отрицательные сенсорные контрактные тесты | invalid DTO, extra coordinate keys, spoof category/source, duplicate ID, bad owner state, incorrect FOV и невалидное действие — отклоняются |
| Смена epoch и попытки доступа чужой ролью | **REJECTED**; новый instance observer может открыть новую epoch, старый не переносит курсор молча |
| E1.2–E2.2 legacy и crash regression | **PASS**; `E2_2_LIVE_GATE_PASS` после новой E2.3 проверки |
| CI | **4/4 SUCCESS**, verified code SHA выше |

Из результата live: seed 7 — числа видимых записей `7/7/8/7/7`; seed 8 — `6/7/8/7/6`. Они не являются универсальным oracle количества объектов; получены для конкретной геометрии, seed и начальной позиции.

Отрицательные CI-прогоны до завершения: первый обнаружил недоступность `Vector2i.dot()` в Godot 4.7.2, второй — несовместимость типизированного `Array[String]` с ternary `Array`, третий — ошибку eager-formatting в **лабораторном тесте**, а не в алгоритме восприятия. Исправлены и перепроверены на указанном конечном SHA; не объявлять промежуточные неуспешные runs доказательством PASS.

## 3. Границы и оставшиеся риски

**E23-R1 — Cognitive World Model, OPEN.** Нет самопостроенной топологической карты, относительной локализации из последовательности наблюдений, обнаружения противоречий и проверки, улучшает ли память поведение. Это исследуется в E2.4.

**E23-R2 — full Raw/Core, OPEN.** Opt-in `observe_view` **не подключён** к E2.2 `E22RawCaptureService` и canonical Core Raw; E2.2 регрессионный PASS относится **к legacy`observe` отдельно**. Нельзя заявлять, что новые эгоцентрические наблюдения долговременно сохраняются или идут в `CoreIngress` и Context. На следующем шаге нужен версионированный, provenanced ingestion с отдельным source и мостом чтения в Memory/WorldModel, сохраняя fail-closed.

**E23-R3 — actions, OPEN.** E2.3 `world.turn/step` допускаются Godot по test executor credentials; они **не** подключены к Stage6/Core Goal/Task/Execution/Verification, и не должны быть доступны напрямую FAST. Проверенный Godot receipt не является разрешением Core на действие.

**E23-R4 — LLM cognitive initiative, OPEN.** Продуктовый `CognitiveCoordinator`, операции Retrieval→Outcome, поведенческий DecisionRecord, FAST/DEEP и самостоятельное целеполагание **не реализованы**. Один лаб-валидатор предложения не подтверждает эти возможности.

**E23-R5 — trust/performance, OPEN.** Guarded bearer keys не означают OS isolation, `source_ref` и SHA не удостоверяют внешний недоверенный процесс; same-UID exposure остаётся. Тесты не доказывают пропускную способность больших визуальных потоков, power-loss или сохранение Godot ledger после остановки процесса. Ограничения E2.2 сохраняются.

## 4. Решение и следующий шаг

**Принять E2.3 как `PASS_LAB_SENSOR_ONLY`.** Готов минимальный контролируемый источник относительных сенсорных данных и повернутого взгляда, пригодный для проектирования механизмов памяти и принятия решений. Он **не** означает, что ANIMA научилась ориентироваться или мыслить.

**Следующий этап — E2.4 / Working World Model & Memory:** от agent-only Raw с provenance к временным ObservedFacts, топологическим связям/ориентирам и пересмотру гипотез; отдельная хронология `known/unknown/unobserved`, `world_instance_id+epoch`. Прежде чем сравнивать FAST и deterministic/stub, реализовать ограниченный CognitiveOperation→Core Admission→Outcome→DecisionRecord без второго владельца Core и без автоматического Knowledge. **Сравнение LLM начать рано на минимальном цикле**, не ждать идеальной карты.

Долговременное Core-native Raw storage, согласованные backup/restore и полноценный persistent instance остаются задачами E4; требования E2.2 к уже принятому raw захвату не ослаблять.

## 5. Воспроизведение

```bash
# Из чистой изолированной копии E2.3 branch, официальный Godot 4.7.2:
GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
bash scripts/run_e23_live_gate.sh "$GODOT_BIN"
# Только быстрый новый gate:
python -m pytest -q -p no:cacheprovider \
  tests/test_e23_egocentric_contract.py tests/test_e23_cognitive_proposal_contract.py
python -m labs.virtual_anima_lab.python.lifecycle.e23_view_live_gate \
  --godot "$GODOT_BIN"
```

Доказательства: [проверенный CI run](https://github.com/VankoRokh/ANIMA/actions/runs/45200287800) и его raw-evidence artifact. Ни команды, ни испытания не используют профиль пользователя или постоянную память ANIMA.
