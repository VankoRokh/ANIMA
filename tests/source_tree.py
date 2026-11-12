"""Bounded source snapshots for tests, from current files rather than Git objects.

Git supplies tracked + nonignored pending paths when available. Source-only exports
use the same explicit file manifest. Neither mode copies a whole workspace.
Directory symlinks are never walked; selected file symlinks must resolve inside root.
"""

import os
from pathlib import Path
import re
import shutil
import subprocess

_ROOT_FILES = {"README.md", "main.py", ".gitignore"}
_ROOT_SUFFIXES = {
    "anima": {".py"}, "tests": {".py"}, "scripts": {".py", ".sh"},
    "config": {".json"}, ".vscode": {".json"}, "docs": {".md", ".json"},
}
# Only these laboratory source files are linked from project documentation.
# Documentation fixtures must carry the targets, not arbitrary labs or artifacts.
_EXP009_DOC_SOURCES = frozenset({
    Path("labs/exp009/c2_observe.py"),
    Path("labs/exp009/c2_memory_observe.py"),
    Path("labs/exp009/c2_memory_forensics.py"),
    Path("labs/exp009/graph_memory_probe.py"),
    Path("labs/exp009/c2_graph_compare.py"),
    Path("labs/exp009/c2_retrieval_abcd.py"),
    Path("labs/exp009/event_retrieval_c3.py"),
    Path("labs/exp009/memory_encoding_shadow.py"),
    Path("labs/exp009/memory_encoding_e2.py"),
    Path("labs/exp009/memory_encoding_e3.py"),
    Path("labs/exp009/episode_link_triage.py"),
    Path("labs/exp009/e4_l0_observation.py"),
    Path("labs/exp009/e4_l1_association.py"),
    Path("labs/exp009/e4_evaluator.py"),
})

# These are never source subdirectories, even when a filename looks like source.
_ARTIFACT_DIRS = {"__pycache__", "node_modules", "__pypackages__", "venv", "env",
                  "build", "dist", "target", "htmlcov", "coverage", "cache",
                  "logs", "backups", "snapshots", "private", "secrets"}
_PRIVATE_TOKENS = {"secret", "secrets", "private", "credentials", "password", "local"}


def _relative(name):
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or "\\" in str(name):
        raise ValueError("Source path escapes repository")
    return path


def _allowed(path):
    parts = path.parts
    if not parts:
        return False
    if any((part.startswith(".") and not (index == 0 and part == ".vscode"))
           or part.lower() in _ARTIFACT_DIRS for index, part in enumerate(parts[:-1])):
        return False
    tokens = set(re.split(r"[_.-]+", path.name.lower()))
    if tokens & _PRIVATE_TOKENS or (path.suffix == ".json" and tokens & {"key", "keys", "token", "tokens", "auth"}):
        return False
    if path in _EXP009_DOC_SOURCES:
        return True
    if len(parts) == 1:
        return path.name in _ROOT_FILES or (path.name.startswith("requirements") and path.suffix == ".txt")
    return (not path.name.startswith(".") and parts[0] in _ROOT_SUFFIXES
            and path.suffix in _ROOT_SUFFIXES[parts[0]])


def source_manifest(root):
    root = Path(root).resolve(strict=True)
    if (root / ".git").exists():
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard",
             "--", *_ROOT_FILES, "requirements*.txt", *_ROOT_SUFFIXES],
            check=True, capture_output=True,
        )
        names = [os.fsdecode(name) for name in result.stdout.split(b"\0") if name]
    else:
        names = [path.name for path in root.iterdir()]
        for directory in _ROOT_SUFFIXES:
            start = root / directory
            if not start.is_dir() or start.is_symlink():
                continue
            for parent, directories, files in os.walk(start, followlinks=False):
                directories[:] = [name for name in directories if not name.startswith(".")
                                  and name.lower() not in _ARTIFACT_DIRS
                                  and not (Path(parent) / name).is_symlink()]
                names.extend(str((Path(parent) / name).relative_to(root)) for name in files)
    # Include only existing, explicitly documented lab sources in both Git and
    # source-only modes. Keep the general lab tree excluded from source copies.
    names.extend(str(path) for path in _EXP009_DOC_SOURCES if (root / path).is_file())
    return tuple(sorted({path for name in names if _allowed(path := _relative(name))}))


def copy_source_tree(root, destination, *, paths=None):
    """Copy only a validated source manifest; do not mutate Git or consult HEAD.

    An explicit manifest is subject to the same path and file-type checks. The
    destination must be outside the source and absent, preventing recursive copies
    and accidental overwrites. Validation completes before destination creation.
    """
    root = Path(root).resolve(strict=True)
    destination = Path(destination).resolve()
    if destination.is_relative_to(root) or root.is_relative_to(destination):
        raise ValueError("Source snapshot destination must be outside repository")
    if destination.exists():
        raise ValueError("Source snapshot destination already exists")
    selected = source_manifest(root) if paths is None else tuple(_relative(name) for name in paths)
    files = []
    for path in selected:
        if not _allowed(path):
            raise ValueError(f"Not a project source path: {path}")
        source = root / path
        if not source.resolve().is_relative_to(root):
            raise ValueError(f"Source path escapes repository: {path}")
        if source.is_file():
            files.append((source, path))
    destination.mkdir(parents=True)
    for source, path in files:
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return tuple(path for _, path in files)
