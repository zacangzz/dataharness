# Compaction Behaviour & Workflow

This document provides a detailed technical breakdown of the Chat Compaction process in DataHarness, structured by architectural layers and a step-wise execution workflow.

## 1. Layer-wise Key Functions

### Layer 3: Harness (Core Logic & Persistence)
*   **`Orchestrator.run_turn` (`src/harness/orchestrator.py`)**
    *   **Role**: Detects "Token Pressure".
    *   **Logic**: Before building a runtime request, it calculates pressure via `runtime.token_pressure()`. If `pressure.over_threshold` (80%), it calls `compact_chat_history` before proceeding.
*   **`Orchestrator.compact_chat_history` (`src/harness/orchestrator.py`)**
    *   **Role**: High-level orchestration.
    *   **Logic**: Instantiates/uses `ChatCompactor`. Iterates through compaction statuses (`queued` -> `running` -> `completed`) and yields `ChatHistoryCompacted` events. Manual user compaction passes `recent_turns_kept=0`; token-pressure compaction keeps the compactor's recent-message window.
*   **`ChatCompactor.compact` (`src/harness/chat.py`)**
    *   **Role**: Transformation logic.
    *   **Logic**: Acquires `runtime_lock`. Loads `ChatRecord`. Calculates which turns to replace. Manual compaction replaces all non-summary messages; token-pressure compaction replaces all non-summary messages except the recent window. Existing summary markers are folded into the next summary and replaced by a single new marker.
*   **`ChatCompactor._summarize_via_runtime` (`src/harness/chat.py`)**
    *   **Role**: LLM-backed summarization.
    *   **Logic**: Loads the canonical prompt from `src/harness/prompts/compaction.md`, then sends a targeted `RuntimeRequest` to the LLM to generate a DataHarness handoff checkpoint. The prompt requires a compact continuation summary, merges old summary markers, preserves concrete workspace facts such as file paths/schemas/results/errors, and rejects transcript copying, greetings, and filler. If the runtime echoes a transcript fragment instead of summarizing, the compactor falls back to deterministic summary text.
*   **`ChatCompactor._fallback_summary` (`src/harness/chat.py`)**
    *   **Role**: Deterministic backup summarization.
    *   **Logic**: Emits the same DataHarness handoff structure as the runtime prompt: current user goal, progress/facts, data references, constraints/preferences, and next steps. It strips role prefixes and previous summary headings, filters trivial greetings/test messages, and extracts common workspace file references.
*   **`ChatStore.append_compaction` (`src/harness/chat.py`)**
    *   **Role**: Durable storage update.
    *   **Logic**: Creates a `ChatMessage` with `role="compacted_summary"`. Preserves only non-summary messages after the replaced range, then writes `[marker] + preserved_non_summary`. Updates metadata and writes to `messages.jsonl` and `metadata.json`.
*   **`RuntimeRequestBuilder.build_messages` (`src/harness/chat.py`)**
    *   **Role**: Context assembly.
    *   **Logic**: Aggregates all `compacted_summary` messages from history. Places them at the start of the context window (system/first-user block) subject to a 15% budget cap.

### Layer 4: Application Session (Facade & Mapping)
*   **`AppSession.compact_chat_history` (`src/app/session.py`)**
    *   **Role**: Facade.
    *   **Logic**: Forwards call to Layer 3 `Orchestrator` and wraps returned `HarnessEvent`s as `AppEvent`s using `to_app_event`.

### Layer 4a: TUI (Presentation & State Management)
*   **`DataHarnessApp._handle_chat_history_compacted` (`src/app/tui/app.py`)**
    *   **Role**: UI Event Handler.
    *   **Logic**: 
        *   Ignores `queued` and `running` statuses (quiet compaction).
        *   On `completed`, triggers `_rehydrate_active_chat` and `_refresh_sidebar_resources` workers.
        *   On `failed`, appends a failure block to the transcript.
