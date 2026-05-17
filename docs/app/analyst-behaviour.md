# Analyst Behaviour & Workflow

This document describes how DataHarness handles analytical and data science questions across the application, harness, runtime, and worker layers.

## 1. Layer-wise Key Functions

### Layer 4: Application Session Facade
*   **`AppSession.run_user_turn` (`src/app/session.py`)**
    *   **Role**: Layer 4 facade.
    *   **Logic**: A passthrough — forwards the user turn to `Orchestrator.run_agentic_turn` and maps harness events into app events for the TUI. It does not select the mode or supply prompts; routing and prompt selection are owned by Layer 3.

### Layer 3: Harness Agentic Loop And Tool Dispatch
*   **`ModeRouter.route` (`src/harness/services/mode_router.py`)**
    *   **Role**: Prompt-profile selection for each user turn.
    *   **Logic**: Routes to analyst mode when the prompt contains analysis, aggregation, transformation, charting, forecasting, or workspace data-reference language. Knowledge-capture language routes to knowledge mode first; otherwise it defaults to interaction mode unless an optional LLM classifier returns another mode. Returns a `ProfileDecision` (`.mode`/`.reason`); `request_mode()` is a stable alias of `route()`. The orchestrator invokes this via `Orchestrator._select_profile`, which applies mode continuity and writes `state.active_agent_mode`.
*   **`PromptProfileRegistry.load` (`src/harness/services/prompt_profiles.py`)**
    *   **Role**: Prompt assembly.
    *   **Logic**: Builds a `PromptPackage` from the shared system prompt, the persona prompt (e.g. `analyst.md` under `src/harness/prompts/`), the registered tool catalog, and the response-format prompt. The analyst profile exposes the analyst-visible harness tools: `analysis_plan`, `analysis_request_execution`, `file_read`, `knowledge_recall`, and `respond_to_user`. The catalog is backed by `HarnessToolRegistry`, not the command registry.
*   **`Orchestrator.run_agentic_turn` (`src/harness/orchestrator.py`)**
    *   **Role**: Agentic control loop.
    *   **Logic**: Selects the prompt profile internally (via `_select_profile`/`ModeRouter`), runs the runtime turn, captures structured tool calls, handles mid-turn handoff to analyst mode, dispatches tools through `HarnessToolRegistry`, formats tool results into follow-up prompts, and stops at approval gates.
*   **`AnalysisFlow` (`src/harness/core/analysis_flow.py`)**
    *   **Role**: Durable per-chat analysis state.
    *   **Logic**: Tracks an in-flight analysis through `inspecting`, `plan_pending`, `approval_pending`, `executing`, `done`, and `failed`. The orchestrator persists and replays this state so a multi-turn analysis is not lost when a later message would otherwise route to a different mode.
*   **`Orchestrator._dispatch_tool_call` (`src/harness/orchestrator.py`)**
    *   **Role**: Model tool enforcement.
    *   **Logic**: Resolves and validates every model-emitted tool through `tool_registry` only. Command-only names such as `plan_analysis`, `doctor`, and `compact` do not dispatch as model tools.
*   **`file_read` (`src/harness/tools/file.py`)**
    *   **Role**: Workspace inspection tool.
    *   **Logic**: Lists files, inspects schema/metadata, or reads text content under the active workspace. Analysts use it before planning when required schema or source text is missing from context.
*   **`analysis_plan` (`src/harness/tools/analysis.py`)**
    *   **Role**: Model-facing analysis planning tool.
    *   **Logic**: Accepts a code-free plan from the model, then routes to `AnalysisService.assemble_plan_events`.
*   **`AnalysisService.assemble_plan_events` (`src/harness/services/analysis.py`)**
    *   **Role**: Plan assembly and validation.
    *   **Logic**: Uses a second internal generation to synthesize Python for each plain-language step, validates generated code against worker policy and expected outputs, retries code generation once per invalid step, creates `Plan` and `StepContract` records, and emits one `ApprovalRequired` event.
*   **`Orchestrator._analysis_plan_events` (`src/harness/orchestrator.py`)**
    *   **Role**: Command compatibility path.
    *   **Logic**: Handles user/app command calls to `plan_analysis`, where code is supplied directly. This path does not use the model-facing code-free plan flow.

### Layer 2: Worker Execution
*   **`Orchestrator.resume_approved_step` (`src/harness/orchestrator.py`)**
    *   **Role**: Approval-gated execution entry point.
    *   **Logic**: After the user approves a plan step, submits the stored `StepContract` to the worker, streams task status, records artifacts, and emits result events.
*   **`worker.executor` and `worker.sandbox_bootstrap` (`src/worker/`)**
    *   **Role**: Sandboxed Python execution.
    *   **Logic**: Runs only approved analyst code with staged declared inputs, bounded writes, import policy checks, and no shell or network access.

