# Проверка проекта и доказательств

**Цель:** различать «ссылка работает», «тест прошёл», «лаборатория подтвердила гипотезу» и «версия принята». Источники истины: [релизный контракт](versions/v0.1/contract.md), [карточка приёмки](versions/v0.1/acceptance.md), [исторические TV](TESTING/Results/README.md) и исходные отчёты экспериментов.

## Уровни проверки

| Уровень | Чем проверяется | Что подтверждает | Чего не подтверждает |
| --- | --- | --- | --- |
| 0 — static docs | `scripts/update_docs.py --check`, `scripts/check.sh` | Согласованность metadata/AUTO, локальных Markdown paths/anchors, достижимость страниц, AST/shell/JSON | Исполнение Core или корректность результата |
| 1 — targeted regression | `pytest` с явными файлами и негативными случаями | Конкретные проверяемые инварианты и отказ по заданным условиям | Отсутствие других дефектов |
| 2 — полный regression | `python -m pytest -q` на зафиксированном tree | Совместимость известных тестов выбранного snapshot | Release acceptance без утверждённых требований |
| 3 — functional gate | `scripts.run_release_v01_gate` | Identity, Events, provenance, replay, sandbox, bounded ресурсы в фиксированном корпусе | Production SLO, весь внешний мир, произвольный power-loss |
| 4 — independent lab / hardware | Собственные runner, версия Python/Godot/Pi, raw JSON, SHA и negative fixtures | Только указанный профиль, workload и сбои | Автоматическое включение исследования в релиз |
| 5 — release decision | R-01–R-10, CI, review, явное решение владельца | Принятие конкретного тега и границ версии | Универсальные гарантии за пределами профиля |

`Passed`, `Failed`, `Inconclusive` — результаты **отчёта**, а не свойства всего ANIMA. В частности, [TV-0053](TESTING/Results/TV-0053.md) остаётся `Inconclusive`, даже если отдельные ответы модели прошли, а [TV-0054](TESTING/Results/TV-0054.md) относится к своей границе Core/PC/Pi.

## Команды для чистого Git checkout

```bash
git rev-parse HEAD
git status --short --branch
python3 scripts/update_docs.py --check
bash scripts/check.sh
.venv/bin/python -m pytest -q tests/test_documentation.py
.venv/bin/python -m pytest -q tests/test_release_v01.py tests/test_release_v01_acceptance.py
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.run_release_v01_gate --events 128 --report /tmp/anima-v01-new-unique.json
git diff --check
git status --short --branch
```

`--report` должен указывать **на новый, не существующий** JSON-файл; runner использует `open("x")` и не перезаписывает evidence. Для машинной приёмки нужна идентичность дерева до и после: commit SHA, чистота рабочего каталога, окружение и результаты. Если прогон выполнялся на грязном дереве, нельзя выдавать его как доказательство принятого `HEAD`. После финального документационного commit повторить хотя бы static check и полную релевантную матрицу — старые результаты не переносятся автоматически.

На GitHub Actions проверять **точный commit head/merge checkout**, Python 3.12, 3.13, 3.14 и состояние всех обязательных jobs. PR run может использовать временный merge SHA; нельзя выдавать его за SHA ветки без различения двух идентификаторов. Ссылка на конкретный run/артефакт — часть evidence.

## Что делает `scripts/check.sh`

[`scripts/check.sh`](../scripts/check.sh) вызывает [`check_project.py`](../scripts/check_project.py). Текущий checker:

1. проверяет [`project.json`](project.json) и исходные TV metadata через [`update_docs.py`](../scripts/update_docs.py), два generated AUTO-блока;
2. проверяет локальные Markdown-ссылки и heading anchors, запрет выхода за корень, замкнутые fences, достижимость всех Markdown-страниц от `docs/README.md`;
3. сверяет строки канонической [архитектурной таблицы](system/README.md#разделы-по-ответственности) с существующими Python-кодом **и** профильным тестом;
4. разбирает Python через AST, `.vscode/*.json` через JSON parser, `scripts/*.sh` через `bash -n`, проверяет расположение CLI;
5. в Git checkout убеждается, что tracked `data/`, `models/`, backups, `.env` и локальные настройки не вошли в индекс.

Если checkout без `.git`, проверка tracked paths **пропускается**; это надо обозначать в отчёте. Скрипт не проверяет удалённые URL, не запускает Python-бизнес-логику и не удостоверяет подлинность внешнего источника.

## Поведение релизного gate и статус ресурсов

[`scripts.run_release_v01_gate`](../scripts/run_release_v01_gate.py) предназначен для provisional notebook acceptance. В отчёте записываются `source_sha`, `checkout_clean`, `python`, `machine`, `events`, `identity_reopen`, `source_links`, `sandbox_effects`, `report_latency_ms`, RSS и размеры хранилища. `test_status=FUNCTIONAL_GATE_PASS` не делает `performance_status=MEASURED_NOT_SLO_GATED` автоматически SLO.

Исторические p95 **9,823 мс**, RSS **33 640 KiB** относятся к [старому ноутбучному снимку](RELEASES/ANIMA_v0_1_Notebook_Evidence.md). **R-08 принято в ограниченном профиле**: p95 < 100 мс и RSS < 256 MiB на Linux x86-64 / Python 3.14.4 / фиксированных 128 reports. Измерения после исправления Memory и границы [зафиксированы отдельно](versions/v0.1/resources.md) на SHA `6203e3f355fda0c9ec8a4377f6106ee51795f49e`. Runner продолжает печатать `MEASURED_NOT_SLO_GATED` как первичный результат измерения — принятие нормы документируется в release acceptance, а не подменяет поле JSON. **R-09** — проверка окончательного дерева, **R-10** — формальный вердикт и тег.

## Требования к доказательству

| Поле | Что указывать |
| --- | --- |
| Идентичность | commit SHA ветки, при CI — фактический checkout SHA, clean/dirty status |
| Окружение | OS, CPU/архитектура, Python и версии зависимостей, модель/Godot/Pi если участвовали |
| Контракт | версия интерфейса, профиль, scope теста, начальные и негативные условия |
| Наблюдения | команды, expected/actual, `PASS/FAIL/Inconclusive`, счетчики и raw log/JSON |
| Интерпретация | что доказано, что **не** доказано, ограничения репликации |
| Решение | какая функция интегрирована/отклонена и что всё ещё блокирует выпуск |

**Исторический TV** имеет frontmatter `id,title,date,stage,result,snapshot` и обязательные разделы «Цель», «Условия», «Сценарий и входные данные», «Ожидаемый результат», «Фактический результат», «Метрики», «Доказано», «Не доказано». Его статус и snapshot не меняют задним числом; новый gate — новый отчёт или ссылочная запись, а не выдуманный PASS. Подробнее — [исходные правила тестирования](TESTING/README.md#показательные-отчёты) и [правила документации](documentation.md).

## Перед финальной приёмкой R-09/R-10

- Проверить [структуру документации](documentation.md), историю Stage и сохранение 54 исходных отчётов, включая frozen evidence; статус старого PR #7 не является релизным критерием.
- На **точном релизном Git SHA** запустить полный `python -m pytest -q` на Python 3.12/3.13/3.14 и сохранить фактический checkout SHA. Прогон синтетического PR merge checkout отличать от прогона head/release commit.
- На каждом Python проверить 128-event functional gate и сохранить JSON; на ноутбуке выполнить независимую локальную проверку финального SHA.
- Проверить, что документация не объявляет `v0.1` принятым до отдельного решения владельца и создания тега. После последнего документационного commit обязательные проверки должны относиться к **новому** дереву.
