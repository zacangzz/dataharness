# Doctor Behaviour & Workflow

This document provides a detailed technical breakdown of the Doctor function in DataHarness, structured by architectural layers and a step-wise execution workflow.

## 1. Layer-wise Key Functions

### Layer 3: Harness (Diagnostics & Platform Actions)
*   **`Orchestrator._handle_doctor` (`src/harness/orchestrator.py`)**
    *   **Role**: Entry point for manual `/doctor` command.
    *   **Logic**: Dispatches to `DoctorRunner.run`.
*   **`DoctorRunner.run` (`src/harness/doctor_runner.py`)**
    *   **Role**: Orchestration of diagnostic phases.
    *   **Logic**: Iterates through `PHASES` (scan_sources, review_tmp, review_memory, etc.). Emits `DoctorFinding`, `DoctorActionProposed`, and `DoctorReportReady`.
*   **`Doctor.check_all_sources` (`src/harness/doctor.py`)**
    *   **Role**: Source integrity check.
    *   **Logic**: Scans `data/` folder, compares with `source_records`, and identifies drift or broken lineage via `lazy_fingerprint`.
*   **`Doctor.inventory_tmp_artifacts` (`src/harness/doctor.py`)**
    *   **Role**: Tmp management.
    *   **Logic**: Scans `artifacts/tmp/` for stale (7+ days) or orphaned files. Classifies them for `cleanup` or `keep`.
*   **`DoctorRunner._run_chat_knowledge_mining` (`src/harness/doctor_runner.py`)**
    *   **Role**: Semantic diagnostic.
    *   **Logic**: Uses Runtime/LLM to extract notes and preferences from recent chat turns.
*   **`Orchestrator.apply_doctor_actions` (`src/harness/orchestrator.py`)**
    *   **Role**: Action orchestration.
    *   **Logic**: Filters `tmp_actions` based on user `action_ids` and invokes `Doctor.apply_tmp_action`. Emits `DoctorActionsApplied`.
*   **`Doctor.apply_tmp_action` (`src/harness/doctor.py`)**
    *   **Role**: File system operations.
    *   **Logic**: Performs `unlink` for cleanup or `rename` for promotion to `memory/functions` or `artifacts/`.

### Layer 4: Application Session (Narration & Wrapping)
*   **`AppSession.handle_direct_command` (`src/app/session.py`)**
    *   **Role**: Workflow wrapper.
    *   **Logic**: Intercepts `doctor` command output. After `AppDoctorReportReady`, it triggers `_stream_doctor_narration_and_approval`.
*   **`AppSession._render_doctor_narration` (`src/app/session.py`)**
    *   **Role**: Semantic summary.
    *   **Logic**: Sends findings to the LLM (using `doctor_narrator.md`) to produce a user-friendly explanation of why actions are proposed.
*   **`AppSession.handle_doctor_approval` (`src/app/session.py`)**
    *   **Role**: Decision routing.
    *   **Logic**: Forwards user-selected action IDs to `Orchestrator.apply_doctor_actions`.

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
7.  **Narration**: `AppSession` uses the LLM to generate a natural language summary (`DoctorNarrationReady`).
8.  **Request**: `AppSession` emits `DoctorApprovalRequested`.

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
