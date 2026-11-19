# ANIMA v0.2 — R6.1 Knowledge Write Authority

**Статус:** IMPLEMENTED / LOCAL TESTS NOT YET REPORTED. Не является release approval и не закрывает весь v0.2 RC.

**Основа:** принятый R6.0, commit `1ba0bb0c2da147cd3df2ed82f23689818596f4ee`.
**Основание:** независимый H5.5 post-remediation audit, находки NEW-01 (P1) и NEW-02 (P1).

## Контракт

1. `LinkStore.create_knowledge()` создаёт только `provisional`. `confirmed`, `challenged`, `rejected`, `superseded` требуют явного перехода через `KnowledgeLayer` (Evidence + History). Отдельного публичного import-mode сейчас нет.
2. `LinkStore.create_relation()` не может вставлять `supports/contradicts` в Knowledge, чей статус уже не `provisional`. Проверка статуса находится внутри SQLite writer transaction. Публичная подготовка Evidence на `provisional` сохраняется; R3 overlap guard действует независимо от статуса.
3. `KnowledgeLayer.confirm/challenge/reject/supersede` перед публикацией проверяют **все** прикреплённые `supports/contradicts` (в том числе ранее добавленные на `provisional` и будущие/исторические): согласованность Memory provenance, существование Memory и непустые физические Raw source Events. Только Evidence, действующее в момент перехода по полуоткрытому интервалу, должно быть CLOSED именно тогда. Упорядоченность и наличие нужных доказательств для конкретного перехода сохраняют прежние проверки H2.2/R2–R5.
4. Offline H5.0 диагностирует статусы без соответствующей lifecycle History, а также повреждённое опубликованное Evidence без Memory/Raw sources; H5.4b обязан возвращать BLOCKED для таких повреждений. Ничего не ремонтирует.
5. Ветку не сливать и не маркировать релизом до полной локальной регрессии и независимого реаудита. Положительные тесты старого H2.2 и F-04 сохраняются; старую негативную SQL-legacy фикстуру `test_h2_2_orphan_contradiction_cannot_reject_knowledge` исправили так, чтобы она не использовала теперь запрещённый public writer.

## Вне R6.1

- NEW-03: прямой `MemoryProcessor` concurrency — R6.2.
- NEW-04/05: конечные Evidence intervals и adapter retrieval metadata — R6.3.
- NEW-06: dangling source owner в recovery — R6.4.
- Произвольные SQL/некооперативные Raw writers, семантическая истинность Raw ID и общая cross-file atomicity **не гарантированы**.
- Запрет позднего Evidence до будущего revision API преднамеренный; не добавлять обход через параметр `unsafe`, `force` или специальные тестовые режимы.

## Локальная приёмка

Работать в отдельном worktree точного SHA ветки; не изменять экземпляры пользователя.

```bash
git fetch origin
git rev-parse HEAD
git status --short
PYTHONPATH="$PWD" .venv/bin/python -m pytest -q -rx \
  tests/test_v02_r6_1_knowledge_write_authority.py \
  tests/test_v02_h2_2_evidence.py \
  tests/test_v02_h55_r3_evidence_consistency.py \
  tests/test_v02_h55_r5_standalone_raw_authority.py
bash scripts/check.sh
PYTHONPATH="$PWD" .venv/bin/python -m pytest -q -rx
```

**Условия PASS:** все новые отрицательные сценарии отказывают без новых Relations/History/статусов; валидный Knowledge lifecycle продолжает работать; H5.0/H5.4b блокируют повреждённые legacy snapshots; полная регрессия и `scripts/check.sh` завершаются с кодом 0. Отчёт владельца должен содержать точный SHA.

**Не заявлять PASS заранее.** Пакет тестов написан, но в среде GitHub connector исполняемый Python checkout отсутствует.
