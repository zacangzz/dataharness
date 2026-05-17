import pytest

from harness.core.command_registry import (
    ArgSpec, CommandContext, HarnessCommandDescriptor, HelpResult,
    HarnessCommandRegistry,
)


def desc(name="doctor", arguments=None, available=True, disabled_reason=None):
    return HarnessCommandDescriptor(
        name=name, slash_alias=f"/{name}",
        short_description="run doctor",
        arguments=arguments or [],
        available=available,
        disabled_reason=disabled_reason,
        affected_resource="doctor",
        expected_event_types=["DoctorStarted", "DoctorReportReady", "CommandCompleted"],
        example_usage=f"/{name}",
    )


def test_register_and_list_descriptors():
    reg = HarnessCommandRegistry()

    async def handler(ctx, args):
        if False:
            yield
    reg.register(desc(), handler)
    listed = reg.list_descriptors(CommandContext(
        workspace_id="w", chat_id=None, run_id=None,
        has_pending_approval=False, has_pending_clarification=False,
    ))
    assert len(listed) == 1 and listed[0].name == "doctor"


def test_help_for_unknown_returns_not_found():
    reg = HarnessCommandRegistry()
    res = reg.help("nope")
    assert isinstance(res, HelpResult)
    assert res.not_found is True
    assert res.commands == []


def test_help_for_known_returns_single_descriptor():
    reg = HarnessCommandRegistry()

    async def handler(ctx, args):
        if False: yield
    reg.register(desc(), handler)
    res = reg.help("doctor")
    assert res.not_found is False
    assert [d.name for d in res.commands] == ["doctor"]


def test_arg_validation_required_missing():
    reg = HarnessCommandRegistry()
    arg = ArgSpec(name="path", type="path", required=True, description="x", example=None)

    async def handler(ctx, args):
        if False: yield
    reg.register(desc(name="inspect_artifact", arguments=[arg]), handler)
    with pytest.raises(ValueError):
        reg.validate("inspect_artifact", {})


def test_arg_validation_type_coercion():
    reg = HarnessCommandRegistry()

    async def handler(ctx, args):
        if False: yield
    reg.register(
        desc(name="rerun_step", arguments=[ArgSpec(name="step_id", type="step_id", required=True, description="x", example=None)]),
        handler,
    )
    parsed = reg.validate("rerun_step", {"step_id": "step_5"})
    assert parsed["step_id"] == "step_5"
