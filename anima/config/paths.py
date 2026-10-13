import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_data_dir():
    configured = os.environ.get("ANIMA_DATA_DIR")

    if configured is None:
        return PROJECT_ROOT / "data"

    if not configured.strip():
        raise ValueError(
            "ANIMA_DATA_DIR must not be empty"
        )

    data_dir = Path(configured).expanduser()

    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir

    return data_dir.resolve()
