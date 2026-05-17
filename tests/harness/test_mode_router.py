from harness.services.mode_router import ModeRouter


def test_router_routes_analysis_intent():
    r = ModeRouter()
    assert r.route("count the rows in data/sales.csv").mode == "analyst"


def test_router_routes_knowledge_intent():
    r = ModeRouter()
    assert r.route("remember that revenue means net of refunds").mode == "knowledge"


def test_router_defaults_to_interaction():
    r = ModeRouter()
    assert r.route("hello there").mode == "interaction"


def test_request_mode_delegates_to_route():
    r = ModeRouter()
    decision = r.request_mode("count the rows in data/sales.csv")
    assert decision.mode == "analyst"
    assert decision == r.route("count the rows in data/sales.csv")
