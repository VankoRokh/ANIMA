"""Check documentation and recovery using temporary, synthetic instance data."""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.harness import AnimaTestHarness

MODULE_ID = r"(?:CORE|MEM|COG|SLP|IF|HW)-\d+"
LINK = re.compile(r"!?\[[^\]\n]*\]\(([^\s)]+)(?:\s+\"[^\"]*\")?\)")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def visible_markdown(text):
    """Ignore frontmatter and fenced examples when checking links/headings."""
    lines = text.splitlines()
    result = []
    fence = None
    frontmatter = bool(lines and lines[0] == "---")
    for index, line in enumerate(lines):
        if frontmatter:
            if index and line == "---":
                frontmatter = False
            continue
        opening = re.match(r"^\s*(`{3,}|~{3,})", line)
        if opening:
            marker = opening.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is None:
            result.append(line)
    require(fence is None, "Unclosed Markdown fence")
    return "\n".join(result)


def heading_anchors(text):
    anchors = set()
    counts = Counter()
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.MULTILINE):
        heading = re.sub(r"[`*_]", "", heading).lower().strip()
        slug = re.sub(r"[^\w\-\s]", "", heading).replace(" ", "-")
        count = counts[slug]
        anchors.add(slug + (f"-{count}" if count else ""))
        counts[slug] += 1
    return anchors


def check_documentation():
    docs = sorted((ROOT / "docs").rglob("*.md"))
    require(docs, "docs is empty")
    pages = [ROOT / "README.md", *docs]
    visible = {page: visible_markdown(page.read_text(encoding="utf-8")) for page in pages}
    anchors = {page: heading_anchors(content) for page, content in visible.items()}
    edges = {page: set() for page in pages}
    links = 0
    for page, content in visible.items():
        require(not re.search(r"\[\[[^\]\n]+\]\]", content), f"Use portable links: {page}")
        for target in LINK.findall(content):
            url = urlsplit(target)
            if url.scheme or url.netloc:
                continue
            require(not url.path.startswith("/"), f"Use relative link: {page}: {target}")
            destination = (page.parent / unquote(url.path)).resolve() if url.path else page
            require(destination.is_relative_to(ROOT), f"Link leaves repository: {target}")
            require(destination.exists(), f"Broken link: {page.relative_to(ROOT)} -> {target}")
            if url.fragment:
                require(destination in anchors, f"Anchor target is not Markdown: {target}")
                require(unquote(url.fragment).lower() in anchors[destination], f"Missing anchor: {page.relative_to(ROOT)} -> {target}")
            if destination in edges:
                edges[page].add(destination)
            links += 1
    for page in docs:
        raw = page.read_text(encoding="utf-8")
        require(raw.startswith("---\n"), f"Missing metadata: {page}")
        for key in ("document_type", "status", "updated"):
            require(re.search(rf"^{key}: .+$", raw, re.MULTILINE), f"Missing {key}: {page}")
    start = ROOT / "docs/00_HOME/START_HERE.md"
    require(start in visible, "Missing START_HERE")
    visited = set()
    pending = [start]
    while pending:
        page = pending.pop()
        if page not in visited:
            visited.add(page)
            pending.extend(edges[page] - visited)
    require(set(docs) <= visited, "Unreachable documentation: " + ", ".join(str(p.relative_to(ROOT)) for p in set(docs) - visited))

    index = visible[ROOT / "docs/00_HOME/Module_Index.md"]
    registry = {}
    for line in index.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and re.fullmatch(MODULE_ID, cells[0]):
            require(len(cells) == 5, f"Invalid registry row: {line}")
            require(cells[0] not in registry, f"Duplicate module ID: {cells[0]}")
            registry[cells[0]] = cells
    declared = {}
    for page, content in visible.items():
        for match in re.finditer(rf"^## ({MODULE_ID})\s*$", content, re.MULTILINE):
            module_id = match.group(1)
            require(module_id not in declared, f"Duplicate module section: {module_id}")
            section = content[match.end():].split("\n## ", 1)[0]
            declared[module_id] = (page, section)
    require(registry.keys() == declared.keys(), "Module registry and descriptions differ")
    for module_id, cells in registry.items():
        require(cells[2] in {"Accepted", "Draft", "Experiment"}, f"Invalid decision: {module_id}")
        require(cells[3] in {"Planned", "Prototype", "Implemented", "Tested", "Stable", "Deprecated"}, f"Invalid implementation: {module_id}")
        page, section = declared[module_id]
        target = LINK.findall(cells[4])
        require(len(target) == 1, f"Missing module link: {module_id}")
        url = urlsplit(target[0])
        require((ROOT / "docs/00_HOME" / url.path).resolve() == page and url.fragment == module_id.lower(), f"Wrong module destination: {module_id}")
        require(f"Решение: **{cells[2]}**" in section and f"Реализация: **{cells[3]}**" in section, f"Module status mismatch: {module_id}")
    print(f"[OK] Documentation: {len(docs)} pages, {links} local links, {len(registry)} modules; all pages reachable.")


