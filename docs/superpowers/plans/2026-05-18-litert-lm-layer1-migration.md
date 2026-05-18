# LiteRT-LM Layer 1 Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current llama.cpp Python runtime with Google LiteRT-LM for a macOS Apple Silicon first release, using Gemma 4 E4B `.litertlm`, GPU-first loading with CPU fallback, LiteRT-LM-native streaming/tool behavior, and a first-run model download UX.

**Architecture:** Layer 1 becomes a LiteRT-LM runtime package that owns engine loading, model-status reporting, backend fallback, streaming conversion, LiteRT-LM-native tool integration, and token-pressure estimation. Layer 3 remains the owner of orchestration, prompt profiles, DataHarness tool policy, approvals, workspace/memory access, and worker dispatch; Layer 4 only renders runtime/model state and user controls. The migration removes llama.cpp completely after the LiteRT-LM spike proves Python API behavior on Apple Silicon.

**Tech Stack:** Python 3.13 unless LiteRT-LM Python support forces Python 3.12, `uv`, `litert-lm-api-nightly`, Google LiteRT-LM, Gemma 4 E4B `.litertlm`, Hugging Face `litert-community/gemma-4-E4B-it-litert-lm`, Textual, PyInstaller, Pydantic v2, pytest.

---

## Sources And Constraints

Sources reviewed on 2026-05-18:
- LiteRT-LM Python API: `https://ai.google.dev/edge/litert-lm/python`
- LiteRT-LM overview and platform/model table: `https://ai.google.dev/edge/litert-lm/overview`
- LiteRT-LM GitHub README and Gemma 4 E4B CLI example: `https://github.com/google-ai-edge/LiteRT-LM`
- LiteRT samples compiled model API: `https://github.com/google-ai-edge/litert-samples/tree/main/compiled_model_api`

Constraints:
- First implementation targets macOS on Apple Silicon only.
- Preferred backend is LiteRT-LM GPU; runtime must fall back to CPU when GPU load fails.
- User requested "Apple Silicon mlx only"; current LiteRT-LM docs expose `Backend.GPU`, not an Apple MLX API. This plan treats that as Apple Silicon GPU acceleration through LiteRT-LM. If the requirement is literal Apple `mlx-lm`, stop this plan and write a separate MLX runtime plan.
- Default model is Gemma 4 E4B from Hugging Face repo `litert-community/gemma-4-E4B-it-litert-lm`, file `gemma-4-E4B-it.litertlm`, matching the LiteRT-LM README example.
- Model download UX is part of the migration, not a later enhancement.
- Full transition means `llama-cpp-python`, `src/runtime/llama_cpp_runtime.py`, llama-specific config fields, llama PyInstaller collection, and llama tests are removed.
- Do not git commit while executing this plan unless the user explicitly authorizes it. Use `git diff --check` and status checkpoints instead.

## Current State Map

Runtime entry points:
- `src/runtime/protocol.py` defines the public async runtime protocol.
- `src/runtime/types.py` defines `RuntimeMessage`, `RuntimeRequest`, `RuntimeEvent`, `TokenPressure`, and runtime status values.
- `src/runtime/config.py` is llama.cpp-specific today.
- `src/runtime/llama_cpp_runtime.py` owns llama.cpp model loading, Gemma chat-format folding, blocking-to-async bridge usage, EOS stripping, reasoning parsing, and prompt-text tool-call parsing.
- `src/runtime/tool_calls.py` parses prompt-emitted `<tool_call>` blocks and fenced Python code.

Harness integration points:
- `src/harness/services/chat.py` builds `RuntimeRequest` messages and performs compaction summarization through the runtime.
- `src/harness/orchestrator.py` calls the runtime for normal turns, analysis-plan forcing, tool repair retries, gen-2 code synthesis, and mode-handled continuations.
- `src/harness/services/doctor.py` calls the runtime for semantic doctor phases and narration.
- `src/harness/services/mode_router.py` can use an LLM fallback classifier.
- `src/harness/services/prompt_profiles.py` loads profile prompts and model-callable tool catalogs.
- `src/harness/tools/*` define DataHarness model-facing tools, but Layer 3 dispatches and validates them.

App/CLI/packaging integration points:
- `src/cli.py` dynamically imports the runtime factory and default model path.
- `scripts/build_app.sh` collects `runtime.llama_cpp_runtime` and `llama_cpp`.
- `tests/packaging/test_build_app_script.py` asserts the current PyInstaller dynamic-import rules.
- `CODEMAP.md` documents imports, definitions, and call relationships and must be updated after structural changes.

Known blocker already documented in `Issues.md`:
- `src/cli.py` imports stale `harness.factory` and `harness.workspace` dynamic paths; fix this before validating runtime startup.

## Target File Structure

Create:
- `docs/runtime/litert-lm-migration-notes.md` - API spike notes and confirmed LiteRT-LM behavior.
- `src/runtime/litert_lm_runtime.py` - LiteRT-LM engine adapter implementing `Runtime`.
- `src/runtime/litert_messages.py` - conversion between DataHarness runtime messages and LiteRT-LM message/content dictionaries.
- `src/runtime/litert_tools.py` - LiteRT-LM native tool bridge helpers that expose DataHarness tools without importing Layer 3.
- `src/runtime/model_assets.py` - runtime-level model path constants and model integrity contract.
- `src/harness/services/model_catalog.py` - model metadata, installed-state checks, and default Gemma 4 E4B entry.
- `src/harness/services/model_download.py` - resumable model download, verification, and install state.
- `src/harness/commands/model.py` - `/model_status`, `/model_download`, `/model_use`, `/model_delete`.
- `src/app/tui/screens/model_manager.py` - first-run model setup/download screen.
- `tests/runtime/test_litert_messages.py`
- `tests/runtime/test_litert_lm_runtime.py`
- `tests/runtime/test_litert_tools.py`
- `tests/harness/test_model_catalog.py`
- `tests/harness/test_model_download.py`
- `tests/harness/test_model_commands.py`
- `tests/app/tui/test_model_manager.py`
- `scripts/probe_litert_lm.py`

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
- `src/harness/commands/__init__.py`
- `src/app/events.py`
- `src/app/event_mapping.py`
- `src/app/tui/app.py`
- `src/app/tui/screens/__init__.py`
- `src/app/tui/sidebar_sections.py`
- `src/cli.py`
- `src/observability/events.py`
- `pyproject.toml`
- `scripts/build_app.sh`
- `tests/runtime/*`
- `tests/harness/test_agentic_turn.py`
- `tests/harness/test_runtime_bridge.py`
- `tests/packaging/test_build_app_script.py`
- `CODEMAP.md`
- `Lessons.md`

