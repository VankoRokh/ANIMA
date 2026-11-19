# ANIMA v0.2 RC1 — карточка независимой приёмки

**Дата решения владельца:** 19 ноября 2026 года.  
**Решение:** принять заключение H5.8 и разрешить оформление **Release Candidate** v0.2 в [ограниченном контракте](contract.md). Это не объявление окончательной stable-версии. Аннотированный Git tag опубликован отдельно; GitHub Release пока не опубликован.

## 1. Неизменяемая цель

| Поле | Значение |
| --- | --- |
| Версия | ANIMA v0.2 RC1 |
| Аннотированный Git tag | `v0.2.0-rc.1` — опубликован и проверен 19 ноября 2026; peeled commit равен проверенному SHA |
| Проверенный кодовый commit | `1364e62634669ef553df0b2f2d7a1159d404383f` |
| Tree | `e8b2dda15b265185990b3010041f821ffdc765dd` |
| Аудиторская ветка | `audit/v02-h58-r8-post-integration-candidate`, идентична коду RC |
| Выпускная ветка | `release/v0.2.0-rc.1`, создаётся на точном кодовом commit |
| ТЗ | `docs/TESTING/ANIMA_v0_2_H5_8_Independent_Reaudit_Brief.md` в `work/v02-h58-independent-audit-prep` |
| Документы версии | Постприёмочная редакция в отдельной ветке; не входят в target tree |
| Итого по H5.8 | **PASS / APPROVE_RC** в ограниченном профиле |

GitHub Git ref проверен: аннотированный `v0.2.0-rc.1` указывает на Git tag object `02c4b2e1fe9c956e21ff4ccbb54217905b95f641`, который указывает на проверенный commit `1364e62634669ef553df0b2f2d7a1159d404383f`. GitHub **Release пока отсутствует**; публикацию prerelease подтвердить отдельно. Этот документ и subsequent docs commits не входят в tag tree.

## 2. История владельческой проверки

| Этап | Full pytest (локально, owner-reported) | Docs/static |
| --- | ---: | --- |
| Исходный H5.7 | 2166 PASS | PASS |
| R8.0 Knowledge Proof Novelty | 2179 PASS | PASS |
| R8.1 Context Adapter Integrity | 2243 PASS | PASS |
| R8.2 Temporal Validation Consistency | 2298 PASS | PASS |
| R8.3 Integration & Acceptance | **2315 PASS за 97.09 s** | **PASS** |

Последний `scripts/check.sh` на Python 3.14.4: **182 страницы**, **1334 локальные ссылки**, AST/syntax 420 Python-файлов, 3 VS Code JSON, 3 Bash, корректная CLI extraction и отсутствие личных данных/instance файлов в tracked paths. Это результат на **кодовой** ревизии до последующего изменения релизных документов.

## 3. Независимая проверка H5.8

Независимый reviewer подтвердил точный HEAD/tree, clean detached checkout и сохранение SHA-256 всех **905 tracked файлов** до/после. ТЗ H5.8 получено отдельно от target; исторические original probes выполнены на временных тестовых экземплярах.

| Проверка | Результат |
| --- | --- |
| Environment | CPython 3.14.4, pytest 9.2.0, SQLite 3.50.4, x86_64, Linux 6.18.57, shared AMD EPYC VM |
| `scripts/check.sh` | PASS; 182 документа, 1334 ссылки, 420 Python |
| Targeted repository suites | **265 passed** |
| Full repository pytest | **2315 passed**, exit 0 |
| Оригинальные formal H5.7 probes на старом H5.7 | 6 failed / 56 passed: исходные дефекты воспроизведены |
| Те же оригинальные probes на H5.8 | **62 passed**, exit 0 |
| Новая reviewer matrix + supplementary | **229 + 6 = 235 passed** |
| Live same-second repro | `confirmed`, без подмены системных часов |
| Crash/recovery, concurrency, WAL/backup | PASS в заданных software/filesystem условиях |
| H57-01–H57-03 | **FIXED_VERIFIED** каждый |
| H56-01–06, NEW-01–07, F-01–08 | Контрактные регрессии не выявлены в протестированных границах |
| Новые нарушения P0–P3 | Не обнаружены |

В исходных H56 exploratory checks остались **2 неуспешных проверки** — automatic aging и immutable historic Memory text, сознательно исключённые из версии. Два исходных H57 observation assertions ожидали старый TypeError; новый корректный ValueError делает их неуспешными по старому ожиданию. Эти результаты сохранены и **не** переименованы в PASS. Одно собственное ошибочное предположение reviewer о содержимом старого SHA исправлено **только в новом harness**, не в коде или оригинальных assertions.

## 4. Исходные материалы и контроль целостности

**Независимые первичные материалы:** `ANIMA_v0_2_H58_Independent_Reaudit_RU.md` и `ANIMA_v0_2_H58_Evidence.zip` (хранятся отдельно от source tree). Проверяющий может воспроизвести сценарии из `probes/reproduce_h58.py` после инспекции на disposable checkout.

| Файл | SHA-256 архива/документа |
| --- | --- |
| `ANIMA_v0_2_H58_Evidence.zip` | `82d1dd04cc73940b8caf77ef328c918fee47b362c7100c66544822f5487c03eb` |
| `ANIMA_v0_2_H58_Independent_Reaudit_RU.md` | `3747454265baa48e0ce63c479f4d6467a6c4880b7e6f73a3f48956b923118680` |

Наличие этих хешей в документации само по себе не означает, что ZIP опубликован как GitHub release asset или скопирован в репозиторий. В H5.8 evidence manifest проверены 151/151 записей, включая прежний H5.7 archive; исходные reviewer tests и логи сохранены.

## 5. Проверенные исправления

- **H57-01:** `KnowledgeLayer.confirm` отличает собственную только что созданную Relation от старой поддержки при совпадении временных instant; true old/future/expired witness запрещён, Raw-backed fresh witness принят.
- **H57-02:** `ContextBuilder` валидирует все candidates до selection, coverage и provenance; неверный `kind`, ID, record/text, score или reasons отвергаются с `ValueError`.
- **H57-03:** все `supports/contradicts` Evidence intervals проверяются прежде, чем терминальный Knowledge write начнёт comparisons/effects; corrupted naive/invalid/empty intervals дают `ValueError` с rollback.

R8.3 изменил только tests/docs относительно проверенного R8.2. Сравнение H5.7→H5.8: **15 коммитов, 10 файлов**, production только `anima/memory/knowledge.py` и `anima/memory/context_builder.py`.

## 6. Принятые ограничения и следующее исследование

Открыты наблюдения H5.8 **O58-01 (Raw alias identity)** и **O58-02 (custom adapter content truthfulness)**. Они не новые production regressions, но их устранение необходимо для любого будущего контракта независимости свидетельств и подключения недоверенных когнитивных/инструментальных компонентов.

Профиль доверенных Memory writers и adapters является **условием допуска**, а не рекомендацией. Не сертифицированы automatic aging, frozen historical Memory revisions, `candidate=None` global ranking freshness, cross-file JSONL/SQLite atomicity, physical power-loss, ARM/RPi, real legacy DB, масштабная latency/SLO, семантическая truthfulness и LLM inference. `v0.2 RC1` не должен объявлять их работающими.

Подробности: [контракт](contract.md) и [релизные заметки](release-notes.md). Следующий исследовательский этап планируется **после фиксации RC**, с отдельным scope и своими критериями.