*   **`DataHarnessApp._handle_command_started/completed` (`src/app/tui/app.py`)**
    *   **Role**: Manual Status Communication.
    *   **Logic**: When triggered via `/compact`, these handlers update the **Sidebar's "Commands" section** to show active/completed compaction status.
*   **`ConversationPane.rehydrate_from_record` (`src/app/tui/widgets.py`)**
    *   **Role**: History Replacement.
    *   **Logic**: **Entirely replaces** the UI transcript. It calls `self.remove_children()` to clear all existing message widgets and then iterates through the updated `ChatRecord.messages` to mount fresh `UserMessage`, `AssistantMessage`, and `CompactionSummaryBlock` widgets.
*   **`WorkspaceBar` and `Sidebar.update_status`**
    *   **Role**: Global State.
    *   **Logic**: These widgets do NOT update specifically for compaction events. They reflect the `RunState` and `ActiveMode`, which remain unchanged during a background compaction.

---

## 2. Step-wise Workflow Logic

### Phase A: Trigger & Communication
1.  **Manual**: User types `/compact`. 
    *   `AppCommandStarted` -> Sidebar "Commands" shows `compact`.
2.  **Automatic**: `Orchestrator.run_turn` detects >80% pressure.
    *   Quiet trigger; no Command events emitted.

### Phase B: Processing (Harness)
3.  **Harness Check**: `Orchestrator` verifies the chat exists.
4.  **Compactor Start**: `ChatCompactor.compact` yields `ChatHistoryCompacted(status="queued")`.
5.  **Lock Acquisition**: Waits for `runtime_lock`. Once acquired, yields `status="running"`.
6.  **Selection**: 
    *   Counts non-summary messages.
    *   Manual `/compact`: selects all non-summary messages.
    *   Token-pressure compact: selects all non-summary messages except the recent-message window.
7.  **Summarization**: LLM generates a DataHarness handoff checkpoint. The summary should preserve current user goal, durable progress/facts, workspace file references, constraints/preferences, and next steps. Transcript-echo output falls back to deterministic summary text with the same structure.

### Phase C: Persistence & Replacement (Durable Store)
8.  **Marker Creation**: New `ChatMessage(role="compacted_summary")` created.
9.  **Storage Update**: `ChatStore` writes `rec.messages = [marker] + preserved_non_summary`.
    *   *Note*: Old summary markers are collapsed into the new marker instead of accumulating.
10. **File Flush**: `metadata.json` and `messages.jsonl` are updated on disk.

### Phase D: UI Refresh (TUI)
11. **Event**: `ChatHistoryCompacted(status="completed")` arrives at the TUI.
12. **Rehydration Worker**: `DataHarnessApp` starts `_rehydrate_active_chat`.
13. **Full Clear**: `ConversationPane.remove_children()` wipes the current transcript.
14. **Re-mount**: The pane iterates through the new on-disk message list and mounts all blocks. The new `CompactionSummaryBlock` appears at the top (or after any remaining older messages).
15. **Sidebar Sync**: Sidebar "Commands" updates to `completed` (if manual), and the chat list refreshes so the message count reflects the compacted record.

---

## 3. Potential Failure Points for Debugging

1.  **Selection Logic**: `replaced_turn_count` calculation. It is based on replaced non-summary messages; storage must preserve non-summary messages after that range, not slice the full message list by the same count.
2.  **Summary Quality**: A compacted summary that contains role prefixes, "Prior summary context", greetings, or transcript-copy wording means the runtime prompt/fallback contract has regressed.
3.  **Auto-Compaction Silence**: Because auto-compaction doesn't emit `CommandStarted`, users might be confused if the chat history suddenly "flickers" (rehydrates) without warning.
4.  **Lock Deadlocks**: If a turn starts but doesn't release the `runtime_lock`, compaction will hang at `status="queued"`.
5.  **UI Flicker**: `remove_children()` followed by re-mounting can cause a visible scroll jump or flicker if the history is long.
