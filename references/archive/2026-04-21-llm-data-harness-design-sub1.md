# 🧠 Sub-Spec 1: The Brain-LLM Interface (The "Nervous System")

**Date:** 2026-04-21  
**Status:** Finalized (User Approved)  
**Parent Spec:** `docs/superpowers/specs/2026-04-21-llm-data-harness-design.md`

## 1. Overview
This specification defines the technical implementation of the "Brain" (The Orchestrator). It details how a Python-based environment uses a local LLM (via `llama_cpp_python`) to transform natural language into a structured, iterative, and self-correcting analytical workflow.

The core of this design is the **Plan-Execute-Replan (PER) Loop**, which leverages a structured object-based plan and the model's ability to perform inter-task replanning based on real-world observations.

## 2. Technical Stack
* **Core Engine:** `llama_cpp_python` (with support for tool-calling and structured output).
* **Model:** Gemma 4 E4B IT (optimized for reasoning via native `<|think|>` mode and 128k context window).
* **Logic Language:** Python 3.10+.
* **Communication:** Structured JSON via the Python-to-LLM interface, preceded by internal reasoning blocks.

## 3. The Architecture: The "Brain" Components

The Brain is not a single script, but a collection of interacting Python components.

### 3.1 The `Brain` Class (The Orchestrator)
The primary entry point. It manages the high-level lifecycle:
1. **Initialization:** Sets up the LLM context and loads the `Manifest`.
2. **The Master Loop:** Manages the transitions between Planning, Execution, and Verification.
3. **User Interface:** Handles the CLI-based input and output.

### 3.2 The `Planner` Component (The "Strategist")
The component responsible for the "Plan" in the PER loop.
* **Role:** It generates the initial task list and handles all "Re-planning" logic.
* **Contextual Awareness:** It pulls the current state (schema, variable handles, and task history) from the `Manifest` to ensure the plan is grounded in the current reality.
* **Decision Point:** After every task completion (from the Worker), the `Planner` evaluates whether the current plan should continue, be modified (replanned), or be terminated.

### 3.3 The `Task-Controller` (The "Tactician")
The component that manages the lifecycle of a single task.
* **Role:** It takes a single task from the `Planner` and coordinates the interaction with the `Worker` and the `Parser`.
* **Verification Protocol:** It enforces the "Read-Before-Write" and "Verify-After-Execution" rules.
* **Logic:** It manages the specific "Code-Execute-Observe" loop for a single task, ensuring that every task-level action is validated against the user's intent and the data's reality.

### 3.4 The `Parser` (The "Interpreter")
The bridge between the LLM's text output and the Python logic.
* **Role:** It interprets the structured output (JSON or tool-call) from the LLM and converts it into the appropriate command for the `Task-Controller`.
* **Logic:** It must be robust enough to handle "noisy" outputs from the model, ensuring that every command is valid and every error is captured.

---

## 4. The "Plan-Execute-Replan" (PER) Workflow

This is the core operational loop of the system.

### Phase 1: Plan Generation (The "Strategy" Phase)
1. The Brain analyzes the user query and the current `Manifest` state to generate a plan of atomic tasks.
2. The Brain generates the initial **Structured Plan Object**.

### Phase 2: Task Execution (The "Tactical" Phase)
For each task in the plan:
1. **Pre-Execution (Read-Before-Write):** The Brain identifies the necessary context (e.g., a data schema or a specific variable) from the `Manifest` and instructs the LLM to prepare its environment.
2. The Brain instructs the LLM to generate the **Task Code** (Python) and the **Task Intent**.
3. The Brain sends the code to the **Worker**.
4. The Worker executes the code, saves the resulting artifacts (e.g., `.md`, `.parquet`), and returns results to the Brain.
5. **Post-Execution (Verification):** The Brain parses the results and performs a verification check (e.g., "Does this code-generated variable match the expected type?", "Does this output meet the task intent?").

### Phase 3: Re-evaluation (The "Review" Phase)
After every task completion (and successful verification):
1. The Brain triggers the `Planner` for a **Re-evaluation**.
2. The `Planner` analyzes the current state (the new data/manifest updates) against the original goal.
3. **Decision Logic:**
    * **If the task was successful and the goal is met:** The plan is finished.
    * **If the task was successful but the goal is NOT met:** The `Planner` generates a **Revised Plan** (the "Re-plan") and the loop returns to Phase 2.
    * **If the task failed or the verification failed:** The `Planner` generates a **Correction Plan** to address the error, and the loop returns to Phase 2.

---

## 5. Prompt Engineering Strategy

To guide the model through this loop, we use a multi-stage prompting strategy.

### 5.1 The System Prompt (The "Persona")
A foundational prompt that defines the agent's identity, rules of engagement (no hallucinations, no external tool calls outside the system), and the required output format.

### 5.2 The Planning Prompt (The "Strategist's Voice")
Used during Phase 1 and 3. It instructs the model to act as a high-level strategist, focusing on decomposing the user's request into logical, independent, and verifiable tasks. It must produce a **JSON-structured plan**.

### 5.3 The Execution Prompt (The "Tactician's Voice")
Used during Phase 2. It instructs the model to focus on the specific technical requirements of the current task, generating clean, efficient Python code.

---

## 6. Success Criteria for Sub-Spec 1
* **Reliability:** The `Brain` can successfully recover from a failed task via the "Re-plan" logic.
* **Stability:** The `Plan-to-Task` mapping remains consistent and doesn't drift into uncontrolled behavior.
* **Auditability:** Every decision made by the `Planner` is clearly recorded in the `Manifest`.

***

## 7. Summary: The Design Philosophy
The system is designed to be a **Self-Documenting Analytical Engine**. By separating the "Thinker" (Brain) from the "Doer" (Worker) and recording every action in a "Registry" (Manifest), we create a system that is inherently reliable, auditable, and scalable.
