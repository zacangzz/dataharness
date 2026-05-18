# MLC Layer 1 Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current llama.cpp Layer 1 runtime with MLC LLM for an Apple Silicon only CLI release that ships precompiled `unsloth/gemma-4-E4B-it` MLC artifacts and uses MLC/OpenAI-compatible streaming and tool calling end to end.

**Architecture:** This plan is split into two subplans in one file. Subplan A proves and builds the release model artifact outside user startup: Hugging Face safetensors -> MLC converted weights -> Apple Metal model library -> `dist/models/...` artifact layout. Subplan B migrates DataHarness to load those bundled artifacts through `AsyncMLCEngine`, removes llama.cpp prompt/tool parsing, and keeps Layer 3 as the only owner of tool validation, approval, orchestration, workspace access, and worker dispatch.

**Tech Stack:** Python 3.13, `uv`, MLC LLM nightly packages from `https://mlc.ai/wheels`, MLC `AsyncMLCEngine`, Apple Silicon Metal, Hugging Face source repo `unsloth/gemma-4-E4B-it`, quantization `q4f16_1`, context window `131072`, PyInstaller one-file CLI binary, sibling `dist/models/` artifact directory, Pydantic v2, pytest.

---

## Locked Product Decisions

- Metal is acceptable. This is not an Apple MLX runtime migration.
- The source model is exactly `unsloth/gemma-4-E4B-it`.
- The app release is Apple Silicon only.
- The app must ship with precompiled MLC artifacts. End users must not download, convert, or compile the model on first run.
- Keep the existing packaging shape: one extensionless CLI binary at `dist/dataharness` plus fixed relative model paths. Do not move to `.dmg` or `.app` packaging in this plan.
- Ship one model variant first: `q4f16_1`, context window `131072`, runtime mode `interactive`.
- Fully transition runtime behavior to MLC/OpenAI-compatible messages, streaming, function tools, `tool_choice`, and JSON response format where supported. Do not keep prompt-text `<tool_call>` as the primary path.
- CPU fallback is dropped. If MLC Metal cannot run on the target machine, report an unsupported runtime state.

## MLC Docs And Facts To Preserve

Sources reviewed on 2026-05-18:
- MLC convert weights: `https://llm.mlc.ai/docs/compilation/convert_weights.html`
- MLC compile model libraries: `https://llm.mlc.ai/docs/compilation/compile_models.html`
- MLC package libraries and weights: `https://llm.mlc.ai/docs/compilation/package_libraries_and_weights.html`
- MLC Python API: `https://llm.mlc.ai/docs/deploy/python_engine.html`
- MLC REST/OpenAI-compatible API and tool calling: `https://llm.mlc.ai/docs/deploy/rest.html`
- Hugging Face source model: `https://huggingface.co/unsloth/gemma-4-E4B-it`

Observed requirements:
- MLC conversion starts from a local Hugging Face model directory containing safetensors and tokenizer/config files.
- `mlc_llm convert_weight` produces MLC converted weights for the requested quantization.
- `mlc_llm gen_config` produces `mlc-chat-config.json` and must use the chosen conversation template and context window.
- `mlc_llm compile ... --device metal` produces the Apple Metal model library.
- Runtime loads converted weights plus model library with `AsyncMLCEngine(model=..., model_lib=..., mode="interactive")`.
- MLC supports OpenAI-compatible streaming chat completion and tool calling, but the exact streamed chunk shape must still be probed against the installed package version.
- If the Gemma 4 E4B architecture or conversation template is unsupported by MLC, this migration stops until MLC support is added upstream or patched locally.

## Release Artifact Layout

The packaged CLI remains a single binary, but the model is a sibling directory because MLC weights and libraries are large runtime artifacts.

```text
dist/
  dataharness
  models/
    gemma-4-E4B-it-q4f16_1-MLC/
      mlc-chat-config.json
      params_shard_*.bin
      tokenizer.model or tokenizer.json
      ...
    lib/
      gemma-4-E4B-it-q4f16_1-metal.so
```

Source mode may use the same relative layout under the resolved app root:

```text
<app_root>/
  models/
    gemma-4-E4B-it-q4f16_1-MLC/
    lib/gemma-4-E4B-it-q4f16_1-metal.so
```

The runtime config should allow explicit env overrides for development, but production defaults should resolve to this fixed relative layout.

## Go / No-Go Gates

Do not start Subplan B until all Subplan A gates pass.

- Gate A1: `mlc_llm` imports successfully in the repo `uv` environment on Apple Silicon Python 3.13.
- Gate A2: MLC can run a small official MLC model with `AsyncMLCEngine` using Metal.
- Gate A3: `unsloth/gemma-4-E4B-it` downloads as a local safetensors Hugging Face snapshot.
- Gate A4: `mlc_llm convert_weight` succeeds for `unsloth/gemma-4-E4B-it` with `q4f16_1`.
- Gate A5: `mlc_llm gen_config` succeeds with a proven Gemma 4 compatible conversation template and `--context-window-size 131072`.
- Gate A6: `mlc_llm compile <mlc-chat-config.json> --device metal` produces `gemma-4-E4B-it-q4f16_1-metal.so`.
- Gate A7: `AsyncMLCEngine` loads the converted Gemma 4 E4B weights and Metal library and streams a text response.
- Gate A8: MLC tool calling emits OpenAI-style `tool_calls` without executing DataHarness tools in Layer 1.
- Gate A9: MLC streaming exposes enough chunk structure to convert text, tool calls, finish reasons, and usage into DataHarness `RuntimeEvent`.
- Gate A10: The artifact bundle can be copied beside `dist/dataharness` and found by fixed relative paths.

