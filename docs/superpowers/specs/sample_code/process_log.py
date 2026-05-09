"""Streamed per-agent process log widget for the Textual UI.

Renders one collapsible block per agent. Each block shows activity
rows (tool calls, reasoning summaries, status updates) and uses
+/- title state to indicate collapsed/expanded.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from textual.widgets import Collapsible, Static


@dataclass
class _ToolRow:
    name: str
    tool_call_id: str
    args: str = ""
    output_lines: list[str] = field(default_factory=list)

    def render_lines(self) -> list[str]:
        label = self.name or "tool"
        call = f"-> {label}({self.args})" if self.args else f"-> {label}(...)"
        return [call, *[f"<- {output}" for output in self.output_lines]]


class AgentProcessBlock(Collapsible):
    """Collapsible block for a single agent's activity."""

    DEFAULT_CSS = """
    AgentProcessBlock {
        margin: 0 1;
        padding: 0 1;
    }
    """

    def __init__(self, agent: str) -> None:
        self.agent = agent
        self._rows: list[str | _ToolRow] = []
        self._tool_rows: dict[str, _ToolRow] = {}
        self._text_content = ""
        self._content_widget = Static("", markup=False)
        super().__init__(self._content_widget, title=f"+ {agent}", collapsed=True)

    def on_mount(self) -> None:
        self.expand(False)

    @property
    def renderable_text(self) -> str:
        """Return all text content of the block."""
        return self._text_content

    def append_row(self, agent: str, text: str) -> None:
        """Append a row of text to the block."""
        self._rows.append(text)
        self._refresh()

    def _ensure_tool_row(self, tool_call_id: str, name: str = "") -> _ToolRow:
        row = self._tool_rows.get(tool_call_id)
        if row is None:
            row = _ToolRow(name=name, tool_call_id=tool_call_id)
            self._tool_rows[tool_call_id] = row
            self._rows.append(row)
        elif name:
            row.name = name
        return row

    def start_tool_call(self, tool_call_id: str, name: str) -> None:
        self._ensure_tool_row(tool_call_id, name=name)
        self._refresh()

    def complete_tool_call(self, tool_call_id: str, name: str, args: str) -> None:
        row = self._ensure_tool_row(tool_call_id, name=name)
        row.args = args
        self._refresh()

    def append_tool_output(self, tool_call_id: str, output: str) -> None:
        row = self._ensure_tool_row(tool_call_id)
        row.output_lines.append(output)
        self._refresh()

    def _refresh(self) -> None:
        lines: list[str] = []
        for row in self._rows:
            if isinstance(row, _ToolRow):
                lines.extend(row.render_lines())
            else:
                lines.append(row)
        self._text_content = "\n".join(lines)
        self._content_widget.update(self._text_content)

    def expand(self, expanded: bool = True) -> None:
        """Set expanded/collapsed state."""
        self.collapsed = not expanded
        self.title = f"{'-' if expanded else '+'} {self.agent}"


class ProcessLog(Static):
    """Container for per-agent collapsible process blocks."""

    DEFAULT_CSS = """
    ProcessLog {
        dock: right;
        width: 40%;
        border: solid blue;
        overflow-y: auto;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._blocks: dict[tuple[str, str], AgentProcessBlock] = {}
        self._pending_blocks: list[AgentProcessBlock] = []

    def on_mount(self) -> None:
        """Mount any blocks that were created before the widget was mounted."""
        for block in self._pending_blocks:
            super().mount(block)
        self._pending_blocks.clear()

    def _mount_block(self, block: AgentProcessBlock) -> None:
        """Mount a block, deferring if not yet mounted ourselves."""
        if self.is_mounted:
            super().mount(block)
        else:
            self._pending_blocks.append(block)

    def has_block(self, agent: str, turn_id: str | None = None) -> bool:
        return (turn_id or "", agent) in self._blocks

    def get_block(self, agent: str, turn_id: str | None = None) -> AgentProcessBlock | None:
        return self._blocks.get((turn_id or "", agent))

    def handle_event(self, event) -> None:
        """Dispatch a harness event to the appropriate block."""
        payload = getattr(event, "payload", {}) or {}
        kind = getattr(event, "kind", type(event).__name__)
        turn_id = getattr(event, "turn_id", None) or payload.get("turn_id", "") or ""
        agent = getattr(event, "agent", None) or payload.get("agent")

        if kind == "PlanReady":
            agent = agent or "planner"
            key = (turn_id, agent)
            if key not in self._blocks:
                block = AgentProcessBlock(agent=agent)
                self._blocks[key] = block
                self._mount_block(block)
            block = self._blocks[key]
            block.append_row(agent, "[plan_ready]")
            for step in payload.get("steps", []):
                block.append_row(agent, f"- {step.get('id')}: {step.get('title')}")
            return

        if agent is None:
            return

        key = (turn_id, agent)
        if kind == "AgentStarted":
            if key not in self._blocks:
                block = AgentProcessBlock(agent=agent)
                self._blocks[key] = block
                self._mount_block(block)
            self._blocks[key].append_row(agent, "[started]")
        elif kind == "ReasoningSummary":
            block = self._blocks.get(key)
            if block:
                block.append_row(agent, f"thinking: {payload.get('text', getattr(event, 'text', ''))}")
        elif kind == "StatusUpdate":
            block = self._blocks.get(key)
            if block:
                level = payload.get("level", getattr(event, "level", "info"))
                text = payload.get("text", getattr(event, "text", ""))
                block.append_row(agent, f"[{level}] {text}")
        elif kind == "ToolCallStart":
            block = self._blocks.get(key)
            if block:
                block.start_tool_call(payload.get("tool_call_id", ""), payload.get("name", ""))
        elif kind == "ToolCallComplete":
            block = self._blocks.get(key)
            if block:
                block.complete_tool_call(
                    payload.get("tool_call_id", ""),
                    payload.get("name", ""),
                    payload.get("args", ""),
                )
        elif kind == "ToolOutput":
            block = self._blocks.get(key)
            if block:
                block.append_tool_output(payload.get("tool_call_id", ""), payload.get("output", ""))
        elif kind == "Handoff":
            from_agent = payload.get("from_agent", "")
            block = self._blocks.get((turn_id, from_agent))
            if block:
                block.append_row(from_agent, f"handoff -> {payload.get('to_agent', '')}")
        elif kind == "AgentFinished":
            block = self._blocks.get(key)
            if block:
                block.append_row(agent, f"[{payload.get('outcome', getattr(event, 'outcome', 'done'))}]")
                block.expand(False)

    def reset(self) -> None:
        for block in list(self._blocks.values()):
            block.remove()
        self._blocks.clear()
        self._pending_blocks.clear()
