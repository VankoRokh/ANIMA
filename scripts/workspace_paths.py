"""Пути к общим моделям и llama.cpp для opt-in экспериментов.

Приоритет: CLI > окружение > config/workspace.local.json > ~/Projects.
Runtime v0.1 не использует этот модуль: его --data-dir всегда задаётся отдельно.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LOCAL_CONFIG = REPOSITORY_ROOT / "config" / "workspace.local.json"


def _read_config() -> dict:
    if not LOCAL_CONFIG.exists():
        return {}
    try:
        config = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Не удалось прочитать {LOCAL_CONFIG}: {exc}") from exc
    if not isinstance(config, dict):
        raise ValueError(f"{LOCAL_CONFIG}: ожидается JSON-объект")
    return config


def _absolute_path(value: object, source: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: ожидается непустая строка пути")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{source}: укажите абсолютный путь или ~/...")
    return path


def _override(config: dict, key: str, env_name: str) -> Path | None:
    if env_name in os.environ:
        return _absolute_path(os.environ[env_name], env_name)
    if key in config:
        return _absolute_path(config[key], f"{LOCAL_CONFIG}:{key}")
    return None


def _projects_root(config: dict) -> Path:
    return _override(config, "projects_root", "ANIMA_PROJECTS_DIR") or (
        Path.home() / "Projects"
    )


def projects_root() -> Path:
    """Рабочая папка, по умолчанию ~/Projects."""
    return _projects_root(_read_config())


def models_root() -> Path:
    """Каталог GGUF-моделей вне исходников ANIMA."""
    config = _read_config()
    return _override(config, "models_root", "ANIMA_MODELS_DIR") or (
        _projects_root(config) / "models"
    )


def llama_server_binary() -> Path:
    """Исполняемый llama-server в самостоятельном checkout llama.cpp."""
    config = _read_config()
    return _override(config, "llama_server", "ANIMA_LLAMA_SERVER") or (
        _projects_root(config) / "llama.cpp" / "build" / "bin" / "llama-server"
    )