Delete:
- `src/runtime/llama_cpp_runtime.py`
- llama-specific runtime tests whose assertions only cover `build_llama_kwargs`, llama chat-format folding, or llama chunk shapes.

Retain unless replaced by confirmed LiteRT-LM native structured output:
- `src/runtime/tool_calls.py` only for fenced-code extraction and backward-compatible repair tests. Remove prompt `<tool_call>` parsing after native tool bridge passes.

## Task 1: Fix CLI Dynamic Import Blocker

**Files:**
- Modify: `src/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/packaging/test_build_app_script.py`
- Modify: `CODEMAP.md`

- [ ] **Step 1: Write failing tests for canonical imports**

Add assertions to `tests/test_cli.py`:

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

- [ ] **Step 2: Run the failing test**

Run:

```bash
uv run pytest tests/test_cli.py::test_build_app_imports_canonical_harness_modules -q
```

Expected: FAIL because `src/cli.py` currently imports `harness.factory` and `harness.workspace`.

- [ ] **Step 3: Update `src/cli.py` dynamic imports**

Change:

```python
factory_module = importlib.import_module("harness.factory")
workspace_module = importlib.import_module("harness.workspace")
```

To:

```python
factory_module = importlib.import_module("harness.core.factory")
workspace_module = importlib.import_module("harness.services.workspace")
```

- [ ] **Step 4: Update packaging test expectations**

In `tests/packaging/test_build_app_script.py`, replace `harness.core.workspace` expectations with `harness.services.workspace` if the packaging script no longer needs the core workspace module as a hidden import.

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/test_cli.py tests/packaging/test_build_app_script.py -q
```

Expected: PASS.

- [ ] **Step 6: Update `CODEMAP.md`**

Update the `src/cli.py` import description and any factory path notes so they reference `harness.core.factory` and `harness.services.workspace`.

## Task 2: Prove LiteRT-LM API Behavior On Apple Silicon

**Files:**
- Create: `scripts/probe_litert_lm.py`
- Create: `docs/runtime/litert-lm-migration-notes.md`
- Modify: `Lessons.md`

- [ ] **Step 1: Add the probe script**

Create `scripts/probe_litert_lm.py`:

```python
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--backend", choices=["gpu", "cpu"], default="gpu")
    parser.add_argument("--prompt", default="Say hello in one sentence.")
    parser.add_argument("--cache-dir", type=Path, default=Path("/tmp/dataharness-litert-cache"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        import litert_lm
    except Exception as exc:
        print(json.dumps({"ok": False, "phase": "import", "error": repr(exc)}))
        return 2

    backend = litert_lm.Backend.GPU if args.backend == "gpu" else litert_lm.Backend.CPU
    litert_lm.set_min_log_severity(litert_lm.LogSeverity.ERROR)
    started = time.perf_counter()
    try:
        with litert_lm.Engine(
            str(args.model),
            backend=backend,
            cache_dir=str(args.cache_dir),
            enable_speculative_decoding=(args.backend == "gpu"),
        ) as engine:
            chunks = []
            with engine.create_conversation(
                messages=[
                    {"role": "system", "content": [{"type": "text", "text": "You are concise."}]}
                ]
            ) as conversation:
                for chunk in conversation.send_message_async(args.prompt):
                    chunks.append(chunk)
            print(json.dumps({
                "ok": True,
                "python": sys.version.split()[0],
                "machine": platform.machine(),
                "backend": args.backend,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "chunk_count": len(chunks),
                "first_chunk_keys": sorted(chunks[0].keys()) if chunks else [],
                "chunks": chunks[:3],
            }, default=str))
            return 0
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "phase": "engine_or_stream",
            "backend": args.backend,
            "error": repr(exc),
        }))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Install the LiteRT-LM Python package in the project environment**

Run:

```bash
uv add litert-lm-api-nightly
```

Expected: `pyproject.toml` updated and `uv.lock` refreshed.

- [ ] **Step 3: Download the Gemma 4 E4B model manually for the spike**

Run:

```bash
uvx huggingface_hub download litert-community/gemma-4-E4B-it-litert-lm gemma-4-E4B-it.litertlm --local-dir /tmp/dataharness-litert-probe
```

Expected: `/tmp/dataharness-litert-probe/gemma-4-E4B-it.litertlm` exists.

- [ ] **Step 4: Run GPU probe**

Run:

```bash
uv run python scripts/probe_litert_lm.py --model /tmp/dataharness-litert-probe/gemma-4-E4B-it.litertlm --backend gpu
```

Expected: JSON with `"ok": true`, `"backend": "gpu"`, non-zero `chunk_count`, and `chunks` containing streamed text content.

- [ ] **Step 5: Run CPU probe**

Run:

```bash
uv run python scripts/probe_litert_lm.py --model /tmp/dataharness-litert-probe/gemma-4-E4B-it.litertlm --backend cpu
```

Expected: JSON with `"ok": true`, `"backend": "cpu"`, non-zero `chunk_count`, and slower `duration_ms` than GPU on the same prompt.

- [ ] **Step 6: Document confirmed API behavior**

Create `docs/runtime/litert-lm-migration-notes.md` with:

```markdown
# LiteRT-LM Migration Notes

Date: 2026-05-18

## Confirmed Package

- Python package: `litert-lm-api-nightly`
- Model repo: `litert-community/gemma-4-E4B-it-litert-lm`
- Model file: `gemma-4-E4B-it.litertlm`

## Confirmed macOS Apple Silicon Behavior

- GPU engine load:
- CPU engine load:
- GPU fallback trigger observed:
- Streaming chunk structure:
- System message behavior:
- Tool registration behavior:
- Sampling parameters exposed by Python API:
- Token/context metadata exposed by Python API:

## Runtime Decisions

- Backend policy: request GPU, fall back to CPU after engine-load failure.
- Speculative decoding: enable on GPU, disable on CPU.
- Tool execution policy: Layer 3 owns DataHarness tools; Layer 1 may register LiteRT-LM callable proxies that delegate through runtime-typed callbacks supplied by Layer 3.
- Token pressure policy:
```

Fill each bullet with the actual probe findings. Do not proceed past Task 2 until the notes file contains concrete results for every bullet.

- [ ] **Step 7: Update `Lessons.md`**

Add a brief entry under runtime lessons:

```markdown
- LiteRT-LM on macOS should be validated with a real `.litertlm` model before changing runtime code. Probe GPU and CPU separately, record chunk shape, tool behavior, sampling knobs, and whether token/context metadata is exposed.
```

## Task 3: Redesign Runtime Types And Config For LiteRT-LM