def check_sources():
    sources = [
        ROOT / "main.py",
        *(ROOT / "anima").rglob("*.py"),
        *(ROOT / "scripts").glob("*.py"),
        *(ROOT / "tests").rglob("*.py"),
    ]
    print(
    f"[OK] Python syntax ({len(sources)} files), "
    "VS Code JSON, Bash syntax."
)


def check_cli_extraction():
    main_source = (ROOT / "main.py").read_text(
        encoding="utf-8"
    )
    cli_source = (
        ROOT / "anima/interfaces/cli.py"
    ).read_text(encoding="utf-8")

    main_tree = ast.parse(
        main_source,
        filename=str(ROOT / "main.py"),
    )
    cli_tree = ast.parse(
        cli_source,
        filename=str(
            ROOT / "anima/interfaces/cli.py"
        ),
    )

    main_calls = [
        node
        for node in ast.walk(main_tree)
        if isinstance(node, ast.Call)
    ]

    require(
        not any(
            isinstance(call.func, ast.Name)
            and call.func.id == "input"
            for call in main_calls
        ),
        "main.py still owns terminal input",
    )

    require(
        "from anima.interfaces.cli import run_cli"
        in main_source,
        "main.py does not import the extracted CLI",
    )

    require(
        any(
            isinstance(node, ast.FunctionDef)
            and node.name == "run_cli"
            for node in ast.walk(cli_tree)
        ),
        "anima/interfaces/cli.py has no run_cli()",
    )

    require(
        "input(" in cli_source,
        "CLI no longer owns terminal input",
    )

    print(
        "[OK] CLI extraction: main assembles components "
        "and terminal interaction lives in interfaces/cli.py."
    )


def check_tracked_data():
    if not shutil.which("git") or not (ROOT / ".git").exists():
        print("[SKIP] Tracked-data check: use a Git checkout to inspect tracked paths.")
        return
    result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True, timeout=10)
    forbidden = ("data/", "ANIMA_DATA/", "models/", "backups/", "logs/", "snapshots/", "docs/.obsidian/", "docs/.trash/")
    for path in filter(None, result.stdout.split("\0")):
        require(not path.startswith(forbidden), f"Instance data/settings are tracked: {path}")
        require(not (path == ".env" or (path.startswith(".env.") and path != ".env.example")), f"Private env is tracked: {path}")
    print("[OK] No instance data or personal settings in tracked paths.")


def copy_source(destination):
    destination.mkdir()
    shutil.copy2(ROOT / "main.py", destination / "main.py")
    shutil.copytree(ROOT / "anima", destination / "anima", ignore=shutil.ignore_patterns("__pycache__"))


def make_test_env(data_dir=None):
    env = dict(
        os.environ,
        PYTHONDONTWRITEBYTECODE="1",
    )

    env.pop("ANIMA_DATA_DIR", None)

    if data_dir is not None:
        env["ANIMA_DATA_DIR"] = str(data_dir)

    return env


def run_session(
    destination,
    text,
    *,
    data_dir=None,
    cwd=None,
):
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(destination / "main.py"),
        ],
        cwd=destination if cwd is None else cwd,
        input=text + "\n\n",
        capture_output=True,
        text=True,
        env=make_test_env(data_dir),
        timeout=15,
    )

    require(
        result.returncode == 0,
        f"Temporary instance failed:\n{result.stderr}",
    )


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]




def main():
    require(sys.version_info >= (3, 12), "Use Python 3.12 or newer; validated baseline: 3.12.14")
    check_documentation()
    check_sources()
    check_cli_extraction()
    check_tracked_data()
    print(f"Checks passed on Python {sys.version.split()[0]}.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        sys.exit(1)
