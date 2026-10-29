"""Render documentation summaries from canonical metadata, using only stdlib."""

import argparse
import ast
from datetime import date
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
STAGE_STATUSES = {"Planned", "InProgress", "Complete", "Blocked", "Stopped"}
RESULT_STATUSES = {"Passed", "Failed", "Inconclusive"}
REPORT_SECTIONS = (
    "Цель", "Условия", "Сценарий и входные данные", "Ожидаемый результат",
    "Фактический результат", "Метрики", "Доказано", "Не доказано",
)
BLOCKS = {
    "README.md": "summary",
    "docs/ROADMAP/README.md": "roadmap",
    "docs/TESTING/Results/README.md": "results",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def plain(value, label):
    require(isinstance(value, str) and bool(value.strip()), f"Missing {label}")
    require(not any(c in value for c in "\n\r|<>[]"), f"Invalid {label}: use plain single-line text")
    return value


def load_project(root):
    path = root / "docs/project.json"
    project = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(project, dict), "project.json must be an object")
    require(set(project) == {"schema_version", "current_stage", "focus", "stages"}, "Unknown/missing project fields")
    require(type(project["schema_version"]) is int and project["schema_version"] == 1, "Unsupported project schema")
    plain(project["focus"], "focus")
    stages = project["stages"]
    require(isinstance(stages, list) and stages, "stages must be a nonempty list")
    registry = {}
    for stage in stages:
        require(isinstance(stage, dict), "Stage must be an object")
        require(set(stage) == {"id", "title", "status", "depends_on", "outcome"}, "Unknown/missing stage fields")
        stage_id = plain(stage["id"], "stage id")
        require(re.fullmatch(r"(?:D\d+|\d+)", stage_id), f"Invalid stage id: {stage_id}")
        require(stage_id not in registry, f"Duplicate stage id: {stage_id}")
        plain(stage["title"], "stage title")
        plain(stage["outcome"], "stage outcome")
        require(isinstance(stage["status"], str) and stage["status"] in STAGE_STATUSES, f"Invalid status: {stage_id}")
        deps = stage["depends_on"]
        require(isinstance(deps, list) and all(isinstance(d, str) for d in deps), f"Invalid dependencies: {stage_id}")
        require(len(deps) == len(set(deps)), f"Duplicate dependencies: {stage_id}")
        registry[stage_id] = stage
    current = project["current_stage"]
    require(isinstance(current, str) and current in registry, "Unknown current stage")
    require(registry[current]["status"] not in {"Complete", "Stopped"}, "Current stage is already terminal")
    visiting, visited = set(), set()

    def visit(stage_id):
        require(stage_id not in visiting, f"Dependency cycle: {stage_id}")
        if stage_id in visited:
            return
        visiting.add(stage_id)
        for dep in registry[stage_id]["depends_on"]:
            require(dep in registry, f"Unknown dependency: {stage_id} -> {dep}")
            visit(dep)
            if registry[stage_id]["status"] == "Complete":
                require(registry[dep]["status"] == "Complete", f"Incomplete prerequisite: {stage_id} -> {dep}")
        visiting.remove(stage_id)
        visited.add(stage_id)

    for stage_id in registry:
        visit(stage_id)
    return project


def prototype_version(root):
    # Parse the default literal without importing/instantiating an ANIMA runtime.
    path = root / "anima/core/state.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name == "AnimaState":
            for method in cls.body:
                if isinstance(method, ast.FunctionDef) and method.name == "_default_state":
                    for node in ast.walk(method):
                        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                            for key, value in zip(node.value.keys, node.value.values):
                                if isinstance(key, ast.Constant) and key.value == "version":
                                    return plain(ast.literal_eval(value), "prototype version")
    raise ValueError("Cannot read prototype version from AnimaState._default_state")


