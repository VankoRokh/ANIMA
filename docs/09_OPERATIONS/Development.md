---
document_type: guide
status: Accepted
updated: 2026-10-12
tags: [anima, operations]
---

# Работа в VS Code и Obsidian

## Получить обновление существующего проекта

В VS Code открыть **всю папку ANIMA** через File → Open Folder. Source Control показывает текущие изменения.

Во встроенном терминале из корня проекта:

```bash
git status --short --branch
git pull --ff-only
```

Если есть незавершённая работа — сначала сохранить её отдельным осмысленным commit или обсудить состояние. Если pull отказывается из-за расхождения веток, сохранить сообщение и выяснить причину. Обновление не требует принудительного сброса данных.

Локальные изменения на ноутбуке владельца помощнику автоматически не видны.

## Применить первый документационный этап

Прямое сохранение из рабочей среды отклонено подключением GitHub с 403. Подготовлен патч ANIMA_documentation_2026-10-12.patch к опубликованному состоянию 007b652. Положить его в корень локального ANIMA.

Сначала выполнить проверку:

```bash
git apply --check ANIMA_documentation_2026-10-12.patch
```

При успехе применить, затем выполнить Setup и Check:

```bash
git apply ANIMA_documentation_2026-10-12.patch
bash scripts/setup.sh
bash scripts/check.sh
```

При конфликте проверка останавливается до записи. Сохранить текущие изменения и текст ошибки; не применять патч с принудительными заменами.

После проверки редакторов сохранить только файлы системы; скачанный патч добавлять в репозиторий не нужно:

```bash
git add docs scripts .vscode README.md .gitignore
git diff --cached --check
git diff --cached --stat
git commit -m "Establish ANIMA documentation and recovery foundation"
git push
```

Перед публикацией обновить D0-05/D0-07 и Project_Status по фактически выполненным действиям. Если локальная ветка отличается от main, сначала определить целевую ветку; не менять её молча.

## Рабочие действия

| Действие | Способ |
|---|---|
| Вход в проект | docs/00_HOME/START_HERE.md |
| Показ Markdown | Ctrl+Shift+V |
| Preview рядом | Ctrl+K, затем V |
| Найти файл | Ctrl+P |
| Поиск по проекту | Ctrl+Shift+F |
| Изменения Git | Source Control |
| Окружение/проверка/запуск | Terminal → Run Task |

В актуальной документации VS Code Mermaid поддерживается встроенным Markdown preview. Если установленная старая версия показывает исходный блок, обновить редактор или открыть диаграмму в GitHub/Obsidian. [Markdown VS Code](https://code.visualstudio.com/docs/languages/markdown).

## Задачи проекта

Через Ctrl+Shift+P → Tasks: Run Task:

| Задача | Выполняется | Результат |
|---|---|---|
| ANIMA: Setup | bash scripts/setup.sh | Создана/проверена .venv |
| ANIMA: Check | bash scripts/check.sh | Изолированная проверка |
| ANIMA: Run | bash scripts/run.sh | Интерактивный запуск реального экземпляра |

Задачи используют встроенный терминал. Рекомендовано расширение Microsoft Python; для Bash-задач оно не обязательно. При нескольких Python выбрать .venv/bin/python через Python: Select Interpreter. [VS Code Tasks](https://code.visualstudio.com/docs/debugtest/tasks).

## Подключить Obsidian

Open folder as vault → выбрать **ANIMA/docs**. Открыть 00_HOME/START_HERE.

В Settings → Files and links:

- Use Wikilinks — выключить.
- New link format — Relative path to file.
- Automatically update internal links — включить.

Использовать обычные Markdown-ссылки. Они связывают страницы и без специальных плагинов. Исходники вне docs удобнее открывать в VS Code; ссылки на них также доступны в GitHub.

[Открытие vault](https://help.obsidian.md/manage-vaults), [настройки ссылок](https://help.obsidian.md/settings), [форматы ссылок](https://help.obsidian.md/links).

## Сессия разработки

1. Прочитать Project_Status, Current_Stage и нужную карточку модуля.
2. Выбрать одну задачу с критериями.
3. Изменить код и выполнить соответствующую проверку.
4. Обновить описание, статус и этап.
5. Просмотреть diff, убедиться в отсутствии данных экземпляра, сделать commit и push.

Для возобновления обновить текущую задачу и незаконченный шаг до ухода. [Documentation Rules](Documentation_Rules.md).
