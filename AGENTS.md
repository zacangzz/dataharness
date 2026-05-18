# DataHarness
An LLM-powered Data Analysis, Data Science, and Reporting App. It is completely local first, CLI app specifically to support Data work using the files that are supplied directly by the user. The app is largely broken down into these Layers:
1. LLM Runtime - using llama.cpp python, it's the brain of the app
2. Execution Worker - runs python code, it's the hands and legs of the app
3. Harness - core that manges the LLM runtime, execution worker, and contains structure, orchestration, and deterministic logic, the body of the app
4. Application Layer - this where the TUI is at, is the front facing UI/UX that calls the Harness for all it's tasks
Each Layer is completely separate and independent, it is it's own standalone layer. Each layer communicates with other layers to form a functioning whole app.

## Core Rules
- Always read [@CODEMAP.md](./CODEMAP.md) before attempting to make edits, it will help you find the correct insertion point for code edits.
- After editing code, if the structure of code (specifically, the 4 relationship types: "which files import from where, which functions call what, which classes extend and to where, and which files contain which definitions") has changed, update [@CODEMAP.md](./CODEMAP.md) accordingly.
- Use `uv` for Python dependency management. Do not use `pip` or `pip3` directly.
- When adding Python packages, update `pyproject.toml`; do not manually edit `uv.lock`.
- Do not edit any Python uv envrionments directly for e.g. do not edit `.venv`.
- Remember to update `.spec` file for items to include while packaging, this can include tcss (Textual) or md file from prompts/, and also update `.toml` file for necessary packages for app run time.
- Avoid git commit and do not git commit without permission especially on main. Use a worktree to iterate separately. Once done, merge the final back into main as 1 merge (drop history)
- Specs should be light on code, be readable and clear, specifically explicit about app rules and behaviour.
- Plans should be clear and detailed and ensure that it clearly meets Spec requirements.
- As much as possible, keep logic where it belong in each app Layer and do not allow logic to cross over Layer. Shared functions should be made available between Layer.

# Instructions to follow
- When you learn something new about this project, make sure you update Lessons.md using a cheap subagent but keep it brief. For example if you run commands multiple times before learning the correct command then you should update [@Lessons.md](./@Lessons.md)
- When you encounter an issue about this project, do a quick check into [@Lessons.md](./Lessons.md) to see if the knowledge is already available.
- For any bugs you notice, it's important to resolve them or document them in [@Issues.md](./@Issues.md) to be resolved using a subagent even if it is unrelated to the current piece of work after documenting it in [@Issues.md](./@Issues.md). To update this document after applying fix with method/info, never delete old issues/fixes.
- Always ask if there are ambiguous matters to clarify. Never make any assumptions.

## Environment Setup
Run all project commands from the repo root.

```bash
uv venv .venv --python 3.13
source .venv/bin/activate
```
