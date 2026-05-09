# Engine And Agents Model Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the smolagents-era model adapter stack with an Agents SDK-compatible engine layer that still runs fully local on llama.cpp.

**Architecture:** First shrink the current llama.cpp wrapper into a framework-agnostic `src/core/engine/llm.py`. Then add an Agents SDK wrapper in `src/core/engine/agents_model.py` plus `Compaction` in `src/core/engine/compaction.py`, keeping streaming, telemetry, and offline guarantees intact.

**Tech Stack:** Python 3.12, `llama_cpp`, `openai-agents`, `pytest`, local telemetry JSONL, existing prompt files under `src/core/prompts/`

---

### Task 1: Move The Raw Engine Out Of `src/core/model.py`

**Files:**
- Create: `src/core/engine/__init__.py`
- Create: `src/core/engine/llm.py`
- Test: `tests/core/engine/test_llm.py`
- Delete: `src/core/model.py`
- Delete: `tests/core/test_model.py`

- [ ] **Step 1: Write the failing engine-shape tests**

```python
from src.core.engine.llm import EngineConfig, LlmModel


def test_llm_model_has_no_tool_call_api(monkeypatch, tmp_path):
    model = LlmModel(tmp_path / "model.gguf", EngineConfig())
    assert not hasattr(model, "chat_with_tools")


def test_engine_stream_returns_plain_chunks(fake_llama_model):
    chunks = list(
        fake_llama_model.stream(
            [{"role": "user", "content": "hello"}],
            temperature=0.1,
            top_p=0.9,
            max_new_tokens=32,
        )
    )
    assert chunks[-1].finish_reason == "stop"
    assert all(hasattr(chunk, "text") for chunk in chunks)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/engine/test_llm.py -q`
Expected: FAIL because `src/core/engine/llm.py` does not exist yet.

- [ ] **Step 3: Write the minimal engine module**

```python
@dataclass
class CompletionResult:
    text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None


@dataclass
class StreamChunk:
    text: str
    finish_reason: str | None = None


class LlmModel:
    def completion(self, messages: list[dict], *, temperature: float, top_p: float,
                   max_new_tokens: int, stop: list[str] | None = None) -> CompletionResult:
        response = self._llama.create_chat_completion(
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_new_tokens,
            stop=stop,
        )
        return CompletionResult(
            text=response["choices"][0]["message"]["content"],
            prompt_tokens=response.get("usage", {}).get("prompt_tokens"),
            completion_tokens=response.get("usage", {}).get("completion_tokens"),
            finish_reason=response["choices"][0].get("finish_reason"),
        )

    def stream(self, messages: list[dict], *, temperature: float, top_p: float,
               max_new_tokens: int, stop: list[str] | None = None) -> Iterator[StreamChunk]:
        for chunk in self._llama.create_chat_completion(
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_new_tokens,
            stop=stop,
            stream=True,
        ):
            yield StreamChunk(
                text=chunk["choices"][0].get("delta", {}).get("content", ""),
                finish_reason=chunk["choices"][0].get("finish_reason"),
            )
```

- [ ] **Step 4: Port the current RAM-tier sizing and telemetry intact**

```python
def _auto_ctx_from_ram_gb(total_gb: float) -> int:
    if total_gb <= 8:
        return 4096
    if total_gb <= 16:
        return 8192
    if total_gb <= 32:
        return 16384
    return 32768
```

- [ ] **Step 5: Run tests to verify the engine move passes**

Run: `uv run pytest tests/core/engine/test_llm.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/core/engine/__init__.py src/core/engine/llm.py tests/core/engine/test_llm.py
git rm src/core/model.py tests/core/test_model.py
git commit -m "refactor: move raw llama engine into core engine package"
```

### Task 2: Move Memory Compaction Into `src/core/engine/compaction.py`

**Files:**
- Create: `src/core/engine/compaction.py`
- Create: `tests/core/engine/test_compaction.py`
- Modify: `src/core/prompts/compaction_summarize.md`
- Delete: `src/core/agents/memory_manager.py`
- Delete: `tests/core/agents/test_memory_manager.py`

- [ ] **Step 1: Write the failing compaction regression tests**

```python
from src.core.engine.compaction import Compaction


def test_compaction_keeps_system_and_recent_messages(fake_llm):
    compaction = Compaction(llm=fake_llm, n_ctx=8192)
    compacted, changed = compaction.maybe_compact(make_long_message_list())
    assert changed is True
    assert compacted[0]["role"] == "system"
    assert compacted[-1]["role"] in {"assistant", "tool"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/engine/test_compaction.py -q`
Expected: FAIL because `Compaction` has not been moved yet.

- [ ] **Step 3: Move `MemoryManager` logic unchanged except for names**

```python
class Compaction:
    def __init__(self, llm: LlmModel, n_ctx: int, threshold: float = 0.7) -> None:
        self._llm = llm
        self._n_ctx = n_ctx
        self._threshold = threshold

    def maybe_compact(self, messages: list[dict]) -> tuple[list[dict], bool]:
        if not self._should_compact(messages):
            return messages, False
        summary = self._summarize_oldest_half(messages)
        return self._replace_middle_with_memory(messages, summary), True
```

