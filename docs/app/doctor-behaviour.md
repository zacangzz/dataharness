# Doctor Behaviour & Workflow

This document provides a detailed technical breakdown of the Doctor function in DataHarness, structured by architectural layers and a step-wise execution workflow.

> **Off-canonical addition (flagged for future review).** The canonical spec
> (`docs/superpowers/specs/2026-05-11-dataharness-comprehensive-app-spec.md`,
> §7.16 / §15) requires a recorded tmp-review approval gate but does not
> mandate an LLM doctor narration. The current implementation adds an LLM
> narration step and the `DoctorNarrationReady` / `DoctorApprovalRequested`
> event pair on top of that gate. These are now emitted from the Layer 3
> `DoctorRunner` (`src/harness/services/doctor.py`:
> `_collect_tmp_actions` → `_render_narration` / `_fallback_narration` →
> `_narrate_and_request_approval`, with findings passed in as a parameter,
> not held as instance state), NOT from Layer 4 `AppSession`. This is an
> extension over the spec's required behavior and is flagged for future
> spec/code reconciliation; the §7.16 tmp-review approval gate remains the
> authoritative requirement.

## 1. Layer-wise Key Functions

### Layer 3: Harness (Diagnostics & Platform Actions)
*   **`Orchestrator._handle_doctor` (`src/harness/orchestrator.py`)**
    *   **Role**: Entry point for manual `/doctor` command.
    *   **Logic**: Dispatches to `DoctorRunner.run`.
*   **`DoctorRunner.run` (`src/harness/services/doctor.py`)**
    *   **Role**: Orchestration of diagnostic phases.
    *   **Logic**: Iterates through `PHASES` (scan_sources, review_tmp, review_memory, etc.). Emits `DoctorFinding`, `DoctorActionProposed`, and `DoctorReportReady`.
*   **`Doctor.check_all_sources` (`src/harness/services/doctor.py`)**
    *   **Role**: Source integrity check.
    *   **Logic**: Scans `data/` folder, compares with `source_records`, and identifies drift or broken lineage via `lazy_fingerprint`.
*   **`Doctor.inventory_tmp_artifacts` (`src/harness/services/doctor.py`)**
    *   **Role**: Tmp management.
    *   **Logic**: Scans `artifacts/tmp/` for stale (7+ days) or orphaned files. Classifies them for `cleanup` or `keep`.
*   **`DoctorRunner._run_chat_knowledge_mining` (`src/harness/services/doctor.py`)**
    *   **Role**: Semantic diagnostic.
    *   **Logic**: Uses Runtime/LLM to extract notes and preferences from recent chat turns.
*   **`Orchestrator.apply_doctor_actions` (`src/harness/orchestrator.py`)**
    *   **Role**: Action orchestration.
    *   **Logic**: Filters `tmp_actions` based on user `action_ids` and invokes `Doctor.apply_tmp_action`. Emits `DoctorActionsApplied`.
*   **`Doctor.apply_tmp_action` (`src/harness/services/doctor.py`)**
    *   **Role**: File system operations.
    *   **Logic**: Performs `unlink` for cleanup or `rename` for promotion to `memory/functions` or `artifacts/`.

*   **`DoctorRunner._narrate_and_request_approval` (`src/harness/services/doctor.py`)**
    *   **Role**: Narration & approval-request emission (off-canonical, see note above).
    *   **Logic**: Collects proposed tmp actions via `_collect_tmp_actions`, renders an LLM narration via `_render_narration` (falls back to `_fallback_narration` when no runtime / on error, using `doctor_narrator.md`), then emits `DoctorNarrationReady` and `DoctorApprovalRequested`. Findings are passed in as a parameter, not held as instance state.

### Layer 4: Application Session (Pure Passthrough)
*   **`AppSession.handle_direct_command` (`src/app/session.py`)**
    *   **Role**: Passthrough.
    *   **Logic**: Forwards the `doctor` command to `Orchestrator.handle_direct_command` and maps emitted harness events to app events. It no longer renders narration or wraps the doctor flow.
