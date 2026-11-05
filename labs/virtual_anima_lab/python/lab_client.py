"""P5-A Godot loopback client; not an ANIMA Core adapter or auth mechanism."""

from __future__ import annotations

import json
import math
import socket
from typing import Any

PROTOCOL = "val.bridge/0.1"
MAX_LINE_BYTES = 8192
MAX_PROTOCOL_INTEGER = 2147483647


def _exact_protocol_integer(value: Any) -> int | None:
    """Accept JSON 1 and 1.0, but never bool, fractions, NaN or infinity."""
    if type(value) is int and 0 <= value <= MAX_PROTOCOL_INTEGER:
        return value
    if (
        type(value) is float
        and math.isfinite(value)
        and 0.0 <= value <= float(MAX_PROTOCOL_INTEGER)
        and value.is_integer()
    ):
        return int(value)
    return None


class LabProtocolError(RuntimeError):
    """Malformed or mismatched bridge response."""


class LabRejected(RuntimeError):
    """Well-formed command rejected by the test-world bridge."""

    def __init__(self, error: str, *, response: dict[str, Any]):
        super().__init__(error)
        self.error = error
        self.response = response


class LabClient:
    """One sequential request/response stream on 127.0.0.1 only.

    Roles are *self-declared*: P5 uses a local test controller. Until a trusted
    bridge is built in P6, this transport must not be exposed to remote hosts
    or attached to ANIMA production authority.
    """

    def __init__(
        self, port: int = 46019, *, role: str = "agent", timeout: float = 3.0
    ) -> None:
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError("port must be an integer in 1024..65535")
        if role not in ("agent", "operator"):
            raise ValueError("role must be agent or operator")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.port = port
        self.role = role
        self.timeout = timeout
        self._socket: socket.socket | None = None
        self._reader = None
        self._sequence = 0

    def connect(self) -> "LabClient":
        if self._socket is not None:
            raise RuntimeError("LabClient already connected")
        self._socket = socket.create_connection(
            ("127.0.0.1", self.port), timeout=self.timeout
        )
        self._socket.settimeout(self.timeout)
        self._reader = self._socket.makefile("rb")
        return self

    def close(self) -> None:
        if self._reader is not None:
            self._reader.close()
            self._reader = None
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def __enter__(self) -> "LabClient":
        return self.connect()

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    def call(self, op: str, **fields: Any) -> dict[str, Any]:
        if self._socket is None or self._reader is None:
            raise RuntimeError("LabClient is not connected")
        if not op or not isinstance(op, str):
            raise ValueError("operation must be a nonempty string")
        for protected in ("protocol", "role", "id", "op"):
            if protected in fields:
                raise ValueError(f"reserved protocol field: {protected}")
        self._sequence += 1
        request = {
            "protocol": PROTOCOL,
            "id": self._sequence,
            "role": self.role,
            "op": op,
            **fields,
        }
        payload = (json.dumps(request, separators=(",", ":"), sort_keys=True) + "\n").encode(
            "utf-8"
        )
        if len(payload) > MAX_LINE_BYTES:
            raise ValueError("request exceeds the P5-A line limit")
        self._socket.sendall(payload)
        raw = self._reader.readline(MAX_LINE_BYTES + 1)
        if not raw:
            raise LabProtocolError("connection closed before response")
        if len(raw) > MAX_LINE_BYTES or not raw.endswith(b"\n"):
            raise LabProtocolError("response exceeded line limit or lacked terminator")
        try:
            response = json.loads(raw)
        except (UnicodeError, ValueError) as error:
            raise LabProtocolError("non-JSON bridge response") from error
        if type(response) is not dict:
            raise LabProtocolError("bridge response is not an object")
        reply_id = _exact_protocol_integer(response.get("id"))
        tick = _exact_protocol_integer(response.get("tick"))
        if (
            response.get("protocol") != PROTOCOL
            or reply_id != self._sequence
            or tick is None
            or type(response.get("ok")) is not bool
        ):
            raise LabProtocolError(
                f"bridge response contract/id mismatch "
                f"(expected id={self._sequence}; "
                f"got id={response.get('id')!r}, tick={response.get('tick')!r}, "
                f"protocol={response.get('protocol')!r})"
            )
        # Normalize a numeric JSON transport detail before exposing it to
        # the caller; the agent still has no operator privileges.
        response["id"] = reply_id
        response["tick"] = tick
        if not response["ok"]:
            error = response.get("error")
            if not isinstance(error, str) or not error:
                raise LabProtocolError("failed response without error code")
            raise LabRejected(error, response=response)
        if type(response.get("data")) is not dict:
            raise LabProtocolError("successful response without structured data")
        return response
