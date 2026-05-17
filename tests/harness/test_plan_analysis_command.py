from __future__ import annotations

import pytest

from harness.core.command_registry import CommandContext
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
                "code": "import pandas as pd\nfrom pathlib import Path\nn = len(pd.read_csv('data/customers.csv'))\nPath('result.txt').write_text(str(n))\nprint(n)",
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
async def test_plan_analysis_accepts_code_lines_and_stashes_joined_code(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    handler = orch.registry.get_handler("plan_analysis")
    args = {
        "goal": "count customers",
        "steps": [
            {
                "purpose": "Count rows in customers.csv.",
                "code_lines": [
                    "import pandas as pd",
                    "from pathlib import Path",
                    "n = len(pd.read_csv('data/customers.csv'))",
                    "Path('result.txt').write_text(str(n))",
                    "print(n)",
                ],
                "declared_inputs": ["data/customers.csv"],
                "expected_outputs": ["result.txt"],
            }
        ],
    }

    events = [ev async for ev in handler(_ctx(), args)]

    assert [e for e in events if isinstance(e, ApprovalRequired)]
    key = (_ctx().run_id or "", "step_1")
    assert orch._pending_contracts[key].code == (
        "import pandas as pd\n"
        "from pathlib import Path\n"
        "n = len(pd.read_csv('data/customers.csv'))\n"
        "Path('result.txt').write_text(str(n))\n"
        "print(n)"
    )


@pytest.mark.asyncio
async def test_plan_analysis_accepts_matching_code_and_code_lines(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    handler = orch.registry.get_handler("plan_analysis")
    code = "from pathlib import Path\nPath('result.txt').write_text('ok')"
    args = {
        "goal": "write result",
        "steps": [
            {
                "purpose": "Write result.",
                "code": code,
                "code_lines": code.splitlines(),
                "expected_outputs": ["result.txt"],
            }
        ],
    }

    events = [ev async for ev in handler(_ctx(), args)]

    assert [e for e in events if isinstance(e, ApprovalRequired)]


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
async def test_plan_analysis_rejects_empty_code_lines(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    handler = orch.registry.get_handler("plan_analysis")
    args = {"goal": "x", "steps": [{"purpose": "p", "code_lines": []}]}
    events = [ev async for ev in handler(_ctx(), args)]
    completed = [e for e in events if isinstance(e, CommandCompleted)]
    assert completed and "code_lines" in completed[0].result["error"]


@pytest.mark.asyncio
async def test_plan_analysis_rejects_non_string_code_lines(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    handler = orch.registry.get_handler("plan_analysis")
    args = {
        "goal": "x",
        "steps": [{"purpose": "p", "code_lines": ["print('ok')", 3]}],
    }
    events = [ev async for ev in handler(_ctx(), args)]
    completed = [e for e in events if isinstance(e, CommandCompleted)]
    assert completed and "code_lines" in completed[0].result["error"]


@pytest.mark.asyncio
async def test_plan_analysis_rejects_conflicting_code_and_code_lines(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    handler = orch.registry.get_handler("plan_analysis")
    args = {
        "goal": "x",
        "steps": [
            {
                "purpose": "p",
                "code": "from pathlib import Path\nPath('result.txt').write_text('old')",
                "code_lines": [
                    "from pathlib import Path",
                    "Path('result.txt').write_text('new')",
                ],
                "expected_outputs": ["result.txt"],
            }
        ],
    }
    events = [ev async for ev in handler(_ctx(), args)]
    completed = [e for e in events if isinstance(e, CommandCompleted)]
    assert completed and "conflicting 'code' and 'code_lines'" in completed[0].result["error"]


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


@pytest.mark.asyncio
async def test_plan_analysis_accepts_prompt_allowed_time_import(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    handler = orch.registry.get_handler("plan_analysis")
    args = {
        "goal": "write timestamp",
        "steps": [
            {
                "purpose": "Write a timestamp summary.",
                "code_lines": [
                    "import time",
                    "from pathlib import Path",
                    "Path('result.txt').write_text(str(time.time()))",
                ],
                "expected_outputs": ["result.txt"],
            }
        ],
    }

    events = [ev async for ev in handler(_ctx(), args)]

    assert [e for e in events if isinstance(e, ApprovalRequired)]
    key = (_ctx().run_id or "", "step_1")
    assert "time" in orch._pending_contracts[key].permission_envelope["allowed_packages"]


@pytest.mark.asyncio
async def test_plan_analysis_rejects_code_missing_expected_output(tmp_path):
    """Plan must be rejected before approval if code doesn't reference its expected_outputs."""
    orch = Orchestrator(app_root=tmp_path)
    handler = orch.registry.get_handler("plan_analysis")
    args = {
        "goal": "total sales",
        "steps": [
            {
                "purpose": "Inspect columns.",
                "code": "import pandas as pd\ndf = pd.read_csv('data/sales.csv')\nprint(df.columns.tolist())",
                "declared_inputs": ["data/sales.csv"],
                "expected_outputs": ["result.txt"],
            }
        ],
    }
    events = [ev async for ev in handler(_ctx(), args)]
    assert not [e for e in events if isinstance(e, ApprovalRequired)]
    completed = [e for e in events if isinstance(e, CommandCompleted)]
    assert completed
    assert "result.txt" in completed[0].result["error"]
    assert "does not reference expected output" in completed[0].result["error"]
