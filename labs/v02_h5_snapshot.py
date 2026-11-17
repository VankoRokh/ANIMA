"""ANIMA v0.2 H5.4 — explicit offline snapshot and restore (no auto-migration).

CREATE requires a STOPPED, labeled release_v01 instance with its advisory
writer lock available, and creates a NEW snapshot directory exclusively.
All SQLite databases are copied using SQLite's online-backup API; non-DB
files are copied byte-exact with SHA-256 checks. Lock and SQLite transient
WAL/SHM/journal files are never replayed. The source root is not modified.

RESTORE verifies every snapshot entry BEFORE creating a NEW destination
instance and intentionally excludes derived event_index.db, whose SQLite
cursor includes the old EventLog file's inode. It is rebuilt from restored
Raw when open_release initializes. All other DBs/Raw/identity are restored.

Security/atomicity scope: fcntl's release lock protects cooperative writers,
not rogue direct DB/Raw writers; a cross-DB snapshot is only consistent when
all instance writers are stopped. No physical power-loss/fsync guarantees.
Neither step performs legacy Knowledge repairs. This is a LAB workflow,
not a generic production migration tool.

Examples:
  PYTHONPATH="$PWD" .venv/bin/python -m labs.v02_h5_snapshot create \
      --source /path/to/STOPPED-release-instance \
      --destination /path/to/NEW-snapshot-directory

  PYTHONPATH="$PWD" .venv/bin/python -m labs.v02_h5_snapshot verify \
      --snapshot /path/to/snapshot-directory

  PYTHONPATH="$PWD" .venv/bin/python -m labs.v02_h5_snapshot restore \
      --snapshot /path/to/snapshot-directory \
      --destination /path/to/NEW-instance-directory
"""

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import stat
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

from anima.release_v01 import PROTOCOL

SCHEMA = "anima.v02.h5.snapshot/0.1"
MANIFEST = "h5_snapshot_manifest.json"
LOCK = ".anima-v01.lock"
DERIVED = {"event_index.db"}
REQUIRED = {
    "release_profile.json", "identity.json", "state.json",
    "events.jsonl", "memory.db", "internal_state.db", "core_state.db",
}
REQUIRED_SANDBOX = {
    "sandbox_world/virtual_door.db", "core_work.db",
    "tasks.db", "execution.db",
}
IGNORED_SUFFIXES = ("-wal", "-shm", "-journal")


