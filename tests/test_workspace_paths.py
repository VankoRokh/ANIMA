"""Проверки локальных путей экспериментальных CLI без запуска моделей."""
import json
from pathlib import Path

import pytest

from scripts import workspace_paths as paths


ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = (
    "benchmark_stage5_v2.py",
    "benchmark_deep_baseline.py",
    "benchmark_deep_baseline_v02.py",
    "benchmark_deep_cross_role_order.py",
    "benchmark_deep_neutral_control.py",
    "benchmark_deep_order_probe.py",
    "run_stage5_smoke.py",
    "run_stage6_deep_smoke.py",
)
ENV_KEYS = ("ANIMA_PROJECTS_DIR", "ANIMA_MODELS_DIR", "ANIMA_LLAMA_SERVER")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "LOCAL_CONFIG", tmp_path / "workspace.local.json")
    monkeypatch.setenv("HOME", str(tmp_path))
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return tmp_path


def write_config(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def test_defaults_preserve_existing_layout(workspace):
    assert paths.projects_root() == workspace / "Projects"
    assert paths.models_root() == workspace / "Projects/models"
    assert paths.llama_server_binary() == (
        workspace / "Projects/llama.cpp/build/bin/llama-server"
    )


def test_projects_root_rebases_derived_paths(workspace):
    target = workspace / "other-projects"
    write_config(paths.LOCAL_CONFIG, {"projects_root": str(target)})
    assert paths.projects_root() == target
    assert paths.models_root() == target / "models"
    assert paths.llama_server_binary() == target / "llama.cpp/build/bin/llama-server"


def test_local_specific_overrides(workspace):
    model_dir = workspace / "shared-gguf"
    server = workspace / "bin/llama-server"
    write_config(
        paths.LOCAL_CONFIG,
        {"models_root": str(model_dir), "llama_server": str(server)},
    )
    assert paths.models_root() == model_dir
    assert paths.llama_server_binary() == server


def test_environment_takes_precedence_over_local_config(workspace, monkeypatch):
    configured = workspace / "configured"
    write_config(
        paths.LOCAL_CONFIG,
        {
            "projects_root": str(configured),
            "models_root": str(configured / "models"),
            "llama_server": str(configured / "llama-server"),
        },
    )
    override = workspace / "override"
    monkeypatch.setenv("ANIMA_PROJECTS_DIR", str(override))
    monkeypatch.setenv("ANIMA_MODELS_DIR", str(override / "gguf"))
    monkeypatch.setenv("ANIMA_LLAMA_SERVER", str(override / "server"))
    assert paths.projects_root() == override
    assert paths.models_root() == override / "gguf"
    assert paths.llama_server_binary() == override / "server"


def test_environment_projects_root_rebases_without_specific_overrides(
    workspace, monkeypatch
):
    root = workspace / "another-root"
    monkeypatch.setenv("ANIMA_PROJECTS_DIR", str(root))
    assert paths.models_root() == root / "models"
    assert paths.llama_server_binary() == root / "llama.cpp/build/bin/llama-server"


@pytest.mark.parametrize("value", [[], None, {"models_root": 3}])
def test_invalid_config_values_are_rejected(workspace, value):
    write_config(paths.LOCAL_CONFIG, value)
    with pytest.raises(ValueError):
        paths.models_root()


def test_bad_json_is_rejected(workspace):
    paths.LOCAL_CONFIG.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="Не удалось прочитать"):
        paths.models_root()


@pytest.mark.parametrize("raw", ["", "relative/models", "  "])
def test_invalid_environment_paths_are_rejected(workspace, monkeypatch, raw):
    monkeypatch.setenv("ANIMA_MODELS_DIR", raw)
    with pytest.raises(ValueError, match="ANIMA_MODELS_DIR"):
        paths.models_root()


def test_experiment_scripts_have_no_independent_home_projects_defaults():
    for name in BENCHMARKS:
        source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "Projects/models" not in source, name
        assert "Projects/llama.cpp" not in source, name
        assert "from scripts.workspace_paths import" in source, name


def test_existing_cli_overrides_remain_available():
    root_scripts = (
        "benchmark_stage5_v2.py",
        "benchmark_deep_baseline.py",
        "benchmark_deep_baseline_v02.py",
        "benchmark_deep_cross_role_order.py",
        "benchmark_deep_neutral_control.py",
        "benchmark_deep_order_probe.py",
    )
    for name in root_scripts:
        content = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "--models-root" in content
        assert "--server-binary" in content
    smoke5 = (ROOT / "scripts/run_stage5_smoke.py").read_text(encoding="utf-8")
    smoke6 = (ROOT / "scripts/run_stage6_deep_smoke.py").read_text(encoding="utf-8")
    assert "--model-file" in smoke5 and "--server-binary" in smoke5
    assert "--model" in smoke6 and "--binary" in smoke6