def load_reports(root, project):
    reports = []
    ids = set()
    stages = {stage["id"] for stage in project["stages"]}
    for path in sorted((root / "docs/TESTING/Results").glob("TV-*.md")):
        text = path.read_text(encoding="utf-8")
        match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
        require(match is not None, f"Missing report metadata: {path.name}")
        meta = {}
        for line in match[1].splitlines():
            field = re.fullmatch(r"([a-z_]+):\s*(.+)", line)
            require(field is not None, f"Invalid report field: {path.name}: {line}")
            key, value = field.groups()
            require(key not in meta, f"Duplicate report field: {path.name}: {key}")
            meta[key] = plain(json.loads(value), f"{path.name}: {key}")
        require(set(meta) == {"id", "title", "date", "stage", "result", "snapshot"}, f"Unknown/missing report fields: {path.name}")
        require(re.fullmatch(r"TV-\d{4}", meta["id"]), f"Invalid report ID: {path.name}")
        require(path.stem == meta["id"] and meta["id"] not in ids, f"Duplicate/mismatched report ID: {path.name}")
        ids.add(meta["id"])
        require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", meta["date"]), f"Invalid report date: {path.name}")
        date.fromisoformat(meta["date"])
        require(meta["stage"] in stages, f"Unknown report stage: {path.name}")
        require(meta["result"] in RESULT_STATUSES, f"Invalid report result: {path.name}")
        require(meta["snapshot"] == "not-recorded" or re.fullmatch(r"[a-f0-9]{7,40}", meta["snapshot"]), f"Invalid report snapshot: {path.name}")
        body = text[match.end():]
        for heading in REPORT_SECTIONS:
            require(re.search(rf"^## {re.escape(heading)}\n\s*\S", body, re.MULTILINE), f"Missing report section: {path.name}: {heading}")
        reports.append(meta)
    return sorted(reports, key=lambda r: (r["date"], r["id"]))


def stage_anchor(stage_id):
    return stage_id.lower() if stage_id.startswith("D") else f"stage-{stage_id}"


def render_blocks(root):
    project = load_project(root)
    reports = load_reports(root, project)
    registry = {s["id"]: s for s in project["stages"]}
    current = registry[project["current_stage"]]
    version = prototype_version(root)
    summary = (
        f"Версия прототипа: **{version}** (из кода).\n\n"
        f"Текущий фокус: **{current['id']} — {current['title']}** ({current['status']}).\n\n"
        f"{project['focus']}\n\n"
        "[Этапы и критерии](docs/ROADMAP/README.md).\n"
    )
    roadmap = [
        f"**Текущая работа:** {project['focus']}", "",
        f"**Фокус:** {current['id']} — {current['title']} ({current['status']}).", "",
        "| Этап | Проверяемый результат | Статус | Зависимости |",
        "|---|---|---|---|",
    ]
    for stage in project["stages"]:
        deps = ", ".join(f"[{d}](#{stage_anchor(d)})" for d in stage["depends_on"]) or "—"
        label = f"{stage['id']} — {stage['title']}"
        roadmap.append(f"| [{label}](#{stage_anchor(stage['id'])}) | {stage['outcome']} | {stage['status']} | {deps} |")
    results = [
        "| ID / проверка | Дата | Этап | Результат | Проверенный snapshot |",
        "|---|---|---|---|---|",
    ]
    for report in reports:
        sha = report["snapshot"]
        snapshot = "не записан" if sha == "not-recorded" else f"[{sha[:7]}](https://github.com/VankoRokh/ANIMA/commit/{sha})"
        stage = report["stage"]
        results.append(
            f"| [{report['id']} — {report['title']}]({report['id']}.md) | {report['date']} | "
            f"[{stage}](../../ROADMAP/README.md#{stage_anchor(stage)}) | {report['result']} | {snapshot} |"
        )
    contents = {"summary": summary, "roadmap": "\n".join(roadmap) + "\n", "results": "\n".join(results) + "\n"}
    rendered = {}
    for relative, block in BLOCKS.items():
        path = root / relative
        original = path.read_text(encoding="utf-8")
        start, end = f"<!-- AUTO:{block}:START -->", f"<!-- AUTO:{block}:END -->"
        markers = re.findall(r"<!-- AUTO:.*? -->", original)
        require(markers == [start, end], f"Missing/duplicate/unknown AUTO markers: {relative}")
        pattern = re.compile(rf"^{re.escape(start)}\n.*?^{re.escape(end)}$", re.MULTILINE | re.DOTALL)
        require(pattern.search(original), f"Malformed AUTO block: {relative}")
        replacement = start + "\n" + contents[block] + end
        rendered[path] = pattern.sub(lambda _: replacement, original, count=1)
    return rendered


def update(root=ROOT, *, check=False):
    # Validate and render every target before writing any of them.
    rendered = render_blocks(root)
    stale = [path for path, content in rendered.items() if path.read_text(encoding="utf-8") != content]
    if check:
        require(not stale, "Stale generated documentation: " + ", ".join(str(p.relative_to(root)) for p in stale) + "; run python3 scripts/update_docs.py")
    else:
        for path in stale:
            path.write_text(rendered[path], encoding="utf-8")
    return len(stale)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail on stale blocks; do not write")
    args = parser.parse_args()
    try:
        changed = update(check=args.check)
    except (ValueError, OSError, SyntaxError) as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        return 1
    print("[OK] Generated documentation is current." if args.check else f"[OK] Updated {changed} documentation file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
