import json

import pytest

from harness.analysis_flow import AnalysisFlow, AnalysisPhase
from harness.orchestrator import Orchestrator


def test_analysis_flow_model_defaults() -> None:
    flow = AnalysisFlow(
        chat_id="chat_1",
        run_id="run_1",
        workspace_id="w_0001",
        phase=AnalysisPhase.INSPECTING,
        original_request="hire rates?",
    )
    assert flow.phase is AnalysisPhase.INSPECTING
    assert flow.force_attempts == 0
    assert flow.plan_id is None
    assert flow.created_at is not None
    assert flow.updated_at is not None


def test_analysis_phase_members() -> None:
    assert {p.value for p in AnalysisPhase} == {
        "inspecting",
        "plan_pending",
        "approval_pending",
        "executing",
        "done",
        "failed",
    }


def test_set_phase_persists_and_replays(tmp_path) -> None:
    orch = Orchestrator(app_root=tmp_path)
    flow = AnalysisFlow(
        chat_id="chat_x",
        run_id="run_x",
        workspace_id="w_0001",
        phase=AnalysisPhase.INSPECTING,
        original_request="hire rates?",
    )
    orch._analysis_flows["chat_x"] = flow
    orch._append_analysis_flow("chat_x", {"action": "set", "flow_data": flow.model_dump(mode="json")})
    orch._set_phase("chat_x", AnalysisPhase.PLAN_PENDING, inspection_summary="2 csv files")

    log = tmp_path / "state" / "analysis_flows.jsonl"
    assert log.exists()

    # Fresh orchestrator replays the log.
    orch2 = Orchestrator(app_root=tmp_path)
    replayed = orch2._get_flow("chat_x")
    assert replayed is not None
    assert replayed.phase is AnalysisPhase.PLAN_PENDING
    assert replayed.inspection_summary == "2 csv files"


def test_replay_prunes_done_and_failed(tmp_path) -> None:
    orch = Orchestrator(app_root=tmp_path)
    for cid, phase in (("c_done", AnalysisPhase.DONE), ("c_failed", AnalysisPhase.FAILED)):
        flow = AnalysisFlow(
            chat_id=cid,
            run_id="r",
            workspace_id="w_0001",
            phase=AnalysisPhase.INSPECTING,
        )
        orch._analysis_flows[cid] = flow
        orch._append_analysis_flow(cid, {"action": "set", "flow_data": flow.model_dump(mode="json")})
        orch._set_phase(cid, phase)

    orch2 = Orchestrator(app_root=tmp_path)
    assert orch2._get_flow("c_done") is None
    assert orch2._get_flow("c_failed") is None


def test_drop_flow_removes_and_persists(tmp_path) -> None:
    orch = Orchestrator(app_root=tmp_path)
    flow = AnalysisFlow(
        chat_id="c_drop",
        run_id="r",
        workspace_id="w_0001",
        phase=AnalysisPhase.INSPECTING,
    )
    orch._analysis_flows["c_drop"] = flow
    orch._append_analysis_flow("c_drop", {"action": "set", "flow_data": flow.model_dump(mode="json")})
    orch._drop_flow("c_drop")
    assert orch._get_flow("c_drop") is None

    orch2 = Orchestrator(app_root=tmp_path)
    assert orch2._get_flow("c_drop") is None
