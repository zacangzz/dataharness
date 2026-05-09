# UI Streaming And Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the old post-hoc `Agent Steps` panel with streamed per-agent process blocks and make the packaged app runnable under the new Agents SDK runtime.

**Architecture:** Refactor the Textual app into a renderer for live `PipelineEvent`s instead of a synchronous consumer of `PipelineResult.agent_steps`. Once the UI can render the streamed lifecycle, swap dependencies and packaging metadata to ship the Agents SDK runtime, sandbox mount policy, and smoke coverage.

**Tech Stack:** Textual, Python 3.12 async workers, `openai-agents`, PyInstaller, existing build scripts, pytest, shell smoke scripts

---

### Task 1: Add Process-Log Widgets For Per-Agent Streaming

**Files:**
- Create: `src/cli/process_log.py`
- Modify: `src/cli/app.py`
- Create: `tests/cli/test_process_log.py`

- [ ] **Step 1: Write the failing widget tests**

```python
async def test_process_log_creates_one_collapsible_per_agent():
    log = ProcessLog()
    log.handle_event(AgentStarted(agent="triage"))
    log.handle_event(AgentStarted(agent="data_analyst"))
    assert log.has_block("triage")
    assert log.has_block("data_analyst")


async def test_process_log_uses_plus_minus_title_state():
    block = AgentProcessBlock("triage")
    assert block.title.startswith("+ ")
    block.expand()
    assert block.title.startswith("- ")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_process_log.py -q`
Expected: FAIL because no process-log widget exists yet.

- [ ] **Step 3: Add the new widget module**

```python
class AgentProcessBlock(Collapsible):
    def __init__(self, agent: str) -> None:
        super().__init__(title=f"+ {agent}", collapsed=True)

    def set_expanded_state(self, expanded: bool) -> None:
        self.title = f"{'-' if expanded else '+'} {self.agent}"
```

- [ ] **Step 4: Replace `AgentStepView` usage with `ProcessLog` mounting**

```python
yield ProcessLog(id="process-log")
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/cli/test_process_log.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/cli/process_log.py src/cli/app.py tests/cli/test_process_log.py
git commit -m "feat: add streamed process log widgets for agent activity"
```

### Task 2: Render Live Pipeline Events In `ChatApp`

**Files:**
- Modify: `src/cli/app.py`
- Modify: `src/cli/status_bar.py`
- Modify: `tests/cli/test_app.py`
- Modify: `tests/cli/test_status_bar.py`

- [ ] **Step 1: Write the failing UI streaming tests**

```python
@pytest.mark.asyncio
async def test_chat_app_appends_reasoning_to_process_block(mock_pipeline):
    app = ChatApp(model_path="/fake/model.gguf", manager=_make_mock_manager())
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        await app._handle_pipeline_event(ReasoningSummary(agent="triage", text="Checking route"))
    assert "thinking:" in app.query_one("#process-log").renderable_text


@pytest.mark.asyncio
async def test_status_update_updates_bar_and_process_block(mock_pipeline):
    app = ChatApp(model_path="/fake/model.gguf", manager=_make_mock_manager())
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        await app._handle_pipeline_event(StatusUpdate(text="Calling list_files...", level="tool", agent="data_analyst"))
    assert "Calling list_files" in str(app.query_one(StatusBar).render())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_app.py tests/cli/test_status_bar.py -q`
Expected: FAIL because `ChatApp` still waits for one final `PipelineResult`.

- [ ] **Step 3: Change `_run_pipeline` to forward live events**

```python
async def _handle_pipeline_event(self, event: PipelineEvent) -> None:
    if event.kind == "agent_started":
        self.query_one("#process-log", ProcessLog).handle_event(event)
    elif event.kind == "token_delta":
        self._append_assistant_delta(event)
```

- [ ] **Step 4: Keep reasoning summarized and out of the transcript**

```python
elif event.kind == "reasoning_summary":
    process_log.append_row(event.agent, f"thinking: {event.text}")
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/cli/test_app.py tests/cli/test_status_bar.py tests/cli/test_process_log.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/cli/app.py src/cli/status_bar.py tests/cli/test_app.py tests/cli/test_status_bar.py
git commit -m "feat: stream pipeline events into textual ui"
```

