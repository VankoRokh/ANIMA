"""Regression checks for safe generation and useful documentation failures."""

import json
from pathlib import Path
import subprocess

import pytest

from scripts.check_project import check_documentation, check_sources
from scripts.update_docs import BLOCKS, load_project, update
from tests.source_tree import copy_source_tree


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo(tmp_path):
    destination = tmp_path / "repo"
    copy_source_tree(ROOT, destination)
    return destination


def edit_project(repo, change):
    path = repo / "docs/project.json"
    project = json.loads(path.read_text(encoding="utf-8"))
    change(project)
    path.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")


def test_generation_is_idempotent_and_preserves_human_text(repo):
    readme = repo / "README.md"
    readme.write_text(readme.read_text() + "\nРучная заметка владельца.\n")
    edit_project(repo, lambda p: p["stages"][0].update(outcome="Новая историческая запись."))

    assert update(repo) == 1
    assert "Новая историческая запись." in (repo / "docs/history/stages.md").read_text()
    assert "Новая историческая запись." not in readme.read_text()
    assert "Текущий фокус: **7" not in readme.read_text()
    assert readme.read_text().endswith("Ручная заметка владельца.\n")
    snapshot = {p: (repo / p).read_bytes() for p in BLOCKS}
    assert update(repo) == 0
    assert {p: (repo / p).read_bytes() for p in BLOCKS} == snapshot
    assert not (repo / "data").exists()


def test_stale_check_is_read_only(repo):
    edit_project(repo, lambda p: p["stages"][0].update(outcome="Другая история."))
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
    edit_project(repo, lambda p: p["stages"][0].update(outcome="Изменённый итог."))
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



def test_results_point_to_history_not_live_roadmap(repo):
    results = (repo / "docs/TESTING/Results/README.md").read_text()
    assert "../../history/stages.md#stage-9" in results
    assert "../../ROADMAP/README.md#stage-9" not in results
    roadmap = (repo / "docs/roadmap.md").read_text()
    assert "R-08" in roadmap and "R-10" in roadmap
    for suffix in ("d0", "d1", *(f"stage-{n}" for n in range(12))):
        page = (repo / "docs/ROADMAP/README.md").read_text().lower()
        assert f"../history/stages.md#{suffix}" in page


def test_canonical_release_and_architecture_routes(repo):
    contract = (repo / "docs/versions/v0.1/contract.md").read_text()
    for number in range(1, 11):
        assert f"R-{number:02d}" in contract
    legacy_contract = (repo / "docs/RELEASES/ANIMA_v0_1_Release_Contract.md").read_text()
    assert "../versions/v0.1/contract.md" in legacy_contract
    assert "## 4. Приёмка R-01–R-10" in legacy_contract
    architecture = (repo / "docs/system/README.md").read_text()
    assert "CoreIngress" in architecture and "sandbox-door" in architecture
    assert "| `CoreDoorExecution` / `CoreAutonomy` | Нет |" in architecture
    check_documentation(repo)



def test_research_catalog_preserves_negative_evidence(repo):
    index = (repo / "docs/RESEARCH/README.md").read_text()
    assert "retrieval.md" in index
    assert "memory-encoding.md" in index
    assert "semantics.md" in index
    assert "virtual-world.md" in index
    assert "future-directions.md" in index

    encoding = (repo / "docs/RESEARCH/memory-encoding.md").read_text()
    assert "AUTHORITY FAIL" in encoding
    assert "NO-GO" in encoding
    assert "128" in encoding
    assert "Memory_E4_Crash_Scale_Exit_Gate_v0.md" in encoding

    semantics = (repo / "docs/RESEARCH/semantics.md").read_text()
    assert "Inconclusive" in semantics
    assert "48/50" in semantics
    assert "CR-032" in semantics
    assert "revision-residual/0.3" in semantics

    virtual = (repo / "docs/RESEARCH/virtual-world.md").read_text()
    assert "10/10" in virtual
    assert "true_sigkill_tested=false" in virtual
    assert "operator_authenticated=false" in virtual
    assert "anima-m6b2-PC-20261114-172243.json" in virtual
    assert "7465684725551188215a932dca6c42f98250c7d4" in virtual
    assert "10/10" in virtual and "world_effect_total=2" in virtual

    legacy = (repo / "docs/RESEARCH/legacy-index.md").read_text()
    assert "## Отдельные направления" in legacy
    assert "legacy-index.md" in index
    names = [p.name.casefold() for p in (repo / "docs").iterdir() if p.is_dir()]
    assert len(names) == len(set(names)), "Case-only docs directories collide"
    check_documentation(repo)



def test_operations_verification_and_documentation_routes(repo):
    home = (repo / "docs/README.md").read_text()
    for name in ("operations.md", "verification.md", "documentation.md"):
        assert f"({name})" in home

    operations = (repo / "docs/operations.md").read_text()
    assert 'release_profile.json' in operations
    assert 'memory.db' in operations
    assert '--sandbox-door' in operations
    assert 'instance.tar.gz.sha256' in operations
    assert 'sha256sum -c' in operations
    assert 'Runtime.sleep()' in operations

    legacy = (repo / "docs/OPERATIONS/README.md").read_text()
    assert '../operations.md#резервное-копирование-v01' in legacy
    assert 'memories.jsonl' in legacy  # Historical warning, not a backup prerequisite.
    assert 'for name in state.json' not in legacy

    verification = (repo / "docs/verification.md").read_text()
    assert 'MEASURED_NOT_SLO_GATED' in verification
    assert 'scripts.run_release_v01_gate' in verification
    assert 'R-08' in verification and 'R-09' in verification and 'R-10' in verification

    rules = (repo / "docs/documentation.md").read_text()
    assert 'AUTO:roadmap:START/END' in rules
    assert 'AUTO:results:START/END' in rules
    assert 'RESEARCH/' in rules
    check_documentation(repo)


def test_case_only_documentation_paths_are_rejected(repo):
    lower = repo / "docs/research"
    if lower.exists():
        pytest.skip("Case-insensitive filesystem cannot create distinct path")
    lower.mkdir()
    (lower / "collision.md").write_text("# Коллизия путей\n")
    with pytest.raises(RuntimeError, match="Case-only documentation path collision"):
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


def test_multiple_bad_local_links_are_reported_together(repo):
    research = repo / "docs/ROADMAP/Research.md"
    research.write_text(
        research.read_text()
        + "\n[Нет файла](missing-one.md)\n"
        + "[Вне репозитория](../../../../outside.md)\n"
    )
    with pytest.raises(RuntimeError) as captured:
        check_documentation(repo)
    message = str(captured.value)
    assert "Broken link" in message
    assert "Link leaves repository" in message


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
    path = repo / "docs/system/README.md"
    rows = path.read_text().splitlines()
    updated = False
    for index, row in enumerate(rows):
        if row.startswith("| [Runtime]("):
            cells = row.split("|")
            assert len(cells) >= 5
            cells[3] = cells[3].replace("[test_runtime.py](../../tests/test_runtime.py)", "Проверки потеряны")
            rows[index] = "|".join(cells)
            updated = True
            break
    assert updated, "Runtime architecture row not found"
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
