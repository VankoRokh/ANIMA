# ANIMA v0.2 — H5.5 remediation / Evidence Lifecycle

**Статус:** R1 (F-01) реализован; **ещё не испытан**. R2–R4 не начаты; v0.2 RC **BLOCKED**.

## Источник и ревизия

- Независимый аудит проводился на commit `28e8438f8408e85b52e237eaedcf024354a4522a`. Исправления выполняются только в ветке `work/v02-h55-evidence-remediation` от этого SHA; ветка `audit/v02-h5-rc-candidate` не изменялась.
- Предоставленный владельцем `ANIMA_v0.2_H5.5_evidence.zip` проверен по `evidence_manifest.json`: **351/351** файлов совпали по размеру и SHA-256. Изучены `h55_work/independent_probes.py` (точные сценарии `evidence_merge`, `evidence_update`) и `h55_work/independent*.json` с подтверждёнными аудитором контрпримерами. Архив не публикуется в Git и не исполнялся при подготовке R1.
- Отчёт H5.5: **BLOCKED**; три P1 — F-01, F-02, F-04. 1967 PASS на 3.14.4 и 3.12.14 — результаты независимого аудита **исходной**, не исправленной ревизии.

## R1 / F-01 — граница мутаций действующего Evidence

### Дефект

Публичная цепочка `Raw → Memory → close → KnowledgeLayer.confirm` создаёт подтверждённое Knowledge. Следующий `MemoryLifecycle.merge(source,target)` меняет статус source на `merged`, а `MemoryStore.update_memory(source)` допускает открытие либо переписывание того же source. Knowledge остаётся `confirmed`, хотя его Evidence уже недействительно. Аудитор независимо воспроизвёл оба случая на Python 3.14.4 и 3.12.14.

### Исправление

- Общий метод `MemoryStore._require_no_confirmed_knowledge_dependencies(connection, memory_id)` блокирует мутации Memory при `supports/contradicts` Relation к текущему `Knowledge.status=confirmed`.
- `MemoryStore.update_memory()` проверяет зависимость и изменяет запись в одной транзакции `BEGIN IMMEDIATE`. Любой update меняет `updated_at` и потому считается изменением источника доказательств, включая importance.
- `MemoryLifecycle.merge()` под тем же типом writer lock проверяет **source и target** до переноса Raw sources, Relations и изменения статусов.
- Ограничение намеренно консервативно: Relation к `confirmed` защищена независимо от срока `valid_until` (в том числе историческая/будущая). Уточнение допуска возможно лишь после явного механизма Knowledge revision/revocation; автоматического изменения Knowledge или истории нет.
- `provisional` и несвязанные Memory не замораживаются. Не менялись SQL schema, Raw, EventProcessing, `PROCESSOR_VERSION`, release protocol, Knowledge writer.
- Прямые SQL, некооперативные writers, F-02 и F-04 не закрываются этим исправлением.

### Регрессии

`tests/test_v02_h55_r1_evidence_lifecycle.py`: **8 pytest cases**:

1. Отказ `confirm → merge` (точный сценарий F-01) с проверкой исходных source/target/ledger/Knowledge/History/Raw и здорового H5.0 diagnostic.
2. Отказ `confirm → update_memory(content)`, сохранение состояния.
3. Отказ `confirm → update_memory(status='open')`.
4. Отказ `confirm → update_memory(importance)`.
5. Отказ `confirm → update_memory(closed_at)`.
6. Несвязанную Memory можно обновить и слить без влияния на подтверждённый Knowledge.
7. `provisional` candidate не блокирует обычный update.
8. `provisional` candidate не блокирует прежний merge.

Расчёт полного pytest: **1975 passed** (1967 + 8). **Это не исполнявшийся результат.**

Проверить на ноутбуке (из корня репозитория):

```bash
git status --short
git rev-parse HEAD
PYTHONPATH="$PWD" .venv/bin/python -m pytest -q -rx \
  tests/test_v02_h55_r1_evidence_lifecycle.py \
  tests/test_v02_h2_2_evidence.py \
  tests/test_v02_h2_2_memory_dependencies.py \
  tests/test_memory_lifecycle.py \
  tests/test_v02_h5_4_compatibility.py
PYTHONPATH="$PWD" .venv/bin/python -m pytest -q
```

**Критерий приёмки:** каждый отказ произошёл *до* изменения данных; успешен весь pytest и старые N1–N9. Старый аудиторский репродуктор на исправленной ветке ожидаемо перестанет получать свой прежний `contract=FAIL`; это свидетельствует об исправленном поведении, а не о сбое проверки R1. Для принятия используем новые негативные тесты, проверяющие `ValueError` и неизменность состояния.

## Оставшиеся блокеры

R2 / F-02 — проверять существование Raw для каждого обязательного Event source при подтверждении Knowledge.

R3 / F-04 — запрет конфликтующих `supports/contradicts` в публичном writer и обнаружение этих конфликтов в read-only H5 diagnostics.

R4 / F-03,F-05,F-06,F-07,F-08 — processing-result tombstones, temporal merge/confirm, метаданные неполного Context, WAL/SHM snapshot contract.

После устранения подтверждённых дефектов — новый фиксированный SHA и независимый аудит. Текущий v0.2 RC не принят.
