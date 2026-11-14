# ANIMA v0.1 — карточка приёмки

**Дата решения: 15 ноября 2026 года. Статус: R-10 `ACCEPTED` (владелец утвердил выпуск).** R-08 — `ACCEPTED_SCOPED`, R-09 — `PASS`. **Публикация Git tag `v0.1` — отдельная операция, её успешность нельзя предполагать до проверки Git.**

## Неизменяемый релизный снимок

| Поле | Значение |
| --- | --- |
| Версия | **ANIMA v0.1 Foundation** |
| Проверенный Git SHA | `0c334a0cc51782eb460028f643ba7c2b83d5e821` |
| Ветки в момент решения | `develop`, `release/v0.1` — указанный SHA |
| Профиль | `anima.release_v01`, базовый без обязательной LLM, Godot, Pi, сенсоров и внешних capability |
| Дополнительная песочница | `--sandbox-door` только явным opt-in в отдельном экземпляре |
| R-10 | **Принят владельцем 15 ноября 2026 года** |
| Git tag `v0.1` | **Публикация ожидает подтверждения Git ref**; должен указывать на точный SHA выше |
| Последующие редакционные коммиты | Допускаются в `develop`, **не** меняют принятый release commit/tag |

Релизное описание: [release-notes.md](release-notes.md); норматив: [contract.md](contract.md); ограниченные ресурсы: [resources.md](resources.md).

## Матрица R-01–R-10

| Требование | Итог | Свидетельство |
| --- | --- | --- |
| **R-01–R-04** | **PASS** в пределах базового профиля | Запуск, Identity, Raw Events/Memory, provenance, reopen, ноутбучный release gate на финальном SHA |
| **R-05–R-07** | **PASS** в пределах sandbox-границ | Проверки Authority, Goal/Task, Verification, idempotent/recovery в полной матрице и release gate; **не** реальное отключение питания |
| **R-08** | **ACCEPTED_SCOPED** | Утверждены p95 report < 100 мс и peak process RSS < 256 MiB на фиксированном Linux/Python 3.14.4 gate с 128 событиями; на финальном SHA **9.305 мс / 33692 KiB** |
| **R-09** | **PASS** | Полный pytest **1806 PASS** в CI на Python 3.12, 3.13, 3.14 и на ноутбуке Python 3.14.4; документация, чистота checkout и функциональный gate |
| **R-10** | **ACCEPTED** | Явное решение владельца от 15 ноября 2026 года о выпуске версии v0.1 с известными ограничениями; публикация тега контролируется отдельно |

Успешные тесты не доказывают отсутствие всех ошибок и не расширяют контракт за пределы проверенных профилей.

## CI: точный SHA

**Две независимые матрицы на `0c334a0cc51782eb460028f643ba7c2b83d5e821`**:

- [`release/v0.1` — Actions run 43641219611](https://github.com/VankoRokh/ANIMA/actions/runs/43641219611): **3/3 SUCCESS**, 1806 `pytest` PASS на каждой Python 3.12/3.13/3.14.
- [`develop` — Actions run 43641007939](https://github.com/VankoRokh/ANIMA/actions/runs/43641007939): **3/3 SUCCESS** на том же SHA.

На каждом Python release gate обработал 128 Reports: `FUNCTIONAL_GATE_PASS`, `source_links=ALL_ACCOUNTED`, `identity_reopen=true`, `event_index_complete=true`, `model_calls=0`. Диагностические `plain` и `labeled` обработали по 160 Events: **8 Memory, 0 смешанных тем, 16/16 raw marker probes** в каждом режиме. JSON evidence сохранены в artifacts workflow.

## Локальная финальная проверка

Ноутбук владельца, Linux `7.0.0-43-generic`, x86_64, Python **3.14.4**, чистый detached worktree на точном релизном SHA:

- `bash scripts/check.sh`: **PASS** — 180 страниц, 1333 локальные ссылки, AST 375 Python-файлов, VS Code JSON (3), Bash syntax (3), без tracked instance data или личных настроек.
- Полный `pytest -q`: **1806 passed in 90.82 s**.
- `git status --short --branch`: `## HEAD (нет ветки)`, иных изменений нет.
- `uniform(1).json`: 128 Events, `FUNCTIONAL_GATE_PASS`, p95 **9.305 мс**, RSS **33692 KiB**, `ALL_ACCOUNTED`.
- `plain(1).json` / `labeled(1).json`: по 160 Events, **8 Memory / 0 смешанных**, 16/16 точных raw запросов, индекс и Identity восстановлены.

**SHA-256 локальных первичных JSON:**

```text
uniform(1).json  d670f6fab46c51f57bf4af27c8c1cd2e20841461fe90b9c512d845e0c02add03
plain(1).json    9f2b2a1ff64485346f2b01f68323e4b8b9115e3f23eaca60198c35feca7a91ea
labeled(1).json  3d2a5ecda516a5d9e250d154ac1d656f848270a95213044f05fdbc780b129238
```

Эти данные предоставлены владельцем и сверены с файлами; **не** являются независимым выполнением на его ноутбуке reviewer.

## Принятые ограничения

1. `MemoryProcessor` использует детерминированную эвристику: тест с известными структурными префиксами и двумя корпусами не доказывает корректную сегментацию любых естественных сообщений.
2. `RuleBasedComposer` ограничивает `Memory.content` **512 символами**. `ContextBundle` — сокращённая проекция, не гарантия полноты всех исходных фактов. Raw Events и Provenance остаются доступны через Event Retrieval.
3. Тесты не доказывают длительное масштабирование до сотен тысяч Events, resource SLO на другой машине, работу при реальном power-loss или на Raspberry Pi.
4. FAST/DEEP LLM, расширенный SLEEP, Stage 7 Knowledge, Godot/VAL и физические сенсоры не входят в обязательный базовый релиз.
5. Предшествующие уже смешанные Memory **не мигрируются автоматически**; развитие L2/семантического поиска — отдельный будущий проект.

## Решение владельца по R-10

**15 ноября 2026 года: «принимаем релиз и вносим данные в документацию».**

**Вердикт:** `ANIMA v0.1 Foundation — ACCEPTED` на точном SHA `0c334a0cc51782eb460028f643ba7c2b83d5e821`, с перечисленными ограничениями и без расширения scope.

Для публикации **аннотированный тег `v0.1` должен указывать на этот коммит**. Последующие изменения README/acceptance в `develop` — пострелизная документация; они не входят в исходное дерево `v0.1`. Создание GitHub Release допускается после проверки опубликованного тега, а не вместо проверки тега.

[К дорожной карте](../../roadmap.md) · [К контракту](contract.md) · [К ресурсам R-08](resources.md) · [К версии](release-notes.md).
