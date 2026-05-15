import pytest

from harness.tools.registry import HarnessToolRegistry, ToolArgSpec, ToolDescriptor


def test_tool_registry_lists_model_callable_tools_only():
    registry = HarnessToolRegistry()
    registry.register(
        ToolDescriptor(
            name="file_read",
            family="core",
            short_description="Read workspace file information",
            arguments=[
                ToolArgSpec(
                    name="operation",
                    type="str",
                    required=True,
                    description="list|inspect|content",
                    allowed_values=["list", "inspect", "content"],
                ),
            ],
        ),
        lambda _ctx, _args: None,
    )

    names = [tool.name for tool in registry.list_tools()]
    assert names == ["file_read"]


def test_tool_registry_rejects_unknown_tool():
    registry = HarnessToolRegistry()
    with pytest.raises(ValueError, match="unknown tool"):
        registry.validate("doctor", {})


def test_tool_registry_rejects_disallowed_value():
    registry = HarnessToolRegistry()
    registry.register(
        ToolDescriptor(
            name="file_read",
            family="core",
            short_description="Read workspace file information",
            arguments=[
                ToolArgSpec(
                    name="operation",
                    type="str",
                    required=True,
                    description="list|inspect|content",
                    allowed_values=["list", "inspect", "content"],
                ),
            ],
        ),
        lambda _ctx, _args: None,
    )

    with pytest.raises(ValueError, match="invalid value"):
        registry.validate("file_read", {"operation": "delete"})


def test_tool_registry_rejects_regex_mismatch():
    registry = HarnessToolRegistry()
    registry.register(
        ToolDescriptor(
            name="file_read",
            family="core",
            short_description="Read workspace file information",
            arguments=[
                ToolArgSpec(
                    name="path",
                    type="path",
                    required=True,
                    description="workspace-relative path",
                    regex=r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$)).+",
                ),
            ],
        ),
        lambda _ctx, _args: None,
    )

    with pytest.raises(ValueError, match="does not match"):
        registry.validate("file_read", {"path": "../secret.txt"})
