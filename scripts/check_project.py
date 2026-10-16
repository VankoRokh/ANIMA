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
    sources = [ROOT / "main.py", *(ROOT / "anima").rglob("*.py"), *(ROOT / "scripts").glob("*.py")]
    for path in sources:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for path in (ROOT / ".vscode").glob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))
    for path in (ROOT / "scripts").glob("*.sh"):
        subprocess.run(["bash", "-n", str(path)], check=True, timeout=10)
    print(f"[OK] Python syntax ({len(sources)} files), VS Code JSON, Bash syntax.")


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

def check_event_validation():
    from anima.core.event_bus import Event

    valid_events = [
        ("wake", None),
        ("sleep", None),
        ("user_input", {"text": "hello"}),
        ("user_input", {"text": "   "}),
    ]

    for event_type, payload in valid_events:
        event = Event(event_type, payload)
        require(
            event.event_type == event_type,
            f"Valid event {event_type!r} was not created correctly",
        )

    invalid_events = [
        (
            123,
            None,
            "Event type must be a string",
        ),
        (
            "unknown",
            None,
            "Unknown event type",
        ),
        (
            "wake",
            {"unexpected": True},
            "must have null payload",
        ),
        (
            "sleep",
            {},
            "must have null payload",
        ),
        (
            "user_input",
            "hello",
            "payload must be an object",
        ),
        (
            "user_input",
            {},
            "must contain 'text'",
        ),
        (
            "user_input",
            {"text": 123},
            "'text' must be a string",
        ),
    ]

    for event_type, payload, expected_message in invalid_events:
        try:
            Event(event_type, payload)
        except ValueError as error:
            require(
                expected_message in str(error),
                f"Unexpected validation error for {event_type!r}: {error}",
            )
        else:
            raise RuntimeError(
                f"Invalid event {event_type!r} was unexpectedly accepted"
            )

    print("[OK] Event validation: valid events accepted and invalid events rejected.")

def check_event_log_validation():
    from anima.core.event_bus import Event
    from anima.memory.event_log import EventLog

    with tempfile.TemporaryDirectory(prefix="anima-event-log-check-") as temp_dir:
        log_file = Path(temp_dir) / "events.jsonl"
        event_log = EventLog(log_file)

        event_log.write(Event("wake"))
        event_log.write(Event("user_input", {"text": "hello"}))

        loaded = event_log.load_events()

        require(
            len(loaded) == 2,
            "Event log did not return expected records",
        )

        require(
            loaded[0]["type"] == "wake"
            and loaded[1]["type"] == "user_input",
            "Event log returned unexpected event order",
        )

        malformed_file = Path(temp_dir) / "malformed.jsonl"
        malformed_file.write_text(
            '{"type":"wake","payload":null,"timestamp":"2026-10-13T12:00:00"}\n'
            '{"type":\n',
            encoding="utf-8",
        )

        malformed_log = EventLog(malformed_file)

        try:
            malformed_log.load_events()
        except ValueError as error:
            require(
                "line 2: malformed JSON" in str(error),
                f"Malformed event log produced unclear error: {error}",
            )
        else:
            raise RuntimeError(
                "Malformed event log was unexpectedly accepted"
            )

        incompatible_file = Path(temp_dir) / "incompatible.jsonl"
        incompatible_file.write_text(
            '{"type":"wake","payload":{"bad":true},'
            '"timestamp":"2026-10-13T12:00:00"}\n',
            encoding="utf-8",
        )

        incompatible_log = EventLog(incompatible_file)

        try:
            incompatible_log.load_events()
        except ValueError as error:
            require(
                "line 1" in str(error)
                and "must have null payload" in str(error),
                f"Incompatible event log produced unclear error: {error}",
            )
        else:
            raise RuntimeError(
                "Incompatible event log was unexpectedly accepted"
            )

    print(
        "[OK] Event log validation: valid records load and "
        "damaged lines report their location."
    )

