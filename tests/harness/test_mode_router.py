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


def test_route_is_deterministic():
    r = ModeRouter()
    decision = r.route("count the rows in data/sales.csv")
    assert decision.mode == "analyst"
    assert decision == r.route("count the rows in data/sales.csv")


def test_request_mode_alias_removed():
    assert not hasattr(ModeRouter, "request_mode")