- [ ] **Step 4: Rename the prompt file and keep content identical**

```python
_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "compaction_summarize.md"
```

- [ ] **Step 5: Run compaction tests**

Run: `uv run pytest tests/core/engine/test_compaction.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/core/engine/compaction.py src/core/prompts/compaction_summarize.md tests/core/engine/test_compaction.py
git rm src/core/agents/memory_manager.py tests/core/agents/test_memory_manager.py
git commit -m "refactor: move context compaction into engine layer"
```

### Task 3: Add The Agents SDK Model Wrapper

**Files:**
- Create: `src/core/engine/agents_model.py`
- Create: `tests/core/engine/conftest.py`
- Create: `tests/core/engine/test_agents_model.py`
- Delete: `src/core/agents/model_adapter.py`

- [ ] **Step 1: Write the failing wrapper tests**

```python
from src.core.engine.agents_model import LlamaCppAgentsModel, ModelConfig


def test_agents_model_strips_reasoning_from_final_text(fake_engine):
    model = LlamaCppAgentsModel(fake_engine, ModelConfig(), agent_label="triage")
    response = model._response_from_text("<|channel>thought\\nplan\\n<channel|>\\nHello")
    assert response.output_text == "Hello"


def test_agents_model_emits_multiple_stream_events(fake_engine):
    model = LlamaCppAgentsModel(fake_engine, ModelConfig(), agent_label="triage")
    events = list(model.stream_response(messages=[{"role": "user", "content": "hi"}]))
    assert len(events) > 1
    assert events[-1].finish_reason == "stop"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/engine/test_agents_model.py -q`
Expected: FAIL because the new wrapper does not exist yet.

- [ ] **Step 3: Write the wrapper with explicit finish-reason mapping**

```python
class LlamaCppAgentsModel(Model):
    def __init__(self, llm: LlmModel, config: ModelConfig, agent_label: str,
                 n_ctx: int, compaction: Compaction | None = None) -> None:
        self._llm = llm
        self._config = config
        self._agent_label = agent_label
        self._n_ctx = n_ctx
        self._compaction = compaction

    async def response(self, input, model_settings, tools, handoffs):
        messages = self._build_messages(input, tools, handoffs)
        raw = self._llm.completion(messages, temperature=self._config.temperature,
                                   top_p=self._config.top_p, max_new_tokens=self._config.max_new_tokens,
                                   stop=self._config.stop)
        reasoning, output_text = _extract_reasoning(raw.text)
        return ModelResponse(
            output_text=output_text,
            finish_reason=raw.finish_reason or "stop",
            usage={"input_tokens": raw.prompt_tokens, "output_tokens": raw.completion_tokens},
            reasoning=reasoning,
        )

    async def stream_response(self, input, model_settings, tools, handoffs):
        messages = self._build_messages(input, tools, handoffs)
        for chunk in self._llm.stream(messages, temperature=self._config.temperature,
                                      top_p=self._config.top_p, max_new_tokens=self._config.max_new_tokens,
                                      stop=self._config.stop):
            yield self._stream_event_from_chunk(chunk)
```

- [ ] **Step 4: Preserve telemetry and reasoning-summary extraction**

```python
def _extract_reasoning(text: str) -> tuple[list[str], str]:
    thoughts: list[str] = []
    stripped = _THOUGHT_BLOCK_RE.sub(lambda m: thoughts.append(m.group(0)) or "", text).strip()
    return thoughts, stripped
```

- [ ] **Step 5: Run wrapper tests**

Run: `uv run pytest tests/core/engine/test_agents_model.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/core/engine/agents_model.py tests/core/engine/conftest.py tests/core/engine/test_agents_model.py
git rm src/core/agents/model_adapter.py
git commit -m "feat: add agents sdk llama.cpp model wrapper"
```

### Task 4: Rewire Imports And Remove Smolagents Adapter Usage

**Files:**
- Modify: `src/core/__init__.py`
- Modify: `tests/core/agents/conftest.py`
- Test: `tests/core/engine/test_llm.py`
- Test: `tests/core/engine/test_compaction.py`
- Test: `tests/core/engine/test_agents_model.py`

- [ ] **Step 1: Update imports to the new engine package**

```python
from src.core.engine.llm import EngineConfig, LlmModel
from src.core.engine.compaction import Compaction
from src.core.engine.agents_model import LlamaCppAgentsModel, ModelConfig
```

- [ ] **Step 2: Remove stale smolagents test fixtures**

```python
# tests/core/agents/conftest.py
pytest_plugins = ["tests.core.engine.conftest"]
```

- [ ] **Step 3: Run the new fast test slice**

Run: `uv run pytest tests/core/engine/test_llm.py tests/core/engine/test_compaction.py tests/core/engine/test_agents_model.py -q`
Expected: PASS

- [ ] **Step 4: Grep for retired adapter references**

Run: `rg -n "model_adapter|MemoryManager|smolagents" src tests`
Expected: only known remaining migration references outside the retired adapter path.

- [ ] **Step 5: Commit**

```bash
git add src/core/__init__.py tests/core/agents/conftest.py
git commit -m "chore: point core imports at new engine foundation"
```
