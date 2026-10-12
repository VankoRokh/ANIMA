# ANIMA

**Autonomous Neural Intelligence & Modular Architecture**

Проект модульного ИИ-агента с сохраняемым опытом, ролями Fast/Deep и перспективой сменного физического тела. Сейчас реализован Python-прототип 00.1-alpha: состояние сессий, события, сырой журнал и отбор непустого пользовательского ввода.

## Начать работу

[START_HERE](docs/00_HOME/START_HERE.md) → [состояние проекта](docs/00_HOME/Project_Status.md) → [карта](docs/00_HOME/System_Map.md) → [реестр модулей](docs/00_HOME/Module_Index.md).

- [Общая архитектура](docs/02_ARCHITECTURE/System_Architecture.md).
- [План и этапы](docs/06_ROADMAP/Roadmap.md).
- [Текущая задача](docs/06_ROADMAP/Current_Stage.md).
- [Архитектурные решения](docs/08_DECISIONS/README.md).
- [Контекст для нового ИИ-помощника](docs/00_HOME/AI_CONTEXT.md).

Документация на русском, форматы Markdown/Mermaid. VS Code открывает весь проект; Obsidian может открыть docs как vault.

## Проверить и запустить

Linux/Bash, Python 3.12+. Проверенная среда: Python 3.12.14. Текущий прототип использует стандартную библиотеку.

```bash
bash scripts/setup.sh
bash scripts/check.sh
bash scripts/run.sh
```

В VS Code доступны задачи **ANIMA: Setup / Check / Run**. [Развёртывание](docs/09_OPERATIONS/Setup.md), [работа в редакторах](docs/09_OPERATIONS/Development.md).

Check использует временные экземпляры. Run создаёт или продолжает реальный локальный data.

## Сохранение экземпляра

Код и документация находятся в Git. Персональный data исключён из репозитория и резервируется отдельно. Новый clone без восстановления data создаёт новое состояние.

[Backup](docs/09_OPERATIONS/Backup.md) и [Recovery](docs/09_OPERATIONS/Recovery.md).

## Текущее ограничение

EpisodicMemory читает events.jsonl, хотя отобранная память пишется в memories.jsonl. Identity и выделенный CLI пока пусты. Модели, эмоции и когнитивный сон ещё не реализованы. [Аудит](docs/03_SOFTWARE/Repository_Audit.md).

Цель проекта — открытое развитие; выбор лицензии пока в [Backlog](docs/06_ROADMAP/Backlog.md).
