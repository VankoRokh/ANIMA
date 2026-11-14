# Эксплуатация ANIMA

**Для кого:** разработчик или оператор, запускающий экземпляр ANIMA на Linux. **Текущий продукт:** `ANIMA v0.1 Foundation` — кандидат, без финального тега. [Точный объём](versions/v0.1/contract.md) · [состав сборки](system/README.md) · [статус приёмки](versions/v0.1/acceptance.md).

Для организации каталогов `~/Projects`, локальных моделей, `llama.cpp`, Obsidian и временных worktree см. [рабочее пространство](workspace.md). Настройки экспериментальных путей не меняют `--data-dir` экземпляра v0.1.

## Требования и установка

В исходном проекте предусмотрены Linux, Bash, Git, Python **3.12 или новее** и `venv`. Разработческая зависимость `pytest` устанавливается через `requirements-dev.txt`. Ветка/коммит должны быть явными; успешная установка не доказывает release acceptance.

```bash
git clone https://github.com/VankoRokh/ANIMA.git
cd ANIMA
bash scripts/setup.sh
bash scripts/check.sh
.venv/bin/python -m pytest -q
```

Скрипт [`setup.sh`](../scripts/setup.sh) не перезаписывает существующую `.venv` при несовместимости. Для альтернативного интерпретатора: `ANIMA_PYTHON=python3.14 bash scripts/setup.sh`. Перед началом зафиксировать `git rev-parse HEAD`, `git status --short`, `python --version`.

## Запуск базового экземпляра v0.1

**Точка входа:** [`anima.release_v01`](../anima/release_v01.py); **только Linux/POSIX** из-за `fcntl.flock`. Выбрать новый пустой приватный каталог, не повторять путь старого CLI или лаборатории.

```bash
.venv/bin/python -m anima.release_v01 --data-dir "$HOME/anima-v01"
```

После `ready` вводить **по одному JSON-объекту на строку**, например:

```json
{"op":"report","text":"Unit ambercoil temperature reported as 82 C"}
{"op":"search_events","query":"ambercoil"}
{"op":"context","query":"ambercoil"}
{"op":"status"}
{"op":"stop"}
```

| Операция | Результат / ограничение |
| --- | --- |
| `report` | Сохраняет raw `conversation.user`, до 4096 символов; не создаёт trusted Observation |
| `search_events` | Ищет в raw `EventRetrieval`, до 5 результатов; требует полный индекс |
| `context` | Ограниченная Memory-only проекция (`max_items=4`, `max_chars=900`), **не** вызов FAST |
| `status` | `instance_id`, состояние, сессия, число Memories, статус индекса и capabilities |
| `stop` | Штатный выход, `Runtime.sleep()`; не запускает отдельный SLEEP WorkItem |

При некорректной команде протокол выдаёт `op=error`, но ошибки хранения/восстановления **не** маскируются под отрицательный результат поиска. `search_events` и `context` не утверждают «данных нет» при неполном индексе. Stdin — локальный операторский канал, **не аутентифицированный сервер**.

При повторном запуске использовать **тот же путь и тот же профиль**. `release_profile.json` закрепляет capabilities; `.anima-v01.lock` — кооперативная защита от второго штатного writer, не защита от процесса, открывающего SQLite напрямую.

## Дополнительный sandbox-профиль

```bash
.venv/bin/python -m anima.release_v01 --data-dir /tmp/anima-v01-sandbox --sandbox-door
```

Выбирать **другой новый каталог**, а не переключать существующий. Только в этом профиле доступна `{"op":"ensure_sandbox_door_closed"}`; инструмент работает с локальной SQLite-фикстурой, **не** с Godot, сетью или физическим устройством. Raw `report` по-прежнему не выдаёт права вызвать Tool.

