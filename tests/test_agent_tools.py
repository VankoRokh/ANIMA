from dataclasses import FrozenInstanceError

import pytest

from anima.agent.tools import (
    SchemaValidationError,
    ToolDescriptor,
    ToolInputError,
    ToolOutputError,
    ToolRegistry,
    validate_schema,
)


def _input_schema():
    return {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1},
        },
        "required": ["path"],
        "additionalProperties": False,
    }


def _output_schema():
    return {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
        },
        "required": ["content"],
        "additionalProperties": False,
    }


def _descriptor(**overrides):
    values = {
        "name": "fs.read",
        "version": "1",
        "description": "Read one UTF-8 file from the sandbox.",
        "input_schema": _input_schema(),
        "output_schema": _output_schema(),
        "effect_class": "read_only",
        "idempotency": "repeat_safe",
        "effort_hint": "cheap",
        "timeout_seconds": 2,
        "sandbox_scope": ("workspace",),
    }
    values.update(overrides)
    return ToolDescriptor(**values)


def test_tool_descriptor_is_immutable_and_detached_from_source_schema():
    input_schema = _input_schema()
    descriptor = _descriptor(input_schema=input_schema)

    input_schema["properties"]["path"]["minLength"] = 99

    assert descriptor.input_schema["properties"]["path"]["minLength"] == 1
    assert descriptor.timeout_seconds == 2.0
    assert descriptor.key == ("fs.read", "1")

    with pytest.raises(TypeError):
        descriptor.input_schema["properties"]["path"]["minLength"] = 3

    with pytest.raises(FrozenInstanceError):
        descriptor.name = "fs.other"


def test_tool_descriptor_to_dict_returns_detached_json_metadata():
    descriptor = _descriptor()

    exported = descriptor.to_dict()
    exported["input_schema"]["properties"]["path"]["minLength"] = 50
    exported["sandbox_scope"].append("other")

    assert descriptor.input_schema["properties"]["path"]["minLength"] == 1
    assert descriptor.sandbox_scope == ("workspace",)


def test_tool_descriptor_validates_name_version_and_metadata():
    with pytest.raises(ValueError, match="lowercase dotted identifier"):
        _descriptor(name="FS Read")

    with pytest.raises(ValueError, match="version contains unsupported"):
        _descriptor(version="1 beta")

    with pytest.raises(ValueError, match="effect_class"):
        _descriptor(effect_class="maybe")

    with pytest.raises(ValueError, match="idempotency"):
        _descriptor(idempotency="magic")

    with pytest.raises(ValueError, match="effort_hint"):
        _descriptor(effort_hint="huge")

    with pytest.raises(ValueError, match="positive finite"):
        _descriptor(timeout_seconds=0)

    with pytest.raises(ValueError, match="sandbox_scope must be a tuple"):
        _descriptor(sandbox_scope=["workspace"])

    with pytest.raises(ValueError, match="must not contain duplicates"):
        _descriptor(sandbox_scope=("workspace", "workspace"))


def test_read_only_tool_must_be_repeat_safe():
    with pytest.raises(ValueError, match="read_only.*repeat_safe"):
        _descriptor(idempotency="keyed")


def test_write_and_irreversible_metadata_can_describe_future_tools():
    reversible = _descriptor(
        name="fs.write",
        effect_class="reversible_write",
        idempotency="keyed",
    )
    irreversible = _descriptor(
        name="external.submit",
        effect_class="irreversible",
        idempotency="none",
        sandbox_scope=(),
    )

    assert reversible.effect_class == "reversible_write"
    assert reversible.idempotency == "keyed"
    assert irreversible.effect_class == "irreversible"
    assert irreversible.idempotency == "none"


def test_input_schema_requires_strict_object_root():
    with pytest.raises(SchemaValidationError, match="root type must be 'object'"):
        _descriptor(input_schema={"type": "string"})

    with pytest.raises(SchemaValidationError, match="additionalProperties=false"):
        _descriptor(
            input_schema={
                "type": "object",
                "properties": {},
            }
        )


def test_schema_rejects_unknown_keywords_instead_of_silently_ignoring_them():
    schema = _input_schema()
    schema["properties"]["path"]["format"] = "path"

    with pytest.raises(SchemaValidationError, match="Unsupported schema keyword.*format"):
        _descriptor(input_schema=schema)


def test_schema_rejects_invalid_required_and_array_contracts():
    schema = _input_schema()
    schema["required"] = ["missing"]
    with pytest.raises(SchemaValidationError, match="required references unknown"):
        _descriptor(input_schema=schema)

    with pytest.raises(SchemaValidationError, match="items is required"):
        validate_schema({"type": "array"})

    with pytest.raises(SchemaValidationError, match="minItems cannot exceed"):
        validate_schema(
            {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 3,
                "maxItems": 2,
            }
        )


def test_schema_rejects_bad_pattern_and_non_json_values():
    with pytest.raises(SchemaValidationError, match="valid regular expression"):
        validate_schema({"type": "string", "pattern": "["})

    with pytest.raises(SchemaValidationError, match="JSON-compatible"):
        validate_schema({"type": "string", "const": object()})


def test_descriptor_validates_required_and_rejects_additional_input_properties():
    descriptor = _descriptor()

    assert descriptor.validate_input({"path": "data.txt"}) == {"path": "data.txt"}

    with pytest.raises(ToolInputError, match="missing required properties: path"):
        descriptor.validate_input({})

    with pytest.raises(ToolInputError, match="unexpected property: extra"):
        descriptor.validate_input({"path": "data.txt", "extra": True})


