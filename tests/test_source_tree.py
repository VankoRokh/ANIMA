"""Source snapshots must be bounded without losing pending implementation files."""

from pathlib import Path
import subprocess

import pytest

from tests.source_tree import copy_source_tree, source_manifest


def write(root, name, content="sentinel"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_source_only_tree_excludes_local_artifacts_and_keeps_pending_source(tmp_path):
    root = tmp_path / "source"
    write(root, "README.md", "current docs")
    write(root, "anima/new_production_module.py", "VALUE = 42\n")
    write(root, "anima/benchmarks/gateway.py", "# legitimate production source\n")
    write(root, "tests/test_pending.py", "# legitimate pending test\n")
    write(root, "docs/ROADMAP/pending.md", "# pending docs\n")
    write(root, "docs/project.json", "{}")
    write(root, "docs/SCHEMAS/example.schema.json", "{}")
    write(root, "config/pending.json", "{}")
    write(root, ".vscode/settings.json", "{}")
    artifacts = [
        ".venv-qwen-agent/package.py", ".venv-other/package.py", "venv/package.py",
        ".benchmarks/raw.json", "logs/trace.log", "backups/private.py", "snapshots/state.json",
        "models/model.gguf", "build/generated.py", "dist/generated.py", "htmlcov/index.html",
        ".coverage", ".env", ".env.production", "qwen_tool_trace.log", "random.py",
        "docs/.obsidian/settings.json", "docs/.trash/private.md", "docs/private/notes.md",
        "docs/private/config.json", "docs/secret.json", "docs/auth.json",
        "config/credentials.json", "config/settings.local.json", "config/api_key.json", "anima/secrets.py",
        "anima/__pycache__/cache.py", "anima/build/generated.py", "tests/.cache/cache.py",
    ]
    for name in artifacts:
        write(root, name)
    assert not (root / ".git").exists()
    destination = tmp_path / "copy"
    copied = set(copy_source_tree(root, destination))
    assert Path("anima/new_production_module.py") in copied
    assert (destination / "anima/new_production_module.py").read_text() == "VALUE = 42\n"
    assert (destination / "anima/benchmarks/gateway.py").exists()
    assert (destination / "docs/project.json").exists()
    assert (destination / "docs/SCHEMAS/example.schema.json").exists()
    assert (destination / ".vscode/settings.json").exists()
    assert (destination / "config/pending.json").exists()
    assert (destination / "tests/test_pending.py").exists()
    assert (destination / "docs/ROADMAP/pending.md").exists()
    assert all(not (destination / name).exists() for name in artifacts)


def test_only_documented_exp009_sources_are_copied(tmp_path):
    root = tmp_path / "source"
    write(root, "README.md", "source")
    documented = (
        "c2_observe.py",
        "c2_memory_observe.py",
        "c2_memory_forensics.py",
        "graph_memory_probe.py",
        "c2_graph_compare.py",
        "c2_retrieval_abcd.py",
        "event_retrieval_c3.py",
        "memory_encoding_shadow.py",
    )
    for name in documented:
        write(root, f"labs/exp009/{name}", f"# {name}\n")
    write(root, "labs/exp009/unreferenced.py", "# not in documentation")
    write(root, "labs/other/fixture.py", "# not in documentation")
    write(root, "labs/exp009/secret.json", '{"token": "not a source"}')

    copied = set(copy_source_tree(root, tmp_path / "copy"))
    for name in documented:
        path = Path("labs/exp009") / name
        assert path in copied
        assert (tmp_path / "copy" / path).is_file()
    assert Path("labs/exp009/unreferenced.py") not in copied
    assert Path("labs/other/fixture.py") not in copied
    assert Path("labs/exp009/secret.json") not in copied


def test_external_directory_symlink_is_never_walked(tmp_path):
    root = tmp_path / "source"
    write(root, "anima/valid.py", "# valid\n")
    external = tmp_path / "external"
    write(external, "private.py")
    (root / "anima/external").symlink_to(external, target_is_directory=True)
    copy_source_tree(root, tmp_path / "copy")
    assert not (tmp_path / "copy/anima/external").exists()


def test_external_file_symlink_is_rejected_before_copy(tmp_path):
    root = tmp_path / "source"
    write(root, "anima/valid.py")
    external = write(tmp_path, "outside.py")
    (root / "anima/link.py").symlink_to(external)
    with pytest.raises(ValueError, match="escapes repository"):
        copy_source_tree(root, tmp_path / "copy")
    assert not (tmp_path / "copy").exists()


def test_internal_source_file_symlink_keeps_valid_contents(tmp_path):
    root = tmp_path / "source"
    target = write(root, "anima/valid.py", "VALUE = 42\n")
    (root / "anima/link.py").symlink_to(target)
    copy_source_tree(root, tmp_path / "copy")
    assert (tmp_path / "copy/anima/link.py").read_text() == "VALUE = 42\n"
    assert not (tmp_path / "copy/anima/link.py").is_symlink()


@pytest.mark.parametrize("path", ["../outside.py", "/outside.py", "anima/../../outside.py", "..\\outside.py"])
def test_explicit_manifest_rejects_escaping_paths(tmp_path, path):
    root = tmp_path / "source"
    root.mkdir()
    with pytest.raises(ValueError, match="escapes repository"):
        copy_source_tree(root, tmp_path / "copy", paths=(path,))
    assert not (tmp_path / "copy").exists()


def test_destination_inside_source_is_rejected(tmp_path):
    root = tmp_path / "source"
    write(root, "anima/module.py")
    with pytest.raises(ValueError, match="outside repository"):
        copy_source_tree(root, root / "anima/copy")


def test_git_manifest_reads_dirty_worktree_and_pending_files_without_staging(tmp_path):
    # A disposable worktree view of the existing read-only Git index. No git add,
    # commit, reset, or index update is performed, even in the test fixture.
    actual = Path(__file__).resolve().parents[1]
    if not (actual / ".git").exists():
        pytest.skip("Tracked-content check needs Git; source-only behavior is tested separately")
    git_dir = subprocess.check_output(["git", "-C", str(actual), "rev-parse", "--absolute-git-dir"], text=True).strip()
    head = subprocess.check_output(["git", "-C", str(actual), "show", "HEAD:README.md"], text=True)
    root = tmp_path / "source"
    write(root, ".git", f"gitdir: {git_dir}\n")
    write(root, "README.md", head + "\nUncommitted fixture edit.\n")
    write(root, ".gitignore", "anima/ignored.py\n")
    write(root, "anima/ignored.py", "# private ignored source\n")
    write(root, "anima/pending_closure_module.py", "# legitimate pending source\n")
    manifest = source_manifest(root)
    assert Path("README.md") in manifest
    assert Path("anima/pending_closure_module.py") in manifest
    assert Path("anima/ignored.py") not in manifest
    copy_source_tree(root, tmp_path / "copy")
    assert (tmp_path / "copy/README.md").read_text() == head + "\nUncommitted fixture edit.\n"
    assert (tmp_path / "copy/anima/pending_closure_module.py").exists()
    assert not (tmp_path / "copy/anima/ignored.py").exists()
