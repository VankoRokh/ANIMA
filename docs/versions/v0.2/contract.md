# ANIMA v0.2 RC1 — контракт ограниченного детерминированного профиля

**Решение владельца:** 19 ноября 2026 года — разрешён переход к Release Candidate после независимого H5.8.  
**Кодовый snapshot:** `1364e62634669ef553df0b2f2d7a1159d404383f`.  
**Git tree:** `e8b2dda15b265185990b3010041f821ffdc765dd`.  
**Имя RC-тега:** `v0.2.0-rc.1` (факт публикации проверяется отдельно).  
**Статус документа:** постприёмочная редакционная запись; не входит в проверенный кодовый snapshot.  
**Режим допуска:** доверенные локальные Memory writers, Retrieval adapters и SQLite/Raw writers; детерминированная обработка без обязательного вызова LLM.

ANIMA v0.2 RC1 — не универсальный автономный интеллект, не новая система безопасности от локального администратора и не гарантия истинности автоматически сформированных знаний. Версия развивает обработку Memory/Evidence/Knowledge/Context поверх принятого фундамента v0.1.

## 1. Что входит в проверенный профиль

1. Канонические физические Raw Events через `EventLog`, `memory_sources` и `ProvenanceResolver`. При терминальных изменениях Knowledge валидируется существование требуемого Raw, а не семантическая истинность содержимого.
2. `MemoryStore`, `MemoryLifecycle`, `MemoryProcessor`, `EventProcessingCoordinator`: запись/обновление и связывание эпизодов, current-namespace ledger, проверки stale candidate/source-set, атомарное сохранение эффектов в SQLite, повторное открытие и `recover` в проверенных сценариях.
3. `LinkStore` / `KnowledgeLayer`: жизненный цикл `provisional → confirmed / challenged / rejected / superseded` через авторизованные переходы, замкнутые Memory sources, History, Evidence `supports/contradicts`, разрешённые `supersedes`.
4. Временные Evidence как интервалы `[created_at, valid_until)`, с учётом UTC offsets, future/expired/overlap, full-graph validation до публикации и правильным `ValueError` на повреждённых интервалах.
5. `RetrievalEngine`, `ContextBuilder`, `ProvenanceResolver`: ограниченный поиск, FAST/DEEP бюджетирование, независимые показатели Retrieval coverage и Context truncation, структурная валидация каждого candidate от custom adapter до selection/trace/provenance.
6. `MemoryStore` schema compatibility: отказ при неподдерживаемых metadata/version до изменяющего schema bootstrap; транзакционный откат DDL и целостность штатного backup/restore workflow в проверенных условиях.
7. Документированные `Identity`, `Goal/Task`, `Policy`, `Execution`, `Verification` и прочие механизмы v0.1 сохраняются как отдельно принятая основа; настоящие внешние действия и модели не становятся частью обязательного RC только из-за наличия соответствующих компонентов в репозитории.

**Разделение полномочий:** generic graph writer сохраняет только допустимые отношения и не может самостоятельно повысить Knowledge до terminal state; lifecycle writer отвечает за публикацию; physical Raw — проверка происхождения; Context — детерминированная бюджетированная проекция. Для произвольного административного SQL такой barrier не считается security sandbox.

## 2. Допуск источников и адаптеров

**O58-01 — Evidence identity:** новый `Memory ID` может ссылаться на уже использованный `Raw Event ID`. Новизна подтверждения в нынешнем контракте определяется Memory/Relation identity; **не** доказана независимость Raw свидетельств. Все writers Memory должны оставаться доверенными.

**O58-02 — custom adapter truthfulness:** валидный по форме адаптер может вернуть под каноническим ID изменённый `record.content/statement`, который попадёт в Context при реальном Raw provenance по ID. Структурная проверка R8.1 — не канонизация текста и не криптографическая аттестация. До нового trust contract использовать только доверенные adapters.

## 3. Что сознательно не обещается

- Семантическая истинность Knowledge, независимость источников, защита от административных SQL/Raw writers и криптографическая неизменяемость Raw.
- Автоматическое `aging` статуса confirmed при истечении finite support и immutable snapshots прежнего текста Memory после challenge.
- Глобальная свежесть выбора `candidate=None` при конкурентном изменении ранжирования; current chosen-candidate stale guard проверен отдельно.
- Универсальная идемпотентность всех исторических processor namespaces и auto-repair старых/повреждённых баз.
- Единый атомарный COMMIT между JSONL и SQLite, fsync/power-loss durability и устойчивость к внезапной потере питания.
- Недоверенные Retrieval adapters, независимая epistemic authority, обучение/инференс FAST/DEEP/SLEEP LLM, самостоятельное понимание и действие во внешнем мире.
- Raspberry Pi / ARM64, реальные пользовательские legacy DB, Python 3.12/3.13 для данного RC, производительность на иных машинах и SLO для огромных графов.
- Безусловная низкая латентность на повреждённом supersedes-heavy graph: R8.2 добавляет проход по Evidence, R7.2 делает per-edge SQLite lookup для forged supersedes.

## 4. Исполнение и совместимость

RC1 проверен как набор библиотечных/runtime API. У него **нет отдельного обещанного CLI `anima.release_v02`**. Для базового интерактивного профиля по-прежнему доступен `anima.release_v01` по [протоколу v0.1](../v0.1/contract.md); он **не** является интерфейсом ко всем новым функциям Knowledge v0.2. Запускать только в новом выделенном каталоге экземпляра. Не изменять реальные пользовательские базы до отдельного read-only compatibility diagnostic, backup и оценки миграции.

## 5. Приёмочный и релизный критерий

- Точный SHA и дерево кода фиксированы независимо от документационного коммита.
- Локальный полный gate владельца: **2315 passed**, `scripts/check.sh` PASS, Python 3.14.4.
- Независимый H5.8: **PASS / APPROVE_RC**, полный **2315 PASS**, 62/62 оригинальных формальных H5.7 probes, 235 новых reviewer tests, H56/NEW/F historical controls в явно описанных границах.
- Все H57-01, H57-02, H57-03: **FIXED_VERIFIED**. Ни одного нового подтверждённого P0–P3 нарушения заявленного контракта в выполненной матрице.
- Не заменять релизный код документационным SHA. Не публиковать тег `v0.2.0-rc.1` на ветке документации.

Доказательства: [приёмка](acceptance.md), [release notes](release-notes.md). Утверждённые исследования и новые функции — отдельные последующие решения, не часть RC1.
