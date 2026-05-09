from __future__ import annotations

from collections.abc import Callable

from app.events import AppEvent


Handler = Callable[[AppEvent], None]


class EventConsumer:
    def __init__(self, handlers: dict[str, Handler]) -> None:
        self.handlers = handlers

    def dispatch(self, event: AppEvent) -> None:
        handler = self.handlers.get(event.event_name)
        if handler is not None:
            handler(event)