def _hash(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _private_path(path):
    candidate = Path(path).expanduser().absolute()
    if candidate.is_symlink():
        raise ValueError("Symlink root refused: " + str(candidate))
    # Resolve PARENT symlinks too, otherwise a destination alias can evade
    # the overlap gate and snapshot a source into itself.
    return candidate.resolve(strict=False)


def _refuse_overlap(source, destination):
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("Snapshot/restore source and destination must not overlap")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Destination already exists: " + str(destination))
    if not destination.parent.is_dir():
        raise FileNotFoundError("Destination parent directory must already exist")


def _inventory(root, *, skip_transients=False):
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Instance/snapshot must be an existing real directory")
    paths = {}
    for base, directories, files in os.walk(root, followlinks=False):
        for name in directories:
            full = Path(base) / name
            if full.is_symlink():
                raise ValueError("Symlink directory refused: " + str(full))
        for name in files:
            full = Path(base) / name
            mode = full.lstat().st_mode
            if not stat.S_ISREG(mode):
                raise ValueError("Non-regular file refused: " + str(full))
            rel = full.relative_to(root).as_posix()
            if skip_transients and (
                rel == LOCK
                or name.endswith(IGNORED_SUFFIXES) and ".db-" in name
            ):
                continue
            paths[rel] = full
    return dict(sorted(paths.items()))


@contextmanager
def _stopped_release(source):
    if not source.is_dir() or source.is_symlink():
        raise FileNotFoundError("Expected a stopped release instance directory")
    profile_path = source / "release_profile.json"
    if profile_path.is_symlink() or not profile_path.is_file():
        raise ValueError("Unlabeled instance: release_profile.json missing")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    if (
        not isinstance(profile, dict)
        or profile.get("schema") != PROTOCOL
        or profile.get("capability") not in {"none", "sandbox_door"}
        or set(profile) != {"schema", "capability"}
    ):
        raise ValueError("Unsupported release profile; migration not authorized")
    lock = source / LOCK
    if not lock.is_file() or lock.is_symlink():
        raise ValueError("Cannot verify release writer lock: missing lock file")
    # Read-only opening of the existing lock does not create/modify it.
    with lock.open("rb") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Release instance is active; snapshot refused") from error
        try:
            yield profile
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _require_release_files(paths, capability):
    required = set(REQUIRED)
    if capability == "sandbox_door":
        required.update(REQUIRED_SANDBOX)
    missing = sorted(required - set(paths))
    if missing:
        raise ValueError(
            "Snapshot missing release state file(s): " + ", ".join(missing)
        )


def _read_only_sqlite_backup(source, destination):
    uri = "file:" + quote(str(source.resolve()), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as original:
        original.execute("PRAGMA query_only=ON")
        row = original.execute("PRAGMA quick_check(1)").fetchone()
        if row is None or row[0] != "ok":
            raise ValueError("SQLite source quick_check failed: " + str(source))
        with sqlite3.connect(destination) as target:
            original.backup(target)
    destination.chmod(0o600)


def _copy_plain(source, destination):
    begin = _hash(source)
    with source.open("rb") as stream, destination.open("xb") as output:
        shutil.copyfileobj(stream, output, length=1024 * 1024)
        output.flush()
    destination.chmod(0o600)
    if _hash(source) != begin or _hash(destination) != begin:
        raise ValueError("File changed during snapshot/copy: " + str(source))


def _write_manifest(root, entries, profile):
    data = {
        "schema": SCHEMA,
        "release_protocol": PROTOCOL,
        "release_capability": profile["capability"],
        "derived_rebuild_on_restore": sorted(DERIVED),
        "entries": entries,
    }
    with (root / MANIFEST).open("x", encoding="utf-8") as handle:
        json.dump(data, handle, sort_keys=True, ensure_ascii=False, indent=2)
        handle.write("\n")
    (root / MANIFEST).chmod(0o600)
    return data


def create_snapshot(source, destination):
    source, destination = _private_path(source), _private_path(destination)
    _refuse_overlap(source, destination)
    with _stopped_release(source) as profile:
        files = _inventory(source, skip_transients=True)
        if MANIFEST in files:
            raise ValueError("Snapshot manifest name is reserved")
        _require_release_files(files, profile["capability"])
        # Reserve the output only after validating source/lock. If a copy
        # fails, the partial folder has NO manifest and cannot be restored.
        destination.mkdir(mode=0o700)
        entries = []
        for rel, source_file in files.items():
            target = destination / rel
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if rel.endswith(".db"):
                _read_only_sqlite_backup(source_file, target)
                kind = "sqlite_backup"
            else:
                _copy_plain(source_file, target)
                kind = "byte_copy"
            entries.append({
                "path": rel,
                "kind": kind,
                "size": target.stat().st_size,
                "sha256": _hash(target),
            })
        manifest = _write_manifest(destination, entries, profile)
        verify_snapshot(destination)
        return {
            "status": "SNAPSHOT_CREATED",
            "snapshot": str(destination),
            "file_count": len(entries),
            "manifest_sha256": _hash(destination / MANIFEST),
            "protocol": manifest["release_protocol"],
            "derived_rebuild_on_restore": manifest["derived_rebuild_on_restore"],
        }


def verify_snapshot(snapshot):
    snapshot = _private_path(snapshot)
    files = _inventory(snapshot)
    manifest_file = snapshot / MANIFEST
    if MANIFEST not in files:
        raise ValueError("Snapshot incomplete: missing manifest")
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict) or data.get("schema") != SCHEMA
        or data.get("release_protocol") != PROTOCOL
        or data.get("release_capability") not in {"none", "sandbox_door"}
        or data.get("derived_rebuild_on_restore") != sorted(DERIVED)
        or not isinstance(data.get("entries"), list)
    ):
        raise ValueError("Unsupported or malformed snapshot manifest")
    entries = data["entries"]
    expected = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "path", "kind", "size", "sha256"
        }:
            raise ValueError("Malformed snapshot entry")
        rel = entry["path"]
        if (
            not isinstance(rel, str) or not rel or "\\" in rel
            or Path(rel).is_absolute() or ".." in Path(rel).parts
            or Path(rel).as_posix() != rel or rel in expected
            or rel in {LOCK, MANIFEST}
        ):
            raise ValueError("Unsafe or repeated manifest path")
        if entry["kind"] not in {"sqlite_backup", "byte_copy"}:
            raise ValueError("Unknown snapshot entry kind")
        if (
            type(entry["size"]) is not int or entry["size"] < 0
            or not isinstance(entry["sha256"], str)
            or len(entry["sha256"]) != 64
        ):
            raise ValueError("Malformed snapshot hash/size")
        expected[rel] = entry
    if set(files) != set(expected) | {MANIFEST}:
        raise ValueError("Snapshot file set does not match manifest")
    _require_release_files(expected, data["release_capability"])
    for rel, entry in expected.items():
        current = files[rel]
        if (
            current.stat().st_size != entry["size"]
            or _hash(current) != entry["sha256"]
        ):
            raise ValueError("Snapshot hash mismatch: " + rel)
    if "release_profile.json" not in files:
        raise ValueError("Snapshot does not contain release_profile.json")
    profile = json.loads(files["release_profile.json"].read_text(encoding="utf-8"))
    if profile != {
        "schema": PROTOCOL, "capability": data["release_capability"],
    }:
        raise ValueError("Release profile differs from snapshot manifest")
    return {
        "status": "VERIFIED",
        "snapshot": str(snapshot),
        "file_count": len(expected),
        "manifest_sha256": _hash(manifest_file),
        "derived_rebuild_on_restore": sorted(DERIVED),
    }


