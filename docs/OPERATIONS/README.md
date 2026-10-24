# Работа с проектом

## Установка

Linux, Bash, Git, Python 3.12+ и venv. На Ubuntu при необходимости установить
git/python3/python3-venv. Рабочий код и генератор документации используют
стандартную библиотеку; pytest — отдельная зависимость разработки.

```bash
git clone https://github.com/VankoRokh/ANIMA.git
cd ANIMA
bash scripts/setup.sh
bash scripts/check.sh
.venv/bin/python -m pytest -q
```

Setup создаёт .venv, проверяет версию и устанавливает requirements-dev.txt.
Существующую непригодную среду не удаляет. Другой интерпретатор:
`ANIMA_PYTHON=python3.14 bash scripts/setup.sh`.
Окружение создаётся заново, а не переносится между компьютерами.
Условия конкретных проверенных прогонов — в [результатах](../TESTING/Results/README.md).

## Запуск и обновление

```bash
bash scripts/run.sh
```

Одна строка ввода, затем Enter для сна; EOF/Ctrl+C на точках ввода также
завершают сессию. Скрипты выбирают .venv/bin/python, иначе python3;
ANIMA_PYTHON явно переопределяет выбор. Run работает из корня проекта.
Для внешнего экземпляра:

```bash
ANIMA_DATA_DIR="$HOME/anima-instance" bash scripts/run.sh
```

