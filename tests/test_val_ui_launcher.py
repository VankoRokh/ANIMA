"""Desktop integration tests for Virtual ANIMA Lab (no Godot needed)."""

import configparser
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "labs/virtual_anima_lab/install_desktop_launcher.sh"


@pytest.fixture
def installer_env(tmp_path):
    data_home = tmp_path / "data"
    binary = tmp_path / "Godot_test"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    env = os.environ.copy()
    env.update({
        "GODOT_BIN": str(binary),
        "XDG_DATA_HOME": str(data_home),
    })
    return env, data_home / "applications/virtual-anima-lab.desktop"


def test_desktop_installer_is_syntactically_valid():
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)


def test_launcher_installs_user_only_with_normal_and_debug_actions(installer_env):
    env, destination = installer_env
    first = subprocess.run(["bash", str(INSTALLER)], env=env, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert destination.is_file()
    assert destination.stat().st_mode & 0o111 == 0

    parser = configparser.ConfigParser(interpolation=None)
    parser.read(destination, encoding="utf-8")
    main = parser["Desktop Entry"]
    assert main["Name"] == "Virtual ANIMA Lab"
    assert main["Terminal"] == "false"
    assert "--lab-scenario base --lab-ui normal" in main["Exec"]
    assert "Actions" in main
    assert main["Actions"] == "Detour;Clutter;Debug;"
    assert "--lab-scenario detour --lab-ui normal" in parser["Desktop Action Detour"]["Exec"]
    assert "--lab-scenario clutter --lab-ui normal" in parser["Desktop Action Clutter"]["Exec"]
    assert "--lab-scenario base --lab-ui debug" in parser["Desktop Action Debug"]["Exec"]

    previous = destination.read_bytes()
    second = subprocess.run(["bash", str(INSTALLER)], env=env, capture_output=True, text=True)
    assert second.returncode == 0, second.stderr
    assert destination.read_bytes() == previous


def test_launcher_missing_godot_is_fail_closed(installer_env):
    env, destination = installer_env
    env["GODOT_BIN"] = "/missing/godot/binary"
    result = subprocess.run(["bash", str(INSTALLER)], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "missing or not executable" in result.stderr
    assert not destination.exists()


def test_launcher_rejects_shell_escaping_in_paths(installer_env, tmp_path):
    env, destination = installer_env
    binary = tmp_path / "Godot binary"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    env["GODOT_BIN"] = str(binary)
    result = subprocess.run(["bash", str(INSTALLER)], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "unsupported characters" in result.stderr
    assert not destination.exists()