def restore_snapshot(snapshot, destination):
    snapshot, destination = _private_path(snapshot), _private_path(destination)
    _refuse_overlap(snapshot, destination)
    check = verify_snapshot(snapshot)
    data = json.loads((snapshot / MANIFEST).read_text(encoding="utf-8"))
    # Deliberately do not replay the derived FTS index from a different
    # inode / EventLog path. On open_release it is regenerated from Raw.
    skipped = []
    destination.mkdir(mode=0o700)
    for entry in data["entries"]:
        rel = entry["path"]
        if rel in DERIVED:
            skipped.append(rel)
            continue
        source_file = snapshot / rel
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _copy_plain(source_file, target)
    # The lock file is intentionally absent: open_release creates it.
    if (destination / LOCK).exists():
        raise AssertionError("Restore unexpectedly copied a release lock")
    return {
        "status": "RESTORED_TO_NEW_DIRECTORY",
        "destination": str(destination),
        "files_restored": len(data["entries"]) - len(skipped),
        "derived_indexes_rebuild_on_open": skipped,
        "source_manifest_sha256": check["manifest_sha256"],
        "release_protocol": PROTOCOL,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="operation", required=True)
    creator = subs.add_parser("create")
    creator.add_argument("--source", type=Path, required=True)
    creator.add_argument("--destination", type=Path, required=True)
    verifier = subs.add_parser("verify")
    verifier.add_argument("--snapshot", type=Path, required=True)
    restorer = subs.add_parser("restore")
    restorer.add_argument("--snapshot", type=Path, required=True)
    restorer.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.operation == "create":
        report = create_snapshot(args.source, args.destination)
    elif args.operation == "verify":
        report = verify_snapshot(args.snapshot)
    else:
        report = restore_snapshot(args.snapshot, args.destination)
    print(json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