def check_memory_validation():
    from anima.memory.episodic import EpisodicMemory
    from anima.memory.memory_store import MemoryStore

    with tempfile.TemporaryDirectory(prefix="anima-memory-check-") as temp_dir:
        memory_file = Path(temp_dir) / "memories.jsonl"
        memory_store = MemoryStore(memory_file)
        episodic_memory = EpisodicMemory(memory_file)

        valid_memory = {
            "source": "user_input",
            "timestamp": "2026-10-13T12:00:00",
            "content": {
                "text": "hello",
            },
        }

        memory_store.write(valid_memory)

        loaded = episodic_memory.load_memories()

        require(
            loaded == [valid_memory],
            "Valid memory record was not stored and loaded correctly",
        )

        stable_bytes = memory_file.read_bytes()

        invalid_memory = {
            "source": "user_input",
            "timestamp": "2026-10-13T12:01:00",
            "content": {
                "text": 123,
            },
        }

        try:
            memory_store.write(invalid_memory)
        except ValueError as error:
            require(
                "'content.text' must be a string" in str(error),
                f"Invalid memory produced unclear error: {error}",
            )
        else:
            raise RuntimeError(
                "Invalid memory was unexpectedly written"
            )

        require(
            memory_file.read_bytes() == stable_bytes,
            "Invalid memory changed the memory store",
        )

        malformed_file = Path(temp_dir) / "malformed.jsonl"
        malformed_file.write_text(
            '{"source":"user_input","timestamp":"2026-10-13T12:00:00",'
            '"content":{"text":"valid"}}\n'
            '{"source":\n',
            encoding="utf-8",
        )

        malformed_memory = EpisodicMemory(malformed_file)

        try:
            malformed_memory.load_memories()
        except ValueError as error:
            require(
                "line 2: malformed JSON" in str(error),
                f"Malformed memory store produced unclear error: {error}",
            )
        else:
            raise RuntimeError(
                "Malformed memory store was unexpectedly accepted"
            )

        incompatible_file = Path(temp_dir) / "incompatible.jsonl"
        incompatible_file.write_text(
            '{"source":"user_input","timestamp":"2026-10-13T12:00:00",'
            '"content":{"text":123}}\n',
            encoding="utf-8",
        )

        incompatible_memory = EpisodicMemory(incompatible_file)

        try:
            incompatible_memory.load_memories()
        except ValueError as error:
            require(
                "line 1" in str(error)
                and "'content.text' must be a string" in str(error),
                f"Incompatible memory store produced unclear error: {error}",
            )
        else:
            raise RuntimeError(
                "Incompatible memory store was unexpectedly accepted"
            )

    print(
        "[OK] Memory validation: invalid writes are rejected and "
        "damaged lines report their location."
    )

