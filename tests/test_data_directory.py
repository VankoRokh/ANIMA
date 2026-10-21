import shutil

import pytest

from anima.config.paths import PROJECT_ROOT, get_data_dir
from tests.harness import AnimaTestHarness


def test_default_data_directory_is_project_data(
    monkeypatch,
):
    monkeypatch.delenv(
        "ANIMA_DATA_DIR",
        raising=False,
    )

    assert get_data_dir() == PROJECT_ROOT / "data"


def test_absolute_data_directory_is_used(
    tmp_path,
    monkeypatch,
):
    custom_data = tmp_path / "custom-data"

    monkeypatch.setenv(
        "ANIMA_DATA_DIR",
        str(custom_data),
    )

    assert get_data_dir() == custom_data.resolve()


def test_relative_data_directory_is_project_relative(
    monkeypatch,
):
    monkeypatch.setenv(
        "ANIMA_DATA_DIR",
        "test-data",
    )

    assert (
        get_data_dir()
        == (PROJECT_ROOT / "test-data").resolve()
    )


def test_empty_data_directory_is_rejected(
    monkeypatch,
):
    monkeypatch.setenv(
        "ANIMA_DATA_DIR",
        "   ",
    )

    with pytest.raises(
        ValueError,
        match="ANIMA_DATA_DIR must not be empty",
    ):
        get_data_dir()


def test_copied_data_preserves_instance_identity(
    tmp_path,
):
    original_dir = tmp_path / "original"
    copied_dir = tmp_path / "copied"

    original = AnimaTestHarness(original_dir)

    original_id = (
        original.snapshot()["identity"]["instance_id"]
    )

    shutil.copytree(
        original_dir,
        copied_dir,
    )

    copied = AnimaTestHarness(copied_dir)

    copied_id = (
        copied.snapshot()["identity"]["instance_id"]
    )

    assert copied_id == original_id
