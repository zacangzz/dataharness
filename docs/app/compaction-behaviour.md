# Compaction Behaviour & Workflow

This document provides a detailed technical breakdown of the Chat Compaction process in DataHarness, structured by architectural layers and a step-wise execution workflow.

## 1. Layer-wise Key Functions

### Layer 3: Harness (Core Logic & Persistence)
*   **`Orchestrator.run_turn` (`src/harness/orchestrator.py`)**
    *   **Role**: Detects "Token Pressure".
    *   **Logic**: Before building a runtime request, it calculates pressure via `runtime.token_pressure()`. If `pressure.over_threshold` (80%), it calls `compact_chat_history` before proceeding.
*   **`Orchestrator.compact_chat_history` (`src/harness/orchestrator.py`)**
    *   **Role**: High-level orchestration.
    *   **Logic**: Instantiates/uses `ChatCompactor`. Iterates through compaction statuses (`queued` -> `running` -> `completed`) and yields `ChatHistoryCompacted` events.
*   **`ChatCompactor.compact` (`src/harness/chat.py`)**
    *   **Role**: Transformation logic.
    *   **Logic**: Acquires `runtime_lock`. Loads `ChatRecord`. Calculates which turns to replace (all non-summary turns except the last 8). Calls `_summarize_via_runtime`.
*   **`ChatCompactor._summarize_via_runtime` (`src/harness/chat.py`)**
    *   **Role**: LLM-backed summarization.
    *   **Logic**: Sends a targeted `RuntimeRequest` to the LLM to generate 6-10 bullet points for the selected turns.
*   **`ChatStore.append_compaction` (`src/harness/chat.py`)**
    *   **Role**: Durable storage update.
    *   **Logic**: Creates a `ChatMessage` with `role="compacted_summary"`. Updates the `rec.messages` list using the slice: `[marker] + rec.messages[replaced_turn_count:]`. Updates metadata and writes to `messages.jsonl` and `metadata.json`.
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
        *   On `completed`, triggers `_rehydrate_active_chat` worker.
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
    *   If count > 8, selects `len(non_summary) - 8` turns for removal.
7.  **Summarization**: LLM generates 6-10 bullet points.

### Phase C: Persistence & Replacement (Durable Store)
8.  **Marker Creation**: New `ChatMessage(role="compacted_summary")` created.
9.  **Storage Update**: `ChatStore` performs the slice: `rec.messages = [marker] + rec.messages[replaced_turn_count:]`. 
    *   *Note*: This effectively removes the old turns (and any intervening summaries) from the head of the list.
10. **File Flush**: `metadata.json` and `messages.jsonl` are updated on disk.

### Phase D: UI Refresh (TUI)
11. **Event**: `ChatHistoryCompacted(status="completed")` arrives at the TUI.
12. **Rehydration Worker**: `DataHarnessApp` starts `_rehydrate_active_chat`.
13. **Full Clear**: `ConversationPane.remove_children()` wipes the current transcript.
14. **Re-mount**: The pane iterates through the new on-disk message list and mounts all blocks. The new `CompactionSummaryBlock` appears at the top (or after any remaining older messages).
15. **Sidebar Sync**: Sidebar "Commands" updates to `completed` (if manual).

---

## 3. Potential Failure Points for Debugging

1.  **Selection Logic**: `replaced_turn_count` calculation. If it's calculated only against non-summaries but used to slice the *full* list, it may result in incorrect offsets if older summaries already exist.
2.  **Auto-Compaction Silence**: Because auto-compaction doesn't emit `CommandStarted`, users might be confused if the chat history suddenly "flickers" (rehydrates) without warning.
3.  **Lock Deadlocks**: If a turn starts but doesn't release the `runtime_lock`, compaction will hang at `status="queued"`.
4.  **UI Flicker**: `remove_children()` followed by re-mounting can cause a visible scroll jump or flicker if the history is long.