def check_interrupted_sessions():
    with tempfile.TemporaryDirectory(prefix="anima-interrupt-check-") as temp_dir:
        temp = Path(temp_dir)

        def run_with_input(destination, input_text):
            copy_source(destination)

            env = make_test_env()

            return subprocess.run(
                [sys.executable, "-B", "main.py"],
                cwd=destination,
                input=input_text,
                capture_output=True,
                text=True,
                env=env,
                timeout=15,
            )

        # EOF before the first user input.
        early_eof = temp / "early-eof"
        result = run_with_input(early_eof, "")

        require(
            result.returncode == 0,
            f"Early EOF session failed:\n{result.stderr}",
        )

        state = json.loads(
            (early_eof / "data/state.json").read_text(
                encoding="utf-8"
            )
        )
        events = read_jsonl(
            early_eof / "data/events.jsonl"
        )

        require(
            state["status"] == "sleeping",
            "Early EOF left ANIMA awake",
        )
        require(
            [event["type"] for event in events]
            == ["wake", "sleep"],
            "Early EOF produced unexpected event history",
        )
        require(
            state["events_processed"] == 2,
            "Early EOF produced incorrect event count",
        )
        require(
            "Session interrupted: EOFError." in result.stdout,
            "Early EOF was not reported clearly",
        )

        # EOF after a valid user input.
        late_eof = temp / "late-eof"
        result = run_with_input(
            late_eof,
            "Interrupted session memory\n",
        )

        require(
            result.returncode == 0,
            f"Late EOF session failed:\n{result.stderr}",
        )

        state = json.loads(
            (late_eof / "data/state.json").read_text(
                encoding="utf-8"
            )
        )
        events = read_jsonl(
            late_eof / "data/events.jsonl"
        )
        memories = read_jsonl(
            late_eof / "data/memories.jsonl"
        )

        require(
            state["status"] == "sleeping",
            "Late EOF left ANIMA awake",
        )
        require(
            [event["type"] for event in events]
            == ["wake", "user_input", "sleep"],
            "Late EOF produced unexpected event history",
        )
        require(
            state["events_processed"] == 3,
            "Late EOF produced incorrect event count",
        )
        require(
            len(memories) == 1
            and memories[0]["content"]["text"]
            == "Interrupted session memory",
            "Late EOF lost processed user input",
        )

        # KeyboardInterrupt at the first input().
        keyboard_interrupt = temp / "keyboard-interrupt"
        copy_source(keyboard_interrupt)

        env = make_test_env()

        interrupt_code = """
from unittest.mock import patch

import main

with patch(
    "builtins.input",
    side_effect=KeyboardInterrupt,
):
    main.main()
"""

        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                interrupt_code,
            ],
            cwd=keyboard_interrupt,
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )

        require(
            result.returncode == 0,
            f"KeyboardInterrupt session failed:\n{result.stderr}",
        )

        state = json.loads(
            (
                keyboard_interrupt
                / "data/state.json"
            ).read_text(encoding="utf-8")
        )
        events = read_jsonl(
            keyboard_interrupt / "data/events.jsonl"
        )

        require(
            state["status"] == "sleeping",
            "KeyboardInterrupt left ANIMA awake",
        )
        require(
            [event["type"] for event in events]
            == ["wake", "sleep"],
            "KeyboardInterrupt produced unexpected event history",
        )
        require(
            "Session interrupted: KeyboardInterrupt."
            in result.stdout,
            "KeyboardInterrupt was not reported clearly",
        )

        # KeyboardInterrupt after a valid user input.
        late_keyboard_interrupt = temp / "late-keyboard-interrupt"
        copy_source(late_keyboard_interrupt)

        interrupt_code = """
from unittest.mock import patch

import main

with patch(
    "builtins.input",
    side_effect=[
        "Keyboard session memory",
        KeyboardInterrupt,
    ],
):
    main.main()
"""

        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                interrupt_code,
            ],
            cwd=late_keyboard_interrupt,
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )

        require(
            result.returncode == 0,
            f"Late KeyboardInterrupt session failed:\n{result.stderr}",
        )

        state = json.loads(
            (
                late_keyboard_interrupt
                / "data/state.json"
            ).read_text(encoding="utf-8")
        )
        events = read_jsonl(
            late_keyboard_interrupt / "data/events.jsonl"
        )
        memories = read_jsonl(
            late_keyboard_interrupt / "data/memories.jsonl"
        )

        require(
            state["status"] == "sleeping",
            "Late KeyboardInterrupt left ANIMA awake",
        )
        require(
            [event["type"] for event in events]
            == ["wake", "user_input", "sleep"],
            "Late KeyboardInterrupt produced unexpected event history",
        )
        require(
            len(memories) == 1
            and memories[0]["content"]["text"]
            == "Keyboard session memory",
            "Late KeyboardInterrupt lost processed user input",
        )
        require(
            "Session interrupted: KeyboardInterrupt."
            in result.stdout,
            "Late KeyboardInterrupt was not reported clearly",
        )

    print(
        "[OK] Session interruption: EOF and KeyboardInterrupt "
        "finish in sleeping state without losing processed input."
    )

