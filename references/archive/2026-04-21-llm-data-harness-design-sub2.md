# 🛠️ Sub-Spec 2: The Worker-Protocol & Sandbox (The "Body")

**Date:** 2026-04-21  
**Status:** Finalized (User Approved)  
**Parent Spec:** `docs/superpowers/specs/2026-04-21-llm-data-harness-design.md`

## 1. Overview
This specification defines the technical implementation of the **Worker (The "Body")** and the **Bridge (The IPC Protocol)**. 

In this "Session-Persistent" model, a single Worker process is spawned at the start of a user session and remains active until the session ends. The Brain (Orchestrator) communicates with this Worker via a robust Inter-ent-Process Communication (IPC) protocol to execute code, manage data, and report results.

The primary challenge of this design is managing the **"State Leakage"** that occurs in a persistent Python environment.

## 2. Technical Stack
* **Primary Language:** Python 3.10+
* **Communication Protocol:** Structured JSON-RPC (Remote Procedure Call) over a local communication channel (e.g., Unix Sockets or Named Pipes).
* **Runtime Environment:** A single, isolated Python environment (the Worker process).

## 3. The Bridge: IPC Protocol (The "Language")

The Brain and the Worker communicate using a strictly typed **JSON-RPC-based protocol**. Every message sent between the two must be a valid JSON object.

### 3.1 Brain $\to$ Worker (The "Command")
The Brain sends a `command` object to the Worker.
* **`method`:** The type of request (e.g., `execute_code`, `load_data`, `get_status`).
* **`params`:** The payload (e.g., the Python code string, file paths, or variable names).
* **`request_id`:** A unique ID used to match the response to the request.

### 3.2 Worker $\to$ Brain (The "Response")
The Worker returns a `response` object.
* **`request_id`:** Matches the incoming `request_id`.
* **Result/Error:** Either a `result` (the data/message) or an `error` (the error type and message).

---

## 4. The Lifecycle: Process Management

### 4.1 Startup & Session Initialization (The Handshake)
The Brain spawns the Worker process and initiates the handshake.

**The Handshake Sequence:**
1. **Brain $\to$ Worker:** `{"method": "handshake_init", "params": {"session_id": "UUID", "version": "1.0"}, "request_id": "REQ-001"}`
2. **Worker $\to$ Brain:** `{"request_id": "REQ-001", "result": {"status": "READY", "capabilities": ["pandas", "numpy", "plotting"], "env_info": "..."}, "error": null}`

**Verification of Success:** The Brain only proceeds to the first task once it receives the `READY` status and validates the `capabilities` against its own requirements. Once the handshake is complete, the Worker is in its active, waiting state.

### 4.2 Task Execution (The "Work" Cycle & Sandbox)
The Brain sends an `execute_code` command to the Worker.

**The Sandbox Constraints:**
* **Execution Context:** All code is executed within a dedicated, transient Python environment using `exec(code, globals_dict, locals_dict)`.
* **Restricted Globals:** The `globals_dict` is initialized with only the necessary libraries and the `manifest_handle`. It does *not* contain access to `os`, `sys`, or `subprocess` unless explicitly permitted by a specific task-level permission.
* **Filesystem Jail:** The Worker is restricted to a "Jail" directory (`artifacts/`). Any attempt to write or read outside this directory will be caught and reported as a `Security Error`.
* **Resource Limits:** The Worker implements soft limits on memory usage and execution time.

**The Execution Loop:**
1. The Brain sends the `execute_code` command.
2. The Worker executes the code within the sandbox.
3. The Worker captures the standard output (stdout/stderr) and any generated files.
4. The Worker returns the result (e.g., a success message or an error) via the response.

### 4.3 Error Handling & Crash Recovery
* **Soft Errors:** If the Python code fails (e.g., a `ValueError`), the Worker captures the traceback, sends it to the Brain, and stays alive for the next task.
* **Hard Crashes:** If the Worker process crashes (e.g., a Segmentation Fault), the **Brain** must detect the loss of the process, log the failure, and perform a **"Re-initialization"** (re-spawning the worker and re-loading the state from the Manifest).

---

## 5. The Challenge: State Leakage & Isolation

Since the Worker is a persistent process, variables created in Task 1 (e.g., `df_attrition = ...`) will remain in the Worker's memory during Task 2.

### 5.1 The "Clean Scope" Strategy
To minimize leakage, the Worker will wrap every `execute_code` call in a **Transient Scope**.
* Every task is executed within its own `exec(code, globals_dict, locals_dict)` call.
* The `globals_dict` is partially shared (to allow for persistent objects like the database connection), but the `locals_dict` is cleared after every task.
* **The Sandbox Override:** If a task requires elevated privileges (e.g., specific file access), the Brain can temporarily adjust the `globals_dict` for that specific task.

### 5.2 The "Manifest-Driven" State
The **Brain** (not the Worker) is the master of the state. 
* The Worker must not assume it can "remember" objects by name unless they are explicitly registered in the `.json` manifest.
* If the Brain needs to use a variable created in a previous task, it must use the **Handle** provided by the manifest (e.g., `df_attrition_handle`).

---

## 6. Success Criteria for Sub-Spec 2
* **Reliability:** The Worker can survive a Python-level error without crashing the entire session.
* **Control:** The Brain can send commands and receive structured, predictable responses.
* **Isolation:** The "Clean Scope" strategy prevents most "dirty" variable leakage between tasks.

***

## 7. Summary: The Design Philosophy
This is a "Session-Persistent" architecture designed for performance. By using a structured JSON-RPC protocol and a "Clean Scope" execution strategy, we can enjoy the speed of a long-running process while maintaining the isolation and reliability of a task-based system.
