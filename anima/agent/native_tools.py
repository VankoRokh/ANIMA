"""OpenAI-compatible native tool protocol for a frozen read-only registry.

No handlers, credentials for tools, execution authority or task-specific logic.
The caller owns admission, execution, verification and turn budgets.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from urllib.parse import urlsplit

from anima.agent.tools import ToolRegistry


def strict_json(text):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError("duplicate JSON key")
            result[k] = v
        return result

    def constant(value):
        raise ValueError("non-finite JSON: " + value)

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"))


class NativeToolCatalog:
    """Detached registry snapshot. Exact, collision-checked wire-name mapping."""

    def __init__(self, registry):
        if not isinstance(registry, ToolRegistry):
            raise TypeError("ToolRegistry required")
        self._by_wire = {}
        for descriptor in registry.list_descriptors():
            if descriptor.effect_class != "read_only":
                raise ValueError("native read-only profile cannot expose effectful tools")
            wire = descriptor.name.replace(".", "_")
            if len(wire) > 64 or wire in self._by_wire:
                raise ValueError("ambiguous or overlong wire tool name")
            self._by_wire[wire] = descriptor

    def definitions(self):
        return [
            {"type": "function", "function": {
                "name": name, "description": descriptor.description,
                "parameters": descriptor.to_dict()["input_schema"],
            }} for name, descriptor in self._by_wire.items()
        ]

    def decode(self, name, arguments):
        if type(name) is not str or name not in self._by_wire:
            raise ValueError("unknown or unexposed tool")
        if type(arguments) is not str or len(arguments.encode("utf-8")) > 4096:
            raise ValueError("invalid tool arguments envelope")
        args = strict_json(arguments)
        descriptor = self._by_wire[name]
        descriptor.validate_input(args)
        return descriptor, args


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class LoopbackChatTransport:
    """Single local HTTP call; no automatic retry, proxy or redirect."""

    def __init__(self, base_url, *, timeout=45.0):
        u = urlsplit(base_url)
        if (u.scheme != "http" or u.hostname not in ("127.0.0.1", "::1")
                or u.port is None or u.username or u.password
                or u.path not in ("", "/") or u.query or u.fragment):
            raise ValueError("explicit loopback endpoint required")
        self.endpoint = base_url.rstrip("/") + "/v1/chat/completions"
        self.timeout = timeout
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect())

    def complete(self, payload):
        request = urllib.request.Request(self.endpoint,
            data=canonical(payload).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"})
        with self._opener.open(request, timeout=self.timeout) as response:
            raw = response.read(200001)
        if len(raw) > 200000:
            raise ValueError("response exceeds transport budget")
        return strict_json(raw.decode("utf-8"))


class NativeToolSession:
    """One model conversation; caller submits only verified tool results."""

    def __init__(self, catalog, *, model, system_prompt, user_prompt, transport):
        self.catalog = catalog
        self.model = model
        self.transport = transport
        self.messages = [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": user_prompt}]
        self.pending = None
        self.seen_ids = set()
        self.calls = []
        self.terminal = False

    def next(self):
        if self.pending is not None or self.terminal:
            raise ValueError("unresolved tool call or terminal session")
        payload = {"model": self.model, "messages": strict_json(canonical(self.messages)),
                   "tools": self.catalog.definitions(), "tool_choice": "auto",
                   "parallel_tool_calls": False, "temperature": 0, "max_tokens": 256,
                   "chat_template_kwargs": {"enable_thinking": False}}
        record = {"request": payload, "raw_response": None, "transport_ok": False,
                  "valid": False}
        started = time.perf_counter()
        try:
            if len(canonical(payload).encode("utf-8")) > 16000:
                raise ValueError("native request exceeds byte budget")
            response = self.transport.complete(payload)
            record.update(transport_ok=True, raw_response=response)
            if type(response) is not dict:
                raise ValueError("invalid completion response")
            usage = response.get("usage", {})
            if type(usage) is dict:
                record.update(input_tokens=usage.get("prompt_tokens"),
                              output_tokens=usage.get("completion_tokens"))
            choices = response.get("choices")
            if type(choices) is not list or len(choices) != 1:
                raise ValueError("exactly one completion choice required")
            choice = choices[0]
            msg = choice["message"]
            finish = choice["finish_reason"]
            record["finish_reason"] = finish
            if msg.get("role") != "assistant":
                raise ValueError("invalid completion role")
            calls = msg.get("tool_calls", [])
            if type(calls) is not list:
                raise ValueError("invalid tool call list")
            content = msg.get("content")
            if content is not None and type(content) is not str:
                raise ValueError("invalid assistant content")
            if not calls:
                if finish != "stop" or not content or not content.strip():
                    raise ValueError("no explicit completed assistant response")
                self.terminal = True
                record.update(valid=True, final_text=content)
                return None
            if finish != "tool_calls" or len(calls) != 1:
                raise ValueError("expected one complete native tool call")
            call = calls[0]
            if set(call) != {"id", "type", "function"} or call["type"] != "function":
                raise ValueError("unexpected tool call fields")
            call_id = call["id"]
            if (type(call_id) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", call_id)
                    or call_id in self.seen_ids):
                raise ValueError("invalid or reused call identity")
            fn = call["function"]
            if type(fn) is not dict or set(fn) != {"name", "arguments"}:
                raise ValueError("invalid function fields")
            descriptor, args = self.catalog.decode(fn["name"], fn["arguments"])
            self.seen_ids.add(call_id)
            self.pending = (call_id, descriptor)
            self.messages.append({"role": "assistant", "content": content or "",
                                  "tool_calls": [call]})
            record.update(valid=True, tool_name=descriptor.name, arguments=args,
                          tool_call_id=call_id)
            return descriptor, args
        except Exception as exc:
            self.terminal = True
            record["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            record["latency_ms"] = (time.perf_counter() - started) * 1000
            self.calls.append(record)

    def submit_result(self, descriptor, result):
        if self.pending is None or self.pending[1] is not descriptor or self.terminal:
            raise ValueError("result does not bind pending tool")
        descriptor.validate_output(result)
        content = canonical(result)
        if len(content.encode("utf-8")) > 16384:
            raise ValueError("tool result exceeds byte budget")
        self.messages.append({"role": "tool", "tool_call_id": self.pending[0],
                              "content": content})
        self.pending = None
