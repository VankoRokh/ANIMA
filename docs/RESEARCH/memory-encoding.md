# Memory Encoding E1–E4: ассоциация, неопределённость и полномочия отзыва

**Граница:** ни E1–E4, ни `AliasLifecycleLab` не включены в Foundation как новый production MemoryProcessor, автономное Knowledge revision или Action-enabled L2. Не смешивать безопасность транзакции с полномочием источника.

## E1 — независимая shadow-ассоциация

[Результат 12 ноября](../ROADMAP/Memory_Encoding_E1_Results.md), SHA `5bf08efb0b2c85b69769bed9bd1b03afabce4cb6`, [CI](https://github.com/VankoRokh/ANIMA/actions/runs/43094616959): 20 synthetic Events / 12 gold групп, Legacy Composer 64/512 chars и `ShadowEpisodeEncoder`. Pairwise precision Legacy **11/21 = 0,524**, Shadow **11/11 = 1,000**, recall всех вариантов **11/11**. 10 ошибочных Legacy merge pairs, 0 Shadow на **этом** корпусе. Shadow учитывает session, валидированные Entity ID и минимум два значимых токена.

**Методологический предел:** Legacy 64 и 512 дали **одинаковую группировку**. E1 не доказал, что именно компрессия вызвала ошибки; не доказана польза shadow на длинных, мультиязычных или semantic-only continuations. Последующий adversarial probe в самом отчёте **вне таблицы E1** и не должен приписываться указанному CI без отдельного свидетельства.

## E2 — unverified relation candidates

[Контракт E2](../ROADMAP/Memory_Encoding_E2_Brief.md) вводит **непроверенные** возможные связи вместо автоматического merge. Исходный brief на 12 ноября указывает `CI/gold gate OPEN`; это не означает, что каждое последующее лабораторное выполнение осталось открытым. До указания точного более позднего проверенного артефакта не присваивать E2 production PASS. `Candidate` не равно утверждённое `Relation`.

## E3 — review uncertain episode links

[Контракт E3](../ROADMAP/Memory_Encoding_E3_Review_Brief.md): спорная ассоциация проходит отдельные отрицательные и adversarial проверки, включая ложный bridge и дедупликацию. Исходный brief отмечает `CI gate OPEN`; не подменять его более поздними лабораторными результатами без явной связи с SHA. E3 не даёт LLM права переписывать raw Events или автоматически соединять эпизоды.

## E4 — revision/alias lifecycle: последовательность проверок

| Срез и источник | Проверено | Что остаётся блокером |
| --- | --- | --- |
| [Post-alias authority + graph](../TESTING/Memory_E4_PostAlias_Authority_Graph_Gate_v0.md), SHA `e81526c7d59a4f7620484e1b8e82a17844a7b309`, 12 ноября | 1634 полных теста PASS, структурный oracle на DAG; **поддельный** `source="user"` *успешно отозвал чужой alias* | **AUTHORITY FAIL**, production NO-GO. Зелёный тест означает воспроизведение уязвимости |
| [Source Authority Gate](../TESTING/Memory_E4_Source_Authority_Gate_v0.md), SHA `382ef0f370340a3526d11ea456ff13aa1f7c4849`, 13 ноября | Отдельный guarded lab с synthetic admitted principal; 1648 full PASS в CI 3.12–3.14 | Никакой реальной аутентификации, обходы базовой лаборатории остаются |
| [Crash/Scale Exit Gate](../TESTING/Memory_E4_Crash_Scale_Exit_Gate_v0.md), SHA `901a49b8346a672b2cb44057f96878d8fcaef420`, 13 ноября | 1653 full PASS в CI, настоящий child `SIGKILL` до/после COMMIT в **одной SQLite**, synthetic 100/1000/10000 nodes | Нет power-loss, Pi parity, multi-DB atomicity, production admission, high fanout >128 |

**E4 final decision на проверенной границе:** bounded isolated research PASS; **production E4 revocation и autonomous/action-enabled L2 — NO-GO**. Источник может иметь корректный digest, `source` и session, но это **не** аутентифицированный principal. Trusted-adapter fixture не является реальным security perimeter. >128 descendants приводит к атомарному rollback, что защищает от частичной порчи, но блокирует доступность нужной коррекции.

### Масштаб — не SLA

На synthetic graph 100/1 000/10 000 узлов affected count **8/50/64**, median revoke **2,184/3,724/4,531 мс** на GitHub x86-64. Для самого большого графа **9 936 узлов не затронуты**; это не время отзыва 10 000 descendants. Три запуска недостаточны для tail percentile, RSS — high-water всего процесса. Отдельный PC/Pi E4 gate остаётся открытым.

## Следующее обоснованное действие

До production требуется внешний доверенный admission boundary, невозможность bypass, явная политика >128 descendants, масштабирование и восстановление на реальном workload. Однако ради выпуска Foundation **не нужно** расширять E4 или переносить его полномочия в Core. [Концептуальный контракт E4](../ROADMAP/Memory_E4_Architecture_Contract_Draft.md) остаётся draft, не ADR. [Исходные лабораторные спецификации](../TESTING/Laboratory_Integrations.md) не являются release acceptance.
