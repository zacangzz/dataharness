# Fix Plan — chat_8c53c7840bf0 parse_error + gen-2 empty code_lines

Date: 2026-05-18
Trigger: chat run produced two failures:
1. `parse_error: malformed tool call: invalid tool_call json: Expecting property name enclosed in double quotes` raw=`{'name':'file_read', 'arguments': {'operation': 'inspect', 'path': 'data/employees.csv'}}`
2. `Internal validation error: step #1: code generation failed after one retry: step #1: 'code_lines' must be a non-empty list of strings`

## Root Causes (confirmed by code read, not assumed)

### Issue 1 — Python-literal tool call rejected
- `src/runtime/tool_calls.py:82` `_match_and_parse` tries only `json.loads`,
  `json.loads(strict=False)`, `json.loads(_escape_control_chars_in_strings)`.
- Model emitted a **Python dict literal** (single quotes): `{'name':...}`. Not valid JSON.
- `repair_tool_call_block` (line 131) also calls `_match_and_parse` → same failure.
- `event_from_tool_call_text` (`src/runtime/llama_cpp_runtime.py:120-127`) parse →
  repair → both fail → `ModelBehaviorError: malformed tool call`.
- Small local LLMs frequently emit single-quoted dict literals. No fallback exists.

### Issue 2 — gen-2 stop sequence collides with mandatory opening fence
- `_generate_step_code` (`src/harness/orchestrator.py:2564-2579`) sends
  `stop=["```"]`.
- `_GEN2_SYSTEM_PROMPT` (orchestrator.py:76-90) instructs:
  "Output ONLY a fenced ```python code block, nothing before or after it."
- Real llama.cpp halts at the **first** occurrence of any stop string. The first
  ` ``` ` is the **opening** fence → generation halts immediately, buffer ≈ empty.
- `extract_fenced_code("")` (tool_calls.py:108-117) → no ` ``` ` → returns `[]`.
- `normalize_plan_step_code` (analysis.py:24) raises
  `'code_lines' must be a non-empty list of strings`; retry → same →
  `assemble_plan_events` raises "code generation failed after one retry".
- Gen-2 can NEVER return code in production. The docstring claim
  "runtime stops at the closing fence" is factually wrong.
- Tests missed it because `FakeRuntime.stream` (tests/harness/test_agentic_turn.py:66)
  emits `scenario.text` verbatim and ignores `request.stop` → false confidence.
  `test_generate_step_code_returns_fenced_code_lines` even asserts the broken
  `req.stop == ["```"]`.

## Fix

### Fix 1 — tool_calls.py
Add `ast.literal_eval` fallback in `_match_and_parse` after the JSON attempts,
before raising. `ast.literal_eval` safely parses Python literals (single-quoted
strings, `True`/`False`/`None`, dicts) and rejects code/calls. On success, if it
yields a dict, return it; else fall through to the existing raise.

### Fix 2 — orchestrator.py
Remove `stop=["```"]` from the `_generate_step_code` `RuntimeRequest`. The gen-2
prompt mandates a full ```` ```python … ``` ```` block and "nothing after it", so
the model stops on EOS; `_GEN2_MAX_TOKENS=2048` bounds it; `extract_fenced_code`
already trims trailing content and tolerates a missing close fence. Update the
`_generate_step_code` docstring (remove the false "stops at the closing fence").
Update the `extract_fenced_code` docstring comment that references
`gen-2 uses stop=["```"]`.

### Fidelity fix — FakeRuntime honors `stop`
`FakeRuntime.stream` truncates `scenario.text` at the first occurrence of any
`request.stop` string (mimics llama.cpp). This reproduces Issue 2 at the
integration level and removes the false confidence. Verified low blast radius:
only two `stop=[` in orchestrator (gen-2 `["```"]`, force-plan `["</tool_call>"]`);
no `text=` scenario in test_agentic_turn.py embeds backticks or `</tool_call>`
(tool calls flow via `scenario.tool_calls`, not text). force-plan tests use
separate fakes.

## Tests (TDD: RED first)

`tests/runtime/test_tool_calls.py`:
- `test_parse_tool_call_block_accepts_python_dict_literal` — single-quoted payload
  from the real failing raw → parsed name `file_read`, arguments dict.
- `test_repair_tool_call_block_normalizes_python_dict_literal` → valid JSON out.

`tests/harness/test_agentic_turn.py`:
- Make `FakeRuntime` honor `stop` (truncate text at first stop string).
- `test_generate_step_code_returns_fenced_code_lines`: change
  `assert req.stop == ["```"]` → `assert req.stop is None`; fix docstring. With
  fake honoring stop this is RED before Fix 2, GREEN after.
- Existing `test_assemble_plan_*` exercise the full retry/finalize path; they go
  RED→GREEN with the same fix (no rewrite expected; verify).

## Verification
- `uv run pytest tests/runtime/test_tool_calls.py tests/harness/test_agentic_turn.py -q`
- Full suite: `uv run pytest -q` (baseline 670 passed).
- CODEMAP.md: no structural relationship change (no new import/call/extend/define
  edges) — confirm; update only if a new edge is introduced (not expected).
- Issues.md: append both bugs + fixes (never delete prior entries) per AGENTS.md.

## Out of scope
- Broader prompt redesign, GBNF grammar, other stop-sequence call sites.
