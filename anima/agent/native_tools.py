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

from anima.agent.tools import ToolRegistry, validate_schema, validate_instance


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


class NativeArgumentError(ValueError):
    """Well-formed JSON arguments rejected by a known tool's input contract."""
    def __init__(self, descriptor, cause):
        super().__init__(str(cause))
        self.descriptor = descriptor


RECOVERABLE_TOOL_ERRORS = {
    "UNEXPOSED_EVIDENCE_ID": "Use only event IDs already exposed in observations or completed search results. You may choose another available information tool or stop with uncertainty.",
    "INVALID_TOOL_ARGUMENTS": "Arguments do not match the tool input schema. Inspect the available tool definitions, choose valid arguments or stop with uncertainty.",
}


class NativeToolCatalog:
    """Detached registry snapshot. Exact, collision-checked wire-name mapping."""

    def __init__(self, registry, *, set_arguments=None):
        if not isinstance(registry, ToolRegistry):
            raise TypeError("ToolRegistry required")
        self._by_wire = {}
        self._wire_schemas = {}
        self._set_fields = {}
        pending = dict(set_arguments or {})
        for descriptor in registry.list_descriptors():
            if descriptor.effect_class != "read_only":
                raise ValueError("native read-only profile cannot expose effectful tools")
            wire = descriptor.name.replace(".", "_")
            if len(wire) > 64 or wire in self._by_wire:
                raise ValueError("ambiguous or overlong wire tool name")
            self._by_wire[wire] = descriptor
            schema = descriptor.to_dict()['input_schema']
            fields = tuple(pending.pop(descriptor.key, ()))
            for field in fields:
                prop = schema['properties'].get(field, {})
                if (field not in schema['required'] or prop.get('type') != 'array'
                        or prop.get('uniqueItems') is not True
                        or prop.get('items', {}).get('type') != 'string'
                        or type(prop.get('maxItems')) is not int):
                    raise ValueError('set projection requires a bounded required unique string array')
                # Validate original input size and items before canonicalization.
                prop.pop('uniqueItems')
            self._wire_schemas[wire] = schema
            self._set_fields[wire] = fields
        if pending:
            raise ValueError('set projection references unregistered tool version')

    def definitions(self):
        return [
            {"type": "function", "function": {
                "name": name, "description": descriptor.description,
                "parameters": strict_json(canonical(self._wire_schemas[name])),
            }} for name, descriptor in self._by_wire.items()
        ]

    def decode(self, name, arguments):
        if type(name) is not str or name not in self._by_wire:
            raise ValueError("unknown or unexposed tool")
        if type(arguments) is not str or len(arguments.encode("utf-8")) > 4096:
            raise ValueError("invalid tool arguments envelope")
        args = strict_json(arguments)
        descriptor = self._by_wire[name]
        fields = self._set_fields[name]
        try:
            if fields:
                validate_instance(args, validate_schema(self._wire_schemas[name], input_schema=True))
                args = {**args, **{field: list(dict.fromkeys(args[field])) for field in fields}}
            descriptor.validate_input(args)
        except ValueError as exc:
            raise NativeArgumentError(descriptor, exc) from exc
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

    def __init__(self, catalog, *, model, system_prompt, user_prompt, transport,
                 first_tool_required=False, argument_feedback=False):
        if type(first_tool_required) is not bool:
            raise TypeError('first_tool_required must be boolean')
        self.first_tool_required = first_tool_required
        if type(argument_feedback) is not bool:
            raise TypeError("argument_feedback must be boolean")
        self.argument_feedback = argument_feedback
        self.pending_error = None
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
        require_tool = self.first_tool_required and not self.calls
        payload = {"model": self.model, "messages": strict_json(canonical(self.messages)),
                   "tools": self.catalog.definitions(),
                   "tool_choice": "required" if require_tool else "auto",
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
                if require_tool:
                    raise ValueError("required first tool call missing")
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
            try:
                descriptor, args = self.catalog.decode(fn["name"], fn["arguments"])
            except NativeArgumentError as exc:
                if not self.argument_feedback:
                    raise
                descriptor = exc.descriptor
                self.seen_ids.add(call_id)
                self.pending = (call_id, descriptor)
                self.pending_error = "INVALID_TOOL_ARGUMENTS"
                self.messages.append({"role":"assistant", "content":content or "",
                                      "tool_calls":[call]})
                record.update(valid=False, error=str(exc), tool_name=descriptor.name,
                              tool_call_id=call_id, error_code=self.pending_error,
                              original_arguments=strict_json(fn["arguments"]))
                return descriptor, None
            original_args = strict_json(fn["arguments"])
            record.update(original_arguments=original_args,
                          arguments_normalized=original_args != args)
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
        if (self.pending is None or self.pending[1] is not descriptor or self.terminal
                or self.pending_error is not None):
            raise ValueError("result does not bind valid pending tool")
        descriptor.validate_output(result)
        content = canonical(result)
        if len(content.encode("utf-8")) > 16384:
            raise ValueError("tool result exceeds byte budget")
        self.messages.append({"role": "tool", "tool_call_id": self.pending[0],
                              "content": content})
        self.pending = None


    def reject_pending(self, descriptor, *, reason_code):
        """Resolve a syntactically valid call with a trusted denial, not a result.

        Only the host may invoke this method after recording non-execution.
        Does not change the catalog, arguments, or source permissions.
        """
        if self.pending is None or self.pending[1] is not descriptor or self.terminal:
            raise ValueError("error does not bind pending tool")
        expected = self.pending_error or "UNEXPOSED_EVIDENCE_ID"
        if reason_code != expected or reason_code not in RECOVERABLE_TOOL_ERRORS:
            raise ValueError("unsupported or mismatched recoverable rejection")
        self.messages.append({"role": "tool", "tool_call_id": self.pending[0],
            "content": canonical({"status": "rejected", "error_code": reason_code,
                                  "execution_performed": False,
                                  "message": RECOVERABLE_TOOL_ERRORS[reason_code]})})
        self.pending = None
        self.pending_error = None
