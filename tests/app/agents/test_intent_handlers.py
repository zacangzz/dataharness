import pytest

from app.agents.intent_handlers import handle_knowledge_intent


class FakeKnowledgeManager:
    def __init__(self) -> None:
        self.proposals: list[dict] = []

    def propose_update(
        self,
        *,
        memory_target: str,
        source_refs: list[str],
        proposed_content: str,
        conflicts: list[str] | None = None,
    ):
        proposal = {
            "memory_target": memory_target,
            "source_refs": source_refs,
            "proposed_content": proposed_content,
            "conflicts": conflicts or [],
            "status": "pending",
        }
        self.proposals.append(proposal)
        return proposal


def test_store_workspace_knowledge_intent_creates_pending_proposal_to_notes() -> None:
    manager = FakeKnowledgeManager()
    handle_knowledge_intent(
        manager,
        tool_call={
            "name": "store_workspace_knowledge",
            "arguments": {
                "title": "attrition",
                "content": "voluntary leavers / avg headcount",
                "source_refs": ["turn:r_1"],
            },
        },
    )
    assert manager.proposals[0]["memory_target"].startswith("memory/notes/")
    assert manager.proposals[0]["status"] == "pending"


def test_update_preferences_intent_targets_preferences_file() -> None:
    manager = FakeKnowledgeManager()
    handle_knowledge_intent(
        manager,
        tool_call={
            "name": "update_preferences",
            "arguments": {"key": "style", "value": "concise", "source_refs": ["turn:r_1"]},
        },
    )
    assert manager.proposals[0]["memory_target"] == "memory/preferences.json"


def test_record_gap_intent_targets_memory_notes_gaps() -> None:
    manager = FakeKnowledgeManager()
    handle_knowledge_intent(
        manager,
        tool_call={
            "name": "record_gap",
            "arguments": {"description": "missing department mapping", "source_refs": ["turn:r_1"]},
        },
    )
    assert manager.proposals[0]["memory_target"].startswith("memory/notes/gaps/")


def test_save_function_candidate_intent_targets_memory_functions() -> None:
    manager = FakeKnowledgeManager()
    handle_knowledge_intent(
        manager,
        tool_call={
            "name": "save_function_candidate",
            "arguments": {
                "name": "attrition_rate",
                "code": "def attrition_rate(...): ...",
                "source_refs": ["turn:r_1"],
            },
        },
    )
    assert manager.proposals[0]["memory_target"].startswith("memory/functions/")
    assert "def attrition_rate" in manager.proposals[0]["proposed_content"]


def test_unknown_intent_raises_so_caller_can_record_failure() -> None:
    with pytest.raises(ValueError, match="unknown knowledge intent"):
        handle_knowledge_intent(FakeKnowledgeManager(), tool_call={"name": "bogus", "arguments": {}})
