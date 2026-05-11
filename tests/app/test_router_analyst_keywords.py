from __future__ import annotations

import pytest

from app.agents.router import AgentModeRouter


@pytest.fixture
def router(tmp_path):
    # Telemetry is satisfied by default; constructor takes no required args.
    return AgentModeRouter()


@pytest.mark.parametrize("text", [
    "how many customers do we have?",
    "count of distinct regions",
    "what is the average amount?",
    "total sales by region",
    "show me the top 5 products",
    "number of rows in sales.csv",
    "compute median amount",
])
def test_analyst_routing(router, text):
    assert router.route(text).mode == "analyst"


@pytest.mark.parametrize("text", [
    "hi",
    "what can you do",
    "tell me about the workspace",
    "list files",
])
def test_interaction_routing(router, text):
    assert router.route(text).mode == "interaction"


@pytest.mark.parametrize("text", [
    "remember my preference for pandas",
    "save this as a note",
])
def test_knowledge_routing(router, text):
    assert router.route(text).mode == "knowledge"


def test_llm_classifier_fallback_disabled_by_default(router):
    assert router.route("does that make sense").mode == "interaction"


def test_llm_classifier_fallback_when_enabled():
    def fake(text: str) -> str:
        return "analyst"
    r = AgentModeRouter(enable_llm_classifier=True, llm_classifier=fake)
    assert r.route("does that make sense").mode == "analyst"


def test_llm_classifier_caches_results():
    calls: list[str] = []

    def fake(text: str) -> str:
        calls.append(text)
        return "analyst"

    r = AgentModeRouter(enable_llm_classifier=True, llm_classifier=fake)
    r.route("ambiguous query")
    r.route("ambiguous query")
    assert len(calls) == 1
