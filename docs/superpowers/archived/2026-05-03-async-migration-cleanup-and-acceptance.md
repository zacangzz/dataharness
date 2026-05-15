# Async Migration — Cross-Cutting Cleanup & V1 Acceptance

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-05-01-async-layered-architecture-design.md` §11 (migration policy), §13 (V1 acceptance criteria), §12 (packaging).

**Goal:** Run after plans 1, 2, 3a, 3b, 3c, 4 are merged. Removes any lingering sync surfaces, packaging gaps, and adds the V1 acceptance test that binds to spec §13 invariants. Final smoke ensures full repo passes async-only.

**Architecture:** No new modules. Pure cleanup + acceptance test.

---

## File Structure

- `tests/acceptance/test_v1_async_acceptance.py` — **new**: end-to-end binding to spec §13.
- `hragent.spec` — update to include any new TUI screens/prompts.
- Deletions / edits across `src` to remove forbidden sync paths.

---

## Task 1: Forbidden symbol scan

- [ ] **Step 1.1: Run grep for forbidden symbols**

```bash
grep -rn -E "Runtime\.complete|def complete\(self, request|max_new_tokens|RuntimeResponse|class SessionConfig.*max_parallel_runs|compact_context|WorkspaceActivated|AppTurnResult|handle_turn|submit_user_text\(.*\) ?-> ?AppTurnResult" src tests || true
```

- [ ] **Step 1.2: Resolve every match**

Each remaining match must be deleted or rewritten per its plan. None of the items listed in spec §11 may remain in `src/`. Tests proving the new behavior live in plans 1–4; this step ensures nothing slipped through.

- [ ] **Step 1.3: Run full suite**

```bash
uv run pytest -q
```
Expected: PASS.

- [ ] **Step 1.4: Commit**

```bash
git add -A
git commit -m "chore: enforce removal of legacy sync surfaces per spec §11"
```

---

## Task 2: Packaging update

- [ ] **Step 2.1: Inspect `hragent.spec`**

Run: `cat hragent.spec`

- [ ] **Step 2.2: Add new screens / prompt files**

If new files exist under `src/app/tui/screens/` or new `prompts/*.md` were added during plans 4 / 3c, add them to `hragent.spec`'s `datas`/`hiddenimports` per the existing pattern.

- [ ] **Step 2.3: Run packaging test if present**

`uv run pytest tests/packaging -v`

- [ ] **Step 2.4: Commit**

```bash
git add hragent.spec
git commit -m "chore(packaging): include new TUI screens and prompt assets"
```

---

## Task 3: V1 acceptance test

**Files:**
- Create: `tests/acceptance/test_v1_async_acceptance.py`

- [ ] **Step 3.1: Implement acceptance test**

```python
# tests/acceptance/test_v1_async_acceptance.py
import asyncio
from pathlib import Path

import pytest

from app.session import AppSession
from harness.exceptions import RunAlreadyActive, WorkspaceSwitchBlocked


class FakeRuntime:
    async def context_window(self): return 4096
    async def status(self): return "ready"
    async def validate_request(self, r): return None
    async def token_pressure(self, r):
        from runtime.types import TokenPressure
        return TokenPressure(
            request_id=r.request_id, context_window=4096,
            prompt_tokens=10, reserved_completion_tokens=r.max_completion_tokens,
            total_tokens=10 + r.max_completion_tokens,
            pressure_ratio=0.05, over_threshold=False,
        )
    async def stream(self, r):
        from runtime.types import RuntimeEvent
        yield RuntimeEvent(type="text_delta", request_id=r.request_id, seq=0, text="ok")
        yield RuntimeEvent(type="finish", request_id=r.request_id, seq=1, finish_reason="stop", usage={})


@pytest.fixture
def session(tmp_path):
    from harness.orchestrator import Orchestrator
    orch = Orchestrator(runtime=FakeRuntime(), app_root=tmp_path)
    return AppSession(orchestrator=orch, app_root=tmp_path)


# Spec §13 — Concurrency
async def test_single_active_run(session, tmp_path):
    from harness.control import RunStateRecord
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    await session.create_workspace("w1")
    chat = await session.create_chat("w1")
    agen = session.run_user_turn(state=state, workspace_dir=tmp_path, chat_id=chat.chat_id, user_text="a")
    await agen.__anext__()
    with pytest.raises(RunAlreadyActive):
        async for _ in session.run_user_turn(
            state=state, workspace_dir=tmp_path, chat_id=chat.chat_id, user_text="b",
        ):
            pass
    async for _ in agen:
        pass


async def test_workspace_switch_blocked_unless_force(session, tmp_path):
    await session.create_workspace("w1")
    await session.create_workspace("w2")
    session.orchestrator._active_run_id = "run_x"
    with pytest.raises(WorkspaceSwitchBlocked):
        await session.activate_workspace("w2", force=False)
    session.orchestrator._active_run_id = None


# Spec §13 — Chat
async def test_no_chat_dir_until_first_message(session, tmp_path):
    await session.create_workspace("w1")
    chat = await session.create_chat("w1")
    chat_dir = tmp_path / "chats" / "w1" / chat.chat_id
    assert not chat_dir.exists()


async def test_chat_files_after_first_message(session, tmp_path):
    from harness.control import RunStateRecord
    await session.create_workspace("w1")
    chat = await session.create_chat("w1")
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    async for _ in session.run_user_turn(state=state, workspace_dir=tmp_path, chat_id=chat.chat_id, user_text="hi"):
        pass
    chat_dir = tmp_path / "chats" / "w1" / chat.chat_id
    assert (chat_dir / "metadata.json").exists()
    assert (chat_dir / "messages.jsonl").exists()


async def test_workspace_delete_cascades_chats(session, tmp_path):
    from datetime import UTC, datetime
    from harness.chat import ChatMessage
    await session.create_workspace("w1")
    chat = await session.create_chat("w1")
    await session.orchestrator.chat_store.append_message(chat.chat_id, ChatMessage(
        message_id="m", role="user", text="x", ts=datetime.now(UTC),
        turn_id=None, active_mode=None, token_estimate=1,
    ))
    await session.delete_workspace("w1")
    assert not (tmp_path / "chats" / "w1").exists()


# Spec §13 — Commands
async def test_help_returns_descriptors(session):
    res = await session.help()
    names = {d.name for d in res.commands}
    for required in ("doctor", "compact", "help"):
        assert required in names


async def test_help_unknown_returns_not_found(session):
    res = await session.help("nope")
    assert res.not_found is True


# Spec §13 — Status
async def test_watch_status_yields_initial_then_heartbeat(session):
    agen = session.watch_status()
    first = await asyncio.wait_for(agen.__anext__(), timeout=2.0)
    assert first.workspace_id is not None or first.workspace_id == ""


# Spec §13 — Doctor
async def test_doctor_emits_full_event_sequence(session, tmp_path):
    from harness.control import RunStateRecord
    await session.create_workspace("w1")
    state = RunStateRecord(workspace_id="w1", active_agent_mode="interaction")
    events = [e async for e in session.handle_direct_command(
        state, command="doctor", arguments={"trigger": "manual"},
    )]
    names = [e.event_name for e in events]
    assert names[0] == "AppCommandStarted"
    assert any(n == "AppCommandProgress" for n in names)
    assert any(n == "AppDoctorReportReady" for n in names)
    assert names[-1] == "AppCommandCompleted"
```

- [ ] **Step 3.2: Run**

`uv run pytest tests/acceptance/test_v1_async_acceptance.py -v`
Expected: PASS.

- [ ] **Step 3.3: Commit**

```bash
git add tests/acceptance/test_v1_async_acceptance.py
git commit -m "test(acceptance): bind V1 invariants from spec §13 to acceptance suite"
```

---

## Task 4: Final repo smoke

- [ ] **Step 4.1: Run full test suite**

```bash
uv run pytest -q
```

- [ ] **Step 4.2: Verify Layer 3 isolation**

```bash
grep -rn "from app\." src/harness && echo "BAD: harness imports app" || echo "OK: harness clean"
grep -rn "from harness.orchestrator" src/app/tui && echo "BAD: tui imports orchestrator directly" || echo "OK: tui clean"
```

- [ ] **Step 4.3: Final commit**

```bash
git add -A
git commit -m "chore: async migration complete; layer isolation verified"
```

---

## Self-Review Checklist

Spec §13 ↔ test mapping:

| Invariant | Test |
|-----------|------|
| Single active run | `test_single_active_run` |
| `WorkspaceSwitchBlocked` unless `force=True` | `test_workspace_switch_blocked_unless_force` |
| Chat directory lazy creation | `test_no_chat_dir_until_first_message`, `test_chat_files_after_first_message` |
| Workspace delete cascade | `test_workspace_delete_cascades_chats` |
| `/help` returns descriptor list | `test_help_returns_descriptors` |
| `/help <unknown>` → `not_found=True` | `test_help_unknown_returns_not_found` |
| `watch_status` yields | `test_watch_status_yields_initial_then_heartbeat` |
| `/doctor` event sequence | `test_doctor_emits_full_event_sequence` |
| Layer 1 bridge queue 64 default | covered in plan 1 Task 3 |
| Cancellation observed within one token | plan 1 Task 4 |
| Worker cancel envelope `status.status=="cancelled"` | plan 2 Task 2 |
| Compaction queues behind runtime | plan 3b Task 3 |
| Recent-8 + 25% reserve + 80% trigger | plan 3b Task 2 + Task 4 |
| Conversation log rehydrates from `view_chat` | plan 4 Task 10 |
| TUI calls Layer 3 only via `AppSession` | plan 4 Task 9 |

If a row is missing a passing test, fix it before declaring the migration complete.
