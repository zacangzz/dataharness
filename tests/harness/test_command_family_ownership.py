from dataclasses import dataclass
from typing import Any

from harness.core.command_registry import HarnessCommandDescriptor
from harness.commands.compact import register_compact_commands
from harness.commands.diagnostics import register_diagnostics_commands
from harness.commands.doctor import register_doctor_commands
from harness.orchestrator import Orchestrator


@dataclass
class _FakeRegistry:
    names: list[str]

    def register(self, descriptor: HarnessCommandDescriptor, handler: Any) -> None:
        self.names.append(descriptor.name)


class _FakeOrchestrator:
    async def _handle_doctor(self, ctx, args):
        if False:
            yield None

    async def _handle_compact(self, ctx, args):
        if False:
            yield None

    async def _handle_help(self, ctx, args):
        if False:
            yield None


def test_doctor_and_compact_have_dedicated_command_modules() -> None:
    fake = _FakeOrchestrator()
    doctor_registry = _FakeRegistry([])
    compact_registry = _FakeRegistry([])

    register_doctor_commands(fake, doctor_registry)
    register_compact_commands(fake, compact_registry)

    assert doctor_registry.names == ["doctor"]
    assert compact_registry.names == ["compact"]


def test_diagnostics_registrar_no_longer_owns_doctor_or_compact() -> None:
    fake = _FakeOrchestrator()
    registry = _FakeRegistry([])

    register_diagnostics_commands(fake, registry)

    assert registry.names == ["help"]


def test_orchestrator_still_registers_doctor_and_compact(tmp_path) -> None:
    orch = Orchestrator(app_root=tmp_path)

    names = {descriptor.name for descriptor in orch.registry.help().commands}

    assert "doctor" in names
    assert "compact" in names
