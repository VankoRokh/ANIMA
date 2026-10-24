"""Regression checks for safe generation and useful documentation failures."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts.check_project import check_documentation, check_sources
from scripts.update_docs import BLOCKS, load_project, update


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo(tmp_path):
    destination = tmp_path / "repo"
    shutil.copytree(
        ROOT, destination,
        ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache", "data"),
    )
    return destination


def edit_project(repo, change):
    path = repo / "docs/project.json"
    project = json.loads(path.read_text(encoding="utf-8"))
    change(project)
    path.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")


def test_generation_is_idempotent_and_preserves_human_text(repo):
    readme = repo / "README.md"
    readme.write_text(readme.read_text() + "\nРучная заметка владельца.\n")
    edit_project(repo, lambda p: p.update(focus="Новая текущая работа."))
    state = repo / "anima/core/state.py"
    state.write_text(state.read_text().replace('"00.1-alpha"', '"00.2-test"'))

    assert update(repo) == 2
    assert "Новая текущая работа." in readme.read_text()
    assert "00.2-test" in readme.read_text()
    assert readme.read_text().endswith("Ручная заметка владельца.\n")
    snapshot = {p: (repo / p).read_bytes() for p in BLOCKS}
    assert update(repo) == 0
    assert {p: (repo / p).read_bytes() for p in BLOCKS} == snapshot
    assert not (repo / "data").exists()


def test_stale_check_is_read_only(repo):
    edit_project(repo, lambda p: p.update(focus="Другой фокус."))
    before = {p: (repo / p).read_bytes() for p in BLOCKS}
    with pytest.raises(ValueError, match="Stale generated documentation"):
        update(repo, check=True)
    assert {p: (repo / p).read_bytes() for p in BLOCKS} == before


@pytest.mark.parametrize("fault, message", [
    ("duplicate", "Duplicate stage id"),
    ("current", "Unknown current stage"),
    ("status", "Invalid status"),
    ("dependency", "Unknown dependency"),
    ("cycle", "Dependency cycle"),
    ("complete", "Incomplete prerequisite"),
    ("schema", "Unsupported project schema"),
])
def test_invalid_stage_metadata_fails(repo, fault, message):
    def change(p):
        if fault == "duplicate":
            p["stages"].append(p["stages"][0].copy())
        elif fault == "current":
            p["current_stage"] = "99"
        elif fault == "status":
            p["stages"][-1]["status"] = "AlmostDone"
        elif fault == "dependency":
            p["stages"][-1]["depends_on"] = ["99"]
        elif fault == "cycle":
            p["stages"][-1]["depends_on"] = [p["stages"][-1]["id"]]
        elif fault == "complete":
            p["stages"][-1]["status"] = "Complete"
        elif fault == "schema":
            p["schema_version"] = True
    edit_project(repo, change)
    with pytest.raises(ValueError, match=message):
        load_project(repo)


def test_all_markers_are_validated_before_writing(repo):
    edit_project(repo, lambda p: p.update(focus="Сводки должны измениться."))
    readme = repo / "README.md"
    before = readme.read_bytes()
    results = repo / "docs/TESTING/Results/README.md"
    results.write_text(results.read_text() + "\n<!-- AUTO:results:START -->\n")
    with pytest.raises(ValueError, match="AUTO markers"):
        update(repo)
    assert readme.read_bytes() == before


def test_result_index_uses_report_metadata(repo):
    reports = repo / "docs/TESTING/Results"
    example = (reports / "TV-0002.md").read_text()
    report = example.replace('id: "TV-0002"', 'id: "TV-9999"').replace(
        'result: "Passed"', 'result: "Failed"'
    ).replace('title: "D1 Runtime / Tests / Observability validation"', 'title: "Новый результат"')
    (reports / "TV-9999.md").write_text(report)
    update(repo)
    index = (reports / "README.md").read_text()
    assert "TV-9999 — Новый результат" in index
    assert "| Failed | не записан |" in index
    check_documentation(repo)


def test_incomplete_report_is_rejected(repo):
    report = repo / "docs/TESTING/Results/TV-0001.md"
    report.write_text(report.read_text().replace("## Не доказано", "## Потерянный раздел"))
    with pytest.raises(ValueError, match="Missing report section"):
        update(repo)


@pytest.mark.parametrize("target, message", [
    ("missing.md", "Broken link"),
    ("README.md#missing-anchor", "Missing anchor"),
    ("../../../../outside.md", "Link leaves repository"),
])
def test_bad_local_links_fail(repo, target, message):
    research = repo / "docs/ROADMAP/Research.md"
    research.write_text(research.read_text() + f"\n[Ссылка]({target})\n")
    with pytest.raises(RuntimeError, match=message):
        check_documentation(repo)


def test_unreachable_page_fails(repo):
    (repo / "docs/lost.md").write_text("# Потерянная страница\n")
    with pytest.raises(RuntimeError, match="Unreachable documentation"):
        check_documentation(repo)


def test_unclosed_fence_fails(repo):
    research = repo / "docs/ROADMAP/Research.md"
    research.write_text(research.read_text() + "\n```text\nнезакрытый пример\n")
    with pytest.raises(RuntimeError, match="Unclosed Markdown fence"):
        check_documentation(repo)


def test_architecture_requires_a_test_reference(repo):
    path = repo / "docs/ARCHITECTURE/README.md"
    rows = path.read_text().splitlines()
    for index, row in enumerate(rows):
        if row.startswith("| Runtime |"):
            cells = row.split("|")
            cells[3] = " Проверки потеряны "
            rows[index] = "|".join(cells)
    path.write_text("\n".join(rows) + "\n")
    with pytest.raises(RuntimeError, match="Missing architecture test reference"):
        check_documentation(repo)


@pytest.mark.parametrize("kind", ["python", "json", "bash"])
def test_source_check_really_parses_files(repo, kind):
    if kind == "python":
        (repo / "anima/runtime.py").write_text("broken = (\n")
        error = SyntaxError
    elif kind == "json":
        (repo / ".vscode/settings.json").write_text("{broken\n")
        error = json.JSONDecodeError
    else:
        (repo / "scripts/run.sh").write_text("if then\n")
        error = subprocess.CalledProcessError
    with pytest.raises(error):
        check_sources(repo)
