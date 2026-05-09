# Guardrails-AI: The Reask Loop — Automated LLM Self-Correction
## How-To Guide for LLM Harness Implementation

> Source: [NeuZhou/awesome-ai-anatomy/guardrails-ai](https://github.com/NeuZhou/awesome-ai-anatomy/tree/main/guardrails-ai)

---

## Core Concept

When an LLM output fails validation, instead of returning an error to the user, the system sends the **failed output + specific error messages** back to the LLM and asks it to fix its own response. This loops until validation passes or a max attempt budget is exhausted.

```
LLM Output → Validate → FAIL → Build reask prompt (prev output + errors) → LLM → Validate → ...
                              ↑_______________________________________|
```

Three failure modes exist, each with its own reask prompt:
- **NonParseableReAsk** — output is not valid JSON at all
- **SkeletonReAsk** — JSON parses but doesn't match expected schema shape
- **FieldReAsk** — schema matches but individual field values fail validator rules

---

## Architecture Overview

```
Guard.__call__(num_reasks=1)
  ↓
Runner.__call__()
  ↓
  for index in range(num_reasks + 1):         # attempts 0..num_reasks
      iteration = step(index, ...)
        ├─ prepare()     → format messages
        ├─ call()        → LLM API call
        ├─ parse()       → JSON parse; NonParseableReAsk if broken
        ├─ validate()    → schema check → field validators → FieldReAsk per failure
        └─ introspect()  → extract all ReAsk objects from output tree

      if not do_loop(index, iteration.reasks):
          break                               # pass OR budget exhausted

      prepare_to_loop()                       # build reask prompt → repeat
  ↓
ValidationOutcome (validationPassed, validatedOutput, reask if still failing)
```

---

## Key Files

| File | Purpose |
|------|---------|
| `run/runner.py` | Main loop: `Runner.__call__`, `step`, `do_loop`, `prepare_to_loop` |
| `actions/reask.py` | ReAsk types + prompt construction: `get_reask_setup`, `get_reask_setup_for_json`, `get_reask_setup_for_string` |
| `guard.py` | Entry point: `Guard.__call__`, `Guard._exec`, `Guard._set_num_reasks` |
| `validator_service/validator_service_base.py` | `perform_correction` — maps `FailResult` → `ReAsk` or fix |
| `schema/validator.py` | `schema_validation` — detects schema mismatch → `SkeletonReAsk` |
| `classes/validation_outcome.py` | `ValidationOutcome.from_guard_history` — final result object |
| `types/on_fail.py` | `OnFailAction` enum |
| `constants.xml` | Reask prompt templates |
| `classes/execution/guard_execution_options.py` | `GuardExecutionOptions` — custom reask message override |

---

## Loop Orchestration

**File**: `run/runner.py`

```python
def __call__(self, call_log: Call, prompt_params=None) -> Call:
    for index in range(self.num_reasks + 1):   # e.g. num_reasks=2 → 3 total attempts
        iteration = self.step(
            index=index,
            output_schema=output_schema,
            call_log=call_log,
            api=api,
            messages=messages,
            prompt_params=prompt_params,
            output=output,
        )

        if not self.do_loop(index, iteration.reasks):
            break

        # Build reask prompt for next attempt
        output_schema, messages = self.prepare_to_loop(
            reasks=iteration.reasks,
            output_schema=output_schema,
            parsed_output=iteration.outputs.parsed_output,
            validated_output=call_log.validation_response,
            prompt_params=prompt_params,
        )

def do_loop(self, attempt_number: int, reasks: Sequence[ReAsk]) -> bool:
    if reasks and attempt_number < self.num_reasks:
        return True
    return False
```

**Loop math**: `num_reasks=1` → 2 total LLM calls (attempt 0 + 1 reask). `num_reasks=2` → 3 total calls. Default is `num_reasks=1`.

---

## Single Step: Parse → Validate → Introspect

**File**: `run/runner.py` — `step()` method

```python
def step(self, index, output_schema, call_log, *, api, messages, prompt_params, output):

    # 1. Call LLM (or use provided output for testing)
    llm_response = self.call(messages, api, output)
    raw_output = llm_response.output

    # 2. Parse — JSON decode
    parsed_output, parsing_error = self.parse(raw_output, output_schema)
    if parsing_error or isinstance(parsed_output, ReAsk):
        iteration.outputs.reasks.append(parsed_output)   # NonParseableReAsk
    else:
        iteration.outputs.parsed_output = parsed_output

    # 3. Validate (only if parsing succeeded)
    if isinstance(parsed_output, NonParseableReAsk):
        reasks, _ = self.introspect(parsed_output)
    else:
        validated_output = self.validate(iteration, index, parsed_output, output_schema)
        reasks, valid_output = self.introspect(validated_output)
        iteration.outputs.guarded_output = valid_output  # best-effort valid portions

    iteration.outputs.reasks = list(reasks)
    return iteration
```

**Validate** runs two sub-passes in order:
1. `schema_validation()` — checks full JSON against schema → `SkeletonReAsk` on mismatch
2. Field-level validators — each field's validators run → `FieldReAsk` per failure

---

## ReAsk Types

**File**: `actions/reask.py`

```python
class ReAsk(BaseModel):
    incorrect_value: Any          # The value that failed
    fail_results: List[FailResult] # Why it failed

class FieldReAsk(ReAsk):
    path: Optional[List[Any]]     # Dot-path to the failing field e.g. ["address", "zip"]

class SkeletonReAsk(ReAsk):
    pass  # JSON parses but doesn't match schema shape

class NonParseableReAsk(ReAsk):
    pass  # Response is not valid JSON
```

```python
class FailResult(BaseModel):
    error_message: str            # Human-readable explanation sent back to LLM
    fix_value: Any                # Static correction (used by FIX / FIX_REASK)
    outcome: str = "fail"
```

---

## Validator On-Fail Actions

**File**: `types/on_fail.py` and `validator_service/validator_service_base.py`

When a validator returns `FailResult`, `perform_correction()` decides what to do:

```python
class OnFailAction(str, Enum):
    REASK     = "reask"      # → FieldReAsk — triggers LLM re-call
    FIX       = "fix"        # → apply fix_value directly, skip LLM
    FIX_REASK = "fix_reask"  # → apply fix_value; if still fails → FieldReAsk
    FILTER    = "filter"     # → remove invalid value from output
    REFRAIN   = "refrain"    # → return None/empty for that field
    NOOP      = "noop"       # → pass through unchanged
    EXCEPTION = "exception"  # → raise immediately
    CUSTOM    = "custom"     # → call custom handler

def perform_correction(self, result: FailResult, value: Any, validator: Validator,
                       rechecked_value=None):
    action = validator.on_fail_descriptor

    if action == OnFailAction.REASK:
        return FieldReAsk(incorrectValue=value, failResults=[result])

    elif action == OnFailAction.FIX:
        return result.fix_value                     # No LLM call

    elif action == OnFailAction.FIX_REASK:
        if isinstance(rechecked_value, FailResult):
            return FieldReAsk(incorrectValue=fixed_value, failResults=[result])
        return fixed_value                          # Fix worked, done

    elif action == OnFailAction.FILTER:
        return FieldReAsk(incorrectValue=value, failResults=[result])
    # ...etc
```

Only `REASK` and `FIX_REASK` (when fix fails) produce `FieldReAsk` objects that trigger a new LLM call.

---

## Reask Prompt Construction

**File**: `actions/reask.py` — `get_reask_setup_for_json()` and `get_reask_setup_for_string()`

The reask prompt contains three things:
1. **The previous (incorrect) LLM response** — full output or only failing fields
2. **Error messages** — from `fail_results`, mapped by field path
3. **Output schema** — what the LLM should produce

### For Field-Level Failures (most common)

```python
# Prune output to only include fields that failed (not the full JSON)
reask_value = prune_obj_for_reasking(validation_response)

# Build error map: field path → error string
error_messages = {
    ".".join(str(p) for p in reask.path): "; ".join(
        f.error_message for f in reask.fail_results or []
    )
    for reask in reasks if isinstance(reask, FieldReAsk)
}
# e.g. {"age": "age must be an integer", "email": "not a valid email"}

# Schema is pruned to only the failing fields
reask_schema = get_reask_subschema(output_schema, field_reasks)
```

### For Schema Shape Mismatch (SkeletonReAsk)

```python
# Full previous response sent (field pruning doesn't apply when shape is wrong)
reask_value = parsing_response
error_messages = skeleton_reask.fail_results[0].error_message
# e.g. "JSON does not match schema:\n{...field errors...}"
```

### For Non-Parseable JSON

```python
# Raw LLM text sent back as-is
reask_value = np_reask.incorrect_value
# No error_messages — prompt just says "make it valid JSON"
```

### Final Message Structure

```python
messages = Messages([
    {"role": "system", "content": Instructions(constants["high_level_json_instructions"])},
    {"role": "user",   "content": prompt_template.format(
        previous_response=json.dumps(reask_value, indent=2),
        output_schema=stringified_schema,
        error_messages=json.dumps(error_messages),
        **prompt_params,
    )},
])
```

---

## Prompt Templates

**File**: `constants.xml`

### Field-Level Reask
```
I was given the following JSON response, which had problems due to incorrect values.

${previous_response}

Help me correct the incorrect values based on the given error messages.

Error Messages:
${error_messages}

Given below is XML that describes the information to extract...
${xml_output_schema}

ONLY return a valid JSON object...
```

### Schema Skeleton Reask
```
I was given the following JSON response, which had problems due to incorrect values.

${previous_response}

Help me correct the incorrect values based on the given error messages.

Error Messages:
${error_messages}

[includes structure example so LLM knows the expected shape]
```

### Non-Parseable JSON Reask
```
I was given the following response, which was not parseable as JSON.

${previous_response}

Help me correct this by making it valid JSON.
```

### String Output Reask
```
This was a previous response you generated:

======
${previous_response}
======

Generate a new response that corrects your old response such that the following issues are fixed
${error_messages}
```

---

## Output Merging After Reask

When reask only fixes specific fields, results are merged back into the original valid output:

**File**: `actions/reask.py` — `merge_reask_output()`

```python
def merge_reask_output(previous_response, reask_response) -> Dict:
    """Patch only the corrected fields back into the full original output."""
    merged_json = deepcopy(previous_response)

    def update_reasked_elements(pruned, reask_dict):
        if isinstance(pruned, dict):
            for key, value in pruned.items():
                if isinstance(value, FieldReAsk):
                    # Replace the FieldReAsk placeholder with LLM's corrected value
                    corrected = reask_dict.get(key)
                    update_response_by_path(merged_json, value.path, corrected)
                else:
                    update_reasked_elements(pruned[key], reask_dict[key])

    update_reasked_elements(pruned, reask_response)
    return merged_json
```

Fields that passed original validation are **never sent back to the LLM** and are **never touched** during merge.

Also, if `fix_value` is available from validators, it substitutes before reask:

```python
def sub_reasks_with_fixed_values(value: Any) -> Any:
    """Walk the output tree; replace FieldReAsk with fix_value where available."""
    if isinstance(value, FieldReAsk):
        fix = (value.fail_results[0].fix_value
               if value.fail_results else None)
        return fix if fix is not None else value  # Still a FieldReAsk if no fix
    # Recurse dicts and lists...
```

---

## Pydantic / Structured Output Difference

When using `Guard.for_pydantic()` (OpenAI function calling), `full_schema_reask=True`:

```python
# full_schema_reask=True: send entire failed JSON back (not pruned)
reask_value = validation_response

# full_schema_reask=False (default): prune to only failing fields
reask_value = prune_obj_for_reasking(validation_response)
reask_schema = get_reask_subschema(output_schema, field_reasks)  # pruned schema too
```

Use `full_schema_reask=True` when the LLM needs full context to reconstruct correctly (e.g., when fields are interdependent). Use `False` (default) to minimize token usage on reask.

---

## Fallback When Budget Exhausted

**File**: `classes/validation_outcome.py` — `ValidationOutcome.from_guard_history()`

```python
@classmethod
def from_guard_history(cls, call: Call):
    last_iteration = call.iterations.last
    last_output = last_iteration.validation_response or safe_get(list(last_iteration.reasks), 0)
    validation_passed = call.status == pass_status

    return cls(
        callId=call.id,
        rawLlmOutput=call.raw_outputs.last,       # raw text from last attempt
        validatedOutput=call.guarded_output,       # valid portions only
        reask=last_output if isinstance(last_output, ReAsk) else None,  # still-failing reask
        validationPassed=validation_passed,        # False if any reasks remain
        error=call.error,
    )
```

After max reasks: validation_passed=False, reask object returned with error details, guarded_output contains whatever valid portions were extracted. Never raises by default — caller checks `outcome.validation_passed`.

---

## Custom Reask Messages

Override default prompt templates per-call:

**File**: `classes/execution/guard_execution_options.py`

```python
class GuardExecutionOptions:
    messages: Optional[List[Dict]] = None        # Initial prompt
    reask_messages: Optional[List[Dict]] = None  # Custom reask prompt (overrides templates)
    num_reasks: Optional[int] = None             # Override budget
```

In `get_reask_setup_for_json()`:
```python
if exec_options.reask_messages:
    return reask_schema, Messages(exec_options.reask_messages)
# else fall through to template construction
```

---

## Concrete Example: Field-Level Reask

```python
# Original LLM output (age field fails validator "must be integer")
{
    "name": "John",
    "age": "not_a_number",    # FAILS
    "email": "john@example.com"  # PASSES
}

# Validator with on_fail="reask" produces:
FieldReAsk(
    path=["age"],
    incorrectValue="not_a_number",
    failResults=[FailResult(errorMessage="age must be an integer", fixValue=None)]
)

# Pruned reask prompt sent to LLM:
{
    "role": "user",
    "content": """I was given the following JSON response, which had problems due to incorrect values.

{"age": "not_a_number"}

Help me correct the incorrect values based on the given error messages.

Error Messages:
{"age": "age must be an integer"}

ONLY return a valid JSON object...
"""
}

# LLM responds:
{"age": 30}

# merge_reask_output() produces final result:
{
    "name": "John",    # from original pass
    "age": 30,         # from reask
    "email": "john@example.com"  # from original pass
}
```

---

## Minimal Implementation

```python
from dataclasses import dataclass, field
from typing import Any, List, Optional, Dict
import json

# --- Types ---

@dataclass
class FailResult:
    error_message: str
    fix_value: Any = None

@dataclass
class FieldReAsk:
    incorrect_value: Any
    fail_results: List[FailResult]
    path: List[str] = field(default_factory=list)

@dataclass
class ValidationOutcome:
    validated_output: Any
    validation_passed: bool
    reask: Optional[FieldReAsk] = None
    raw_llm_output: str = ""

# --- Validator base ---

class Validator:
    on_fail: str = "reask"   # "reask" | "fix" | "noop"

    def validate(self, value: Any) -> FailResult | None:
        raise NotImplementedError

class IsInteger(Validator):
    def validate(self, value):
        try:
            int(value)
            return None   # pass
        except (ValueError, TypeError):
            return FailResult(error_message=f"{value!r} is not an integer", fix_value=None)

class NonEmpty(Validator):
    def validate(self, value):
        if not value or (isinstance(value, str) and not value.strip()):
            return FailResult(error_message="value must not be empty", fix_value="unknown")
        return None

# --- Core reask loop ---

REASK_PROMPT_TEMPLATE = """\
I was given the following JSON response, which had problems due to incorrect values.

{previous_response}

Help me correct the incorrect values based on the given error messages.

Error Messages:
{error_messages}

Return ONLY a valid JSON object with the corrected values."""

NONPARSEABLE_PROMPT_TEMPLATE = """\
I was given the following response, which was not parseable as JSON.

{previous_response}

Help me correct this by making it valid JSON.
Return ONLY a valid JSON object."""

def run_with_reask(
    prompt: str,
    validators: Dict[str, List[Validator]],   # {field_name: [validators]}
    llm_call_fn,                               # fn(messages) -> str
    num_reasks: int = 1,
) -> ValidationOutcome:

    messages = [{"role": "user", "content": prompt}]
    raw_output = ""
    reasks: List[FieldReAsk] = []

    for attempt in range(num_reasks + 1):
        # 1. LLM call
        raw_output = llm_call_fn(messages)

        # 2. Parse
        try:
            parsed = json.loads(raw_output)
        except json.JSONDecodeError:
            if attempt < num_reasks:
                messages = [{
                    "role": "user",
                    "content": NONPARSEABLE_PROMPT_TEMPLATE.format(
                        previous_response=raw_output
                    )
                }]
                continue
            return ValidationOutcome(validated_output=None, validation_passed=False,
                                     raw_llm_output=raw_output)

        # 3. Validate each field
        reasks = []
        for field_name, field_validators in validators.items():
            value = parsed.get(field_name)
            for v in field_validators:
                result = v.validate(value)
                if result is None:
                    continue
                if v.on_fail == "reask":
                    reasks.append(FieldReAsk(
                        incorrect_value=value,
                        fail_results=[result],
                        path=[field_name],
                    ))
                elif v.on_fail == "fix" and result.fix_value is not None:
                    parsed[field_name] = result.fix_value   # fix in-place, no reask

        # 4. Check if done
        if not reasks or attempt >= num_reasks:
            break

        # 5. Build reask prompt — only failing fields
        failed_fields = {".".join(r.path): r.incorrect_value for r in reasks}
        error_messages = {".".join(r.path): r.fail_results[0].error_message for r in reasks}

        messages = [{
            "role": "user",
            "content": REASK_PROMPT_TEMPLATE.format(
                previous_response=json.dumps(failed_fields, indent=2),
                error_messages=json.dumps(error_messages, indent=2),
            )
        }]

    # 6. Merge reask results back (if last attempt returned corrections)
    if not reasks:
        return ValidationOutcome(validated_output=parsed, validation_passed=True,
                                 raw_llm_output=raw_output)

    # Budget exhausted — return best effort
    return ValidationOutcome(
        validated_output=parsed,       # valid fields kept, invalid remain as-is
        validation_passed=False,
        reask=reasks[0],
        raw_llm_output=raw_output,
    )


# --- Usage ---

def my_llm(messages):
    # Replace with actual API call
    import anthropic
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=messages,
    )
    return response.content[0].text

result = run_with_reask(
    prompt='Extract: {"name": str, "age": int, "email": str} from: "John is thirty years old, john@example.com"',
    validators={
        "age": [IsInteger()],
        "name": [NonEmpty()],
    },
    llm_call_fn=my_llm,
    num_reasks=2,
)

print(result.validation_passed)    # True/False
print(result.validated_output)     # {"name": "John", "age": 30, "email": "john@example.com"}
```

---

## DO's

- **DO** send only failing fields in the reask prompt (not the full output) — reduces tokens and focuses the LLM
- **DO** include the original incorrect value alongside the error message — LLM needs to see what it got wrong
- **DO** use `FIX` or `FIX_REASK` for deterministic corrections (regex cleanup, casing) — save LLM calls for cases that genuinely need reasoning
- **DO** prune the schema on reask to only failing fields — reduces prompt size and avoids LLM regenerating already-valid fields incorrectly
- **DO** set `num_reasks=1` as default (2 total attempts) — covers most model mistakes; diminishing returns beyond 2 reasks
- **DO** keep `error_message` in `FailResult` specific and actionable — "age must be an integer between 0 and 150" not "invalid value"
- **DO** check `validation_passed` on `ValidationOutcome` — never assume success
- **DO** allow custom `reask_messages` override — domain-specific prompts outperform generic templates
- **DO** use `merge_reask_output` pattern — never re-validate the entire output after reask, only the corrected fields

## DON'Ts

- **DON'T** send the full original JSON on field-level reask — it invites the LLM to "helpfully" change fields that were already valid
- **DON'T** use `REASK` on validators that have a deterministic fix — use `FIX` or `FIX_REASK` instead; no LLM call needed
- **DON'T** set `num_reasks` above 3 — each reask is a full LLM call; 3+ attempts signal a prompt or schema design problem
- **DON'T** conflate the reask prompt with the original task prompt — reask prompt is correction-only, not a re-statement of the task
- **DON'T** raise exceptions by default on validation failure — use `EXCEPTION` on_fail only for hard invariants; default to `REASK`
- **DON'T** skip the NonParseableReAsk path — models occasionally return markdown-wrapped JSON or explanatory text; handle it explicitly
- **DON'T** use `full_schema_reask=True` unless fields are interdependent — wastes tokens and risks the LLM touching valid fields

---

## Implementation Checklist

- [ ] `FailResult` type: `error_message`, `fix_value`
- [ ] `FieldReAsk` type: `incorrect_value`, `fail_results`, `path` (dot-path to field)
- [ ] `SkeletonReAsk` type: JSON parses but schema shape wrong
- [ ] `NonParseableReAsk` type: raw text not JSON
- [ ] `OnFailAction` enum: `REASK`, `FIX`, `FIX_REASK`, `FILTER`, `REFRAIN`, `NOOP`, `EXCEPTION`
- [ ] `perform_correction()`: maps `FailResult` + `OnFailAction` → `FieldReAsk` or fix value
- [ ] `schema_validation()`: validates parsed JSON against schema → `SkeletonReAsk` on mismatch
- [ ] Main loop: `for attempt in range(num_reasks + 1)` with `do_loop(attempt, reasks)` check
- [ ] `get_reask_setup_for_json()`: builds reask prompt with pruned failing fields + error messages
- [ ] `get_reask_setup_for_string()`: string output variant with bulleted error list
- [ ] Three prompt templates: field-level, skeleton, non-parseable
- [ ] `prune_obj_for_reasking()`: strips passing fields from output before sending to LLM
- [ ] `get_reask_subschema()`: strips passing fields from schema before sending to LLM
- [ ] `merge_reask_output()`: patches corrected fields back into original full output
- [ ] `sub_reasks_with_fixed_values()`: substitutes `fix_value` before reask where available
- [ ] `ValidationOutcome`: `validation_passed`, `validated_output`, `reask`, `raw_llm_output`
- [ ] `GuardExecutionOptions.reask_messages`: allow custom reask prompt override
- [ ] Default `num_reasks=1` (2 total attempts)