Лаборатории VAL, M0–M6-B2 и ранний CLI `bash scripts/run.sh` **не являются** стандартным `release_v01`; их данные и профили доверия нельзя переносить незаметно. Исторические инструкции CLI сохранены в [прежнем документе](OPERATIONS/README.md#старый-интерактивный-cli), экспериментальные проверки — в [исследованиях](RESEARCH/README.md).

## Прежний интерактивный CLI (совместимость)

`bash scripts/run.sh` / `main.py` запускает **прежний терминальный интерфейс**, не JSONL `release_v01`. Для отдельного старого экземпляра можно задать `ANIMA_DATA_DIR`:

```bash
ANIMA_DATA_DIR="$HOME/anima-legacy-instance" bash scripts/run.sh
```

Не подставлять `ANIMA_DATA_DIR` вместо `--data-dir` в релизной команде. Старый путь данных может иметь другие схему и правила регистрации; **автоматического импорта в v0.1 нет**.

## Обновление кода

Перед `git pull --ff-only` проверить `git status --short --branch`, завершить экземпляр и сделать резервную копию. Если ветки разошлись, **не** использовать `reset --hard` как штатную процедуру. Изменение кода не равно миграции формата данных или source registry. Обновление с другой версией схемы требует отдельного явного плана и restore-теста.

Код и документы находятся в Git; **опыт ANIMA не хранится в Git**. Не добавлять пользовательский каталог данных, модели, секреты или `.venv` в репозиторий.

## Резервное копирование v0.1

**Предусловия:** отправить `stop`/закрыть процесс; убедиться, что экземпляр больше не работает. Нельзя копировать `events.jsonl` и несколько SQLite во время записи и обещать согласованный snapshot. В v0.1 память — `memory.db`; требование файла `memories.jsonl` из старой инструкции **не соответствует** текущему `release_v01`.

Пример для *отдельного тестового или собственного* `$HOME/anima-v01`, с доверенным Linux-хостом:

```bash
cd /path/to/ANIMA
instance="$HOME/anima-v01"
test -f "$instance/release_profile.json" || { echo "Not a v0.1 instance" >&2; exit 1; }
umask 077
backup="$HOME/ANIMA-backups/v01-$(date +%Y%m%d-%H%M%S)"
test ! -e "$backup" || { echo "Backup path exists" >&2; exit 1; }
mkdir -p -- "$backup"
tar -C "$instance" -czf "$backup/instance.tar.gz" .
git rev-parse HEAD > "$backup/git-commit.txt"
.venv/bin/python --version > "$backup/python-version.txt"
(cd "$backup" && sha256sum instance.tar.gz > instance.tar.gz.sha256)
```

Сохраняется **весь каталог**, в том числе `identity.json`, `state.json`, `events.jsonl`, SQLite, `release_profile.json`, исходный индекс и дополнительные sandbox-хранилища. Хэш показывает целостность архива при проверке, **не** его полноту или восстановимость. Независимая зашифрованная копия вне ноутбука, права доступа и политика ротации настраиваются оператором отдельно.

## Восстановление на отдельном пути

Делать **из доверенного собственного архива**; неизвестные tar-файлы могут содержать опасные пути и не должны распаковываться этим примером. Никакое восстановление не перезаписывает живой экземпляр.

```bash
cd /path/to/ANIMA
backup="/absolute/path/to/ANIMA-backups/v01-YYYYMMDD-HHMMSS"
(cd "$backup" && sha256sum -c instance.tar.gz.sha256)
tar -tzf "$backup/instance.tar.gz"       # сначала посмотреть состав
git checkout --detach "$(cat "$backup/git-commit.txt")"
bash scripts/setup.sh
bash scripts/check.sh
restored="$HOME/anima-v01-restored"
test ! -e "$restored" || { echo "Restore target exists" >&2; exit 1; }
mkdir -m 700 -- "$restored"
tar -C "$restored" -xzf "$backup/instance.tar.gz"
test -f "$restored/release_profile.json"
.venv/bin/python -m anima.release_v01 --data-dir "$restored"
```

Если архив относится к sandbox-профилю, последнюю команду выполняют **с тем же** `--sandbox-door`; несовпадение профилей должно завершаться отказом. После `ready` сверить прежний `instance_id`, доступность исходных Events и завершение `stop`. Нельзя объявлять восстановление успешным только по `sha256sum`: нужен реальный reopen и проверка данных. Для сохранения кодового окружения архивный commit следует восстановить в **отдельном checkout**; приведённый `git checkout --detach` выполняется только в подготовленном чистом рабочем дереве, иначе остановиться.

**Не доказано этим процессом:** power-loss durability, согласованность снимка, сделанного во время записи, защита от злоумышленника с доступом к хосту, произвольная миграция схем. Контрольные команды и уровни подтверждения — в [Verification](verification.md).
