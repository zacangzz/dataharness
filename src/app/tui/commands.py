from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, cast

from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.types import IgnoreReturnCallbackType

from harness.core.command_registry import CommandContext, HarnessCommandDescriptor

if TYPE_CHECKING:
    from app.tui.app import DataHarnessApp


def build_command_context(app: DataHarnessApp) -> CommandContext:
    return CommandContext(
        workspace_id=app.state.workspace_id,
        chat_id=app.active_chat_id,
        run_id=app.state.run_id,
        has_pending_approval=False,
        has_pending_clarification=False,
    )


def command_title(descriptor: HarnessCommandDescriptor) -> str:
    title = descriptor.slash_alias.lstrip("/")
    if descriptor.available:
        return title
    reason = descriptor.disabled_reason or "unavailable"
    return f"{title} ({reason})"


def build_command_prefill(descriptor: HarnessCommandDescriptor) -> str:
    parts = [descriptor.slash_alias]
    parts.extend(f"<{arg.name}>" for arg in descriptor.arguments if arg.required)
    return " ".join(parts)


EXIT_DESCRIPTOR = HarnessCommandDescriptor(
    name="exit",
    slash_alias="/exit",
    short_description="Exit the application",
    arguments=[],
    available=True,
    affected_resource="workspace",
    expected_event_types=[],
    example_usage="/exit",
)


class DataHarnessCommandProvider(Provider):
    async def _descriptors(self) -> list[HarnessCommandDescriptor]:
        app = cast("DataHarnessApp", self.screen.app)
        descriptors = await app.session.list_commands(build_command_context(app))
        return [*descriptors, EXIT_DESCRIPTOR]

    def _callback_for(self, descriptor: HarnessCommandDescriptor) -> IgnoreReturnCallbackType:
        app = cast("DataHarnessApp", self.screen.app)
        return cast(
            IgnoreReturnCallbackType,
            partial(app.handle_command_palette_selection, descriptor),
        )

    async def discover(self) -> Hits:
        for descriptor in await self._descriptors():
            title = command_title(descriptor)
            yield DiscoveryHit(
                title,
                self._callback_for(descriptor),
                text=title,
                help=descriptor.short_description,
            )

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for descriptor in await self._descriptors():
            title = command_title(descriptor)
            score = matcher.match(title)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(title),
                    self._callback_for(descriptor),
                    text=title,
                    help=descriptor.short_description,
                )
