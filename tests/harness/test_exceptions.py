import pytest

from harness.exceptions import (
    ChatNotFound, ChatWorkspaceMismatch, ChatActiveDeletionBlocked,
    WorkspaceNotFound, RunAlreadyActive, WorkspaceSwitchBlocked,
)


def test_chat_not_found_carries_id():
    with pytest.raises(ChatNotFound) as ei:
        raise ChatNotFound(chat_id="chat_x")
    assert ei.value.chat_id == "chat_x"


def test_workspace_mismatch_holds_actual_and_expected():
    e = ChatWorkspaceMismatch(chat_id="c", expected_workspace="w1", actual_workspace="w2")
    assert e.expected_workspace == "w1"
    assert e.actual_workspace == "w2"


def test_run_already_active_holds_run_id():
    e = RunAlreadyActive(run_id="run_1")
    assert e.run_id == "run_1"


def test_workspace_switch_blocked_holds_active_run():
    e = WorkspaceSwitchBlocked(active_run_id="run_z")
    assert e.active_run_id == "run_z"