*   **`AppSession.handle_doctor_approval` (`src/app/session.py`)**
    *   **Role**: Decision routing.
    *   **Logic**: Forwards user-selected action IDs to `Orchestrator.apply_doctor_actions` and maps emitted events.

### Layer 4a: TUI (Presentation & Review)
*   **`DataHarnessApp._handle_doctor_report_ready` (`src/app/tui/app.py`)**
    *   **Role**: Report handling.
    *   **Logic**: Updates sidebar with summary counts and recommendations.
*   **`DataHarnessApp._handle_doctor_narration_ready` (`src/app/tui/app.py`)**
    *   **Role**: Transcript display.
    *   **Logic**: Appends the LLM-generated narration to the `ConversationPane`.
*   **`ApprovalBanner.show_doctor_review` (`src/app/tui/widgets.py`)**
    *   **Role**: Interactive checklist.
    *   **Logic**: Renders a list of proposed actions with checkboxes. Allows "Accept All", "Reject All", or "Apply Selected".
*   **`DataHarnessApp._on_doctor_apply_selected` (`src/app/tui/app.py`)**
    *   **Role**: Action trigger.
    *   **Logic**: Collects IDs of checked actions and calls `session.handle_doctor_approval`.

---

## 2. Step-wise Workflow Logic

### Phase A: Initiation & Scanning
1.  **Trigger**: User types `/doctor`.
2.  **Start**: `Orchestrator` emits `CommandStarted` and `DoctorStarted`.
3.  **Deterministic Scan**: `DoctorRunner` executes `check_all_sources` (drift detection) and `inventory_tmp_artifacts` (orphaned files).
4.  **Semantic Scan**: (If `mode="full"`) `DoctorRunner` mining chat memory and assessing saved scripts via the Runtime.

### Phase B: Reporting & Narration
5.  **Findings**: Multiple `DoctorFinding` and `DoctorActionProposed` events are yielded and saved to the DB.
6.  **Report**: `DoctorReportReady` is emitted, carrying the final summaries and action records.
7.  **Narration**: `DoctorRunner` (Layer 3) uses the LLM to generate a natural language summary (`DoctorNarrationReady`); deterministic fallback on no runtime / error.
8.  **Request**: `DoctorRunner` emits `DoctorApprovalRequested`.

### Phase C: User Review (TUI)
9.  **Display**: The TUI shows findings in the sidebar and the narration in the chat transcript.
10. **Review UI**: `ApprovalBanner` appears with the checkbox list of proposed actions.
11. **Selection**: User reviews findings and checks/unchecks specific actions.
12. **Submit**: User clicks "Apply Selected".

### Phase D: Execution
13. **Application**: `Orchestrator.apply_doctor_actions` iterates through selected IDs.
14. **Operation**: `Doctor.apply_tmp_action` physically moves or deletes files.
15. **Finalization**: `DoctorActionsApplied` is yielded, and the UI clears the approval banner.

---

## 3. Potential Failure Points for Debugging

1.  **Missing File Detection**: `check_all_sources` iterates *existing* files. It will not find a deleted source file unless it is specifically prompted to compare against the full `source_records` table.
2.  **Active Run Conflicts**: Tmp cleanup for a specific run ID is blocked if the Orchestrator thinks that run is still active. If a run crashed, its artifacts might be "stuck" until the next session.
3.  **Narration Failure**: If the LLM is overloaded or the prompt is malformed, narration falls back to a deterministic bulleted list, which might be less clear to the user.
4.  **Promotion Conflicts**: If `promote` is attempted but a file already exists at the destination (e.g., `memory/functions/step.py`), the application might fail or overwrite without warning.
5.  **Stale Action IDs**: If the user waits a long time before clicking "Apply", the underlying files might have changed, causing `apply_tmp_action` to fail.
