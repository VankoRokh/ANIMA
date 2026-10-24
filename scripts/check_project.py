"""Check project integrity without creating or changing an ANIMA instance."""

import ast
from collections import Counter
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.update_docs import update

LINK = re.compile(r'!?\[[^\]\n]*\]\(([^\s)]+)(?:\s+"[^\"]*")?\)')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def visible_markdown(text):
    """Ignore metadata and fenced examples, rejecting unclosed fences."""
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
    require(not frontmatter, "Unclosed Markdown metadata")
    require(fence is None, "Unclosed Markdown fence")
    return "\n".join(result)


def heading_anchors(text):
    anchors, counts = set(), Counter()
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.MULTILINE):
        heading = re.sub(r"[`*_]", "", heading).lower().strip()
        slug = re.sub(r"[^\w\-\s]", "", heading).replace(" ", "-")
        count = counts[slug]
        anchors.add(slug + (f"-{count}" if count else ""))
        counts[slug] += 1
    return anchors


def check_documentation(root=ROOT):
    update(root, check=True)
    docs = sorted((root / "docs").rglob("*.md"))
    require(docs, "docs is empty")
    pages = [root / "README.md", *docs]
    visible = {}
    for page in pages:
        try:
            visible[page] = visible_markdown(page.read_text(encoding="utf-8"))
        except RuntimeError as error:
            raise RuntimeError(f"{page.relative_to(root)}: {error}") from error
    anchors = {p: heading_anchors(t) for p, t in visible.items()}
    edges = {p: set() for p in pages}
    links = 0
    for page, content in visible.items():
        require(not re.search(r"\[\[[^\]\n]+\]\]", content), f"Use portable links: {page}")
        for target in LINK.findall(content):
            url = urlsplit(target)
            if url.scheme or url.netloc:
                continue
            require(not url.path.startswith("/"), f"Use relative link: {page}: {target}")
            destination = (page.parent / unquote(url.path)).resolve() if url.path else page
            require(destination.is_relative_to(root), f"Link leaves repository: {target}")
            require(destination.exists(), f"Broken link: {page.relative_to(root)} -> {target}")
            if url.fragment:
                require(destination in anchors, f"Anchor target is not Markdown: {target}")
                require(unquote(url.fragment).lower() in anchors[destination], f"Missing anchor: {page.relative_to(root)} -> {target}")
            if destination in edges:
                edges[page].add(destination)
            links += 1
    start = root / "docs/README.md"
    require(start in visible, "Missing docs/README.md")
    visited, pending = set(), [start]
    while pending:
        page = pending.pop()
        if page not in visited:
            visited.add(page)
            pending.extend(edges[page] - visited)
    require(set(pages) <= visited, "Unreachable documentation: " + ", ".join(str(p.relative_to(root)) for p in set(pages) - visited))
    arch = visible[root / "docs/ARCHITECTURE/README.md"]
    table = arch.split("## Компоненты и подтверждение\n", 1)
    require(len(table) == 2, "Missing implemented architecture table")
    rows = [line for line in table[1].split("\n## ", 1)[0].splitlines() if line.startswith("| ")][1:]
    require(rows, "Empty architecture table")
    for row in rows:
        paths = [unquote(urlsplit(t).path) for t in LINK.findall(row)]
        require(any(p.endswith(".py") and (p.startswith("../../anima/") or p in {"../../main.py", "../../tests/harness.py"}) for p in paths), f"Missing architecture code reference: {row}")
        require(any(p.startswith("../../tests/test_") and p.endswith(".py") for p in paths), f"Missing architecture test reference: {row}")
    print(f"[OK] Documentation: {len(docs)} pages, {links} local links; all pages reachable; generated blocks current; architecture references valid.")


def check_sources(root=ROOT):
    sources = [root / "main.py", *(root / "anima").rglob("*.py"), *(root / "scripts").glob("*.py"), *(root / "tests").rglob("*.py")]
    for path in sources:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    configs = sorted((root / ".vscode").glob("*.json"))
    for path in configs:
        json.loads(path.read_text(encoding="utf-8"))
    scripts = sorted((root / "scripts").glob("*.sh"))
    for path in scripts:
        subprocess.run(["bash", "-n", str(path)], check=True, capture_output=True, text=True, timeout=10)
    print(f"[OK] Python syntax ({len(sources)} files), VS Code JSON ({len(configs)} files), Bash syntax ({len(scripts)} files).")


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



def main():
    require(sys.version_info >= (3, 12), "Use Python 3.12 or newer")
    check_documentation()
    check_sources()
    check_cli_extraction()
    check_tracked_data()
    print(f"Checks passed on Python {sys.version.split()[0]}.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, SyntaxError, subprocess.SubprocessError) as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        sys.exit(1)
