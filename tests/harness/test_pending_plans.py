import json
import pytest
from pathlib import Path


@pytest.mark.asyncio
async def test_pending_plans_survive_across_turns(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    plans_file = state_dir / "pending_plans.jsonl"

    plan_data = {"id": "plan_1", "goal": "test", "steps": []}
    with open(plans_file, "a") as f:
        f.write(json.dumps({"action": "created", "plan_id": "plan_1", "plan_data": plan_data, "ts": 1.0}) + "\n")

    pending = {}
    with open(plans_file) as f:
        for line in f:
            entry = json.loads(line.strip())
            pid = entry["plan_id"]
            if entry.get("action") == "created":
                pending[pid] = entry.get("plan_data")
            elif entry.get("action") == "resolved":
                pending.pop(pid, None)

    assert "plan_1" in pending

    with open(plans_file, "a") as f:
        f.write(json.dumps({"action": "resolved", "plan_id": "plan_1", "resolution": "approved", "ts": 2.0}) + "\n")

    pending = {}
    with open(plans_file) as f:
        for line in f:
            entry = json.loads(line.strip())
            pid = entry["plan_id"]
            if entry.get("action") == "created":
                pending[pid] = entry.get("plan_data")
            elif entry.get("action") == "resolved":
                pending.pop(pid, None)

    assert "plan_1" not in pending

