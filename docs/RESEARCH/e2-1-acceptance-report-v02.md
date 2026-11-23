# ANIMA v0.2 — E2.1: приёмка доверенной границы наблюдений

**Вердикт:** `PASS_LAB_APP_BOUNDARY` — принят только контролируемый наблюдательный контур **Core ↔ guarded Godot**, не полный E2.  
**Дата:** 23 ноября 2026.  
**Проверенный кодовый snapshot:** `3e4ea3b93cb093e6c9be45ca926a488c9adf176f`, ветка `work/v02-e21-core-owned-world-gateway`.  
**Первоисточник:** [GitHub Actions 45171807284](https://github.com/VankoRokh/ANIMA/actions/runs/45171807284), **4/4 SUCCESS**, artifact `anima-e21-read-only-core-gateway` с первичными логами.  
**Исходная база:** независимый [E1-min `PASS_LAB_RESTRICTED`](e1-min-acceptance-report-v02.md), `bbdbe3a7429ac3002a832c356c9dedac697c2c79`.  
**Контракт:** [E2.1 trust boundary](e2-core-world-boundary-v02.md).

## 1. Что проверено

| Критерий | Результат / evidence |
| --- | --- |
| Core-binding и типизированное наблюдение | `CoreBoundObservationGateway` принимает только существующий `CoreAssembly` и точную source registration. `WorldObservation` проходит DTO и привязку к handshake, envelope, source, epoch и clocks |
| Режимы полномочий | Opt-in `--lifecycle-guarded`, отдельные observer/executor/operator bearer keys; observer-capabilities ограничены `[observe]` |
| Подмена `role=operator` на raw TCP | **REJECTED** без ключа, с ключом observer или executor; операторский `inspect` разрешён только при operator key |
| Запрет эскалации ключа | Observer key не допускает `act`; executor key не допускает `observe`; неавторизованный `observe` отклоняется на стороне Godot |
| Плохая bootstrap-конфигурация | **REJECTED**: отсутствующие, совпадающие, короткие ключи, `--lifecycle-effects` без ledger и `--lifecycle-ledger` без effects; защищённый listener не стартует |
| Отсутствие утечек в stdout | При guarded-mode seed и bearer-ключи не присутствуют в сообщениях startup / log |
| Core reopen / Godot lifecycle | При новом `CoreAssembly` с тем же Core data dir и **живом** Godot binding сохраняется; reset и замена процесса Godot — **REJECTED** без auto-rebind |
| Source/handshake spoof & rollback | Python-тесты отклоняют чужой source, несовпадающие identity, лишние capabilities, `seed` в hello, старые sample/revision/tick |
| Отсутствие новых полномочий Core | В E2.1 не создаются Raw Events, Goals, Task, эффекты или второй Stage6 executor |
| Совместимость | **2380 pytest PASS** на Python 3.12.16, 3.13.18 и 3.14.10; **2380 PASS** и в Godot CI; прежние E1.2–E1.4, независимый E1-min, P5/P6/P5-C, M2 PASS |
| Целостность документации на кодовой точке | `scripts/check.sh`: **191 страница, 1357 локальных ссылок, PASS** |

Среда: Ubuntu x86_64, официальный Godot `4.7.2.stable.official.ed1daf0bf`, бинарник с проверенным SHA-256. При каждом seed (7, 8) использованы новые изолированные Godot-процессы и временные Core-данные. Проверены изменения, внесённые в ветку исследования, без изменения `anima/` или опубликованного релиза `v0.2.0-rc.1`.

Стандартная лаборатория E1.2–E1.4 остаётся в **старом незащищённом режиме** для воспроизводимости; её известную подмену роли нельзя считать устранённой глобально. В E2.1 защищённый режим включается **явно**.

## 2. Архитектурная оценка

E2.1 сделал отказ в недопустимом действии **исполняемым на стороне Godot**, а не только декларацией Python-адаптера. Gateway получает исключительно ключ наблюдения, не управляет `act`, `operation_status`, `inspect` или `reset`, а проверенный Core binding не допускает молчаливой смены процесса/эпохи.

Это устранение **конкретного E1MIN-01 raw-role-spoof сценария** в guarded test profile, а не доказательство защиты от любого недоверенного кода. Единственным предусмотренным владельцем допуска Goal/Task остаётся существующий Stage6; новый адаптер не создаёт параллельного планировщика или исполнителя.

## 3. Открытые ограничения и обязательные требования

**E21-R1 — межпроцессное доверие, OPEN/HIGH.** Bearer-key в environment дочернего Godot и plaintext-loopback не изолирован от кода с доступом к тому же OS UID, environment или `/proc`. Python private поля также не являются границей против Python introspection. Возможны DoS на локальном сокете и утечка ключа при компрометации хоста. **Запрещено** запускать FAST или недоверенные плагины с доступом к raw socket/секретам; для production потребуется настоящий sandbox/UID/IPC broker. `PASS_LAB_APP_BOUNDARY` не является одобрением физического действия.

**E21-R2 — ключ исполнения ещё не привязан к Stage6, OPEN/REQUIRED.** В E2.1 исполнительный ключ существует только в доверенном Godot test harness, новый gateway **не имеет** его и не выполнял успешный `act` в guarded mode. Перед E2.4 необходимо закрепить этот capability за единственным существующим Core/Stage6 admission flow, проверить запрет альтернативных публичных API и independent readback; выдача исполнительного ключа LLM недопустима.

**E21-R3 — нет canonical Raw/Memory provenance, OPEN/REQUIRED.** CoreIngress `SourceRegistration` — административная регистрация, **не криптографическая аутентификация** наблюдения. В E2.1 gateway лишь закрепляет `sample_seq` и часы в отдельной SQLite, не записывает canonical Raw Event. Между `_pin()` и будущей Raw-записью при сбое возможна потеря незавершённого наблюдения, если использовать binding как irreversible consume cursor. **E2.2 обязан** реализовать durability-first pending observation / outbox с idempotent replay, либо атомарно привязать pointer к immutable Raw. Нельзя считать E2.1 metadata journal долговременной памятью.

**E21-R4 — ограниченность trust proof, ACCEPTED LAB LIMIT.** Сам Godot, Core-host и запускающий harness считаются доверенными. Никаких испытаний same-UID malicious process, проверки sandbox, межхостовой криптографии, LLM prompt injection, электропитания либо реальных устройств не проводилось.

**E21-R5 — непрерывный lifecycle пока отсутствует, ACCEPTED STEP LIMIT.** Нет интеграции `Memory/Context/Goal/FAST/Task/Verification`, продолжения после restart самого мира или самостоятельного выбора маршрута. Это следующие шаги E2.2–E2.6 и E4.

## 4. Решение

**Принять `E2.1 / PASS_LAB_APP_BOUNDARY`** для лабораторного профиля наблюдения с явным guarded-mode и строго доверенным владельцем ключей. Нельзя переносить этот результат на legacy незащищённый Godot, на OS-level security или на полномочия физического исполнительного устройства.

Следующий этап — **E2.2 Raw/Provenance**. Сначала durable capture before exposure/consumption, затем регистрация canonical события через действующий `CoreIngress/Dispatcher`, а не параллельная система памяти. Отдельно сохранить E21-R1 как обязательный критерий готовности E2 к взаимодействию с недоверенным FAST.

## 5. Воспроизведение

```bash
GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"
bash scripts/run_e21_live_gate.sh "$GODOT_BIN"
```

Runner: полный E1.4 / E1-min, негативные unit tests, два seed Core ↔ guarded Godot, пять негативных bootstrap-профилей и позитивная проверка guarded observe-only без исполнительных capabilities. Никогда не передаёт секреты в CLI и не сохраняет их в result/evidence.