### Layer 4a: TUI Presentation And Review
*   **`DataHarnessApp` event handlers (`src/app/tui/app.py`)**
    *   **Role**: User-facing analysis workflow.
    *   **Logic**: Displays streamed runtime text, tool execution traces, plans, approval banners, step progress, completion summaries, and artifacts.
*   **`ApprovalBanner` (`src/app/tui/widgets.py`)**
    *   **Role**: Execution approval UI.
    *   **Logic**: Lets the user approve, reject, or inspect generated analysis steps before any worker code runs.

---

## 2. Step-wise Workflow Logic

### Phase A: Mode Entry
1.  **Trigger**: The user asks for a calculation, comparison, transformation, chart, forecast, summary, aggregation, or data-backed answer.
2.  **Routing**: the Layer-3 `ModeRouter` (via `Orchestrator._select_profile`) selects analyst mode, or the interaction model emits `handoff_to_analyst`.
3.  **Prompting**: The analyst prompt is built with the registered tool catalog and the analyst allowed-tool subset.

### Phase B: Inspection
4.  **Context Check**: The analyst first uses existing workspace context and prior `[TOOL_RESULT]` blocks.
5.  **File Inspection**: If schema or source text is missing, the analyst emits one `file_read` tool call:
    *   `operation="list"` for workspace inventory.
    *   `operation="inspect"` for file metadata and tabular schema.
    *   `operation="content"` for text or note content.
6.  **Follow-up Prompt**: The harness feeds the tool result back to the runtime. File contents should be summarized, not pasted verbatim, unless the user asks for exact text.

### Phase C: Planning
7.  **Plan Proposal**: When computation or artifact-producing work is needed, the analyst emits one `analysis_plan` tool call.
8.  **Code-free Contract**: The model supplies only `goal` and `steps`; each step describes purpose, declared inputs, and expected outputs. It must not include Python code or imports.
9.  **Forced Plan Fallback**: If analyst mode inspects data or appears ready to plan but returns prose instead of a tool call, the harness can run a small non-persisted generation that forces one valid code-free `analysis_plan` call.

### Phase D: Harness Assembly And Approval
10. **Code Synthesis**: Layer 3 generates Python for each step internally from the code-free plan and workspace schemas.
11. **Validation**: The harness validates imports, workspace-relative inputs, output references, and worker policy before approval is requested.
12. **Approval Gate**: The harness emits `PlanReady` and one `ApprovalRequired`. No worker code runs before user approval.
13. **Pending State**: The analysis flow moves to `approval_pending` and is kept sticky for the chat so follow-up questions about the pending plan remain grounded.

### Phase E: Execution And Reporting
14. **Approval Response**: The user approves or rejects the step from the TUI.
15. **Worker Run**: Approved code executes in the sandbox using staged declared inputs and controlled artifact writes.
16. **Result Events**: The harness emits worker status, step completion, artifacts, and final answer events.
17. **Answer Summary**: The analyst-facing response should cite generated artifact paths, distinguish computed facts from interpretation, and avoid inventing results.

---

## 3. Tool And Command Boundary

Analyst model calls use tools:

- `file_read`
- `analysis_plan`
- `analysis_request_execution`
- `knowledge_recall`
- `respond_to_user`

Legacy user/app commands remain commands:

- `plan_analysis`
- `request_execution`
- `inspect_artifact`
- `provenance_inspect`
- `validity_inspect`

The command names are reachable from Layer 4 command surfaces but are not model-callable tools.

---

## 4. Potential Failure Points For Debugging

1.  **Mode Misrouting**: A data question can stay in interaction mode if it uses no analysis keywords, file references, or transformation language. Interaction mode can still hand off to analyst mode when the model recognizes the need.
2.  **Missing Schema**: Bad or absent workspace context can lead to weak plans. The analyst should inspect relevant files before planning.
3.  **Tool Shape Errors**: `analysis_plan` must be code-free. If the model includes `code`, `code_lines`, imports, or malformed JSON, the harness repair path should request one corrected tool call.
4.  **Generated Code Rejection**: Layer 3 rejects disallowed imports, missing expected output writes, path traversal, and invalid declared inputs before approval.
5.  **Approval Stalls**: Once `ApprovalRequired` is emitted, the analyst loop stops. The next step depends on the user approval/rejection path, not another model turn.
6.  **Sticky Flow Drift**: Pending analysis flows keep later chat turns in analyst mode. If the user asks a conceptual prose-only question and no plan intent remains, the harness should release the flow.
7.  **Artifact Summary Gaps**: A successful worker run without a clear `result.txt` or artifact summary can produce a weak final explanation. Plans should always include `result.txt`.