Правила путей и состав данных — в [архитектуре](../ARCHITECTURE/README.md#каталог-и-контракты-данных).
Без восстановленных данных запуск создаёт новый экземпляр.

Перед обновлением сохранить незавершённые изменения и проверить состояние:

```bash
git status --short --branch
git pull --ff-only
```

При расхождении веток выяснить причину; принудительный reset не является
процедурой обновления. Локальные незакоммиченные файлы ноутбука не видны через GitHub.
В VS Code открывается вся папка проекта, доступны Setup/Check/Test/Run/Update Docs.
Obsidian может открыть docs как vault; личные .obsidian/.trash не входят в Git.
Обычные относительные Markdown-ссылки и Mermaid читаются без Obsidian.

## Ведение документации

Один факт — одно каноническое место ([навигация](../README.md)).

| Изменение | Что редактировать |
|---|---|
| Текущая работа, порядок/статусы этапов | docs/project.json |
| Цель, критерии, сценарии этапа | ROADMAP/README.md |
| Нереализованная идея/эксперимент | ROADMAP/Research.md |
| Подтверждённый контракт/поведение | ARCHITECTURE/README.md с code/test links |
| Существенная причина/выбор | DECISIONS/README.md |
| Показательный прогон | Один TESTING/Results/TV-NNNN.md |
| Обычный успешный прогон | Документы не меняются |

project.json содержит schema_version=1, current_stage (ID), focus и stages.
У этапа: id, title, status, depends_on (IDs) и outcome для сводки.
Stage statuses: Planned/InProgress/Complete/Blocked; текущий этап не Complete.
Зависимости ссылаются на существующие IDs, без циклов; Complete требует
завершённых зависимостей. Статус — решение по критериям, он не выводится из
числа зелёных тестов автоматически. Содержательная смена критериев согласуется
с владельцем; мелкие исправления ссылок/разметки не требуют отдельного решения.

```bash
python3 scripts/update_docs.py
python3 scripts/update_docs.py --check
bash scripts/check.sh
```

JSON выбран вместо необязательного YAML-файла из обсуждения: читается штатной
библиотекой, не требует дополнительного пакета. Генератор обновляет только
AUTO:summary/roadmap/results между START/END; остальной текст сохраняется.
Обновление детерминировано, повтор не меняет файлы; --check ничего не пишет и
завершается ошибкой при устаревшей сводке. Ошибочные метаданные/маркеры также дают ошибку.

Версия читается из AnimaState._default_state без запуска экземпляра. Число тестов
и текущие результаты берутся из pytest, Git хранит историю — их не нужно
переписывать по страницам. Нет автозаписи текущей даты, HEAD или длительности
прогона в живые страницы. Даты/commit в отчётах обозначают исторические измерения.
Формат отчёта — [Testing](../TESTING/README.md#показательные-отчёты).

После изменения выполнить релевантные тесты и просмотреть `git diff --check`,
`git diff --stat`, `git diff`. Перед завершением сессии обновить focus, если
изменился следующий незаконченный шаг. После перерыва начать с docs/README,
Roadmap и последних commit; отдельная страница контекста помощнику не нужна.

## Резервирование

Остановить ANIMA до копирования: разные файлы при записи не образуют общий snapshot.
Git хранит код/документацию, а не опыт. Сохраняются весь каталог экземпляра,
commit кода и версия Python; в будущем — конфигурация/версии моделей. Секреты
остаются приватными; .venv не архивируется как переносимая среда.

Из корня проекта после хотя бы одной полной сессии:

```bash
task_python="${ANIMA_PYTHON:-$PWD/.venv/bin/python}"
task_data_dir="$("$task_python" -c 'from anima.config.paths import get_data_dir; print(get_data_dir())')"
task_backup_dir="$HOME/ANIMA-backups"
task_backup_stamp="$(date +%Y%m%d-%H%M%S)"
task_backup_file="$task_backup_dir/ANIMA-$task_backup_stamp.tar.gz"
mkdir -p -- "$task_backup_dir"

for name in state.json identity.json events.jsonl memories.jsonl; do
    test -f "$task_data_dir/$name" || {
        echo "Missing instance file: $task_data_dir/$name" >&2
        exit 1
    }
done

git rev-parse HEAD > "$task_backup_file.commit"
"$task_python" --version > "$task_backup_file.python"
tar -C "$task_data_dir" -czf "$task_backup_file" .
(
    cd -- "$task_backup_dir"
    sha256sum "$(basename "$task_backup_file")" > "$(basename "$task_backup_file").sha256"
)
```

Если рабочий каталог внешний, ANIMA_DATA_DIR должен быть тем же, что при запуске.
Архив/commit/python/sha256 скопировать на независимый носитель или приватное
хранилище. Копия на том же ноутбуке не покрывает его потерю. Резервировать после
значимых сессий и до смены схемы/переноса. Шифрование, ротация, расписание и место
реальной независимой копии ещё не настроены; исключение из Git копию не создаёт.

## Восстановление

Использовать доверенную копию. В её папке проверить соответствующий
`sha256sum -c ANIMA-....tar.gz.sha256` и `tar -tzf ANIMA-....tar.gz`.
Ожидается содержимое каталога экземпляра, возможно с `./`, без старого абсолютного пути.

```bash
git clone https://github.com/VankoRokh/ANIMA.git ANIMA-restored
cd ANIMA-restored
task_backup_file="/absolute/path/ANIMA-YYYYMMDD-HHMMSS.tar.gz"
task_commit="$(cat "$task_backup_file.commit")"
git checkout --detach "$task_commit"
bash scripts/setup.sh
bash scripts/check.sh

task_restore_data_dir="$PWD/data"
test ! -e "$task_restore_data_dir" || {
    echo "Restore target already exists: $task_restore_data_dir" >&2
    exit 1
}
mkdir -p -- "$task_restore_data_dir"
tar -C "$task_restore_data_dir" -xzf "$task_backup_file"
```

Путь может быть новым внешним каталогом. До запуска проверить identity/state,
session и JSONL, при доступном исходнике — побайтное совпадение. Затем:

```bash
ANIMA_DATA_DIR="$task_restore_data_dir" bash scripts/run.sh
```

Подтвердить прежний ID и продолжение истории. Сумма проверяет целостность архива,
продолжение экземпляра — восстановимость. Исходные повреждённые файлы сохраняются
для анализа. Если commit старше scripts, следовать его инструкциям и не запускать
произвольную новую версию как «миграцию». Несовместимость схем требует отдельного
плана и backup. Без копии Git не восстановит опыт.
Регрессия restore входит в pytest, а не в быстрый Check; ручное доказательство —
[TV-0001](../TESTING/Results/TV-0001.md).

Потерянная документация восстанавливается новым clone с предварительным
сохранением незакоммиченных заметок. Неотправленные изменения не восстанавливаются
из GitHub автоматически.
