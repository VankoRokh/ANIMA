"""ANIMA v0.1 foundation: persistent, LLM-free, line-oriented local runtime.

Run with: python -m anima.release_v01 --data-dir <private-directory>
The stdin protocol is a local operator channel, NOT a network/authentication
boundary. Reports cannot impersonate registered Core observations or create
executable Goal bindings. This module composes existing production Core services.
"""

import argparse
import fcntl
import json
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from anima.core.assembly import build_core, CoreAssembly
from anima.memory.context_builder import ContextBuilder
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import RetrievalEngine


PROTOCOL = "anima.release.v0_1/0.1"
MAX_REPORT = 4096
MAX_QUERY = 256


class ProtocolError(ValueError):
    """Only client-shape errors; persistence/recovery failures must surface."""


def _request_text(request, *, name, limit):
    value = request.get(name)
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise ProtocolError(f"{name} must be nonempty text of at most {limit} characters")
    return value.strip()


def _exact_keys(request, keys):
    if type(request) is not dict or set(request) != set(keys):
        raise ProtocolError(f"expected fields: {', '.join(sorted(keys))}")


@contextmanager
def _single_writer(root: Path):
    """Protect multi-DB release instance from concurrent cooperative processes.

    POSIX advisory lock: a trusted local process can still bypass this lock
    by opening storage directly. Lock releases on SIGKILL.
    """
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".anima-v01.lock"
    with lock_path.open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"ANIMA v0.1 instance is already running: {root}") from exc
        try:
            yield root
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@dataclass
class ReleaseSession:
    core: CoreAssembly
    context: ContextBuilder
    stopped: bool = False

    def _index_complete(self):
        """Bounded incremental sync; never fabricate a complete search result."""
        index = self.core.event_retrieval
        for _ in range(256):
            row = index.sync(max_events=256)
            if row["status"] == "complete":
                return row
            if row["indexed_now"] == 0:
                break
        raise RuntimeError("Raw Event index incomplete; search refused")

    def status(self):
        state = self.core.state.get()
        return {
            "schema": PROTOCOL,
            "instance_id": self.core.identity.get()["instance_id"],
            "state": state["status"],
            "session": state["session"],
            "memories": self.core.memory_store.count(),
            "event_index": self.core.event_retrieval.status(),
            "model_required": False,
            "world_required": False,
            "external_executor_enabled": False,
        }

    def handle(self, request):
        if type(request) is not dict or type(request.get("op")) is not str:
            raise ProtocolError("request must be an object with a string op")
        op = request["op"]
        if op == "status":
            _exact_keys(request, {"op"})
            return {"op": op, "ok": True, "result": self.status()}
        if op == "report":
            _exact_keys(request, {"op", "text"})
            text = _request_text(request, name="text", limit=MAX_REPORT)
            events = self.core.runtime.user_input(text)
            return {
                "op": op, "ok": True,
                "event_ids": [event.event_id for event in events],
                "memory_count": self.core.memory_store.count(),
            }
        if op == "search_events":
            _exact_keys(request, {"op", "query"})
            query = _request_text(request, name="query", limit=MAX_QUERY)
            self._index_complete()
            results = self.core.event_retrieval.search(query, top_k=5)
            return {"op": op, "ok": True, "result": results}
        if op == "context":
            _exact_keys(request, {"op", "query"})
            query = _request_text(request, name="query", limit=MAX_QUERY)
            self._index_complete()
            bundle = self.context.build(
                query, consumer="FAST", max_items=4, max_chars=900,
                retrieval_options={"kinds": ("memory",)},
            )
            return {"op": op, "ok": True, "result": bundle}
        if op == "stop":
            _exact_keys(request, {"op"})
            self.stopped = True
            return {"op": op, "ok": True, "result": "STOP_REQUESTED"}
        raise ProtocolError("unsupported operation; no source, Goal or Tool commands accepted")


@contextmanager
def open_release(root: str | Path):
    """Open one continuous instance. No test world, LLM or implicit tool rights."""
    with _single_writer(Path(root)) as data_dir:
        core = build_core(
            data_dir,
            sources={}, properties={}, goal_actions={},
            enable_event_retrieval=True,
            auto_core=False,
        )
        if (
            core.core_events is None or core.core_decision is None
            or core.core_execution is not None or core.core_autonomy is not None
        ):
            raise AssertionError("v0.1 no-actuator composition contract violated")
        provenance = ProvenanceResolver(
            core.memory_store, core.link_store, core.event_log,
            event_retrieval=core.event_retrieval,
        )
        context = ContextBuilder(
            retrieval=RetrievalEngine(
                memory_store=core.memory_store, link_store=core.link_store,
            ),
            provenance=provenance,
        )
        core.runtime.wake()
        session = ReleaseSession(core=core, context=context)
        try:
            yield session
        finally:
            if core.state.get()["status"] != "sleeping":
                core.runtime.sleep()


def serve(root: str | Path, *, instream=None, outstream=None):
    """Process multiple ordered commands in one interpreter; EOF shuts down."""
    instream = sys.stdin if instream is None else instream
    outstream = sys.stdout if outstream is None else outstream

    def emit(value):
        outstream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        outstream.flush()

    with open_release(root) as session:
        emit({"op": "ready", "ok": True, "result": session.status()})
        for line in instream:
            if not line.strip():
                continue
            try:
                request = json.loads(line)
                result = session.handle(request)
            except (json.JSONDecodeError, ProtocolError) as exc:
                emit({"op": "error", "ok": False, "reason": str(exc)})
                continue
            emit(result)
            if session.stopped:
                break


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    serve(args.data_dir)


if __name__ == "__main__":
    main()
