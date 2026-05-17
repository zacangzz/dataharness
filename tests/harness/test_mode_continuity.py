from harness.control import RunStateRecord
from harness.orchestrator import Orchestrator


def _profile_for(orch, state, text):
    # Pure routing helper the orchestrator will expose (Task 6 wires it in).
    return orch._select_profile(state, chat_id="c1", user_input=text)


async def test_router_picks_analyst_for_analysis_text(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    state = RunStateRecord(workspace_id="w1", run_id="r1", active_agent_mode="interaction")
    assert _profile_for(orch, state, "count rows in data/x.csv") == "analyst"


async def test_active_agent_mode_written_back_in_place(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    state = RunStateRecord(workspace_id="w1", run_id="r1", active_agent_mode="interaction")
    state_id = id(state)
    orch._select_profile(state, chat_id="c1", user_input="count rows in data/x.csv")
    # Same object mutated, not a copy:
    assert id(state) == state_id
    assert state.active_agent_mode == "analyst"


async def test_ambiguous_followup_keeps_prior_profile(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    state = RunStateRecord(workspace_id="w1", run_id="r1", active_agent_mode="analyst")
    # "the 2024 one" has no analysis keywords -> must stay analyst, not interaction.
    assert orch._select_profile(state, chat_id="c1", user_input="the 2024 one") == "analyst"


async def test_empty_prior_falls_through_to_routed(tmp_path):
    orch = Orchestrator(app_root=tmp_path)
    # Empty prior (cold start): the `and prior` guard must not preserve it;
    # ambiguous text routes to interaction.
    state = RunStateRecord(workspace_id="w1", run_id="r1", active_agent_mode="")
    assert orch._select_profile(state, chat_id="c1", user_input="the 2024 one") == "interaction"
    assert state.active_agent_mode == "interaction"
