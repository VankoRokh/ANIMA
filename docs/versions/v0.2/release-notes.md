# ANIMA v0.2.0-rc.1 — Release Candidate 1

**Профиль:** локальная детерминированная обработка Memory, Knowledge, Evidence и Context.  
**Дата допуска владельцем:** 19 ноября 2026 года.  
**Проверенный commit:** `1364e62634669ef553df0b2f2d7a1159d404383f`.  
**Audit:** H5.8 **PASS / APPROVE_RC** в ограниченном профиле.  
**Официальный Git tag:** аннотированный `v0.2.0-rc.1` **опубликован и проверен**; GitHub Pre-release **опубликован** и доступен [по тегу](https://github.com/VankoRokh/ANIMA/releases/tag/v0.2.0-rc.1). Документационная ветка не заменяет tag.  
**Тип выпуска:** prerelease / Release Candidate, **не stable v0.2**.

## Кратко

ANIMA v0.2 RC1 — продолжение проверенного детерминированного ядра v0.1. Версия развивает слои Memory/Knowledge/Provenance и исправляет обнаруженные независимыми аудитами ошибки в lifecycle, temporal Evidence, source integrity, Context Coverage, recovery и границах записи.

**Этот выпуск не превращает ANIMA в чат-бота или полностью автономную когнитивную систему.** Работа локального Core, Identity и событий остаётся независимой от обязательного LLM inference.

## Главное в v0.2 RC1

- Физическая привязка опубликованных Knowledge Evidence к каноническим Raw Events через CLOSED Memory и проверяемые source mappings; fail-closed при отсутствующих, повреждённых и дублированных Raw.
- Явный lifecycle `KnowledgeLayer` с переходами `confirm/challenge/reject/supersede`, History и временными Relations `supports/contradicts`; препятствия против generic status/Relation обходов.
- Проверяемые half-open интервалы `[created_at, valid_until)`, UTC offsets, future/expired/finite Evidence; обязательная validation всех attached интервалов до Knowledge publication.
- Запрет stale Memory candidate/source-set, source-only merge race, противоречивых Writers и повторного применения уже завершённой проекции в current processor namespace.
- `RetrievalEngine` и `ContextBuilder`: deterministic FAST/DEEP selection, entity/graph associations в пределах контрактов, бюджетирование без скрытого разрезания записей, tri-state coverage, проверка формы custom adapter кандидатов до selection и trace.
- SQLite schema-version preflight и транзакционный bootstrap без записи при неподдерживаемой схеме; проверенные сценарии logical backup/restore, software crash, reopen и Recovery.
- R8.0: свежий Raw-backed proof, созданный после challenge, допускается при одинаковой секундной отметке `confirm`; прежний source не становится новым только из-за новых отношений.
- R8.1: неподдерживаемый `kind` или повреждённый record adapter отвергается, а не исчезает как `complete=True`.
- R8.2: malformed Evidence timestamp даёт последовательный `ValueError` до datetime comparisons и сохраняет rollback.
- R8.3: cross-module integration tests Raw → Memory → Knowledge → FAST/DEEP Context → reopen/recover и отрицательные аварийные проверки.

## Проверка

| Контроль | Фактический результат |
| --- | --- |
| Локальный full pytest владельца на кодовом SHA | **2315 passed / 97.09 s**, Python 3.14.4 |
| Документационный gate на кодовом SHA | PASS, 182 страницы / 1334 ссылок |
| Независимый H5.8 full pytest | **2315 passed**, exit 0 |
| H5.7 original formal findings на H5.8 | **62 passed**, exit 0; на H5.7 control 6 failed / 56 passed |
| Дополнительные независимые H5.8 проверки | **235 passed**, включая negative/crash/recovery |
| H57-01–03 | **FIXED_VERIFIED** |
| H56-01–06, NEW-01–07, F-01–08 | Исторические контракты в заявленной границе сохранены |
| Independent verdict | **PASS / APPROVE_RC** для доверенного профиля |

Тестовые количества из разных прогонов **не суммируются** как количество уникальных тестов. Независимый аудит не охватывает все возможные состояния.

## Ограничения (обязательно читать)

**O58-01 — новизна Evidence:** один Raw Event может обслуживать несколько разных Memory ID. После challenge новая Memory, ссылающаяся на прежний Raw, иногда способна вновь подтвердить Knowledge. Новизна по Memory/Relation ID **не равна независимости первичного свидетельства**.

**O58-02 — достоверность adapters:** custom adapter может сохранить канонический ID, но подменить text payload. Даже DEEP с настоящим provenance по ID не доказывает, что adapter text соответствует канонической Memory. **Только доверенные adapters/writers** входят в этот RC.

Остаются вне RC: automatic aging Knowledge, immutable historic Memory text, `candidate=None` global ranking freshness, криптографическая Raw integrity, намеренно враждебный SQLite/Raw writer, power-loss, разные Python builds, ARM64/Raspberry Pi latency, real legacy data migrations и LLM inference/самостоятельная автономия. Отсутствует SLO для malformed/forged-heavy graphs; на синтетике 50k forged supersedes до ~50k SQLite connections и ~10 s.

Не объявлять структурную валидацию адаптеров semantic truth guard. Не считать coverage доказательством полноты всех исходных фактов или подтверждением реальности знания.

## Как использовать

RC1 адресован разработчикам и исследователям **API `anima.memory.*` и Core**, а не конечному пользователю с установленным приложением. При использовании кода:

1. Получать исходники по конкретному SHA либо по опубликованному и проверенному тегу `v0.2.0-rc.1`.
2. Создавать **отдельную новую директорию данных**; не подключать существующую реальную legacy базу без offline compatibility/backup/verify.
3. Использовать доверенные Memory/Raw writers и Retrieval adapters; сохранять provenance.
4. Для базового текстового профиля доступен существующий `python -m anima.release_v01 --data-dir /tmp/anima-v02-rc1-instance`. Это **launcher базового v0.1-профиля**, не отдельный v0.2 CLI и не демонстрация всех новых Knowledge/Context API.
5. `bash scripts/check.sh` и `python -m pytest -q` относятся к исходному зафиксированному checkout, с доступным Python/pytest.

## Принятие, публикация и следующие шаги

- Решение владельца 19.11.2026: **допустить SHA `1364e626...` к статусу RC**.
- Релизная ветка `release/v0.2.0-rc.1` должна быть **идентична** проверенному SHA.
- Аннотированный Git tag `v0.2.0-rc.1` **указывает на этот SHA** (проверено через GitHub Git API). Запрещён `--force`.
- GitHub Release **опубликован по существующему тегу** с флагом **Pre-release** (`prerelease=true`, `draft=false`); исходный код не изменён.
- Постприёмочные docs могут жить на отдельной ветке и обновлять навигацию; они **не меняют tree тега**.
- Git tag и [GitHub Pre-release](https://github.com/VankoRokh/ANIMA/releases/tag/v0.2.0-rc.1) подтверждены через GitHub API.
- После публикации RC допускается новый отдельный этап исследований: Evidence source identity/O58-01, канонический текст/O58-02, метапамять и работа с новыми когнитивными модулями — без обратной записи в RC.

Полный [контракт](contract.md), [карточка приёмки](acceptance.md), исторический [H5.8 audit brief](https://github.com/VankoRokh/ANIMA/blob/work/v02-h58-independent-audit-prep/docs/TESTING/ANIMA_v0_2_H5_8_Independent_Reaudit_Brief.md).
