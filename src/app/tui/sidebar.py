from __future__ import annotations

from collections import deque


class SidebarState:
    def __init__(self) -> None:
        self.workspace_id = "unknown"
        self.run_state = "starting"
        self.active_mode = "interaction"
        self.runtime_status = "checking"
        self.chat_id: str | None = None
        self.files: list[str] = []
        self.chats: list[str] = []
        self.chat_summaries: list = []
        self.trace: deque[str] = deque(maxlen=20)
        self.commands: deque[str] = deque(maxlen=12)
        self.doctor: deque[str] = deque(maxlen=8)
        self.failure = "no failures"

    def update_status(
        self,
        *,
        workspace_id: str,
        run_state: str,
        active_mode: str,
        runtime_status: str,
        chat_id: str | None = None,
    ) -> None:
        self.workspace_id = workspace_id
        self.run_state = run_state
        self.active_mode = active_mode
        self.runtime_status = runtime_status
        self.chat_id = chat_id

    def set_files(self, files: list[str]) -> None:
        self.files = list(files)[:12]

    def set_chats(self, chats: list[str]) -> None:
        self.chats = list(chats)[:8]

    def set_chat_summaries(self, summaries: list) -> None:
        capped = list(summaries)[:8]
        self.chat_summaries = capped
        derived: list[str] = []
        for summary in capped:
            chat_id = getattr(summary, "chat_id", None)
            if chat_id is None:
                derived.append(str(summary))
                continue
            title = getattr(summary, "title", None) or chat_id
            count = getattr(summary, "message_count", 0)
            derived.append(f"{title} · {count} msgs")
        self.chats = derived

    def update_trace(self, lines: list[str]) -> None:
        self.trace.clear()
        self.trace.extend(lines)

    def command_started(self, command: str) -> None:
        self.commands.append(f"/{command}: running")

    def command_progress(self, command: str, phase: str, phase_index: int, phase_total: int) -> None:
        self.commands.append(f"/{command}: {phase} {phase_index}/{phase_total}")

    def command_completed(self, text: str) -> None:
        self.commands.append(text)

    def append_doctor(self, text: str) -> None:
        self.doctor.append(text)

    def set_failure(self, summary: str, error_code: str) -> None:
        self.failure = f"{error_code}: {summary}"

    def text_buffer(self) -> str:
        files = "\n".join(self.files) or "no files"
        chats = "\n".join(self.chats) or (self.chat_id or "no active chat")
        trace = "\n".join(self.trace) or "no trace yet"
        commands = "\n".join(self.commands) or "no commands yet"
        doctor = "\n".join(self.doctor) or "no doctor findings"
        return (
            f"WORKSPACE\n{self.workspace_id}\nstate: {self.run_state}\n"
            f"mode: {self.active_mode}\nruntime: {self.runtime_status}\n\n"
            f"CHAT\n{chats}\n\n"
            f"FILES\n{files}\n\n"
            f"TRACE\n{trace}\n\n"
            f"COMMANDS\n{commands}\n\n"
            f"DOCTOR\n{doctor}\n\n"
            f"FAILURES\n{self.failure}"
        )