def test_descriptor_validates_nested_input_types_and_constraints():
    descriptor = _descriptor(
        name="math.sum",
        input_schema={
            "type": "object",
            "properties": {
                "values": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0},
                    "minItems": 1,
                    "maxItems": 3,
                    "uniqueItems": True,
                }
            },
            "required": ["values"],
            "additionalProperties": False,
        },
        output_schema={"type": "integer"},
    )

    descriptor.validate_input({"values": [1, 2, 3]})

    with pytest.raises(ToolInputError, match="expected integer, got bool"):
        descriptor.validate_input({"values": [True]})

    with pytest.raises(ToolInputError, match="expected value >= 0"):
        descriptor.validate_input({"values": [-1]})

    with pytest.raises(ToolInputError, match="duplicate item"):
        descriptor.validate_input({"values": [1, 1]})

    with pytest.raises(ToolInputError, match="expected at most 3 items"):
        descriptor.validate_input({"values": [1, 2, 3, 4]})


def test_descriptor_validates_output_separately_from_execution_success():
    descriptor = _descriptor()

    assert descriptor.validate_output({"content": "hello"}) == {"content": "hello"}

    with pytest.raises(ToolOutputError, match="missing required properties: content"):
        descriptor.validate_output({})

    with pytest.raises(ToolOutputError, match="unexpected property: ok"):
        descriptor.validate_output({"content": "hello", "ok": True})


def test_schema_supports_enum_const_string_and_numeric_bounds():
    descriptor = _descriptor(
        name="demo.contract",
        input_schema={
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["fast", "deep"]},
                "tag": {"type": "string", "const": "stable"},
                "ratio": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "maximum": 1,
                },
            },
            "required": ["mode", "tag", "ratio"],
            "additionalProperties": False,
        },
    )

    descriptor.validate_input({"mode": "fast", "tag": "stable", "ratio": 0.5})

    with pytest.raises(ToolInputError, match="not in enum"):
        descriptor.validate_input({"mode": "other", "tag": "stable", "ratio": 0.5})

    with pytest.raises(ToolInputError, match="does not match const"):
        descriptor.validate_input({"mode": "fast", "tag": "other", "ratio": 0.5})

    with pytest.raises(ToolInputError, match="expected value > 0"):
        descriptor.validate_input({"mode": "fast", "tag": "stable", "ratio": 0})


def test_registry_registers_exact_versions_and_lists_deterministically():
    read_v1 = _descriptor()
    read_v2 = _descriptor(version="2")
    write_v1 = _descriptor(
        name="fs.write",
        effect_class="reversible_write",
        idempotency="keyed",
    )
    registry = ToolRegistry((write_v1, read_v2, read_v1))

    assert registry.get("fs.read", "1") is read_v1
    assert registry.get("fs.read", "2") is read_v2
    assert registry.versions("fs.read") == ("1", "2")
    assert [item.key for item in registry.list_descriptors()] == [
        ("fs.read", "1"),
        ("fs.read", "2"),
        ("fs.write", "1"),
    ]


def test_registry_rejects_duplicate_exact_version_without_overwrite():
    original = _descriptor()
    registry = ToolRegistry((original,))
    duplicate = _descriptor(description="Different contract, same identity.")

    with pytest.raises(ValueError, match="already registered: fs.read@1"):
        registry.register(duplicate)

    assert registry.get("fs.read", "1") is original


def test_register_many_is_atomic_on_duplicates_or_collisions():
    registry = ToolRegistry((_descriptor(),))
    write = _descriptor(
        name="fs.write",
        effect_class="reversible_write",
        idempotency="keyed",
    )
    duplicate_read = _descriptor(description="collision")

    with pytest.raises(ValueError, match="already registered"):
        registry.register_many((write, duplicate_read))

    assert not registry.contains("fs.write", "1")

    with pytest.raises(ValueError, match="duplicate tool versions"):
        ToolRegistry((write, write))


def test_registry_unknown_tool_and_version_are_explicit_errors():
    registry = ToolRegistry((_descriptor(),))

    with pytest.raises(ValueError, match="Unknown tool: fs.missing@1"):
        registry.get("fs.missing", "1")

    with pytest.raises(ValueError, match="Unknown tool: fs.read@99"):
        registry.get("fs.read", "99")


def test_registry_delegates_input_and_output_validation():
    registry = ToolRegistry((_descriptor(),))

    registry.validate_input("fs.read", "1", {"path": "a.txt"})
    registry.validate_output("fs.read", "1", {"content": "A"})

    with pytest.raises(ToolInputError):
        registry.validate_input("fs.read", "1", {})

    with pytest.raises(ToolOutputError):
        registry.validate_output("fs.read", "1", {})


def test_planner_snapshot_is_detached_from_registry_authority():
    registry = ToolRegistry((_descriptor(),))

    snapshot = registry.planner_snapshot()
    snapshot[0]["input_schema"]["properties"]["path"]["minLength"] = 100
    snapshot[0]["sandbox_scope"].append("outside")

    descriptor = registry.get("fs.read", "1")
    assert descriptor.input_schema["properties"]["path"]["minLength"] == 1
    assert descriptor.sandbox_scope == ("workspace",)


def test_registry_requires_descriptor_instances():
    registry = ToolRegistry()

    with pytest.raises(TypeError, match="requires a ToolDescriptor"):
        registry.register({"name": "fs.read"})

    with pytest.raises(TypeError, match="requires ToolDescriptor values"):
        registry.register_many((_descriptor(), {"name": "fs.write"}))