**Files:**
- Modify: `src/runtime/config.py`
- Modify: `src/runtime/types.py`
- Modify: `src/runtime/protocol.py`
- Modify: `tests/runtime/test_config.py`
- Modify: `tests/runtime/test_types.py`
- Create: `tests/runtime/test_protocol_shape.py`

- [ ] **Step 1: Write config tests**

Update `tests/runtime/test_config.py` to assert LiteRT-LM defaults:

```python
from runtime.config import RuntimeConfig


def test_runtime_config_defaults_to_litert_gemma4_e4b() -> None:
    cfg = RuntimeConfig(model_path="/models/gemma-4-E4B-it.litertlm")
    assert cfg.engine == "litert_lm"
    assert cfg.model_path == "/models/gemma-4-E4B-it.litertlm"
    assert cfg.model_family == "gemma4"
    assert cfg.model_variant == "e4b"
    assert cfg.preferred_backend == "gpu"
    assert cfg.allow_cpu_fallback is True
    assert cfg.enable_speculative_decoding is True
    assert cfg.cache_dir is None
    assert cfg.context_window == 131072
    assert cfg.enable_reasoning_stream is True


def test_runtime_config_removes_llama_cpp_fields() -> None:
    for field in ("chat_format", "n_batch", "n_gpu_layers", "offload_kqv", "flash_attn", "type_k", "type_v"):
        assert field not in RuntimeConfig.model_fields
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/runtime/test_config.py -q
```

Expected: FAIL because current config is llama.cpp-specific.

- [ ] **Step 3: Replace `RuntimeConfig`**

Replace `src/runtime/config.py` with:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


RuntimeBackend = Literal["gpu", "cpu"]


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_path: str
    engine: Literal["litert_lm"] = "litert_lm"
    model_family: str = "gemma4"
    model_variant: str = "e4b"
    preferred_backend: RuntimeBackend = "gpu"
    allow_cpu_fallback: bool = True
    cache_dir: str | None = None
    context_window: int = 131072
    max_completion_tokens_default: int = 2048
    enable_speculative_decoding: bool = True
    enable_reasoning_stream: bool = True
    bridge_queue_size: int = 64
```

- [ ] **Step 4: Extend runtime event/status types**

In `src/runtime/types.py`, add:

```python
RuntimeStatus = Literal["not_loaded", "loading", "ready", "streaming", "downloading", "error"]


class RuntimeBackendInfo(BaseModel):
    requested: Literal["gpu", "cpu"]
    active: Literal["gpu", "cpu"] | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
```

Keep existing `RuntimeRequest`, `RuntimeMessage`, `RuntimeEvent`, and `TokenPressure` compatible unless Task 2 proves LiteRT-LM requires richer message content. If richer content is required, add `content_parts: list[dict[str, Any]] | None = None` to `RuntimeMessage` while keeping `content: str` for text-only callers.

- [ ] **Step 5: Update protocol for backend introspection**

In `src/runtime/protocol.py`, add:

```python
from runtime.types import RuntimeBackendInfo

async def backend_info(self) -> RuntimeBackendInfo: ...
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run pytest tests/runtime/test_config.py tests/runtime/test_types.py tests/runtime/test_protocol_shape.py -q
```

Expected: PASS after tests are updated for the new `backend_info` protocol method.

## Task 4: Add Model Catalog And Download Service

**Files:**
- Create: `src/runtime/model_assets.py`
- Create: `src/harness/services/model_catalog.py`
- Create: `src/harness/services/model_download.py`
- Create: `tests/harness/test_model_catalog.py`
- Create: `tests/harness/test_model_download.py`
- Modify: `src/harness/services/__init__.py`

- [ ] **Step 1: Write model catalog tests**

Create `tests/harness/test_model_catalog.py`:

```python
from pathlib import Path

from harness.services.model_catalog import ModelCatalog, default_model_catalog


def test_default_catalog_contains_gemma4_e4b() -> None:
    catalog = default_model_catalog()
    model = catalog.get("gemma4-e4b")
    assert model.model_id == "gemma4-e4b"
    assert model.display_name == "Gemma 4 E4B"
    assert model.huggingface_repo == "litert-community/gemma-4-E4B-it-litert-lm"
    assert model.filename == "gemma-4-E4B-it.litertlm"
    assert model.preferred_backend == "gpu"
    assert model.allow_cpu_fallback is True


def test_catalog_resolves_install_path(tmp_path: Path) -> None:
    catalog = default_model_catalog()
    path = catalog.install_path(tmp_path, "gemma4-e4b")
    assert path == tmp_path / "models" / "gemma4-e4b" / "gemma-4-E4B-it.litertlm"


def test_catalog_reports_missing_model(tmp_path: Path) -> None:
    catalog = default_model_catalog()
    status = catalog.status(tmp_path, "gemma4-e4b")
    assert status.model_id == "gemma4-e4b"
    assert status.state == "missing"
    assert status.path.endswith("gemma-4-E4B-it.litertlm")
```

- [ ] **Step 2: Implement catalog models**

Create `src/harness/services/model_catalog.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


ModelInstallState = Literal["missing", "installed", "partial", "invalid"]


class ModelStatus(BaseModel):
    model_id: str
    state: ModelInstallState
    path: str
    bytes_on_disk: int = 0
    message: str = ""


@dataclass(frozen=True)
class ModelCatalogEntry:
    model_id: str
    display_name: str
    huggingface_repo: str
    filename: str
    size_bytes: int
    preferred_backend: Literal["gpu", "cpu"] = "gpu"
    allow_cpu_fallback: bool = True
    context_window: int = 131072


