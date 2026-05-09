# LLM Harness Must-Haves: Principles for a Data Analysis Agent

This document distills the core, non-negotiable principles from research into three high-performance LLM architectures and integrates them with the fundamental engineering of agentic systems.

---

## 1. The Fundamental Distinction: Brain vs. System

The most critical realization in agent design is that **Prompt Engineering is not Agent Design.** 

While prompt engineering optimizes the "Brain," a true agent requires a complete "Body" and "Nervous System" to be useful in the real world.

| Component | Technical Name | Role in the Agent |
| :--- | :--- | :--- |
| **The Brain** | **Prompt Engineering** | The internal reasoning, planning, and logic. It processes the input. |
| **The Body** | **Tool Integration** | The ability to interact with the world (e.g., SQL, Python, File I/O). |
| **The Nervous System** | **The Control Loop** | The software loop that manages execution, catches errors, and drives the "Brain" to the next step. |
| **The Memory** | **State Management** | The persistent storage of context, schema, and intermediate results. |

**An Agent is a software system that uses an LLM as its central reasoning engine to interact with an environment.**

---

## 2. The Core "Non-Negotiable" Worldview (Research Synthesis)

The research identifies three divergent but complementary methodologies. For a data analysis agent, these are the stages of a successful task lifecycle.

| Philosophy | Core Concept | Application to Data Analysis |
| :--- | :--- | :--- |
| **Anthropic (Team-Based)** | **Specialization:** A team of specialized agents. | Use for the **Discovery/Planning Phase**. A "Data Architect" agent defines the schema, and a "Statistician" agent plans the analysis. |
| **OpenAI (Software-First)** | **Monolithic/One-Task:** One thing per loop. | Use for the **Execution/Refinement Phase**. Instead of "analyze everything," the agent performs: 1. Load data $\to$ 2. Clean data $\to$ 3. Calculate metric $\to$ 4. Find anomalies. |
| **Ralph (Monolithic/Human)** | **Read-First/Verifiable:** Read, then act, then verify. | Use for the **Verification/Reporting Phase**. Ensure the agent *reads* the data/results before making a claim, and the human can verify the logic. |

---

## 3. Best Practices for the Data Analysis Chatbot

To create an agentic chatbot capable of answering complex queries like *"analyst turnover rate for the last 12 months and find anomalies"*, the following engineering practices are mandatory.

### A. The "Single-Task" Execution Pattern (The "One Thing" Rule)
*   **The Problem:** Asking an LLM to "analyze turnover and find anomalies" in one prompt leads to hallucinations and messy code.
*   **The Must-Have:** The harness must break the user's prompt into a sequence of atomic, verifiable tasks.
    *   **Task 1:** Fetch/Load the specific data subset.
    *   **Task 2:** Calculate the turnover metric.
    *   **Task 3:** Run an anomaly detection algorithm.
*   **Benefit:** If the anomaly detection fails, you know exactly which step failed. You can "fix" the error in the loop without re-running the whole analysis.

### B. The "Read-Before-Write" Requirement (Contextual Integrity)
*   **The Problem:** LLMs often "hallucinate" data or assume a structure that doesn't exist.
*   **The Must-Have:** Before the agent writes a single line of analysis or summary, it **must** read the schema, the data sample, and the previous step's output.
    *   **Action:** `read_data_schema() -> plan_query() -> execute_query() -> read_result_sample() -> verify_result()`
*   **Benefit:** Ensures the agent's "mental model" of the data matches the actual file on disk.

### C. Tool-Centric Design (Not Prompt-Centric)
*   **The Problem:** Trying to do complex math inside a prompt is unreliable.
*   **The Must-Have:** The agent should not "calculate" in the prompt. It should **use tools** to calculate.
    *   **Bad:** "The turnover rate is 15% because..." (LLM guessing)
    *   **Good:** The agent writes a Python script to calculate the rate, executes it, and then *reads* the result.
*   **Benefit:** Precision and auditability. The "truth" comes from the tool's output, not the LLM's prediction.

### D. Metadata & State Retention
*   **The Problem:** Losing context of what was analyzed in previous turns.
*   **The Must-Have:** The harness must maintain a structured "State" (Working Memory) that tracks:
    *   **Data Schema:** What columns exist?
    *   **Applied Filters:** What data was excluded?
    *   **Calculated Metrics:** What are the current results?

---

## 4. Summary: The "Ideal" Workflow for a Data Query

When a user asks: *"Calculate turnover rate and find anomalies."*

1.  **Planning (Anthropic-style):** An agent analyzes the query and identifies the necessary tools (e.g., `sql_query`, `python_executor`) and the required steps.
2.  **Execution (OpenAI-style):**
    *   **Step 1:** Agent calls `sql_query` to get the last 12 months of data.
    *   **Step 2:** Agent calls `python_executor` to calculate the turnover rate.
    *   **Step 3:** Agent calls `python_executor` to run an anomaly detection script.
3.  **Verification (Ralph-style):** The agent reads the results of the calculations, compares them to the original data context, and presents a human-verifiable summary.

## 5. Conclusion
A successful LLM harness for data analysis is not a single "smart" prompt. It is a **structured software loop** that breaks complex queries into small, measurable, and tool-driven steps, with a heavy emphasis on **reading context before acting** and **verifying results after calculation.**
