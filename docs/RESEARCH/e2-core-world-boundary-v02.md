# ANIMA v0.2 — E2.1: Core-owned observation gateway и разграничение Godot-ролей

**Статус:** **`Validated Lab / E2.1 PASS_LAB_APP_BOUNDARY`** — только app-level guarded observation, не E2 full, Stage6 execution или production security.  
**Проверенный кодовый snapshot:** `fe1cf645e186d7dd520a50cd23e636ba45c67de5`; [CI 45170677368](https://github.com/VankoRokh/ANIMA/actions/runs/45170677368) — 4/4 PASS. [Подробный вердикт](e2-1-acceptance-report-v02.md).  
**Основа:** [E1-min independent acceptance](e1-min-acceptance-report-v02.md), `bbdbe3a7429ac3002a832c356c9dedac697c2c79`, `PASS_LAB_RESTRICTED`.  
**Ветка:** `work/v02-e21-core-owned-world-gateway`. Изменения только в исследовательском контуре `labs/`, tests, CI и документации; release `v0.2.0-rc.1` не затрагивается.  
**Архитектурный инвариант:** единственная система принятия решений/допуска действий — существующий Core/Stage6. Новый `RecoverableAgentLoop`, независимый GoalStore/TaskStore или второй executor не создаются.

## 1. Поставленная задача и минимальная граница

Единственный наблюдательный вход `CoreBoundObservationGateway` для нового мира `LifecycleWorld`: принимать только typed `WorldObservation`, закреплять источник за собранным Core и хранить устойчивую привязку мира. Код FAST, Retrieval, внешний текст и неавторизованные плагины не должны получать `LabClient`, TCP-порт, секреты исполнительного/операторского уровня или raw `act` API.

**В E2.1 не допускается ни одного нового действия.** Передача предложений модели Stage6, запись canonical Raw Event, долговременные Goals и Verification принадлежат дальнейшим E2.2–E2.6. Невозможность сделать `act` через read-only gateway **не является доказательством** того, что Stage6 уже подключён к Godot.

## 2. Граница полномочий в guarded mode

Обычный E1.2/E1.3/E1.4 `LifecycleWorld` сохраняет совместимость; его `role=agent/operator` по-прежнему **не аутентифицируется**. Для нового лабораторного E2.1 режима необходим флаг `--lifecycle-guarded` и **три разные сильные одноразовые bearer-строки** через **окружение дочернего Godot-процесса**, не через аргументы командной строки:

| Ключ в переменной окружения Godot | Операции внутри guarded world | Кто получает |
| --- | --- | --- |
| `ANIMA_LIFECYCLE_OBSERVER_KEY` | `hello` с `capabilities=[observe]`, `observe` | Только trusted `CoreBoundObservationGateway` |
| `ANIMA_LIFECYCLE_EXECUTOR_KEY` | `hello` с `act/operation_status`, `act`, `operation_status` | **Не выдаётся** gateway, FAST или E2.1. Зарезервирован для будущего Stage6 binding |
| `ANIMA_LIFECYCLE_OPERATOR_KEY` | `inspect/reset/set_obstacle`, операторский hello | Только отдельный доверенный test harness |

Ключи должны быть разными, от 32 до 128 символов `[A-Za-z0-9_-]`. В случае неполной конфигурации защищённый мир обязан отказать при запуске. Каждый запрос защищённого мира несёт отдельное поле `auth`, которое **удаляется перед валидацией WorldAction / записью event log / формированием receipt**. Запрос без ключа и `role=operator` с ключом наблюдателя/исполнителя возвращают `UNAUTHORIZED`; попытка `act` с ключом наблюдателя — `FORBIDDEN`. `hello` наблюдателя не раскрывает ни seed, ни hidden map, ни другие capabilities. Сообщение запуска и UI в guarded mode не публикуют seed.

**Важная граница:** это разделение возможностей на уровне приложения, **не** изоляция недоверенного процесса на уровне ОС. Bearer secrets передаются через локальный TCP без TLS и хранятся в процессе. Код с тем же UID и доступом к `/proc`, environment или к Python introspection может обойти Python gateway и извлечь ключи. Настоящая изоляция недоверенного FAST-процесса требует отдельного sandbox/UID/network namespace или иного непроницаемого broker. E2.1 не объявляет эту проблему полностью устранённой. Незащищённый legacy-режим остаётся пригодным **только** для прежних лабораторных тестов, не для подключения новой автономии.

## 3. Core-bound gateway

Класс `labs/virtual_anima_lab/python/lifecycle/core_gateway.py:CoreBoundObservationGateway`:

1. Принимает **только** `CoreAssembly` с совпадающими ссылками на `Runtime`, и запрещает подключение, если в той же сборке уже есть собственный исполнитель или автономный scheduler.
2. Требует явную точную регистрацию `lab.sensor.anima.proximity → lab.world.lifecycle.adapter` через существующий `CoreIngress.SourceRegistration`. Регистрация конструируется доверенным composition root, а **не** на основании поля из сетевого ответа. В E2.1 не осуществляется `ingress.admit`, запись `Raw`, `Memory`, `Knowledge` или `Goal`.
3. Принимает `hello` только защищённого мира `lifecycle-grid/0.1` с `capabilities=[observe]` и `auth_mode=guarded`; любые дополнительные полномочия / `seed` / `walls` / неправильный identity — отказ.
4. Проверяет полную схему immutable `WorldObservation`, `source_ref`, `observer_ref` и согласование `world_id/epoch/revision/tick` между handshake, ответом и сенсором.
5. **До возврата данных** атомарно записывает в отдельную SQLite `e21_world_binding.db` идентификатор Core, мира, эпоху, `sample_seq/revision/tick`; повтор или откат счётчиков, `reset` и замена процесса Godot с тем же Core instance **не выполняют auto-rebind**.
6. Выдаёт наружу только sealed `WorldObservation` и копию метаданных `binding_snapshot()`. Публичные `act`, `inspect`, `reset`, `operation_status`, `client` отсутствуют.

Сам по себе `WorldObservation.source_ref` — **не** аутентификация. Даже полученная через bearer-ключ запись не становится истинным Raw Event до отдельного доказуемого пути в E2.2. `binding_snapshot` не должен использоваться как автономное решение о действии.

## 4. Приёмочные требования E2.1

| ID | Критерий |
| --- | --- |
| E21-01 | Обычный E1.2–E1.4 режим не изменился (полная регрессия P5/P6/M2 и E1-min) |
| E21-02 | Без ключа/с неправильным ключом Godot не выдаёт наблюдение/операторские данные |
| E21-03 | Ключ наблюдателя не допускает `act`, `operation_status`, `inspect`; ключ исполнителя не допускает `observe`, роль оператора защищена третьим ключом |
| E21-04 | Неверный/недостаточный набор ключей и spoofed handshake не приводят к fail-open |
| E21-05 | Gateway строго привязан к одному `CoreAssembly`, source registry и одному world instance/epoch |
| E21-06 | После restart Core при **живом** Godot binding не теряется; после reset/restart Godot происходит fail-closed |
| E21-07 | Replay sample, откат tick/revision, подмена `source_ref`, `world_id`, чужое поле capabilities блокируются |
| E21-08 | Никаких Core Raw / Knowledge / Goal и виртуальных эффектов E2.1 не создаёт |
| E21-09 | CI Python 3.12/3.13/3.14 + Godot 4.7.2 + предшествующие gates PASS |
| E21-10 | Вердикт честно разделяет app-level bearer checks и отсутствие OS-level секьюрности |

## 5. Выполнение (только изолированная лаборатория)

Исполняемый runner: `scripts/run_e21_live_gate.sh`. Он сначала воспроизводит замороженную полную E1.4-регрессию, затем E1-min independent black-box и отдельно двухseedовый E2.1 live test с несколькими свежими Godot-процессами. Ключи создаются test harness через `secrets.token_urlsafe()` и передаются только дочернему Godot, **не записываются в evidence**.

```bash
GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
bash scripts/run_e21_live_gate.sh "$GODOT_BIN"
```

**Интерпретация `PASS`:** только `PASS_LAB_APP_BOUNDARY`, если выполнены ВСЕ пункты и исключён raw socket из возможностей model-facing слоя. Это **не** production authentication, не E2 loop, не разрешение FAST запускать world effects.

## 6. Требования к следующему шагу

- **E2.2:** реализовать единую цепь Canonical Raw, bound provenance и durable read-first capture в существующем Core EventLog/Memory; запретить модельные утверждения `source_ref=lab.sensor.*` как будто это sensor admission.
- **E2.3–E2.4:** интегрировать advice-кандидата `ID/NO_ADVICE` с единственным Stage6 Goal/Task admission; ключ исполнительных операций выдавать **только** доверенному Core executor, не gateway/FAST.
- **E2.5:** Core restart при живом Godot, durable decision-before-effect, проверяемое восстановление `RECORDED/UNKNOWN`, без второго эффекта.
- До любого production применения: OS/IPC/UID sandbox и аутентификация внешнего мира; локальный bearer лишь защита в контексте контролируемой лаборатории.

Прямое подключение модели к `LabClient` или обход `CoreBoundObservationGateway` недопустим.
