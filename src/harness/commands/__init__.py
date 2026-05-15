"""Command family registration modules.

Each module exposes a ``register_<family>_commands(orchestrator, registry)``
function that registers HarnessCommandDescriptors and wires them to handler
methods that still live on the Orchestrator. Behaviour and descriptors are
unchanged relative to the previous monolithic ``Orchestrator._register_commands``.
"""

from harness.commands.chat import register_chat_commands
from harness.commands.diagnostics import register_diagnostics_commands
from harness.commands.memory import register_memory_commands
from harness.commands.provenance import register_provenance_commands
from harness.commands.run import register_run_commands
from harness.commands.workspace import register_workspace_commands

__all__ = [
    "register_chat_commands",
    "register_diagnostics_commands",
    "register_memory_commands",
    "register_provenance_commands",
    "register_run_commands",
    "register_workspace_commands",
]
