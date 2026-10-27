import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
TOOL_VERSION_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]*$")

EFFECT_CLASSES = {"read_only", "reversible_write", "irreversible"}
IDEMPOTENCY_CLASSES = {"repeat_safe", "keyed", "none"}
EFFORT_HINTS = {"cheap", "normal", "expensive"}

JSON_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}
COMMON_SCHEMA_KEYWORDS = {"type", "description", "enum", "const"}
TYPE_SCHEMA_KEYWORDS = {
    "object": {"properties", "required", "additionalProperties", "minProperties", "maxProperties"},
    "array": {"items", "minItems", "maxItems", "uniqueItems"},
    "string": {"minLength", "maxLength", "pattern"},
    "integer": {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"},
    "number": {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"},
    "boolean": set(),
    "null": set(),
}


class SchemaValidationError(ValueError):
    """A Tool JSON Schema or JSON-compatible value violates the supported contract."""


class ToolInputError(ValueError):
    """Tool input does not satisfy the registered input schema."""


class ToolOutputError(ValueError):
    """Tool output does not satisfy the registered output schema."""


def _validate_non_empty_string(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")


def _validate_json_value(value, *, path="$", label="JSON value"):
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SchemaValidationError(f"{label} at {path} must be finite")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, path=f"{path}[{index}]", label=label)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise SchemaValidationError(f"{label} at {path} must use string object keys")
            _validate_json_value(item, path=f"{path}.{key}", label=label)
        return
    raise SchemaValidationError(
        f"{label} at {path} must be JSON-compatible, got {type(value).__name__}"
    )


def _canonical_json(value):
    _validate_json_value(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _freeze_json(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value):
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _require_non_negative_int(value, *, path, keyword):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SchemaValidationError(
            f"Schema {path}.{keyword} must be a non-negative integer"
        )


def _require_number(value, *, path, keyword):
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise SchemaValidationError(f"Schema {path}.{keyword} must be a finite number")


def _validate_schema_node(schema, *, path="$schema"):
    if not isinstance(schema, Mapping):
        raise SchemaValidationError(f"Schema at {path} must be an object")

    schema_type = schema.get("type")
    if schema_type not in JSON_TYPES:
        raise SchemaValidationError(
            f"Schema {path}.type must be one of {sorted(JSON_TYPES)}, got {schema_type!r}"
        )

    allowed_keywords = COMMON_SCHEMA_KEYWORDS | TYPE_SCHEMA_KEYWORDS[schema_type]
    unknown = set(schema) - allowed_keywords
    if unknown:
        raise SchemaValidationError(
            f"Unsupported schema keyword(s) at {path}: {', '.join(sorted(unknown))}"
        )

    if "description" in schema:
        _validate_non_empty_string(schema["description"], f"Schema {path}.description")

    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, (list, tuple)) or not enum:
            raise SchemaValidationError(f"Schema {path}.enum must be a non-empty array")
        keys = []
        for index, value in enumerate(enum):
            _validate_json_value(value, path=f"{path}.enum[{index}]", label="enum value")
            key = _canonical_json(_thaw_json(value))
            if key in keys:
                raise SchemaValidationError(f"Schema {path}.enum contains duplicates")
            keys.append(key)

    if "const" in schema:
        _validate_json_value(schema["const"], path=f"{path}.const", label="const value")

    if schema_type == "object":
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            raise SchemaValidationError(f"Schema {path}.properties must be an object")
        for name, child in properties.items():
            if not isinstance(name, str) or not name:
                raise SchemaValidationError(
                    f"Schema {path}.properties must use non-empty string names"
                )
            _validate_schema_node(child, path=f"{path}.properties.{name}")

        required = schema.get("required", ())
        if not isinstance(required, (list, tuple)) or any(
            not isinstance(name, str) or not name for name in required
        ):
            raise SchemaValidationError(f"Schema {path}.required must be an array of strings")
        if len(required) != len(set(required)):
            raise SchemaValidationError(f"Schema {path}.required contains duplicates")
        missing_properties = set(required) - set(properties)
        if missing_properties:
            raise SchemaValidationError(
                f"Schema {path}.required references unknown properties: "
                + ", ".join(sorted(missing_properties))
            )

        additional = schema.get("additionalProperties", True)
        if type(additional) is not bool:
            raise SchemaValidationError(
                f"Schema {path}.additionalProperties must be boolean in Stage 4 baseline"
            )

        for keyword in ("minProperties", "maxProperties"):
            if keyword in schema:
                _require_non_negative_int(schema[keyword], path=path, keyword=keyword)
        if (
            "minProperties" in schema
            and "maxProperties" in schema
            and schema["minProperties"] > schema["maxProperties"]
        ):
            raise SchemaValidationError(
                f"Schema {path}.minProperties cannot exceed maxProperties"
            )

    elif schema_type == "array":
        if "items" not in schema:
            raise SchemaValidationError(f"Schema {path}.items is required for arrays")
        _validate_schema_node(schema["items"], path=f"{path}.items")
        for keyword in ("minItems", "maxItems"):
            if keyword in schema:
                _require_non_negative_int(schema[keyword], path=path, keyword=keyword)
        if (
            "minItems" in schema
            and "maxItems" in schema
            and schema["minItems"] > schema["maxItems"]
        ):
            raise SchemaValidationError(f"Schema {path}.minItems cannot exceed maxItems")
        if "uniqueItems" in schema and type(schema["uniqueItems"]) is not bool:
            raise SchemaValidationError(f"Schema {path}.uniqueItems must be boolean")

    elif schema_type == "string":
        for keyword in ("minLength", "maxLength"):
            if keyword in schema:
                _require_non_negative_int(schema[keyword], path=path, keyword=keyword)
        if (
            "minLength" in schema
            and "maxLength" in schema
            and schema["minLength"] > schema["maxLength"]
        ):
            raise SchemaValidationError(
                f"Schema {path}.minLength cannot exceed maxLength"
            )
        if "pattern" in schema:
            pattern = schema["pattern"]
            if not isinstance(pattern, str):
                raise SchemaValidationError(f"Schema {path}.pattern must be a string")
            try:
                re.compile(pattern)
            except re.error as error:
                raise SchemaValidationError(
                    f"Schema {path}.pattern is not a valid regular expression"
                ) from error

    elif schema_type in {"integer", "number"}:
        for keyword in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
            if keyword in schema:
                _require_number(schema[keyword], path=path, keyword=keyword)
        lower = schema.get("minimum")
        upper = schema.get("maximum")
        if lower is not None and upper is not None and lower > upper:
            raise SchemaValidationError(f"Schema {path}.minimum cannot exceed maximum")
        exclusive_lower = schema.get("exclusiveMinimum")
        exclusive_upper = schema.get("exclusiveMaximum")
        if (
            exclusive_lower is not None
            and exclusive_upper is not None
            and exclusive_lower >= exclusive_upper
        ):
            raise SchemaValidationError(
                f"Schema {path}.exclusiveMinimum must be below exclusiveMaximum"
            )


def validate_schema(schema, *, input_schema=False):
    """Validate the strict Stage 4 JSON Schema subset and return a deep immutable copy."""

    if not isinstance(schema, dict):
        raise SchemaValidationError("Tool schema must be a JSON object")
    _validate_json_value(schema, label="schema")
    _validate_schema_node(schema)
    if input_schema:
        if schema.get("type") != "object":
            raise SchemaValidationError("Tool input_schema root type must be 'object'")
        if schema.get("additionalProperties") is not False:
            raise SchemaValidationError(
                "Tool input_schema must set additionalProperties=false"
            )
    return _freeze_json(json.loads(_canonical_json(schema)))


def _matches_json_type(value, schema_type):
    if schema_type == "null":
        return value is None
    if schema_type == "boolean":
        return type(value) is bool
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "object":
        return isinstance(value, dict) and all(isinstance(key, str) for key in value)
    return False


def _instance_error(path, message):
    raise ValueError(f"{path}: {message}")


def _validate_instance(value, schema, *, path="$"):
    schema_type = schema["type"]
    if not _matches_json_type(value, schema_type):
        _instance_error(path, f"expected {schema_type}, got {type(value).__name__}")

    if "enum" in schema:
        value_key = _canonical_json(value)
        enum_keys = {_canonical_json(_thaw_json(item)) for item in schema["enum"]}
        if value_key not in enum_keys:
            _instance_error(path, "value is not in enum")

    if "const" in schema and _canonical_json(value) != _canonical_json(
        _thaw_json(schema["const"])
    ):
        _instance_error(path, "value does not match const")

    if schema_type == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", ())
        missing = [name for name in required if name not in value]
        if missing:
            _instance_error(path, "missing required properties: " + ", ".join(missing))

        if "minProperties" in schema and len(value) < schema["minProperties"]:
            _instance_error(path, f"expected at least {schema['minProperties']} properties")
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            _instance_error(path, f"expected at most {schema['maxProperties']} properties")

        additional = schema.get("additionalProperties", True)
        for name, item in value.items():
            child = properties.get(name)
            if child is None:
                if not additional:
                    _instance_error(path, f"unexpected property: {name}")
                continue
            _validate_instance(item, child, path=f"{path}.{name}")

    elif schema_type == "array":
        if "minItems" in schema and len(value) < schema["minItems"]:
            _instance_error(path, f"expected at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            _instance_error(path, f"expected at most {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            seen = set()
            for index, item in enumerate(value):
                key = _canonical_json(item)
                if key in seen:
                    _instance_error(f"{path}[{index}]", "duplicate item")
                seen.add(key)
        for index, item in enumerate(value):
            _validate_instance(item, schema["items"], path=f"{path}[{index}]")

    elif schema_type == "string":
        if "minLength" in schema and len(value) < schema["minLength"]:
            _instance_error(path, f"expected length >= {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            _instance_error(path, f"expected length <= {schema['maxLength']}")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            _instance_error(path, f"does not match pattern {schema['pattern']!r}")

    elif schema_type in {"integer", "number"}:
        if "minimum" in schema and value < schema["minimum"]:
            _instance_error(path, f"expected value >= {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            _instance_error(path, f"expected value <= {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            _instance_error(path, f"expected value > {schema['exclusiveMinimum']}")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            _instance_error(path, f"expected value < {schema['exclusiveMaximum']}")


def validate_instance(value, schema):
    """Validate one JSON-compatible value against a validated Stage 4 schema."""

    _validate_json_value(value, label="instance")
    _validate_instance(value, schema)
    return value


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    name: str
    version: str
    description: str
    input_schema: Mapping
    output_schema: Mapping
    effect_class: str
    idempotency: str
    effort_hint: str = "normal"
    timeout_seconds: float = 10.0
    sandbox_scope: tuple[str, ...] = ()

    def __post_init__(self):
        _validate_non_empty_string(self.name, "ToolDescriptor name")
        if TOOL_NAME_PATTERN.fullmatch(self.name) is None:
            raise ValueError(
                "ToolDescriptor name must be lowercase dotted identifier segments"
            )
        _validate_non_empty_string(self.version, "ToolDescriptor version")
        if TOOL_VERSION_PATTERN.fullmatch(self.version) is None:
            raise ValueError("ToolDescriptor version contains unsupported characters")
        _validate_non_empty_string(self.description, "ToolDescriptor description")
        if self.effect_class not in EFFECT_CLASSES:
            raise ValueError(f"Unknown ToolDescriptor effect_class: {self.effect_class!r}")
        if self.idempotency not in IDEMPOTENCY_CLASSES:
            raise ValueError(f"Unknown ToolDescriptor idempotency: {self.idempotency!r}")
        if self.effect_class == "read_only" and self.idempotency != "repeat_safe":
            raise ValueError("read_only ToolDescriptor must use repeat_safe idempotency")
        if self.effort_hint not in EFFORT_HINTS:
            raise ValueError(f"Unknown ToolDescriptor effort_hint: {self.effort_hint!r}")
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("ToolDescriptor timeout_seconds must be a positive finite number")
        if not isinstance(self.sandbox_scope, tuple):
            raise ValueError("ToolDescriptor sandbox_scope must be a tuple")
        normalized_scope = []
        for item in self.sandbox_scope:
            _validate_non_empty_string(item, "ToolDescriptor sandbox_scope item")
            normalized_scope.append(item.strip())
        if len(normalized_scope) != len(set(normalized_scope)):
            raise ValueError("ToolDescriptor sandbox_scope must not contain duplicates")

        frozen_input = validate_schema(dict(self.input_schema), input_schema=True)
        frozen_output = validate_schema(dict(self.output_schema))
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "version", self.version.strip())
        object.__setattr__(self, "description", self.description.strip())
        object.__setattr__(self, "timeout_seconds", float(self.timeout_seconds))
        object.__setattr__(self, "sandbox_scope", tuple(normalized_scope))
        object.__setattr__(self, "input_schema", frozen_input)
        object.__setattr__(self, "output_schema", frozen_output)

    @property
    def key(self):
        return (self.name, self.version)

    def to_dict(self):
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "input_schema": _thaw_json(self.input_schema),
            "output_schema": _thaw_json(self.output_schema),
            "effect_class": self.effect_class,
            "idempotency": self.idempotency,
            "effort_hint": self.effort_hint,
            "timeout_seconds": self.timeout_seconds,
            "sandbox_scope": list(self.sandbox_scope),
        }

    def validate_input(self, arguments):
        try:
            validate_instance(arguments, self.input_schema)
        except (ValueError, SchemaValidationError) as error:
            raise ToolInputError(f"Invalid input for {self.name}@{self.version}: {error}") from error
        return arguments

    def validate_output(self, result):
        try:
            validate_instance(result, self.output_schema)
        except (ValueError, SchemaValidationError) as error:
            raise ToolOutputError(f"Invalid output for {self.name}@{self.version}: {error}") from error
        return result


class ToolRegistry:
    """System-owned registry of immutable ToolDescriptor capability contracts."""

    def __init__(self, descriptors=()):
        self._descriptors = {}
        self.register_many(descriptors)

    def register(self, descriptor):
        if not isinstance(descriptor, ToolDescriptor):
            raise TypeError("ToolRegistry.register() requires a ToolDescriptor")
        if descriptor.key in self._descriptors:
            raise ValueError(
                f"ToolDescriptor already registered: {descriptor.name}@{descriptor.version}"
            )
        self._descriptors[descriptor.key] = descriptor
        return descriptor

    def register_many(self, descriptors):
        descriptors = tuple(descriptors)
        for descriptor in descriptors:
            if not isinstance(descriptor, ToolDescriptor):
                raise TypeError("ToolRegistry.register_many() requires ToolDescriptor values")
        incoming_keys = [descriptor.key for descriptor in descriptors]
        if len(incoming_keys) != len(set(incoming_keys)):
            raise ValueError("ToolRegistry.register_many() contains duplicate tool versions")
        collision = next(
            (key for key in incoming_keys if key in self._descriptors),
            None,
        )
        if collision is not None:
            raise ValueError(f"ToolDescriptor already registered: {collision[0]}@{collision[1]}")
        for descriptor in descriptors:
            self._descriptors[descriptor.key] = descriptor
        return descriptors

    def get(self, name, version):
        _validate_non_empty_string(name, "ToolRegistry name")
        _validate_non_empty_string(version, "ToolRegistry version")
        descriptor = self._descriptors.get((name, version))
        if descriptor is None:
            raise ValueError(f"Unknown tool: {name}@{version}")
        return descriptor

    def contains(self, name, version):
        return (name, version) in self._descriptors

    def versions(self, name):
        _validate_non_empty_string(name, "ToolRegistry name")
        return tuple(sorted(version for tool_name, version in self._descriptors if tool_name == name))

    def list_descriptors(self):
        return tuple(
            self._descriptors[key]
            for key in sorted(self._descriptors)
        )

    def planner_snapshot(self):
        """Return detached JSON-compatible metadata; the Planner cannot mutate Registry state."""

        return tuple(descriptor.to_dict() for descriptor in self.list_descriptors())

    def validate_input(self, name, version, arguments):
        return self.get(name, version).validate_input(arguments)

    def validate_output(self, name, version, result):
        return self.get(name, version).validate_output(result)
