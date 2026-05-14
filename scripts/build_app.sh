#!/usr/bin/env bash
set -euo pipefail

# Build standalone macOS CLI binary at dist/dataharness via PyInstaller.

cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

mkdir -p dist

uv run --with pyinstaller pyinstaller \
  --noconfirm \
  --clean \
  --onefile \
  --name dataharness \
  --paths src \
  --hidden-import app.tui.app \
  --hidden-import app.session \
  --hidden-import harness.control \
  --hidden-import harness.factory \
  --hidden-import harness.workspace \
  --hidden-import runtime.config \
  --hidden-import runtime.llama_cpp_runtime \
  --hidden-import worker.sandbox_bootstrap \
  --add-data "${PROJECT_ROOT}/src/app/agents/prompts:app/agents/prompts" \
  --add-data "${PROJECT_ROOT}/src/app/tui/dataharness.tcss:app/tui" \
  --add-data "${PROJECT_ROOT}/src/harness/prompts:harness/prompts" \
  --collect-submodules app \
  --collect-submodules harness \
  --collect-submodules observability \
  --collect-submodules runtime \
  --collect-submodules worker \
  --collect-all textual \
  --collect-all pydantic \
  --collect-all pydantic_core \
  --collect-all llama_cpp \
  --collect-all pandas \
  --collect-all numpy \
  --distpath dist \
  --workpath build/pyinstaller \
  --specpath build/pyinstaller \
  src/cli.py

echo
echo "Built: dist/dataharness"
file dist/dataharness
