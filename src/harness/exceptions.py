from __future__ import annotations


class HarnessError(Exception):
    pass


class ChatNotFound(HarnessError):
    def __init__(self, *, chat_id: str) -> None:
        super().__init__(f"chat not found: {chat_id}")
        self.chat_id = chat_id


class ChatWorkspaceMismatch(HarnessError):
    def __init__(self, *, chat_id: str, expected_workspace: str, actual_workspace: str) -> None:
        super().__init__(
            f"chat {chat_id} belongs to workspace {actual_workspace}, expected {expected_workspace}"
        )
        self.chat_id = chat_id
        self.expected_workspace = expected_workspace
        self.actual_workspace = actual_workspace


class ChatActiveDeletionBlocked(HarnessError):
    def __init__(self, *, chat_id: str) -> None:
        super().__init__(f"cannot delete active chat: {chat_id}")
        self.chat_id = chat_id


class WorkspaceNotFound(HarnessError):
    def __init__(self, *, workspace_id: str) -> None:
        super().__init__(f"workspace not found: {workspace_id}")
        self.workspace_id = workspace_id


class RunAlreadyActive(HarnessError):
    def __init__(self, *, run_id: str) -> None:
        super().__init__(f"run already active: {run_id}")
        self.run_id = run_id


class WorkspaceSwitchBlocked(HarnessError):
    def __init__(self, *, active_run_id: str) -> None:
        super().__init__(f"workspace switch blocked while run {active_run_id} active")
        self.active_run_id = active_run_id