class ModelCatalog:
    def __init__(self, entries: list[ModelCatalogEntry]) -> None:
        self._entries = {entry.model_id: entry for entry in entries}

    def list(self) -> list[ModelCatalogEntry]:
        return list(self._entries.values())

    def get(self, model_id: str) -> ModelCatalogEntry:
        try:
            return self._entries[model_id]
        except KeyError as exc:
            raise ValueError(f"unknown model id: {model_id}") from exc

    def install_path(self, app_root: Path, model_id: str) -> Path:
        entry = self.get(model_id)
        return app_root / "models" / entry.model_id / entry.filename

    def status(self, app_root: Path, model_id: str) -> ModelStatus:
        path = self.install_path(app_root, model_id)
        if not path.exists():
            return ModelStatus(model_id=model_id, state="missing", path=str(path), message="model file not found")
        size = path.stat().st_size
        entry = self.get(model_id)
        if size <= 0:
            return ModelStatus(model_id=model_id, state="invalid", path=str(path), bytes_on_disk=size, message="empty model file")
        if size < max(entry.size_bytes // 2, 1):
            return ModelStatus(model_id=model_id, state="partial", path=str(path), bytes_on_disk=size, message="model file is smaller than expected")
        return ModelStatus(model_id=model_id, state="installed", path=str(path), bytes_on_disk=size, message="model installed")


def default_model_catalog() -> ModelCatalog:
    return ModelCatalog([
        ModelCatalogEntry(
            model_id="gemma4-e4b",
            display_name="Gemma 4 E4B",
            huggingface_repo="litert-community/gemma-4-E4B-it-litert-lm",
            filename="gemma-4-E4B-it.litertlm",
            size_bytes=3_654_000_000,
        )
    ])
```

- [ ] **Step 3: Write download service tests with a fake fetcher**

Create `tests/harness/test_model_download.py`:

```python
from pathlib import Path

from harness.services.model_catalog import default_model_catalog
from harness.services.model_download import DownloadProgress, ModelDownloadService


class FakeFetcher:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    def stream(self, repo: str, filename: str):
        assert repo == "litert-community/gemma-4-E4B-it-litert-lm"
        assert filename == "gemma-4-E4B-it.litertlm"
        for chunk in self.chunks:
            yield chunk


def test_download_writes_model_atomically(tmp_path: Path) -> None:
    service = ModelDownloadService(default_model_catalog(), fetcher=FakeFetcher([b"abc", b"def"]))
    events = list(service.download(tmp_path, "gemma4-e4b"))
    assert isinstance(events[-1], DownloadProgress)
    assert events[-1].state == "complete"
    path = tmp_path / "models" / "gemma4-e4b" / "gemma-4-E4B-it.litertlm"
    assert path.read_bytes() == b"abcdef"
    assert not path.with_suffix(path.suffix + ".partial").exists()
```

- [ ] **Step 4: Implement download service**

Create `src/harness/services/model_download.py`:

```python
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel

from harness.services.model_catalog import ModelCatalog


class ModelFetcher(Protocol):
    def stream(self, repo: str, filename: str) -> Iterator[bytes]: ...


class HuggingFaceModelFetcher:
    def stream(self, repo: str, filename: str) -> Iterator[bytes]:
        from huggingface_hub import hf_hub_download

        downloaded = Path(hf_hub_download(repo_id=repo, filename=filename))
        with downloaded.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk


class DownloadProgress(BaseModel):
    model_id: str
    state: Literal["starting", "downloading", "complete", "failed"]
    bytes_downloaded: int = 0
    path: str
    message: str = ""


class ModelDownloadService:
    def __init__(self, catalog: ModelCatalog, fetcher: ModelFetcher | None = None) -> None:
        self.catalog = catalog
        self.fetcher = fetcher or HuggingFaceModelFetcher()

    def download(self, app_root: Path, model_id: str) -> Iterator[DownloadProgress]:
        entry = self.catalog.get(model_id)
        final_path = self.catalog.install_path(app_root, model_id)
        partial_path = final_path.with_suffix(final_path.suffix + ".partial")
        final_path.parent.mkdir(parents=True, exist_ok=True)
        downloaded = 0
        yield DownloadProgress(model_id=model_id, state="starting", path=str(final_path))
        try:
            with partial_path.open("wb") as handle:
                for chunk in self.fetcher.stream(entry.huggingface_repo, entry.filename):
                    handle.write(chunk)
                    downloaded += len(chunk)
                    yield DownloadProgress(model_id=model_id, state="downloading", bytes_downloaded=downloaded, path=str(final_path))
            partial_path.replace(final_path)
            yield DownloadProgress(model_id=model_id, state="complete", bytes_downloaded=downloaded, path=str(final_path), message="model installed")
        except Exception as exc:
            yield DownloadProgress(model_id=model_id, state="failed", bytes_downloaded=downloaded, path=str(final_path), message=str(exc))
```

- [ ] **Step 5: Add dependency**

Run:

```bash
uv add huggingface_hub
```

Expected: `pyproject.toml` includes `huggingface_hub` and `uv.lock` is updated.

- [ ] **Step 6: Run tests**

Run:

```bash
uv run pytest tests/harness/test_model_catalog.py tests/harness/test_model_download.py -q
```

Expected: PASS.

## Task 5: Add Model Commands And Startup Status

**Files:**
- Create: `src/harness/commands/model.py`
- Modify: `src/harness/commands/__init__.py`
- Modify: `src/harness/orchestrator.py`
- Modify: `src/harness/status.py`
- Create: `tests/harness/test_model_commands.py`

- [ ] **Step 1: Write command tests**

Create `tests/harness/test_model_commands.py`:

```python
from pathlib import Path

import pytest

from harness.orchestrator import Orchestrator


@pytest.mark.asyncio
async def test_model_status_reports_missing_default_model(tmp_path: Path) -> None:
    orch = Orchestrator(runtime=None, app_root=tmp_path)
    events = [event async for event in orch.handle_direct_command("model_status", {})]
    completed = events[-1]
    assert completed.command_name == "model_status"
    assert completed.result["model_id"] == "gemma4-e4b"
    assert completed.result["state"] == "missing"


@pytest.mark.asyncio
async def test_model_use_rejects_unknown_model(tmp_path: Path) -> None:
    orch = Orchestrator(runtime=None, app_root=tmp_path)
    events = [event async for event in orch.handle_direct_command("model_use", {"model_id": "bad"})]
    completed = events[-1]
    assert completed.command_name == "model_use"
    assert completed.result["error"] == "unknown model id: bad"
```

- [ ] **Step 2: Implement model command registrar**

Create `src/harness/commands/model.py`:

```python
from __future__ import annotations

from harness.core.command_registry import ArgSpec, HarnessCommandRegistry


def register_model_commands(registry: HarnessCommandRegistry, orchestrator) -> None:
    registry.register(
        "model_status",
        "Show installed model status.",
        [],
        orchestrator._handle_model_status,
    )
    registry.register(
        "model_download",
        "Download the default Gemma 4 E4B LiteRT-LM model.",
        [ArgSpec(name="model_id", required=False, default="gemma4-e4b")],
        orchestrator._handle_model_download,
    )
    registry.register(
        "model_use",
        "Select an installed model.",
        [ArgSpec(name="model_id", required=True)],
        orchestrator._handle_model_use,
    )
    registry.register(
        "model_delete",
        "Delete an installed model.",
        [ArgSpec(name="model_id", required=True)],
        orchestrator._handle_model_delete,
    )
```

- [ ] **Step 3: Register commands in orchestrator**

In `Orchestrator._register_commands`, import and call:

```python
from harness.commands.model import register_model_commands

register_model_commands(self.registry, self)
```

- [ ] **Step 4: Add orchestrator handlers**

Add handlers in `src/harness/orchestrator.py` that use `default_model_catalog()` and `ModelDownloadService`. The download handler must yield `CommandProgress` for each `DownloadProgress` and a final `CommandCompleted` with `state`, `bytes_downloaded`, and `path`.

- [ ] **Step 5: Run command tests**

Run:

```bash
uv run pytest tests/harness/test_model_commands.py tests/harness/test_command_family_ownership.py -q
```

Expected: PASS.

## Task 6: Add First-Run Model Download UX

**Files:**
- Create: `src/app/tui/screens/model_manager.py`
- Modify: `src/app/tui/screens/__init__.py`
- Modify: `src/app/tui/app.py`
- Modify: `src/app/event_mapping.py`
- Modify: `src/app/events.py`
- Create: `tests/app/tui/test_model_manager.py`

- [ ] **Step 1: Write TUI model screen tests**

Create `tests/app/tui/test_model_manager.py`:

```python
from app.tui.screens.model_manager import ModelManagerScreen


def test_model_manager_renders_missing_state() -> None:
    screen = ModelManagerScreen(
        model_id="gemma4-e4b",
        display_name="Gemma 4 E4B",
        state="missing",
        path="/tmp/models/gemma4-e4b/gemma-4-E4B-it.litertlm",
    )
    assert screen.model_id == "gemma4-e4b"
    assert screen.display_name == "Gemma 4 E4B"
    assert screen.state == "missing"
```

- [ ] **Step 2: Implement screen skeleton**

Create `src/app/tui/screens/model_manager.py`:

```python
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, ProgressBar, Static


class ModelManagerScreen(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, *, model_id: str, display_name: str, state: str, path: str) -> None:
        super().__init__()
        self.model_id = model_id
        self.display_name = display_name
        self.state = state
        self.path = path

    def compose(self) -> ComposeResult:
        with Vertical(id="model_manager"):
            yield Label(self.display_name, id="model_title")
            yield Static(f"status: {self.state}", id="model_state")
            yield Static(self.path, id="model_path")
            yield ProgressBar(total=100, show_eta=False, id="model_download_progress")
            yield Button("Download", id="model_download", variant="primary")
            yield Button("Use CPU", id="model_use_cpu")
            yield Button("Close", id="model_close")
```

- [ ] **Step 3: Wire startup model status check**

In `DataHarnessApp.on_mount`, after workspace snapshot setup, run `model_status`. If the result state is `missing`, push `ModelManagerScreen`.

- [ ] **Step 4: Wire download button**

When `#model_download` is pressed, call `_stream_command("model_download", {"model_id": "gemma4-e4b"})`. Update `#model_download_progress` from `CommandProgress` events.

- [ ] **Step 5: Run TUI tests**

Run:

```bash
uv run pytest tests/app/tui/test_model_manager.py tests/app/tui/test_textual_app.py -q
```

Expected: PASS.

## Task 7: Implement LiteRT-LM Message Conversion

**Files:**
- Create: `src/runtime/litert_messages.py`
- Create: `tests/runtime/test_litert_messages.py`
- Modify: `src/harness/services/chat.py`

- [ ] **Step 1: Write message conversion tests**

Create `tests/runtime/test_litert_messages.py`:

```python
from runtime.litert_messages import to_litert_messages
from runtime.types import RuntimeMessage


def test_to_litert_messages_preserves_system_user_assistant_order() -> None:
    messages = [
        RuntimeMessage(role="system", content="system text"),
        RuntimeMessage(role="user", content="hello"),
        RuntimeMessage(role="assistant", content="hi"),
    ]
    converted = to_litert_messages(messages)
    assert [item["role"] for item in converted] == ["system", "user", "assistant"]
    assert converted[0]["content"] == [{"type": "text", "text": "system text"}]
    assert converted[1]["content"] == [{"type": "text", "text": "hello"}]


def test_to_litert_messages_maps_tool_messages_to_text_blocks() -> None:
    messages = [RuntimeMessage(role="tool", content='{"ok": true}', name="file_read", tool_call_id="call_1")]
    converted = to_litert_messages(messages)
    assert converted == [{
        "role": "tool",
        "content": [{"type": "text", "text": '{"ok": true}'}],
        "name": "file_read",
        "tool_call_id": "call_1",
    }]
```

- [ ] **Step 2: Implement conversion helper**

Create `src/runtime/litert_messages.py`:

```python
from __future__ import annotations

from typing import Any

from runtime.types import RuntimeMessage


def to_litert_messages(messages: list[RuntimeMessage]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        item: dict[str, Any] = {
            "role": message.role,
            "content": [{"type": "text", "text": message.content}],
        }
        if message.name is not None:
            item["name"] = message.name
        if message.tool_call_id is not None:
            item["tool_call_id"] = message.tool_call_id
        converted.append(item)
    return converted
```

- [ ] **Step 3: Run tests**

Run:

```bash
uv run pytest tests/runtime/test_litert_messages.py -q
```

Expected: PASS.

- [ ] **Step 4: Update `RuntimeRequestBuilder` prompts**

In `src/harness/services/chat.py`, remove Gemma llama.cpp system-message folding assumptions. Preserve system messages as `RuntimeMessage(role="system", ...)`, because LiteRT-LM supports conversation `messages=[{"role": "system", ...}]`.

## Task 8: Implement LiteRT-LM Runtime With GPU Fallback

**Files:**
- Create: `src/runtime/litert_lm_runtime.py`
- Create: `tests/runtime/test_litert_lm_runtime.py`
- Modify: `src/runtime/__init__.py`

- [ ] **Step 1: Write fake-module runtime tests**

Create `tests/runtime/test_litert_lm_runtime.py`:

```python
import asyncio
from types import SimpleNamespace

import pytest

from runtime.config import RuntimeConfig
from runtime.litert_lm_runtime import LiteRTLmRuntime
from runtime.types import RuntimeMessage, RuntimeRequest


class FakeConversation:
    def __init__(self, chunks):
        self.chunks = chunks
        self.messages = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def send_message_async(self, message):
        for chunk in self.chunks:
            yield chunk


class FakeEngine:
    failures = []

    def __init__(self, model_path, **kwargs):
        if kwargs["backend"].name in self.failures:
            raise RuntimeError(f"{kwargs['backend'].name} unavailable")
        self.model_path = model_path
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def create_conversation(self, **kwargs):
        return FakeConversation([
            {"content": [{"type": "text", "text": "hel"}]},
            {"content": [{"type": "text", "text": "lo"}]},
        ])


class FakeBackend:
    GPU = SimpleNamespace(name="GPU")
    CPU = SimpleNamespace(name="CPU")


def fake_litert_module():
    return SimpleNamespace(
        Engine=FakeEngine,
        Backend=FakeBackend,
        LogSeverity=SimpleNamespace(ERROR="ERROR"),
        set_min_log_severity=lambda severity: None,
    )


@pytest.mark.asyncio
async def test_litert_runtime_streams_text(monkeypatch):
    monkeypatch.setattr("runtime.litert_lm_runtime._import_litert_lm", fake_litert_module)
    runtime = LiteRTLmRuntime(RuntimeConfig(model_path="/tmp/model.litertlm"))
    request = RuntimeRequest(
        messages=[RuntimeMessage(role="user", content="hello")],
        max_completion_tokens=32,
        request_id="r1",
    )
    events = [event async for event in runtime.stream(request)]
    assert [event.type for event in events] == ["text_delta", "text_delta", "finish"]
    assert "".join(event.text or "" for event in events) == "hello"


@pytest.mark.asyncio
async def test_litert_runtime_falls_back_to_cpu(monkeypatch):
    FakeEngine.failures = ["GPU"]
    monkeypatch.setattr("runtime.litert_lm_runtime._import_litert_lm", fake_litert_module)
    runtime = LiteRTLmRuntime(RuntimeConfig(model_path="/tmp/model.litertlm"))
    info = await runtime.backend_info()
    assert info.requested == "gpu"
    assert info.active == "cpu"
    assert info.fallback_used is True
    FakeEngine.failures = []
```

- [ ] **Step 2: Implement runtime**

Create `src/runtime/litert_lm_runtime.py` with these required behaviors:
- import `litert_lm` lazily through `_import_litert_lm()`
- set log severity to ERROR
- try GPU first when configured
- on GPU engine-load failure and `allow_cpu_fallback=True`, emit telemetry and retry CPU
- expose `backend_info()`
- convert chunks containing `{"content": [{"type": "text", "text": "..."}]}` to `RuntimeEvent(type="text_delta")`
- emit one finish event with `finish_reason="stop"`
- use `SyncToAsyncBridge` if LiteRT-LM streaming iterator blocks the event loop in probe results

- [ ] **Step 3: Run runtime tests**

Run:

```bash
uv run pytest tests/runtime/test_litert_lm_runtime.py tests/runtime/test_bridge.py -q
```

Expected: PASS.

## Task 9: Design And Implement LiteRT-LM Native Tool Bridge

**Files:**
- Create: `src/runtime/litert_tools.py`
- Create: `tests/runtime/test_litert_tools.py`
- Modify: `src/runtime/types.py`
- Modify: `src/harness/orchestrator.py`
- Modify: `tests/harness/test_agentic_turn.py`

- [ ] **Step 1: Confirm native tool callback behavior from Task 2 notes**

Read `docs/runtime/litert-lm-migration-notes.md`. Continue only when it confirms whether LiteRT-LM Python tool functions:
- auto-execute synchronously inside `send_message` / `send_message_async`
- can receive normal Python type hints/docstrings
- can return strings/dicts
- expose a tool-call event before execution

- [ ] **Step 2: Write tool proxy tests**

Create `tests/runtime/test_litert_tools.py`:

```python
from runtime.litert_tools import build_litert_tool_proxy


def test_tool_proxy_delegates_to_callback() -> None:
    calls = []

    def callback(name: str, arguments: dict):
        calls.append((name, arguments))
        return {"ok": True}

    proxy = build_litert_tool_proxy(
        name="file_read",
        description="Read a workspace file.",
        parameters={"path": {"type": "string"}},
        callback=callback,
    )

    assert proxy.__name__ == "file_read"
    assert proxy(path="data/sales.csv") == {"ok": True}
    assert calls == [("file_read", {"path": "data/sales.csv"})]
```

- [ ] **Step 3: Implement proxy builder**

Create `src/runtime/litert_tools.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from typing import Any


RuntimeToolCallback = Callable[[str, dict[str, Any]], Any]


def build_litert_tool_proxy(
    *,
    name: str,
    description: str,
    parameters: dict[str, Any],
    callback: RuntimeToolCallback,
) -> Callable[..., Any]:
    def proxy(**kwargs: Any) -> Any:
        return callback(name, dict(kwargs))

    proxy.__name__ = name
    proxy.__doc__ = _render_docstring(description, parameters)
    return proxy


def _render_docstring(description: str, parameters: dict[str, Any]) -> str:
    lines = [description, "", "Args:"]
    for arg_name, spec in parameters.items():
        arg_description = spec.get("description", "")
        lines.append(f"    {arg_name}: {arg_description}")
    return "\n".join(lines)
```

- [ ] **Step 4: Add Layer 3 callback bridge**

In `src/harness/orchestrator.py`, add a private method that turns `HarnessToolRegistry` descriptors into LiteRT-LM tool proxy callbacks. The callback must:
- validate tool name against `self.tool_registry`
- dispatch through `_dispatch_tool_call` for deterministic tools
- return compact JSON-serializable results
- for approval-gated analysis tools, return a structured message telling the model that approval is pending and emit existing approval events through the normal orchestrator path

- [ ] **Step 5: Preserve approval boundaries**

Add regression coverage in `tests/harness/test_agentic_turn.py` proving:
- model-facing file/knowledge tools route through Layer 3 registry
- `analysis_plan` still emits `ApprovalRequired`
- worker execution still requires user approval
- Layer 1 imports no `harness.*` modules

- [ ] **Step 6: Run tool bridge tests**

Run:

```bash
uv run pytest tests/runtime/test_litert_tools.py tests/harness/test_agentic_turn.py tests/app/tui/test_layer_boundaries.py -q
```

Expected: PASS.

## Task 10: Migrate Prompt Profiles And Runtime-Backed Harness Flows

**Files:**
- Modify: `src/harness/services/prompt_profiles.py`
- Modify: `src/harness/prompts/system.md`
- Modify: `src/harness/prompts/interaction.md`
- Modify: `src/harness/prompts/analyst.md`
- Modify: `src/harness/prompts/knowledge.md`
- Modify: `src/harness/prompts/doctor.md`
- Modify: `src/harness/prompts/compaction.md`
- Modify: `src/harness/prompts/response_format.md`
- Modify: `src/harness/services/chat.py`
- Modify: `src/harness/services/doctor.py`
- Modify: `src/harness/services/mode_router.py`
- Modify: `tests/harness/test_prompt_profiles.py`
- Modify: `tests/harness/test_runtime_request_builder.py`
- Modify: `tests/harness/test_chat_compaction.py`
- Modify: `tests/harness/test_doctor_runner.py`

- [ ] **Step 1: Update prompt-profile tests**

Update tests so they assert:
- system instructions remain a separate system message
- tool catalog is passed as LiteRT-LM native tools, not embedded prompt-only XML
- analyst profile does not ask for literal `<tool_call>` tags
- compaction and doctor prompts do not mention llama/GGUF/chat-format behavior

- [ ] **Step 2: Rewrite prompts**

Rewrite prompt files around LiteRT-LM/Gemma 4 E4B:
- `system.md`: DataHarness role, local-first constraints, layer boundaries, concise answer style.
- `interaction.md`: conversational data assistance and clarification behavior.
- `analyst.md`: ask model to use native tools for planning, inspection, and execution request flow.
- `knowledge.md`: native knowledge recall/proposal tools.
- `doctor.md`: semantic diagnostics using native tools only when needed.
- `compaction.md`: handoff checkpoint summary, no transcript echo.
- `response_format.md`: normal answer formatting, no prompt-level tool-call XML.

- [ ] **Step 3: Update request builder**

In `src/harness/services/chat.py`, build system messages as first-class `RuntimeMessage(role="system")`, keep recent chat history in role order, and pass model-facing tool descriptors via `RuntimeRequest.tools`.

- [ ] **Step 4: Update runtime-backed doctor and router flows**

Remove llama-specific stop strings and prompt repair assumptions from:
- `DoctorRunner._render_narration`
- semantic doctor phases
- `ModeRouter` LLM fallback path

- [ ] **Step 5: Run harness prompt/flow tests**

Run:

```bash
uv run pytest tests/harness/test_prompt_profiles.py tests/harness/test_runtime_request_builder.py tests/harness/test_chat_compaction.py tests/harness/test_doctor_runner.py tests/harness/test_mode_router.py -q
```

Expected: PASS.

## Task 11: Switch CLI Factory And Remove llama.cpp

**Files:**
- Modify: `src/cli.py`
- Modify: `pyproject.toml`
- Modify: `src/runtime/__init__.py`
- Delete: `src/runtime/llama_cpp_runtime.py`
- Modify/Delete: llama-specific runtime tests
- Modify: `tests/test_cli.py`
- Modify: `tests/runtime/test_runtime_layer_boundaries.py`

- [ ] **Step 1: Update CLI factory test**

In `tests/test_cli.py`, assert the default runtime factory imports `runtime.litert_lm_runtime` and constructs `LiteRTLmRuntime`.

- [ ] **Step 2: Update `_default_runtime_factory`**

Change `src/cli.py`:

```python
def _default_runtime_factory(config, telemetry):
    runtime_module = importlib.import_module("runtime.litert_lm_runtime")
    return runtime_module.LiteRTLmRuntime(config, telemetry=telemetry)
```

- [ ] **Step 3: Update default model path**

Change default model path in `build_app` to:

```python
default_model_path = Path("models/gemma4-e4b/gemma-4-E4B-it.litertlm")
```

- [ ] **Step 4: Remove llama dependency**

Run:

```bash
uv remove llama-cpp-python
```

Expected: `pyproject.toml` no longer contains `llama-cpp-python`; `uv.lock` is updated.

- [ ] **Step 5: Remove llama runtime file**

Delete `src/runtime/llama_cpp_runtime.py`.

- [ ] **Step 6: Run runtime and CLI tests**

Run:

```bash
uv run pytest tests/runtime tests/test_cli.py -q
```

Expected: PASS after deleting or replacing llama-specific tests.

## Task 12: Update Observability For LiteRT-LM And Downloads

**Files:**
- Modify: `src/observability/events.py`
- Modify: `docs/observability.md`
- Modify: `tests/observability/test_events.py`
- Modify: `tests/observability/test_telemetry.py`

- [ ] **Step 1: Add event tests**

Update `tests/observability/test_events.py` to include:
- `runtime.backend.selected`
- `runtime.backend.fallback`
- `runtime.model.download.start`
- `runtime.model.download.progress`
- `runtime.model.download.end`
- `runtime.model.verify.start`
- `runtime.model.verify.end`

- [ ] **Step 2: Add event kinds**

In `src/observability/events.py`, add:

```python
RUNTIME_BACKEND_SELECTED = "runtime.backend.selected"
RUNTIME_BACKEND_FALLBACK = "runtime.backend.fallback"
RUNTIME_MODEL_DOWNLOAD_START = "runtime.model.download.start"
RUNTIME_MODEL_DOWNLOAD_PROGRESS = "runtime.model.download.progress"
RUNTIME_MODEL_DOWNLOAD_END = "runtime.model.download.end"
RUNTIME_MODEL_VERIFY_START = "runtime.model.verify.start"
RUNTIME_MODEL_VERIFY_END = "runtime.model.verify.end"
```

- [ ] **Step 3: Emit payload fields**

Runtime/load telemetry must include:
- `engine`
- `model_family`
- `model_variant`
- `model_format`
- `backend_requested`
- `backend_active`
- `fallback_used`
- `fallback_reason`
- `speculative_decoding`

Download telemetry must include:
- `model_id`
- `repo`
- `filename`
- `bytes_downloaded`
- `path`
- `state`

- [ ] **Step 4: Update docs**

In `docs/observability.md`, document the new LiteRT-LM runtime and model-download events.

- [ ] **Step 5: Run observability tests**

Run:

```bash
uv run pytest tests/observability -q
```

Expected: PASS.

## Task 13: Update Packaging For LiteRT-LM

**Files:**
- Modify: `scripts/build_app.sh`
- Modify: `tests/packaging/test_build_app_script.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Update packaging tests**

In `tests/packaging/test_build_app_script.py`, assert:

```python
assert "--hidden-import runtime.litert_lm_runtime" in script
assert "--collect-all litert_lm" in script
assert "--collect-all llama_cpp" not in script
assert "--hidden-import runtime.llama_cpp_runtime" not in script
```

- [ ] **Step 2: Update build script**

In `scripts/build_app.sh`:
- replace `--hidden-import runtime.llama_cpp_runtime` with `--hidden-import runtime.litert_lm_runtime`
- add `--hidden-import runtime.litert_messages`
- add `--hidden-import runtime.litert_tools`
- add `--collect-all litert_lm`
- remove `--collect-all llama_cpp`

- [ ] **Step 3: Run packaging tests**

Run:

```bash
uv run pytest tests/packaging/test_build_app_script.py -q
```

Expected: PASS.

## Task 14: Full Source Verification

**Files:**
- No source changes unless verification exposes failures.

- [ ] **Step 1: Run focused runtime suite**

Run:

```bash
uv run pytest tests/runtime -q
```

Expected: PASS.

- [ ] **Step 2: Run harness runtime integration suite**

Run:

```bash
uv run pytest tests/harness/test_runtime_bridge.py tests/harness/test_agentic_turn.py tests/harness/test_force_plan_tool_call.py tests/harness/test_chat_compaction.py tests/harness/test_doctor_runner.py -q
```

Expected: PASS.

- [ ] **Step 3: Run model UX and packaging tests**

Run:

```bash
uv run pytest tests/harness/test_model_catalog.py tests/harness/test_model_download.py tests/harness/test_model_commands.py tests/app/tui/test_model_manager.py tests/packaging/test_build_app_script.py -q
```

Expected: PASS.

- [ ] **Step 4: Run full suite**

Run:

```bash
uv run pytest -q
```

Expected: PASS or only documented load-sensitive worker timeout from `Issues.md`.

## Task 15: Source Smoke Test With Real Model

**Files:**
- No source changes unless smoke test exposes failures.

- [ ] **Step 1: Start source app with empty model directory**

Run from repo root with a temporary app root:

```bash
DATAHARNESS_APP_ROOT=/tmp/dataharness-litert-smoke uv run dataharness
```

Expected:
- app starts
- model setup screen appears
- default model is Gemma 4 E4B
- download action is visible

- [ ] **Step 2: Download model through app UX**

Use the model setup screen to download Gemma 4 E4B.

Expected:
- progress updates
- final model path is `/tmp/dataharness-litert-smoke/models/gemma4-e4b/gemma-4-E4B-it.litertlm`
- `runtime.model.download.end` telemetry has `state="complete"`

- [ ] **Step 3: Run first prompt**

Prompt:

```text
Say hello and list the active runtime backend.
```

Expected:
- answer streams into the conversation
- runtime status returns to ready
- runtime telemetry shows `backend_active="gpu"` on Apple Silicon when GPU load succeeds

- [ ] **Step 4: Simulate GPU fallback**

Run with an environment flag or test config that forces GPU load failure.

Expected:
- app does not crash
- runtime telemetry contains `runtime.backend.fallback`
- `backend_active="cpu"`
- user-visible status indicates CPU fallback

## Task 16: Packaged macOS Verification

**Files:**
- Modify packaging rules only if verification exposes missing native assets.

- [ ] **Step 1: Build package**

Run:

```bash
bash scripts/build_app.sh
```

Expected: `dist/dataharness` exists.

- [ ] **Step 2: Run packaged app with empty app root**

Run:

```bash
DATAHARNESS_APP_ROOT=/tmp/dataharness-litert-packaged-smoke ./dist/dataharness
```

Expected:
- app starts
- model setup screen appears
- download can complete
- first prompt streams
- GPU backend selected or CPU fallback reported cleanly

- [ ] **Step 3: Inspect logs**

Check:

```bash
grep -E "runtime.backend|runtime.model.download|runtime.stream" /tmp/dataharness-litert-packaged-smoke/logs/*.log
```

Expected:
- backend selection/fallback is visible
- model download completion is visible
- runtime stream start/end is visible

## Task 17: Documentation And CODEMAP

**Files:**
- Modify: `CODEMAP.md`
- Modify: `Lessons.md`
- Modify: `README.md`
- Modify: `docs/observability.md`
- Create: `docs/runtime/litert-lm.md`

- [ ] **Step 1: Update `CODEMAP.md`**

Update all four tracked relationship types:
- imports changed from `runtime.llama_cpp_runtime` to `runtime.litert_lm_runtime`
- new model catalog/download services
- new model commands
- new TUI model manager screen
- removed llama definitions
- new LiteRT-LM runtime definitions and call sites

- [ ] **Step 2: Add runtime docs**

Create `docs/runtime/litert-lm.md` documenting:
- macOS Apple Silicon support scope
- GPU-first CPU-fallback behavior
- Gemma 4 E4B model source
- model download path
- environment overrides
- native tool bridge boundary
- telemetry fields
- troubleshooting import, download, GPU, and CPU fallback failures

- [ ] **Step 3: Update `Lessons.md`**

Add durable lessons:
- LiteRT-LM runtime migration is full replacement, not llama-compatible wrapping.
- Layer 3 owns DataHarness tool policy even when LiteRT-LM provides native tool callbacks.
- Model setup UX belongs in Layer 4, but model catalog/download state belongs in Layer 3 services.
- macOS Apple Silicon backend should request GPU and fall back to CPU with explicit telemetry.

- [ ] **Step 4: Run docs consistency checks**

Run:

```bash
rg -n "llama|llama_cpp|GGUF|chat_format|n_gpu_layers" src tests docs README.md pyproject.toml scripts CODEMAP.md
```

Expected:
- no active runtime dependency on llama.cpp remains
- historical archived docs may still mention llama.cpp
- new docs only mention llama.cpp as removed legacy runtime

## Final Acceptance Checklist

- [ ] `llama-cpp-python` is absent from `pyproject.toml`.
- [ ] `src/runtime/llama_cpp_runtime.py` is deleted.
- [ ] `scripts/build_app.sh` does not collect `llama_cpp`.
- [ ] Default model path is `models/gemma4-e4b/gemma-4-E4B-it.litertlm`.
- [ ] Missing model launches model setup UX, not an empty failed assistant message.
- [ ] Model download installs from `litert-community/gemma-4-E4B-it-litert-lm`.
- [ ] Runtime requests GPU first on Apple Silicon.
- [ ] Runtime falls back to CPU with visible telemetry and user status.
- [ ] LiteRT-LM native tool path preserves Layer 3 ownership of tool policy and approval.
- [ ] Worker execution approval remains unchanged.
- [ ] Runtime, harness, TUI, observability, and packaging tests pass.
- [ ] Packaged macOS app can download, load, and stream with Gemma 4 E4B.

## Plan Self-Review

Spec coverage:
- macOS Apple Silicon scope: covered in constraints, runtime config, smoke, package verification.
- GPU fallback to CPU: covered in Tasks 3, 8, 12, 15, 16.
- Gemma 4 E4B: covered in model catalog, CLI default path, download UX.
- Model download UX: covered in Tasks 4, 5, 6, 15.
- Full llama.cpp removal: covered in Tasks 11, 13, 17.
- LiteRT-LM-native prompts/tools/settings: covered in Tasks 2, 8, 9, 10.
- Layer impact map: covered in current state map, target file structure, and task file lists.
- Telemetry/logs: covered in Task 12.

Placeholder scan:
- The plan intentionally contains a Task 2 discovery gate because native LiteRT-LM tool behavior must be proven from the installed package and model. That gate writes concrete findings before runtime implementation proceeds.
- The plan does not use unresolved implementation placeholders for model identity, repo, filename, target backend, app paths, or package names.

Type consistency:
- `RuntimeConfig.preferred_backend`, `RuntimeBackendInfo.requested`, and `RuntimeBackendInfo.active` consistently use `"gpu"` / `"cpu"` in DataHarness types.
- LiteRT-LM package backend constants are isolated inside `LiteRTLmRuntime`.
- Model id is consistently `gemma4-e4b`.