If any Gemma 4 E4B conversion, config, compile, or runtime gate fails, stop and record the reason in `docs/runtime/mlc-migration-notes.md`. Do not substitute another model.

## Current State Map

Runtime entry points:
- `src/runtime/protocol.py` defines the async runtime protocol and currently still includes `chat_format`.
- `src/runtime/types.py` defines `RuntimeMessage`, `RuntimeRequest`, `RuntimeEvent`, and `TokenPressure`.
- `src/runtime/config.py` is llama.cpp-specific.
- `src/runtime/llama_cpp_runtime.py` owns llama.cpp loading, Gemma chat-format folding, sync-to-async bridging, EOS stripping, reasoning parsing, and prompt-text tool-call parsing.
- `src/runtime/tool_calls.py` parses prompt-emitted `<tool_call>` blocks and fenced Python code.

Harness integration points:
- `src/harness/services/chat.py` builds runtime messages and currently folds system text into Gemma user messages when `chat_format` requires it.
- `src/harness/orchestrator.py` creates `RuntimeRequest`, streams runtime events, pauses on tool calls, and dispatches through `HarnessToolRegistry`.
- `src/harness/services/prompt_profiles.py` currently renders textual `<tool_call>` instructions into prompts.
- `src/harness/tools/*` define model-callable DataHarness tools that Layer 3 validates and dispatches.

Packaging integration points:
- `src/cli.py` owns dynamic imports, default runtime factory, default model path, and runtime construction.
- `src/observability/runtime_paths.py` resolves source root or frozen executable parent as app root.
- `scripts/build_app.sh` currently emits one binary at `dist/dataharness`.
- `tests/packaging/test_build_app_script.py` asserts hidden imports and resource collection.

Known blocker:
- `src/cli.py` dynamically imports stale `harness.factory` and `harness.workspace` paths. Fix this before testing any runtime startup path.

## Target File Structure

Create:
- `docs/runtime/mlc-migration-notes.md` - empirical artifact, compile, runtime, and tool-call findings.
- `docs/runtime/mlc.md` - user/developer runtime documentation.
- `scripts/probe_mlc_llm.py` - MLC import, Metal, streaming, and tool-call probe.
- `scripts/build_mlc_gemma4_e4b_artifacts.py` - release-engineering script that downloads, converts, configures, compiles, verifies, and stages artifacts.
- `scripts/verify_mlc_artifact_bundle.py` - verifies staged artifact layout beside a CLI binary.
- `src/runtime/mlc_artifacts.py` - model directory/library path resolver and artifact verifier.
- `src/runtime/mlc_messages.py` - DataHarness runtime messages to OpenAI-compatible MLC messages.
- `src/runtime/mlc_tools.py` - runtime-neutral tool descriptors to OpenAI tool schemas.
- `src/runtime/mlc_runtime.py` - `MLCRuntime` implementing `Runtime`.
- `src/harness/services/model_catalog.py` - bundled model metadata and status.
- `tests/runtime/test_mlc_artifacts.py`
- `tests/runtime/test_mlc_messages.py`
- `tests/runtime/test_mlc_tools.py`
- `tests/runtime/test_mlc_runtime.py`
- `tests/harness/test_model_catalog.py`
- `tests/packaging/test_mlc_artifact_bundle.py`

Modify:
- `src/runtime/__init__.py`
- `src/runtime/config.py`
- `src/runtime/protocol.py`
- `src/runtime/types.py`
- `src/harness/services/chat.py`
- `src/harness/orchestrator.py`
- `src/harness/services/doctor.py`
- `src/harness/services/mode_router.py`
- `src/harness/services/prompt_profiles.py`
- `src/cli.py`
- `src/observability/events.py`
- `src/observability/runtime_paths.py`
- `pyproject.toml`
- `scripts/build_app.sh`
- `tests/runtime/*`
- `tests/harness/test_agentic_turn.py`
- `tests/harness/test_runtime_bridge.py`
- `tests/harness/test_force_plan_tool_call.py`
- `tests/packaging/test_build_app_script.py`
- `CODEMAP.md`
- `Lessons.md`
- `README.md`

Delete after replacement tests are green:
- `src/runtime/llama_cpp_runtime.py`
- llama-specific runtime tests and packaging assertions.

Do not create:
- first-run model download screens
- first-run model compile screens
- CPU fallback UI or telemetry
- `.dmg` or `.app` packaging

---

# Subplan A: MLC Gemma 4 E4B Artifact Build And Verification

## Task A1: Fix CLI Dynamic Import Blocker

**Files:**
- Modify: `src/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `CODEMAP.md`

- [ ] **Step A1.1: Add a failing test for canonical dynamic imports**

Add to `tests/test_cli.py`:

```python
def test_build_app_imports_canonical_harness_modules(monkeypatch, tmp_path):
    imported = []

    class FakeWorkspaceManager:
        def __init__(self, app_root):
            self.app_root = app_root

        def open_default_workspace(self):
            return type("ActiveWorkspace", (), {
                "workspace_id": "w_test",
                "workspace_dir": tmp_path / "workspaces" / "w_test",
            })()

    def fake_import_module(name: str):
        imported.append(name)
        if name == "app.tui.app":
            return type("TuiModule", (), {"DataHarnessApp": lambda **kwargs: object()})
        if name == "app.session":
            return type("SessionModule", (), {"DataAnalysisAppSession": lambda **kwargs: object()})
        if name == "harness.control":
            return type("ControlModule", (), {"RunStateRecord": lambda **kwargs: object()})
        if name == "harness.core.factory":
            return type("FactoryModule", (), {"build_orchestrator": lambda **kwargs: object()})
        if name == "harness.services.workspace":
            return type("WorkspaceModule", (), {"WorkspaceManager": FakeWorkspaceManager})
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(cli.importlib, "import_module", fake_import_module)
    cli.build_app(telemetry=None, app_root=tmp_path, runtime=None)

    assert "harness.core.factory" in imported
    assert "harness.services.workspace" in imported
    assert "harness.factory" not in imported
    assert "harness.workspace" not in imported
