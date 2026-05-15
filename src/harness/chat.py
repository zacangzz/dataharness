from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from harness.exceptions import ChatNotFound, ChatWorkspaceMismatch
from runtime.types import RuntimeMessage, RuntimeRequest

_COMPACTION_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "compaction.md"


class ChatMessage(BaseModel):
    message_id: str
    role: Literal["user", "assistant", "compacted_summary"]
    text: str
    ts: datetime
    turn_id: str | None
    active_mode: str | None
    token_estimate: int


class ChatRecord(BaseModel):
    chat_id: str
    workspace_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    last_active_mode: str | None
    last_run_id: str | None
    message_count: int
    token_estimate: int
    last_compacted_at: datetime | None
    compaction_count: int
    messages: list[ChatMessage] = Field(default_factory=list)


class ChatSummary(BaseModel):
    chat_id: str
    workspace_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int
    token_estimate: int
    last_compacted_at: datetime | None


class ChatDeleteResult(BaseModel):
    chat_id: str
    workspace_id: str
    deleted: bool
    files_removed: int


def _new_chat_id() -> str:
    return f"chat_{uuid4().hex[:12]}"


def _estimate_tokens(text: str) -> int:
    return max(len(text) // 4, 1)


class ChatStore:
    """Workspace-scoped chat persistence under <app_root>/workspaces/<workspace_id>/chats/<chat_id>/."""

    def __init__(self, app_root: Path) -> None:
        self.app_root = app_root
        self._workspaces_dir = app_root / "workspaces"
        self._lock = asyncio.Lock()
        # Pending (lazy) chats not yet flushed to disk.
        self._pending: dict[str, ChatRecord] = {}
        self._migrate_legacy_layout()

    def _migrate_legacy_layout(self) -> None:
        legacy = self.app_root / "chats"
        if not legacy.exists() or not legacy.is_dir():
            return
        for ws_dir in legacy.iterdir():
            if not ws_dir.is_dir():
                continue
            new_root = self._workspaces_dir / ws_dir.name / "chats"
            new_root.mkdir(parents=True, exist_ok=True)
            for chat_dir in ws_dir.iterdir():
                target = new_root / chat_dir.name
                if target.exists():
                    continue
                chat_dir.rename(target)
            try:
                ws_dir.rmdir()
            except OSError:
                pass
        try:
            legacy.rmdir()
        except OSError:
            pass

    def _workspace_chats_dir(self, workspace_id: str) -> Path:
        return self._workspaces_dir / workspace_id / "chats"

    def _chat_dir(self, workspace_id: str, chat_id: str) -> Path:
        return self._workspace_chats_dir(workspace_id) / chat_id

    def _iter_workspace_chat_roots(self) -> "list[Path]":
        if not self._workspaces_dir.exists():
            return []
        roots: list[Path] = []
        for ws_dir in self._workspaces_dir.iterdir():
            if not ws_dir.is_dir():
                continue
            chats_dir = ws_dir / "chats"
            if chats_dir.exists():
                roots.append(chats_dir)
        return roots

    async def create_chat(self, *, workspace_id: str, title: str | None) -> ChatSummary:
        chat_id = _new_chat_id()
        now = datetime.now(UTC)
        rec = ChatRecord(
            chat_id=chat_id, workspace_id=workspace_id, title=title,
            created_at=now, updated_at=now,
            last_active_mode=None, last_run_id=None,
            message_count=0, token_estimate=0,
            last_compacted_at=None, compaction_count=0, messages=[],
        )
        async with self._lock:
            self._pending[chat_id] = rec
        return self._summary(rec)

    async def append_message(self, chat_id: str, message: ChatMessage) -> None:
        async with self._lock:
            rec = await self._load_record(chat_id)
            rec.messages.append(message)
            rec.message_count += 1
            rec.token_estimate += message.token_estimate
            rec.updated_at = datetime.now(UTC)
            if message.active_mode:
                rec.last_active_mode = message.active_mode
            await self._flush_record(rec)

    async def append_compaction(
        self, chat_id: str, *, summary_text: str, replaced_turn_count: int, token_estimate: int,
    ) -> ChatMessage:
        marker = ChatMessage(
            message_id=f"sum_{uuid4().hex[:12]}", role="compacted_summary",
            text=summary_text, ts=datetime.now(UTC),
            turn_id=None, active_mode=None, token_estimate=token_estimate,
        )
        async with self._lock:
            rec = await self._load_record(chat_id)
            non_summary = [m for m in rec.messages if m.role != "compacted_summary"]
            rec.messages = [marker] + non_summary[replaced_turn_count:]
            rec.message_count = len(rec.messages)
            rec.token_estimate = sum(m.token_estimate for m in rec.messages)
            rec.last_compacted_at = datetime.now(UTC)
            rec.compaction_count += 1
            rec.updated_at = datetime.now(UTC)
            await self._flush_record(rec)
            chat_dir = self._chat_dir(rec.workspace_id, rec.chat_id)
            line = json.dumps({
                "ts": datetime.now(UTC).isoformat(),
                "summary_text": summary_text,
                "replaced_turn_count": replaced_turn_count,
                "summary_token_estimate": token_estimate,
            }) + "\n"
            with (chat_dir / "compactions.jsonl").open("a") as f:
                f.write(line)
        return marker

    async def register_chat(self, *, chat_id: str, workspace_id: str, title: str | None = None) -> ChatSummary:
        """Register a chat with a caller-supplied chat_id (no on-disk side effects).

        Used by Orchestrator's compat path for tests that pass arbitrary chat_ids
        without calling create_chat first.
        """
        async with self._lock:
            if chat_id in self._pending:
                return self._summary(self._pending[chat_id])
            # Existing on-disk chat?
            for ws_chats in self._iter_workspace_chat_roots():
                meta = ws_chats / chat_id / "metadata.json"
                if meta.exists():
                    rec = ChatRecord.model_validate_json(meta.read_text())
                    return self._summary(rec)
            now = datetime.now(UTC)
            rec = ChatRecord(
                chat_id=chat_id, workspace_id=workspace_id, title=title,
                created_at=now, updated_at=now,
                last_active_mode=None, last_run_id=None,
                message_count=0, token_estimate=0,
                last_compacted_at=None, compaction_count=0, messages=[],
            )
            self._pending[chat_id] = rec
            return self._summary(rec)

    async def view_chat(self, chat_id: str) -> ChatRecord:
        async with self._lock:
            return await self._load_record(chat_id)

    async def list_chats(self, workspace_id: str) -> list[ChatSummary]:
        async with self._lock:
            ws_dir = self._workspace_chats_dir(workspace_id)
            seen: set[str] = set()
            summaries: list[ChatSummary] = []
            if ws_dir.exists():
                for chat_dir in sorted(ws_dir.iterdir()):
                    meta = chat_dir / "metadata.json"
                    if not meta.exists():
                        continue
                    rec = ChatRecord.model_validate_json(meta.read_text())
                    summaries.append(self._summary(rec))
                    seen.add(rec.chat_id)
            # include in-memory pending chats not yet flushed to disk
            for rec in self._pending.values():
                if rec.workspace_id == workspace_id and rec.chat_id not in seen:
                    summaries.append(self._summary(rec))
            return summaries

    async def delete_chat(self, chat_id: str) -> ChatDeleteResult:
        async with self._lock:
            pending = self._pending.pop(chat_id, None)
            if pending is not None:
                return ChatDeleteResult(
                    chat_id=chat_id, workspace_id=pending.workspace_id,
                    deleted=True, files_removed=0,
                )
            for ws_chats in self._iter_workspace_chat_roots():
                cdir = ws_chats / chat_id
                if cdir.exists():
                    files = sum(1 for _ in cdir.rglob("*") if _.is_file())
                    shutil.rmtree(cdir)
                    return ChatDeleteResult(
                        chat_id=chat_id, workspace_id=ws_chats.parent.name,
                        deleted=True, files_removed=files,
                    )
            raise ChatNotFound(chat_id=chat_id)

    async def cascade_delete_for_workspace(self, workspace_id: str) -> list[ChatDeleteResult]:
        async with self._lock:
            results: list[ChatDeleteResult] = []
            ws_dir = self._workspace_chats_dir(workspace_id)
            if ws_dir.exists():
                for cdir in sorted(ws_dir.iterdir()):
                    if cdir.is_dir():
                        files = sum(1 for _ in cdir.rglob("*") if _.is_file())
                        results.append(ChatDeleteResult(
                            chat_id=cdir.name, workspace_id=workspace_id,
                            deleted=True, files_removed=files,
                        ))
                shutil.rmtree(ws_dir)
            for chat_id, rec in list(self._pending.items()):
                if rec.workspace_id == workspace_id:
                    self._pending.pop(chat_id)
                    results.append(ChatDeleteResult(
                        chat_id=chat_id, workspace_id=workspace_id,
                        deleted=True, files_removed=0,
                    ))
            return results

    def _summary(self, rec: ChatRecord) -> ChatSummary:
        return ChatSummary(
            chat_id=rec.chat_id, workspace_id=rec.workspace_id, title=rec.title,
            created_at=rec.created_at, updated_at=rec.updated_at,
            message_count=rec.message_count, token_estimate=rec.token_estimate,
            last_compacted_at=rec.last_compacted_at,
        )

    async def _load_record(self, chat_id: str) -> ChatRecord:
        if chat_id in self._pending:
            return self._pending[chat_id]
        for ws_chats in self._iter_workspace_chat_roots():
            meta = ws_chats / chat_id / "metadata.json"
            if meta.exists():
                rec = ChatRecord.model_validate_json(meta.read_text())
                msgs_path = ws_chats / chat_id / "messages.jsonl"
                if msgs_path.exists():
                    rec.messages = [
                        ChatMessage.model_validate_json(line)
                        for line in msgs_path.read_text().splitlines() if line.strip()
                    ]
                return rec
        raise ChatNotFound(chat_id=chat_id)

    async def _flush_record(self, rec: ChatRecord) -> None:
        chat_dir = self._chat_dir(rec.workspace_id, rec.chat_id)
        chat_dir.mkdir(parents=True, exist_ok=True)
        meta = rec.model_copy(update={"messages": []})  # metadata excludes messages
        (chat_dir / "metadata.json").write_text(meta.model_dump_json(indent=2))
        (chat_dir / "messages.jsonl").write_text(
            "\n".join(m.model_dump_json() for m in rec.messages) + ("\n" if rec.messages else "")
        )
        self._pending.pop(rec.chat_id, None)


_FORMATS_WITHOUT_SYSTEM_ROLE = ("gemma",)


def _format_drops_system_role(chat_format: str | None) -> bool:
    if not chat_format:
        return False
    return any(chat_format.startswith(prefix) for prefix in _FORMATS_WITHOUT_SYSTEM_ROLE)


class RuntimeRequestBuilder:
    def __init__(
        self,
        context_window: int,
        *,
        completion_reserve_pct: float = 0.25,
        durable_pct: float = 0.30,
        summary_pct: float = 0.15,
        recent_pct: float = 0.25,
        recent_turns_kept: int = 8,
        chat_format: str | None = None,
    ) -> None:
        self.context_window = context_window
        self.completion_reservation = int(context_window * completion_reserve_pct)
        self.durable_budget = int((context_window - self.completion_reservation) * (durable_pct / 0.75))
        self.summary_budget = int((context_window - self.completion_reservation) * (summary_pct / 0.75))
        self.recent_budget = int((context_window - self.completion_reservation) * (recent_pct / 0.75))
        self.recent_turns_kept = recent_turns_kept
        self.chat_format = chat_format
        self.merge_system_into_first_user = _format_drops_system_role(chat_format)

    @staticmethod
    def _truncate(text: str, max_tokens: int) -> str:
        max_chars = max_tokens * 4
        return text if len(text) <= max_chars else text[-max_chars:]

    def build_messages(
        self,
        *,
        active_mode_prompt: str,
        durable_context: str,
        chat_record: ChatRecord | None,
        current_user_text: str,
    ) -> list[RuntimeMessage]:
        summaries: list[ChatMessage] = []
        recent: list[ChatMessage] = []
        if chat_record is not None and chat_record.messages:
            summaries = [m for m in chat_record.messages if m.role == "compacted_summary"]
            recent = [m for m in chat_record.messages if m.role != "compacted_summary"][-self.recent_turns_kept:]

        recent_already_has_current = bool(
            recent
            and recent[-1].role == "user"
            and recent[-1].text == current_user_text
        )

        system_block_parts: list[str] = []
        if active_mode_prompt:
            system_block_parts.append(active_mode_prompt)
        if durable_context.strip():
            system_block_parts.append(
                self._truncate(f"WORKSPACE CONTEXT:\n{durable_context}", self.durable_budget)
            )
        for s in summaries:
            system_block_parts.append(
                self._truncate(f"PRIOR CHAT SUMMARY:\n{s.text}", self.summary_budget)
            )

        out: list[RuntimeMessage] = []

        if self.merge_system_into_first_user:
            system_text = "\n\n".join(p for p in system_block_parts if p)
            prefixed = False
            for idx, m in enumerate(recent):
                role = "user" if m.role == "user" else "assistant"
                content = m.text
                if not prefixed and role == "user" and system_text:
                    content = f"[SYSTEM]\n{system_text}\n[/SYSTEM]\n\n{content}"
                    prefixed = True
                out.append(RuntimeMessage(role=role, content=content))
            if not recent_already_has_current:
                content = current_user_text
                if not prefixed and system_text:
                    content = f"[SYSTEM]\n{system_text}\n[/SYSTEM]\n\n{content}"
                    prefixed = True
                out.append(RuntimeMessage(role="user", content=content))
        else:
            for part in system_block_parts:
                out.append(RuntimeMessage(role="system", content=part))
            for m in recent:
                role = "user" if m.role == "user" else "assistant"
                out.append(RuntimeMessage(role=role, content=m.text))
            if not recent_already_has_current:
                out.append(RuntimeMessage(role="user", content=current_user_text))
        return out


from runtime.protocol import Runtime  # noqa: E402


class ChatCompactor:
    """Replaces older chat turns with a summary, queueing behind any in-flight runtime stream."""

    def __init__(
        self,
        *,
        store: ChatStore,
        runtime: Runtime | None,
        runtime_lock: asyncio.Lock | None = None,
        recent_turns_kept: int = 8,
        max_summary_tokens: int = 256,
    ) -> None:
        self.store = store
        self.runtime = runtime
        self.runtime_lock = runtime_lock or asyncio.Lock()
        self.recent_turns_kept = recent_turns_kept
        self.max_summary_tokens = max_summary_tokens

    async def compact(
        self, chat_id: str, *, reason: str, recent_turns_kept: int | None = None,
    ) -> AsyncIterator[Literal["queued", "running", "completed", "failed"]]:
        yield "queued"
        async with self.runtime_lock:
            yield "running"
            try:
                rec = await self.store.view_chat(chat_id)
                existing_summaries = [m for m in rec.messages if m.role == "compacted_summary"]
                non_summary = [m for m in rec.messages if m.role != "compacted_summary"]
                keep_recent = self.recent_turns_kept if recent_turns_kept is None else max(0, recent_turns_kept)
                if not non_summary or (keep_recent > 0 and len(non_summary) <= keep_recent):
                    yield "completed"
                    return
                older = non_summary if keep_recent == 0 else non_summary[:-keep_recent]
                replaced = len(older)
                if self.runtime is None:
                    summary_text = self._fallback_summary(existing_summaries + older)
                else:
                    summary_text = await self._summarize_via_runtime(existing_summaries + older)
                    if self._looks_like_transcript_echo(summary_text):
                        summary_text = self._fallback_summary(existing_summaries + older)
                token_est = max(len(summary_text) // 4, 1)
                await self.store.append_compaction(
                    chat_id, summary_text=summary_text,
                    replaced_turn_count=replaced, token_estimate=token_est,
                )
                yield "completed"
            except Exception as exc:
                logging.getLogger("harness.compactor").exception(
                    "compactor failed for chat %s: %s", chat_id, exc,
                )
                yield "failed"

    def _fallback_summary(self, messages: list[ChatMessage]) -> str:
        if not messages:
            return "Summary of compacted chat:\n- No prior chat content was available to summarize."

        def clean(text: str, limit: int = 220) -> str:
            collapsed = " ".join(text.split())
            collapsed = re.sub(r"^\[compacted earlier turns\]\s*", "", collapsed, flags=re.IGNORECASE)
            collapsed = re.sub(r"^summary of compacted chat:\s*", "", collapsed, flags=re.IGNORECASE)
            collapsed = re.sub(
                r"^(assistant|user|system|compacted_summary):\s*",
                "",
                collapsed,
                flags=re.IGNORECASE,
            )
            return collapsed if len(collapsed) <= limit else f"{collapsed[: limit - 1].rstrip()}..."

        def is_trivial_user_text(text: str) -> bool:
            normalized = re.sub(r"\s+", " ", text.strip().lower())
            return normalized in {
                "?", "and?", "hello", "hi", "hey", "test", "testing",
                "ok", "okay", "thanks", "thank you",
            }

        def is_trivial_assistant_text(text: str) -> bool:
            normalized = re.sub(r"\s+", " ", text.strip().lower())
            return (
                normalized.startswith("hello. i am dataharness")
                or normalized in {"hello.", "hello", "hi.", "hi"}
            )

        cleaned_messages = [
            (m.role, clean(m.text))
            for m in messages
            if m.text.strip()
        ]
        user_items = [
            text for role, text in cleaned_messages
            if role == "user" and not is_trivial_user_text(text)
        ]
        progress_items = [
            text for role, text in cleaned_messages
            if role in {"assistant", "compacted_summary"} and not is_trivial_assistant_text(text)
        ]
        file_refs = sorted({
            match
            for _, text in cleaned_messages
            for match in re.findall(
                r"\b(?:data/)?[A-Za-z0-9_.-]+\.(?:csv|tsv|xlsx|xls|json|parquet|txt|md|py|ipynb)\b",
                text,
            )
        })

        current_goal = user_items[-1] if user_items else "Continue the active DataHarness data-analysis conversation."
        progress = "; ".join(progress_items[-3:]) if progress_items else "No durable analysis result was established before compaction."
        references = ", ".join(file_refs) if file_refs else "No specific workspace files were established before compaction."

        lines = [
            "Summary of compacted chat:",
            f"- Current user goal: {current_goal}",
            f"- Progress and facts: {progress}",
            f"- Data/workspace references: {references}",
            "- Constraints and preferences: Continue inside DataHarness as a local-first data-analysis assistant; preserve workspace facts, file paths, schemas, approvals, errors, and results.",
            "- Next steps: Answer the latest user request using the preserved context; inspect workspace data or request approval for analysis only when needed.",
        ]
        return "\n".join(lines)

    @staticmethod
    def _looks_like_transcript_echo(summary_text: str) -> bool:
        stripped = summary_text.strip()
        lowered = stripped.lower()
        if lowered.startswith(("assistant:", "user:", "system:", "compacted_summary:")):
            return True
        if "analysis plan request" in lowered:
            return True
        return False

    async def _summarize_via_runtime(self, older: list[ChatMessage]) -> str:
        joined = "\n".join(f"{m.role}: {m.text}" for m in older)
        request = RuntimeRequest(
            messages=[
                RuntimeMessage(role="system", content=self._load_compaction_prompt()),
                RuntimeMessage(role="user", content=joined),
            ],
            max_completion_tokens=self.max_summary_tokens,
            request_id=f"req_compact_{uuid4().hex[:8]}",
        )
        chunks: list[str] = []
        async for ev in self.runtime.stream(request):
            if ev.type == "text_delta":
                chunks.append(ev.text or "")
        return "".join(chunks).strip() or "(empty summary)"

    def _load_compaction_prompt(self) -> str:
        return _COMPACTION_PROMPT_PATH.read_text(encoding="utf-8").strip()