### Task 3: Probe Sandbox Runtime And Package The Agents SDK Runtime

**Files:**
- Modify: `pyproject.toml`
- Modify: `hragent.spec`
- Modify: `scripts/build_app.sh`
- Create: `scripts/smoke_packaged.sh`
- Create: `tests/core/test_packaging_contract.py`
- Modify: `APP.md`
- Modify: `README.md`

- [ ] **Step 1: Write the packaging and dependency assertions**

```python
def test_pyproject_uses_openai_agents_only():
    text = Path("pyproject.toml").read_text()
    assert "openai-agents" in text
    assert "smolagents" not in text


def test_hragent_spec_bundles_new_prompts_and_agents_runtime():
    text = Path("hragent.spec").read_text()
    assert "triage.md" in text
    assert "knowledge.md" in text
    assert "agents.sandbox.sandboxes.unix_local" in text
```

- [ ] **Step 2: Run the dependency assertion**

Run: `uv run pytest tests/core/test_packaging_contract.py -q`
Expected: FAIL because the repo still depends on `smolagents`.

- [ ] **Step 3: Add a runtime probe before finalizing packaging strategy**

```bash
#!/usr/bin/env bash
set -euo pipefail

bash scripts/build_app.sh
printf '/workspace list\n/use 1\nwhat is the mean of the numeric columns?\n/exit\n' | ./dist/hragent/hragent-cli
```

Expected notes to record in `APP.md`:
- which python the sandbox found
- whether `pandas`, `numpy`, and `openpyxl` import inside the sandbox
- whether the packaged process reuses embedded Python or requires host Python

- [ ] **Step 4: Update packaging metadata with the probe outcome**

```toml
[project]
dependencies = [
  "openai-agents>=0.1.0",
]
```

```python
hiddenimports = [
    "agents",
    "agents.sandbox",
    "agents.sandbox.entries",
    "agents.sandbox.capabilities",
    "agents.sandbox.sandboxes.unix_local",
    "agents.tracing",
]
```

- [ ] **Step 5: Add a packaged smoke script with probe, safety, and latency assertions**

```bash
#!/usr/bin/env bash
set -euo pipefail

uv run python -m build
bash scripts/build_app.sh
./dist/hragent/hragent-cli --workspace-fixture tests/fixtures/workspaces/packaged-smoke > /tmp/hragent-packaged.log <<'EOF'
hello
what files do I have?
what's the average salary?
try to overwrite data/employees.csv
extract the hr policy text
/exit
EOF

grep -q "employees.csv" /tmp/hragent-packaged.log
grep -E -q "[0-9]+(\\.[0-9]+)?" /tmp/hragent-packaged.log
grep -q "sandbox_denied" /tmp/hragent-packaged.log
grep -q "hr policy" /tmp/hragent-packaged.log
test -f tests/fixtures/workspaces/packaged-smoke/memory/functions/index.json
test -f tests/fixtures/workspaces/packaged-smoke/memory/notes/index.json
grep -q '"turn_id"' local/hragent-telemetry.log
grep -q '"run_id"' local/hragent-telemetry.log
python scripts/assert_no_network_egress.py local/hragent-telemetry.log
python scripts/assert_smoke_latency.py local/smoke-latency.json tests/integration/budgets.json
```

- [ ] **Step 6: Document the chosen runtime strategy and safety model**

```markdown
## Sandbox runtime

- Analyst turns run through `UnixLocalSandboxClient`
- `/workspace/data` is mounted read-only
- `/workspace/memory` is mounted read-write
- Document one of:
- `Packaged runtime strategy: uses host Python 3.12 with pandas/numpy/openpyxl`
- `Packaged runtime strategy: reuses the frozen embedded Python runtime`
- `Packaged runtime strategy: Docker fallback required for analyst turns`
```

- [ ] **Step 7: Run fast checks**

Run: `uv run pytest tests/core/test_packaging_contract.py -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml hragent.spec scripts/build_app.sh scripts/smoke_packaged.sh tests/core/test_packaging_contract.py APP.md README.md
git commit -m "build: package agents sdk runtime and smoke coverage"
```
