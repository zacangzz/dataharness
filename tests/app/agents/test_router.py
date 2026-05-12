from app.agents.router import AgentModeRequest, AgentModeRouter


def test_router_returns_request_object_not_authoritative_decision() -> None:
    router = AgentModeRouter()
    request = router.request_mode("compare attrition by department")
    assert request.mode == "analyst"
    assert request.reason == "analysis_intent"
    assert isinstance(request, AgentModeRequest)
    assert type(request).__name__ == "AgentModeRequest"


def test_router_selects_analyst_for_analysis_questions() -> None:
    router = AgentModeRouter()
    decision = router.route("compare attrition by department")
    assert decision.mode == "analyst"
    assert decision.reason == "analysis_intent"


def test_router_selects_knowledge_for_teaching_and_memory() -> None:
    router = AgentModeRouter()
    decision = router.route("remember that attrition means voluntary exits")
    assert decision.mode == "knowledge"
    assert decision.reason == "knowledge_capture_intent"


def test_router_defaults_to_interaction() -> None:
    router = AgentModeRouter()
    decision = router.route("hello")
    assert decision.mode == "interaction"
    assert decision.reason == "front_door_default"