```

- [ ] **Step A1.2: Run the failing test**

Run:

```bash
uv run pytest tests/test_cli.py::test_build_app_imports_canonical_harness_modules -q
```

Expected: FAIL because `src/cli.py` imports `harness.factory` and `harness.workspace`.

- [ ] **Step A1.3: Update `src/cli.py` imports**

Change:

```python
factory_module = importlib.import_module("harness.core.factory")
workspace_module = importlib.import_module("harness.services.workspace")
```

- [ ] **Step A1.4: Verify**

Run:

```bash
uv run pytest tests/test_cli.py tests/packaging/test_build_app_script.py -q
```

Expected: PASS.

## Task A2: Add MLC Probe Script

**Files:**
- Create: `scripts/probe_mlc_llm.py`
- Create: `docs/runtime/mlc-migration-notes.md`
- Modify: `Lessons.md`

- [ ] **Step A2.1: Create `scripts/probe_mlc_llm.py`**

```python
from __future__ import annotations

import argparse
import asyncio
import json
import platform
import time
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-lib", default=None)
    parser.add_argument("--device", default="metal")
    parser.add_argument("--mode", default="interactive")
    parser.add_argument("--prompt", default="Say hello in one short sentence.")
    parser.add_argument("--tools", action="store_true")
    parser.add_argument("--response-format-json", action="store_true")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    started = time.perf_counter()
    try:
        from mlc_llm import AsyncMLCEngine
    except Exception as exc:
        print(json.dumps({"ok": False, "phase": "import", "error": repr(exc)}))
        return 2

    tools: list[dict[str, Any]] = []
    if args.tools:
        tools = [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a location.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string"},
                        "unit": {"type": "string", "enum": ["fahrenheit", "celsius"]},
                    },
                    "required": ["location"],
                },
            },
        }]

    try:
        engine_kwargs: dict[str, Any] = {
            "model": args.model,
            "mode": args.mode,
            "device": args.device,
        }
        if args.model_lib:
            engine_kwargs["model_lib"] = args.model_lib
        engine = AsyncMLCEngine(**engine_kwargs)
        request_kwargs: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": "You are concise."},
                {"role": "user", "content": args.prompt},
            ],
            "model": args.model,
            "stream": True,
            "max_tokens": 64,
            "temperature": 0.2,
            "top_p": 0.95,
        }
        if tools:
            request_kwargs["tools"] = tools
            request_kwargs["tool_choice"] = "auto"
        if args.response_format_json:
            request_kwargs["response_format"] = {"type": "json_object"}

        chunks = []
        async for response in await engine.chat.completions.create(**request_kwargs):
            chunks.append(response.model_dump(mode="json") if hasattr(response, "model_dump") else str(response))
        engine.terminate()
        print(json.dumps({
            "ok": True,
            "device": args.device,
            "mode": args.mode,
            "python": platform.python_version(),
            "machine": platform.machine(),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "chunk_count": len(chunks),
            "first_chunk": chunks[0] if chunks else None,
            "last_chunk": chunks[-1] if chunks else None,
        }, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "phase": "engine_or_stream", "device": args.device, "error": repr(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [ ] **Step A2.2: Install MLC packages**

Run the current MLC wheel command proven by MLC docs:

```bash
uv add --index-url https://mlc.ai/wheels --prerelease allow mlc-llm-nightly-cpu mlc-ai-nightly-cpu
```

Expected: packages install. If package names or index flags have changed, record the exact working command in `docs/runtime/mlc-migration-notes.md`.

- [ ] **Step A2.3: Probe a small official MLC model on Metal**

Run:

```bash
uv run python scripts/probe_mlc_llm.py --model HF://mlc-ai/Llama-3-8B-Instruct-q4f16_1-MLC --device metal
```

Expected: JSON with `"ok": true` and non-zero `chunk_count`.

- [ ] **Step A2.4: Probe OpenAI-style tool calls**

Run:

```bash
uv run python scripts/probe_mlc_llm.py --model HF://mlc-ai/Llama-3-8B-Instruct-q4f16_1-MLC --device metal --tools --prompt "What is the weather in Pittsburgh in fahrenheit?"
```

Expected: streamed or final chunks contain OpenAI-style `tool_calls`; no local Python function is auto-executed.

- [ ] **Step A2.5: Probe JSON response format**

Run:

```bash
uv run python scripts/probe_mlc_llm.py --model HF://mlc-ai/Llama-3-8B-Instruct-q4f16_1-MLC --device metal --response-format-json --prompt "Return JSON with key ok and value true."
```

Expected: MLC either accepts `response_format={"type":"json_object"}` or fails clearly. Record the actual behavior.

## Task A3: Build Gemma 4 E4B MLC Artifacts

**Files:**
- Create: `scripts/build_mlc_gemma4_e4b_artifacts.py`
- Create: `docs/runtime/mlc-migration-notes.md`

- [ ] **Step A3.1: Create the artifact builder script**

Create `scripts/build_mlc_gemma4_e4b_artifacts.py` with this contract:

```python
from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
from pathlib import Path


MODEL_ID = "unsloth/gemma-4-E4B-it"
MODEL_SLUG = "gemma-4-E4B-it"
QUANTIZATION = "q4f16_1"
CONTEXT_WINDOW = 131072
MLC_MODEL_DIRNAME = f"{MODEL_SLUG}-{QUANTIZATION}-MLC"
METAL_LIB_NAME = f"{MODEL_SLUG}-{QUANTIZATION}-metal.so"


def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print(json.dumps({"phase": "run", "cmd": cmd, "cwd": str(cwd) if cwd else None}))
    subprocess.run(cmd, cwd=cwd, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument("--conv-template", default="gemma")
    parser.add_argument("--skip-download", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if platform.machine() != "arm64":
        raise SystemExit("Apple Silicon arm64 is required for the Metal artifact build")

    work_dir = args.work_dir.resolve()
    hf_dir = work_dir / "hf" / MODEL_SLUG
    mlc_dir = work_dir / "mlc" / MLC_MODEL_DIRNAME
    lib_dir = work_dir / "lib"
    lib_path = lib_dir / METAL_LIB_NAME
    staged_model_dir = args.dist_dir.resolve() / "models" / MLC_MODEL_DIRNAME
    staged_lib_dir = args.dist_dir.resolve() / "models" / "lib"

    work_dir.mkdir(parents=True, exist_ok=True)
    lib_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_download:
        run([
            "uv", "run", "huggingface-cli", "download", MODEL_ID,
            "--local-dir", str(hf_dir),
        ])

    run([
        "uv", "run", "mlc_llm", "convert_weight", str(hf_dir),
        "--quantization", QUANTIZATION,
        "-o", str(mlc_dir),
    ])
    run([
        "uv", "run", "mlc_llm", "gen_config", str(hf_dir),
        "--quantization", QUANTIZATION,
        "--conv-template", args.conv_template,
        "--context-window-size", str(CONTEXT_WINDOW),
        "-o", str(mlc_dir),
    ])
    run([
        "uv", "run", "mlc_llm", "compile", str(mlc_dir / "mlc-chat-config.json"),
        "--device", "metal",
        "-o", str(lib_path),
    ])

    if not (mlc_dir / "mlc-chat-config.json").exists():
        raise SystemExit("missing mlc-chat-config.json after gen_config")
    if not lib_path.exists():
        raise SystemExit(f"missing compiled Metal library: {lib_path}")

    if staged_model_dir.exists():
        shutil.rmtree(staged_model_dir)
    staged_model_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(mlc_dir, staged_model_dir)
    staged_lib_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(lib_path, staged_lib_dir / lib_path.name)

    print(json.dumps({
        "ok": True,
        "model_dir": str(staged_model_dir),
        "model_lib": str(staged_lib_dir / lib_path.name),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step A3.2: Run conversion and compile**

Run:

```bash
uv run python scripts/build_mlc_gemma4_e4b_artifacts.py --work-dir /tmp/dataharness-mlc-artifacts --dist-dir dist --conv-template gemma
```

Expected:
- `dist/models/gemma-4-E4B-it-q4f16_1-MLC/mlc-chat-config.json` exists.
- `dist/models/lib/gemma-4-E4B-it-q4f16_1-metal.so` exists.

If `--conv-template gemma` fails, check MLC-supported template names and rerun with the exact working template. Record it in `docs/runtime/mlc-migration-notes.md` and in the script default.

- [ ] **Step A3.3: Probe the compiled artifact**

Run:

```bash
uv run python scripts/probe_mlc_llm.py \
  --model dist/models/gemma-4-E4B-it-q4f16_1-MLC \
  --model-lib dist/models/lib/gemma-4-E4B-it-q4f16_1-metal.so \
  --device metal \
  --tools \
  --prompt "Use a tool if appropriate: what is the weather in Pittsburgh?"
```

Expected: JSON with `"ok": true`, non-zero `chunk_count`, and observed chunk shape recorded in `docs/runtime/mlc-migration-notes.md`.

## Task A4: Verify Artifact Bundle Layout

**Files:**
- Create: `src/runtime/mlc_artifacts.py`
- Create: `tests/runtime/test_mlc_artifacts.py`
- Create: `scripts/verify_mlc_artifact_bundle.py`
- Create: `tests/packaging/test_mlc_artifact_bundle.py`

- [ ] **Step A4.1: Add artifact path tests**

Create `tests/runtime/test_mlc_artifacts.py`:

```python
from pathlib import Path

from runtime.mlc_artifacts import MLCModelArtifacts


def test_mlc_model_artifacts_default_relative_layout(tmp_path: Path) -> None:
    artifacts = MLCModelArtifacts.for_app_root(tmp_path)
    assert artifacts.model_dir == tmp_path / "models" / "gemma-4-E4B-it-q4f16_1-MLC"
    assert artifacts.model_lib == tmp_path / "models" / "lib" / "gemma-4-E4B-it-q4f16_1-metal.so"
    assert artifacts.config_path == artifacts.model_dir / "mlc-chat-config.json"


def test_mlc_model_artifacts_missing_status(tmp_path: Path) -> None:
    artifacts = MLCModelArtifacts.for_app_root(tmp_path)
    status = artifacts.verify()
    assert status["installed"] is False
    assert "mlc-chat-config.json" in status["missing"]
    assert "gemma-4-E4B-it-q4f16_1-metal.so" in status["missing"]
```

- [ ] **Step A4.2: Implement artifact resolver**

Create `src/runtime/mlc_artifacts.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


MODEL_ID = "gemma-4-E4B-it"
QUANTIZATION = "q4f16_1"
MLC_MODEL_DIRNAME = f"{MODEL_ID}-{QUANTIZATION}-MLC"
METAL_LIB_NAME = f"{MODEL_ID}-{QUANTIZATION}-metal.so"


@dataclass(frozen=True)
class MLCModelArtifacts:
    model_dir: Path
    model_lib: Path
    config_path: Path

    @classmethod
    def for_app_root(cls, app_root: Path) -> "MLCModelArtifacts":
        model_dir = app_root / "models" / MLC_MODEL_DIRNAME
        model_lib = app_root / "models" / "lib" / METAL_LIB_NAME
        return cls(model_dir=model_dir, model_lib=model_lib, config_path=model_dir / "mlc-chat-config.json")

    def verify(self) -> dict[str, object]:
        missing = []
        if not self.model_dir.exists():
            missing.append(MLC_MODEL_DIRNAME)
        if not self.config_path.exists():
            missing.append("mlc-chat-config.json")
        if not self.model_lib.exists():
            missing.append(METAL_LIB_NAME)
        return {
            "installed": not missing,
            "model_dir": str(self.model_dir),
            "model_lib": str(self.model_lib),
            "missing": missing,
        }
```

- [ ] **Step A4.3: Create bundle verifier**

Create `scripts/verify_mlc_artifact_bundle.py`:

```python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from runtime.mlc_artifacts import MLCModelArtifacts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-root", type=Path, default=Path("dist"))
    args = parser.parse_args()
    status = MLCModelArtifacts.for_app_root(args.app_root.resolve()).verify()
    print(json.dumps(status, indent=2))
    return 0 if status["installed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step A4.4: Verify tests and staged bundle**

Run:

```bash
uv run pytest tests/runtime/test_mlc_artifacts.py tests/packaging/test_mlc_artifact_bundle.py -q
uv run python scripts/verify_mlc_artifact_bundle.py --app-root dist
```

Expected: tests PASS and verifier exits 0 after Task A3 has staged the artifacts.

---

# Subplan B: DataHarness Runtime Migration To Bundled MLC Artifacts

## Task B1: Redesign Runtime Config And Protocol For MLC

**Files:**
- Modify: `src/runtime/config.py`
- Modify: `src/runtime/types.py`
- Modify: `src/runtime/protocol.py`
- Modify: `tests/runtime/test_config.py`
- Modify: `tests/runtime/test_types.py`
- Modify: `tests/runtime/test_protocol_shape.py`

- [ ] **Step B1.1: Replace config tests**

Update `tests/runtime/test_config.py` to assert:

```python
from runtime.config import RuntimeConfig


def test_runtime_config_defaults_to_bundled_mlc_gemma4() -> None:
    cfg = RuntimeConfig(model_path="/app/models/gemma-4-E4B-it-q4f16_1-MLC")
    assert cfg.engine == "mlc"
    assert cfg.model_id == "gemma-4-E4B-it"
    assert cfg.model_lib_path is None
    assert cfg.device == "metal"
    assert cfg.engine_mode == "interactive"
    assert cfg.context_window == 131072
    assert cfg.quantization == "q4f16_1"


def test_runtime_config_has_no_llama_cpp_fields() -> None:
    for field in ("chat_format", "n_batch", "n_gpu_layers", "offload_kqv", "flash_attn", "type_k", "type_v"):
        assert field not in RuntimeConfig.model_fields
```

- [ ] **Step B1.2: Replace `src/runtime/config.py`**

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_path: str
    model_lib_path: str | None = None
    engine: Literal["mlc"] = "mlc"
    model_id: str = "gemma-4-E4B-it"
    quantization: str = "q4f16_1"
    device: Literal["metal"] = "metal"
    engine_mode: Literal["interactive"] = "interactive"
    context_window: int = 131072
    max_completion_tokens_default: int = 2048
    enable_reasoning_stream: bool = True
```

- [ ] **Step B1.3: Extend runtime request/message types**

In `src/runtime/types.py`, add:

```python
class RuntimeMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


class RuntimeRequest(BaseModel):
    messages: list[RuntimeMessage]
    max_completion_tokens: int
    temperature: float = 0.2
    top_p: float = 0.95
    stop: list[str] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    tool_choice: str | dict[str, Any] | None = None
    response_format: dict[str, Any] | None = None
    request_id: str
    correlation_id: str | None = None
```

- [ ] **Step B1.4: Remove protocol `chat_format`**

In `src/runtime/protocol.py`, remove `chat_format: str`. Keep async methods:

```python
class Runtime(Protocol):
    async def stream(self, request: RuntimeRequest) -> AsyncIterator[RuntimeEvent]: ...
    async def context_window(self) -> int: ...
    async def token_pressure(self, request: RuntimeRequest) -> TokenPressure: ...
    async def validate_request(self, request: RuntimeRequest) -> None: ...
    async def status(self) -> RuntimeStatus: ...
```

- [ ] **Step B1.5: Verify**

Run:

```bash
uv run pytest tests/runtime/test_config.py tests/runtime/test_types.py tests/runtime/test_protocol_shape.py -q
```

Expected: PASS.

## Task B2: Convert Messages And Tools To MLC/OpenAI Format

**Files:**
- Create: `src/runtime/mlc_messages.py`
- Create: `src/runtime/mlc_tools.py`
- Create: `tests/runtime/test_mlc_messages.py`
- Create: `tests/runtime/test_mlc_tools.py`

- [ ] **Step B2.1: Add message conversion tests**

Create `tests/runtime/test_mlc_messages.py`:

```python
from runtime.mlc_messages import to_mlc_messages
from runtime.types import RuntimeMessage


def test_to_mlc_messages_preserves_tool_fields() -> None:
    messages = [
        RuntimeMessage(role="system", content="sys"),
        RuntimeMessage(role="assistant", content=None, tool_calls=[{
            "id": "call_1",
            "type": "function",
            "function": {"name": "file_read", "arguments": "{\"operation\":\"list\"}"},
        }]),
        RuntimeMessage(role="tool", content="[]", tool_call_id="call_1"),
    ]
    assert to_mlc_messages(messages) == [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_1",
            "type": "function",
            "function": {"name": "file_read", "arguments": "{\"operation\":\"list\"}"},
        }]},
        {"role": "tool", "content": "[]", "tool_call_id": "call_1"},
    ]
```

- [ ] **Step B2.2: Add tool conversion tests**

Create `tests/runtime/test_mlc_tools.py`:

```python
from runtime.mlc_tools import to_openai_tool_schema


def test_to_openai_tool_schema_from_plain_descriptor() -> None:
    descriptor = {
        "name": "file_read",
        "short_description": "Read workspace files.",
        "arguments": [
            {"name": "operation", "type": "str", "required": True, "description": "Operation.", "allowed_values": ["list", "inspect", "content"]},
            {"name": "path", "type": "path", "required": False, "description": "Workspace relative path."},
        ],
    }
    schema = to_openai_tool_schema(descriptor)
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "file_read"
    assert schema["function"]["parameters"]["required"] == ["operation"]
    assert schema["function"]["parameters"]["properties"]["operation"]["enum"] == ["list", "inspect", "content"]
```

- [ ] **Step B2.3: Implement helpers**

`src/runtime/mlc_tools.py` must not import `harness.*`; pass plain dictionaries from Layer 3.

- [ ] **Step B2.4: Verify**

Run:

```bash
uv run pytest tests/runtime/test_mlc_messages.py tests/runtime/test_mlc_tools.py -q
```

Expected: PASS.

## Task B3: Implement `MLCRuntime`

**Files:**
- Create: `src/runtime/mlc_runtime.py`
- Create: `tests/runtime/test_mlc_runtime.py`
- Modify: `src/runtime/__init__.py`

- [ ] **Step B3.1: Add fake engine tests**

Create tests proving:
- text chunks become `RuntimeEvent(type="text_delta")`
- streamed `tool_calls` become `RuntimeEvent(type="tool_call")`
- finish reason `"tool_calls"` maps to `finish_reason="tool_call"`
- usage maps to the final `RuntimeEvent`
- missing artifact verification produces `RuntimeEvent(type="error", error_code="model_artifacts_missing")`
- Metal load failure produces `RuntimeEvent(type="error", error_code="runtime_unsupported")`

- [ ] **Step B3.2: Implement runtime**

`MLCRuntime` must:
- lazily import `mlc_llm.AsyncMLCEngine`
- verify `MLCModelArtifacts` before creating the engine
- create `AsyncMLCEngine(model=config.model_path, model_lib=config.model_lib_path, device="metal", mode="interactive")`
- pass `max_tokens`, `temperature`, `top_p`, `stop`, `tools`, `tool_choice`, and `response_format`
- convert MLC/OpenAI chunks into DataHarness `RuntimeEvent`
- terminate the engine when closed
- estimate token pressure conservatively if MLC tokenizer metadata is unavailable

- [ ] **Step B3.3: Verify**

Run:

```bash
uv run pytest tests/runtime/test_mlc_runtime.py tests/runtime/test_runtime_layer_boundaries.py -q
```

Expected: PASS.

## Task B4: Migrate Harness Requests To Native MLC Tools

**Files:**
- Modify: `src/harness/services/chat.py`
- Modify: `src/harness/orchestrator.py`
- Modify: `src/harness/services/prompt_profiles.py`
- Modify: `src/harness/prompts/*.md`
- Modify: `tests/harness/test_runtime_request_builder.py`
- Modify: `tests/harness/test_prompt_profiles.py`
- Modify: `tests/harness/test_agentic_turn.py`
- Modify: `tests/harness/test_force_plan_tool_call.py`

- [ ] **Step B4.1: Remove Gemma chat-format folding**

Update `RuntimeRequestBuilder` so system prompts stay as normal `RuntimeMessage(role="system")` messages. Delete `_FORMATS_WITHOUT_SYSTEM_ROLE`, `_format_drops_system_role`, and `chat_format` branching.

- [ ] **Step B4.2: Remove prompt-text tool-call instructions**

Update `src/harness/services/prompt_profiles.py` and `src/harness/prompts/*.md` to stop telling the model to emit `<tool_call>...</tool_call>`. Prompt text should describe when tools are available, but the actual tool schema must travel through `RuntimeRequest.tools`.

- [ ] **Step B4.3: Populate `RuntimeRequest.tools`**

In `Orchestrator.run_turn`, derive the active mode tool names from `PromptProfileRegistry` / `MODE_TOOL_NAMES`, select matching registered `ToolDescriptor` instances, convert them to plain dictionaries, convert those to OpenAI schemas through `runtime.mlc_tools`, and pass:

```python
tools=openai_tools
tool_choice="auto" if openai_tools else None
```

- [ ] **Step B4.4: Convert forced `analysis_plan` path**

Replace forced textual `stop=["</tool_call>"]` plan generation with:

```python
tool_choice={"type": "function", "function": {"name": "analysis_plan"}}
```

If the MLC probe shows forced function choice is unsupported, stop and record that native MLC tool calling does not satisfy DataHarness planning requirements.

- [ ] **Step B4.5: Update gen-2 code synthesis**

Use `RuntimeRequest.response_format={"type": "json_object"}` only if Task A2 proves MLC accepts it. If MLC rejects JSON mode, keep fenced-code extraction for code synthesis but document that this is response parsing, not Layer 1 tool-call emulation.

- [ ] **Step B4.6: Verify**

Run:

```bash
uv run pytest tests/harness/test_runtime_request_builder.py tests/harness/test_prompt_profiles.py tests/harness/test_agentic_turn.py tests/harness/test_force_plan_tool_call.py tests/harness/test_chat_compaction.py tests/harness/test_doctor_runner.py -q
```

Expected: PASS.

## Task B5: Switch CLI Factory And Fixed Relative Model Paths

**Files:**
- Modify: `src/cli.py`
- Modify: `src/observability/runtime_paths.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/packaging/test_build_app_script.py`

- [ ] **Step B5.1: Update runtime factory**

Change:

```python
def _default_runtime_factory(config, telemetry):
    runtime_module = importlib.import_module("runtime.mlc_runtime")
    return runtime_module.MLCRuntime(config, telemetry=telemetry)
```

- [ ] **Step B5.2: Update default paths**

Default path resolution should use the resolved app root:

```python
default_model_path = Path("models/gemma-4-E4B-it-q4f16_1-MLC")
default_model_lib_path = Path("models/lib/gemma-4-E4B-it-q4f16_1-metal.so")
```

`DATAHARNESS_MODEL_PATH` and `DATAHARNESS_MODEL_LIB_PATH` may override these for development.

- [ ] **Step B5.3: Preserve one-binary plus sibling model layout**

Keep `resolve_app_root()` behavior where frozen mode returns `Path(sys.executable).resolve().parent`. This makes `./dist/dataharness` resolve bundled artifacts from `./dist/models/...`.

- [ ] **Step B5.4: Verify**

Run:

```bash
uv run pytest tests/test_cli.py tests/packaging/test_build_app_script.py -q
```

Expected: PASS.

## Task B6: Update Dependencies And PyInstaller Script

**Files:**
- Modify: `pyproject.toml`
- Modify: `scripts/build_app.sh`
- Modify: `tests/packaging/test_build_app_script.py`

- [ ] **Step B6.1: Remove llama dependency**

Run:

```bash
uv remove llama-cpp-python
```

- [ ] **Step B6.2: Add MLC dependencies**

Use the package command proven in Task A2. If MLC wheels cannot be locked in `pyproject.toml` / `uv.lock` from `https://mlc.ai/wheels`, document the release prerequisite and stop before packaging claims are made.

- [ ] **Step B6.3: Update PyInstaller script**

Remove:

```text
--hidden-import runtime.llama_cpp_runtime
--collect-all llama_cpp
```

Add:

```text
--hidden-import runtime.mlc_runtime
--hidden-import runtime.mlc_messages
--hidden-import runtime.mlc_tools
--hidden-import runtime.mlc_artifacts
--collect-all mlc_llm
--collect-all tvm
```

After PyInstaller builds `dist/dataharness`, call:

```bash
uv run python scripts/verify_mlc_artifact_bundle.py --app-root dist
```

Do not compile the model inside `scripts/build_app.sh`.

- [ ] **Step B6.4: Verify**

Run:

```bash
uv run pytest tests/packaging/test_build_app_script.py -q
```

Expected: PASS.

## Task B7: Add MLC Telemetry And Status

**Files:**
- Modify: `src/observability/events.py`
- Modify: `docs/observability.md`
- Modify: `tests/observability/test_events.py`

- [ ] **Step B7.1: Add event kinds**

Add:
- `runtime.backend.selected`
- `runtime.backend.unsupported`
- `runtime.model.artifacts.verify.start`
- `runtime.model.artifacts.verify.end`
- `runtime.model.load.start`
- `runtime.model.load.end`

- [ ] **Step B7.2: Emit payload fields**

Runtime telemetry must include:
- `engine="mlc"`
- `device="metal"`
- `model_id="gemma-4-E4B-it"`
- `quantization="q4f16_1"`
- `context_window=131072`
- `model_path`
- `model_lib_path`
- `engine_mode="interactive"`
- `token_count_source`

- [ ] **Step B7.3: Verify**

Run:

```bash
uv run pytest tests/observability -q
```

Expected: PASS.

## Task B8: Remove llama.cpp Runtime And Update CODEMAP

**Files:**
- Delete: `src/runtime/llama_cpp_runtime.py`
- Modify: `src/runtime/__init__.py`
- Modify: `tests/runtime/*`
- Modify: `CODEMAP.md`
- Modify: `README.md`
- Modify: `docs/runtime/mlc.md`
- Modify: `Lessons.md`

- [ ] **Step B8.1: Delete llama runtime and llama-specific tests**

Remove `src/runtime/llama_cpp_runtime.py` and replace llama-specific tests with MLC runtime tests.

- [ ] **Step B8.2: Update CODEMAP**

Update:
- import graph for `runtime.mlc_runtime`, `runtime.mlc_messages`, `runtime.mlc_tools`, and `runtime.mlc_artifacts`
- definitions for `MLCRuntime` and artifact helpers
- call sites from CLI factory and orchestrator request building
- removal of `LlamaCppRuntime`

- [ ] **Step B8.3: Add MLC runtime docs**

Create `docs/runtime/mlc.md` covering:
- Apple Silicon only support
- Metal, not MLX
- exact model source `unsloth/gemma-4-E4B-it`
- artifact build command
- fixed relative packaged layout
- OpenAI-compatible tool-call flow
- unsupported machine and missing artifact errors

- [ ] **Step B8.4: Cleanup scan**

Run:

```bash
rg -n "llama|llama_cpp|GGUF|chat_format|n_gpu_layers|<tool_call>" src tests docs README.md pyproject.toml scripts CODEMAP.md
```

Expected:
- no active llama.cpp runtime dependency remains
- no active prompt asks the model to emit `<tool_call>`
- archived docs may mention llama.cpp only as removed legacy runtime

## Task B9: Source And Packaged Verification

**Files:**
- No source changes unless verification exposes failures.

- [ ] **Step B9.1: Run focused suites**

Run:

```bash
uv run pytest tests/runtime tests/harness/test_agentic_turn.py tests/harness/test_runtime_bridge.py tests/harness/test_chat_compaction.py tests/harness/test_doctor_runner.py tests/packaging/test_build_app_script.py -q
```

Expected: PASS.

- [ ] **Step B9.2: Run full suite**

Run:

```bash
uv run pytest -q
```

Expected: PASS or only a documented unrelated worker timeout from `Issues.md`.

- [ ] **Step B9.3: Build artifact bundle**

Run:

```bash
uv run python scripts/build_mlc_gemma4_e4b_artifacts.py --work-dir /tmp/dataharness-mlc-artifacts --dist-dir dist
```

Expected: `dist/models/...` contains converted MLC weights and Metal library.

- [ ] **Step B9.4: Build CLI binary**

Run:

```bash
bash scripts/build_app.sh
```

Expected: `dist/dataharness` exists and artifact verifier passes.

- [ ] **Step B9.5: Packaged smoke**

Run:

```bash
DATAHARNESS_APP_ROOT=dist ./dist/dataharness
```

Expected:
- packaged app starts
- MLC imports succeed
- artifact verification succeeds
- Gemma 4 E4B loads on Metal
- prompt streams
- native MLC tool-call path works for `file_read` or `analysis_plan`

## Final Acceptance Checklist

- [ ] MLC probes pass for install, Apple Metal, streaming, JSON mode decision, and tool calls.
- [ ] `unsloth/gemma-4-E4B-it` converts with `q4f16_1`.
- [ ] `mlc_llm gen_config` succeeds with context window `131072` and a documented conversation template.
- [ ] `mlc_llm compile --device metal` produces the Metal library.
- [ ] `AsyncMLCEngine` loads the exact staged Gemma 4 E4B MLC artifacts and streams a response.
- [ ] Runtime uses bundled fixed relative paths by default.
- [ ] Packaged layout remains `dist/dataharness` plus `dist/models/...`; no `.dmg` or `.app`.
- [ ] End users are not asked to download, convert, or compile models on first run.
- [ ] CPU fallback is removed from config, UI, telemetry, and tests.
- [ ] MLC/OpenAI-compatible tool calls preserve Layer 3 dispatch and approval.
- [ ] Prompt-text `<tool_call>` instructions are removed from active prompts.
- [ ] `llama-cpp-python` is removed from `pyproject.toml`.
- [ ] `src/runtime/llama_cpp_runtime.py` is deleted.
- [ ] PyInstaller no longer collects `llama_cpp`.
- [ ] Runtime, harness, observability, and packaging tests pass.
- [ ] `CODEMAP.md`, `Lessons.md`, `README.md`, and `docs/runtime/mlc.md` reflect the final structure.

## Plan Self-Review

Spec coverage:
- Metal accepted: covered by locked decisions, gates, config, artifact builder, and runtime.
- Exact model: every artifact and config path uses `unsloth/gemma-4-E4B-it` / `gemma-4-E4B-it`.
- Precompiled artifacts: covered by Subplan A and fixed `dist/models/...` layout.
- Apple Silicon only: covered by artifact builder preflight and unsupported runtime state.
- One-file CLI packaging: preserved as `dist/dataharness` plus sibling model directory.
- `q4f16_1` and `131072`: covered by config and artifact commands.
- Full MLC transition: covered by RuntimeRequest contract changes, prompt cleanup, native tool schemas, and llama deletion.
- CPU fallback removal: covered by locked decisions and acceptance checklist.

Placeholder scan:
- Remaining empirical choices are gates, not placeholders: MLC package install command, Gemma 4 conversation template, JSON mode support, and streamed tool-call chunk shape must be recorded from real probes before implementation proceeds.

Type consistency:
- Runtime config uses `model_path`, `model_lib_path`, `device="metal"`, `engine_mode="interactive"`, `quantization="q4f16_1"`, and `context_window=131072`.
- Artifact paths consistently use `models/gemma-4-E4B-it-q4f16_1-MLC` and `models/lib/gemma-4-E4B-it-q4f16_1-metal.so`.
