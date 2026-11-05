"""P5-A client contract checks without Godot or ANIMA Core dependencies.

These tests validate transport framing; they do NOT demonstrate an actual
Godot process. The separate headless smoke gate must be run with Godot.
"""

import json
import socketserver
import threading

import pytest

from labs.virtual_anima_lab.python.lab_client import (
    LabClient, LabProtocolError, LabRejected, PROTOCOL,
)


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        for raw in self.rfile:
            request = json.loads(raw)
            if request["op"] == "invalid_json":
                self.wfile.write(b"not-json\n")
                continue
            reply = {
                "protocol": PROTOCOL,
                "id": request["id"] + (1 if request["op"] == "wrong_id" else 0),
                "ok": request["op"] != "forbidden",
                "tick": 3,
                "data": {"role": request["role"], "op": request["op"]},
            }
            if request["op"] == "forbidden":
                reply.pop("data")
                reply["error"] = "FORBIDDEN"
            self.wfile.write((json.dumps(reply) + "\n").encode("utf-8"))


@pytest.fixture()
def bridge():
    class _Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_val_p5a_client_serializes_versioned_sequential_messages(bridge):
    with LabClient(bridge, role="agent") as client:
        first = client.call("ping")
        second = client.call("observe")
    assert (first["id"], second["id"]) == (1, 2)
    assert first["protocol"] == PROTOCOL
    assert second["data"] == {"role": "agent", "op": "observe"}


def test_val_p5a_client_exposes_rejections_without_spoofing_success(bridge):
    with LabClient(bridge, role="agent") as client:
        with pytest.raises(LabRejected) as error:
            client.call("forbidden")
        assert error.value.error == "FORBIDDEN"
        assert error.value.response["ok"] is False


@pytest.mark.parametrize("operation", ["wrong_id", "invalid_json"])
def test_val_p5a_client_rejects_invalid_transport_response(bridge, operation):
    with LabClient(bridge, role="operator") as client:
        with pytest.raises(LabProtocolError):
            client.call(operation)


def test_val_p5a_client_blocks_reserved_request_fields(bridge):
    with LabClient(bridge, role="agent") as client:
        with pytest.raises(ValueError, match="reserved protocol field"):
            client.call("ping", role="operator")


@pytest.mark.parametrize(
    "port,role",
    [(0, "agent"), (46019, "root"), (True, "agent")],
)
def test_val_p5a_client_refuses_bad_configuration(port, role):
    with pytest.raises(ValueError):
        LabClient(port, role=role)
