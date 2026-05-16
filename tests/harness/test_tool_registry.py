import pytest

from harness.tools.registry import HarnessToolRegistry, ToolArgSpec, ToolDescriptor
from harness.orchestrator import Orchestrator


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


def test_orchestrator_tool_registry_excludes_command_only_names(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    names = {tool.name for tool in orch.tool_registry.list_tools()}

    assert {
        "analysis_plan",
        "analysis_request_execution",
        "knowledge_recall",
        "knowledge_propose_update",
        "file_read",
    } <= names
    assert "plan_analysis" not in names
    assert "request_execution" not in names
    assert "workspace_status" not in names
    assert "workspace_inventory" not in names
