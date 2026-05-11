from __future__ import annotations

import pytest

from harness.command_registry import CommandContext
from harness.events import ApprovalRequired, CommandCompleted, PlanReady
from harness.orchestrator import Orchestrator


def _ctx(run_id: str = "run_test") -> CommandContext:
    return CommandContext(
        workspace_id="w_test", chat_id="c1", run_id=run_id,
        has_pending_approval=False, has_pending_clarification=False,
    )


@pytest.mark.asyncio
async def test_plan_analysis_emits_plan_and_approval(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    handler = orch.registry.get_handler("plan_analysis")
    args = {
        "goal": "count customers",
        "steps": [
            {
                "purpose": "Count rows in customers.csv.",
                "code": "import pandas as pd; print(len(pd.read_csv('data/customers.csv')))",
                "declared_inputs": ["data/customers.csv"],
                "expected_outputs": ["result.txt"],
            }
        ],
    }
    events = [ev async for ev in handler(_ctx(), args)]
    plan_evs = [e for e in events if isinstance(e, PlanReady)]
    appr_evs = [e for e in events if isinstance(e, ApprovalRequired)]
    completed = [e for e in events if isinstance(e, CommandCompleted)]
    assert plan_evs and appr_evs and completed
    assert plan_evs[0].plan["goal"] == "count customers"
    assert appr_evs[0].step_id == "step_1"
    # Contract must be stashed for resume_approved_step
    key = (_ctx().run_id or "", "step_1")
    assert key in orch._pending_contracts
    assert orch._pending_contracts[key].code.startswith("import pandas")


@pytest.mark.asyncio
async def test_plan_analysis_rejects_empty_steps(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    handler = orch.registry.get_handler("plan_analysis")
    events = [ev async for ev in handler(_ctx(), {"goal": "x", "steps": []})]
    completed = [e for e in events if isinstance(e, CommandCompleted)]
    assert completed and "error" in completed[0].result


@pytest.mark.asyncio
async def test_plan_analysis_rejects_missing_code(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    handler = orch.registry.get_handler("plan_analysis")
    args = {"goal": "x", "steps": [{"purpose": "p", "code": ""}]}
    events = [ev async for ev in handler(_ctx(), args)]
    completed = [e for e in events if isinstance(e, CommandCompleted)]
    assert completed and "error" in completed[0].result


@pytest.mark.asyncio
async def test_plan_analysis_rejects_absolute_input_path(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    handler = orch.registry.get_handler("plan_analysis")
    args = {
        "goal": "x",
        "steps": [{"purpose": "p", "code": "print(1)", "declared_inputs": ["/etc/passwd"]}],
    }
    events = [ev async for ev in handler(_ctx(), args)]
    completed = [e for e in events if isinstance(e, CommandCompleted)]
    assert completed and "error" in completed[0].result


@pytest.mark.asyncio
async def test_plan_analysis_rejects_disallowed_imports_before_approval(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    handler = orch.registry.get_handler("plan_analysis")
    args = {
        "goal": "total sales",
        "steps": [
            {
                "purpose": "Compute total sales.",
                "code": "import os\nprint(os.getcwd())",
                "declared_inputs": ["data/sales.csv"],
                "expected_outputs": ["result.txt"],
            }
        ],
    }
    events = [ev async for ev in handler(_ctx(), args)]
    assert not [e for e in events if isinstance(e, ApprovalRequired)]
    completed = [e for e in events if isinstance(e, CommandCompleted)]
    assert completed
    assert completed[0].result["error"] == "step #1: package not allowed: os"


def test_plan_analysis_in_runtime_callable_whitelist(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    names = {d.name for d in orch.registry.list_runtime_callable()}
    assert "plan_analysis" in names
    assert "request_execution" in names
