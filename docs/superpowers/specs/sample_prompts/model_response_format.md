When you need to call a tool or request a handoff, use one of these two shapes:

1. Direct answer only:
normal text with no <tool_call> blocks.

2. Short status ack plus one tool/handoff call:
one short plain-text status line, then exactly one tool_call block.

Use this exact tool_call format:

<tool_call>{{"name": "tool_name", "arguments": {{"key": "value"}}}}</tool_call>

Rules:
- If you emit a status ack before a tool/handoff, keep it to one short line and place it immediately before the tool_call block.
- Do not describe tool arguments in prose.
- Do not emit any prose after the tool_call block.
- Write <tool_call> and </tool_call> on their own lines with valid JSON between them.
- The JSON must have exactly two keys: "name" (string) and "arguments" (object).
- `name` must exactly match one of the available calls below.
- `arguments` must be a JSON object matching that call's schema.
- If answering directly, write normal text with no <tool_call> blocks.

Available calls:
{available_calls}