def check_state_write_safety():
    from unittest.mock import patch

    from anima.core.state import AnimaState

    with tempfile.TemporaryDirectory(prefix="anima-state-check-") as temp_dir:
        state_file = Path(temp_dir) / "data" / "state.json"

        anima_state = AnimaState(state_file)
        original_bytes = state_file.read_bytes()

        anima_state.state["session"] = 42
        anima_state.save()

        saved = json.loads(state_file.read_text(encoding="utf-8"))
        require(saved["session"] == 42, "State save did not persist changes")

        temp_files = list(state_file.parent.glob(f".{state_file.name}.*.tmp"))
        require(not temp_files, "Temporary state files remain after successful save")

        stable_bytes = state_file.read_bytes()
        anima_state.state["session"] = 99

        with patch("anima.core.state.os.replace", side_effect=OSError("simulated replace failure")):
            try:
                anima_state.save()
            except OSError:
                pass
            else:
                raise RuntimeError("State save unexpectedly succeeded during simulated failure")

        require(
            state_file.read_bytes() == stable_bytes,
            "Existing state was modified after failed atomic replacement",
        )

        temp_files = list(state_file.parent.glob(f".{state_file.name}.*.tmp"))
        require(not temp_files, "Temporary state file remains after failed save")

        require(original_bytes != stable_bytes, "State safety test did not actually modify state")

        malformed_file = Path(temp_dir) / "malformed" / "state.json"
        malformed_file.parent.mkdir(parents=True, exist_ok=True)
        malformed_file.write_text(
            '{"name": "ANIMA", broken json',
            encoding="utf-8",
        )
        malformed_bytes = malformed_file.read_bytes()

        try:
            AnimaState(malformed_file)
        except ValueError as error:
            require(
                "malformed JSON" in str(error),
                "Malformed state did not produce a clear error",
            )
        else:
            raise RuntimeError("Malformed state was unexpectedly accepted")

        require(
            malformed_file.read_bytes() == malformed_bytes,
            "Malformed state file was modified during failed load",
        )

        incompatible_file = Path(temp_dir) / "incompatible" / "state.json"
        incompatible_file.parent.mkdir(parents=True, exist_ok=True)

        incompatible_state = {
            "name": "ANIMA",
            "version": "00.1-alpha",
            "status": "sleeping",
            "session": "broken",
            "created_at": "2026-10-13T00:00:00",
            "last_wake": None,
            "last_sleep": None,
            "events_processed": 0,
        }

        incompatible_file.write_text(
            json.dumps(
                incompatible_state,
                indent=4,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        incompatible_bytes = incompatible_file.read_bytes()

        try:
            AnimaState(incompatible_file)
        except ValueError as error:
            require(
                "'session' must be a non-negative integer" in str(error),
                "Incompatible state did not produce a clear error",
            )
        else:
            raise RuntimeError("Incompatible state was unexpectedly accepted")

        require(
            incompatible_file.read_bytes() == incompatible_bytes,
            "Incompatible state file was modified during failed load",
        )

    print(
    "[OK] State persistence: atomic save, malformed JSON "
    "and incompatible state handled safely."
    )


def check_data_directory_configuration():
    from unittest.mock import patch

    from anima.config.paths import PROJECT_ROOT, get_data_dir

    # Без настройки используется data в корне проекта.
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("ANIMA_DATA_DIR", None)

        require(
            get_data_dir() == PROJECT_ROOT / "data",
            "Default data directory is not project-root/data",
        )

    # Относительный путь считается от корня проекта,
    # а не от текущей рабочей директории.
    with patch.dict(
        os.environ,
        {"ANIMA_DATA_DIR": "configured-data"},
        clear=False,
    ):
        require(
            get_data_dir()
            == (PROJECT_ROOT / "configured-data").resolve(),
            "Relative ANIMA_DATA_DIR is not resolved from project root",
        )

    # Пустая настройка считается ошибкой.
    with patch.dict(
        os.environ,
        {"ANIMA_DATA_DIR": "   "},
        clear=False,
    ):
        try:
            get_data_dir()
        except ValueError as error:
            require(
                "must not be empty" in str(error),
                "Empty ANIMA_DATA_DIR produced an unclear error",
            )
        else:
            raise RuntimeError(
                "Empty ANIMA_DATA_DIR was unexpectedly accepted"
            )

    with tempfile.TemporaryDirectory(
        prefix="anima-data-dir-check-"
    ) as temp_dir:
        temp = Path(temp_dir)

        application = temp / "application"
        first_cwd = temp / "cwd-one"
        second_cwd = temp / "cwd-two"
        data_dir = temp / "instance-data"
        migrated_dir = temp / "migrated-data"

        copy_source(application)

        first_cwd.mkdir()
        second_cwd.mkdir()

        # Первая сессия использует внешний каталог данных.
        run_session(
            application,
            "Configured session one",
            data_dir=data_dir,
            cwd=first_cwd,
        )

        expected_files = {
            "state.json",
            "identity.json",
            "events.jsonl",
            "memories.jsonl",
        }

        require(
            {
                path.name
                for path in data_dir.iterdir()
                if path.is_file()
            }
            == expected_files,
            "Configured data directory has unexpected contents",
        )

        require(
            not (application / "data").exists(),
            "Application directory received unintended data",
        )

        require(
            not (first_cwd / "data").exists(),
            "Working directory received unintended data",
        )

        first_state = json.loads(
            (data_dir / "state.json").read_text(
                encoding="utf-8"
            )
        )

        first_identity = json.loads(
            (data_dir / "identity.json").read_text(
                encoding="utf-8"
            )
        )

        require(
            first_state["session"] == 1
            and first_state["events_processed"] == 3
            and first_state["status"] == "sleeping",
            "Configured first session has incorrect state",
        )

        instance_id = first_identity["instance_id"]

        # Вторая сессия запускается из другой cwd,
        # но использует тот же экземпляр.
        run_session(
            application,
            "Configured session two",
            data_dir=data_dir,
            cwd=second_cwd,
        )

        second_state = json.loads(
            (data_dir / "state.json").read_text(
                encoding="utf-8"
            )
        )

        second_identity = json.loads(
            (data_dir / "identity.json").read_text(
                encoding="utf-8"
            )
        )

        events = read_jsonl(
            data_dir / "events.jsonl"
        )

        memories = read_jsonl(
            data_dir / "memories.jsonl"
        )

        require(
            second_state["session"] == 2
            and second_state["events_processed"] == 6
            and second_state["status"] == "sleeping",
            "Configured instance did not continue across cwd change",
        )

        require(
            second_identity["instance_id"] == instance_id,
            "Instance ID changed across cwd change",
        )

        require(
            len(events) == 6,
            "Event history was lost across cwd change",
        )

        require(
            len(memories) == 2,
            "Selected memory was lost across cwd change",
        )

        require(
            not (second_cwd / "data").exists(),
            "Second working directory received unintended data",
        )

        # Физически копируем каталог экземпляра.
        shutil.copytree(
            data_dir,
            migrated_dir,
        )

        run_session(
            application,
            "Migrated session",
            data_dir=migrated_dir,
            cwd=first_cwd,
        )

        migrated_state = json.loads(
            (migrated_dir / "state.json").read_text(
                encoding="utf-8"
            )
        )

        migrated_identity = json.loads(
            (migrated_dir / "identity.json").read_text(
                encoding="utf-8"
            )
        )

        migrated_events = read_jsonl(
            migrated_dir / "events.jsonl"
        )

        require(
            migrated_state["session"] == 3
            and migrated_state["events_processed"] == 9
            and migrated_state["status"] == "sleeping",
            "Migrated instance did not continue correctly",
        )

        require(
            migrated_identity["instance_id"] == instance_id,
            "Migrated instance lost its identity",
        )

        require(
            len(migrated_events) == 9,
            "Migrated instance lost event history",
        )

        # Продолжение копии не должно менять исходный каталог.
        original_state = json.loads(
            (data_dir / "state.json").read_text(
                encoding="utf-8"
            )
        )

        require(
            original_state["session"] == 2,
            "Running migrated data modified the original instance data",
        )

    print(
        "[OK] Data directory: explicit path is cwd-independent "
        "and copied data preserves instance continuity."
    )


def check_recovery():
    with tempfile.TemporaryDirectory(prefix="anima-check-") as temp_dir:
        temp = Path(temp_dir)
        original, restored = temp / "original", temp / "restored"
        copy_source(original)
        run_session(original, "Проверка ANIMA")
        state = json.loads((original / "data/state.json").read_text(encoding="utf-8"))
        require(state["session"] == 1 and state["status"] == "sleeping", "First session did not finish correctly")
        backup = temp / "instance.tar.gz"
        with tarfile.open(backup, "w:gz") as archive:
            archive.add(original / "data", arcname="data")
        copy_source(restored)
        with tarfile.open(backup, "r:gz") as archive:
            archive.extractall(restored, filter="data")
        for path in (original / "data").iterdir():
            require(path.read_bytes() == (restored / "data" / path.name).read_bytes(), "Restored data differs before restart")
        run_session(restored, "   ")
        state = json.loads((restored / "data/state.json").read_text(encoding="utf-8"))
        events = read_jsonl(restored / "data/events.jsonl")
        memories = read_jsonl(restored / "data/memories.jsonl")
        require(state["session"] == 2 and state["status"] == "sleeping", "Restored instance did not continue its session")
        require(state["events_processed"] == 6 and len(events) == 6, "Event history was lost across recovery")
        require([event["type"] for event in events] == ["wake", "user_input", "sleep"] * 2, "Unexpected event order across recovery")
        require(len(memories) == 1 and memories[0]["content"]["text"] == "Проверка ANIMA", "Selected memory was lost or blank input was stored")
    print("[OK] Temporary backup/recovery: two sessions, six raw events, one selected memory.")
    print("[OK] Raw event history and selected memory remain separate across recovery.")


def check_runtime_headless():
    with tempfile.TemporaryDirectory(
        prefix="anima-runtime-check-"
    ) as temp_dir:
        anima = AnimaTestHarness(temp_dir)

        wake_events = anima.runtime.wake()
        input_events = anima.runtime.user_input(
            "headless runtime check"
        )
        sleep_events = anima.runtime.sleep()

        require(
            [event.event_type for event in wake_events]
            == ["wake"],
            "Runtime wake produced unexpected events",
        )

        require(
            [event.event_type for event in input_events]
            == ["user_input"],
            "Runtime user_input produced unexpected events",
        )

        require(
            [event.event_type for event in sleep_events]
            == ["sleep"],
            "Runtime sleep produced unexpected events",
        )

        final_state = anima.state.get()

        require(
            final_state["status"] == "sleeping",
            "Headless Runtime did not finish sleeping",
        )

        require(
            final_state["session"] == 1,
            "Headless Runtime session counter is incorrect",
        )

        require(
            final_state["events_processed"] == 3,
            "Headless Runtime processed unexpected event count",
        )

    print(
        "[OK] Runtime headless: lifecycle works "
        "without terminal input."
    )


def check_runtime_snapshot():
    with tempfile.TemporaryDirectory(
        prefix="anima-snapshot-check-"
    ) as temp_dir:
        anima = AnimaTestHarness(temp_dir)

        initial = anima.runtime.snapshot()

        require(
            initial["state"]["status"] == "created",
            "Initial snapshot has unexpected status",
        )

        instance_id = initial["identity"]["instance_id"]

        anima.runtime.wake()
        anima.runtime.user_input(
            "snapshot regression check"
        )
        anima.runtime.sleep()

        final = anima.runtime.snapshot()

        require(
            final["identity"]["instance_id"]
            == instance_id,
            "Snapshot instance identity changed unexpectedly",
        )

        require(
            final["state"]["status"] == "sleeping",
            "Final snapshot has unexpected status",
        )

        require(
            final["state"]["events_processed"] == 3,
            "Final snapshot has unexpected event count",
        )

        require(
            final["memory"]["count"] == 1,
            "Final snapshot has unexpected memory count",
        )

    print(
        "[OK] Runtime snapshot: diagnostic state "
        "remains structured and consistent."
    )


def main():
    require(sys.version_info >= (3, 12), "Use Python 3.12 or newer; validated baseline: 3.12.14")
    check_documentation()
    check_sources()
    check_cli_extraction()
    check_runtime_headless()
    check_runtime_snapshot()
    check_tracked_data()
    check_event_validation()
    check_event_log_validation()
    check_memory_validation()
    check_state_write_safety()
    check_interrupted_sessions()
    check_data_directory_configuration()
    check_recovery()
    print(f"Checks passed on Python {sys.version.split()[0]}.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        sys.exit(1)
