from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class Layer(str, Enum):
    BOOTSTRAP = "bootstrap"
    APP = "app"
    HARNESS = "harness"
    RUNTIME = "runtime"
    WORKER = "worker"
    PERSISTENCE = "persistence"


class Outcome(str, Enum):
    OK = "ok"
    ERROR = "error"


class EventKind(str, Enum):
    BOOTSTRAP_START = "bootstrap.start"
    BOOTSTRAP_PATH_RESOLVED = "bootstrap.path.resolved"
    BOOTSTRAP_IMPORT_START = "bootstrap.import.start"
    BOOTSTRAP_IMPORT_END = "bootstrap.import.end"
    BOOTSTRAP_IMPORT_ERROR = "bootstrap.import.error"
    BOOTSTRAP_APP_CONSTRUCT_START = "bootstrap.app.construct.start"
    BOOTSTRAP_APP_CONSTRUCT_END = "bootstrap.app.construct.end"
    BOOTSTRAP_RUN_START = "bootstrap.run.start"
    BOOTSTRAP_RUN_END = "bootstrap.run.end"
    BOOTSTRAP_ERROR = "bootstrap.error"

    APP_LIFECYCLE_CONSTRUCTED = "app.lifecycle.constructed"
    APP_LIFECYCLE_INITIAL_VIEW = "app.lifecycle.initial_view"
    APP_COMPOSE_START = "app.compose.start"
    APP_COMPOSE_WIDGET = "app.compose.widget"
    APP_COMPOSE_END = "app.compose.end"
    APP_MOUNT_START = "app.mount.start"
    APP_MOUNT_END = "app.mount.end"
    APP_READY = "app.ready"
    APP_SCREEN_SNAPSHOT = "app.screen.snapshot"
    APP_WIDGET_HEALTH = "app.widget.health"
    APP_RENDER_START = "app.render.start"
    APP_RENDER_END = "app.render.end"
    APP_ERROR = "app.error"
    APP_INPUT = "app.input"
    APP_COMMAND = "app.command"
    APP_APPROVAL_OPEN = "app.approval.open"
    APP_WORKSPACE_SWITCH = "app.workspace.switch"
    TURN_START = "turn.start"
    TURN_END = "turn.end"
    TURN_ERROR = "turn.error"
    AGENT_MODE_PROPOSED = "agent.mode.proposed"

    HARNESS_TURN_RECEIVED = "harness.turn.received"
    HARNESS_CONTEXT_REBUILD_START = "harness.context.rebuild.start"
    HARNESS_CONTEXT_REBUILD_END = "harness.context.rebuild.end"
    HARNESS_MODE_ACTIVATED = "harness.mode.activated"
    HARNESS_PROMPT_BUILT = "harness.prompt.built"
    HARNESS_PLAN_BUILT = "harness.plan.built"
    HARNESS_APPROVAL_GATE = "harness.approval.gate"
    HARNESS_STEP_RESUME = "harness.step.resume"
    HARNESS_STEP_DISPATCH = "harness.step.dispatch"
    HARNESS_TURN_COMPLETED = "harness.turn.completed"
    HARNESS_ERROR = "harness.error"

    RUNTIME_INIT_START = "runtime.init.start"
    RUNTIME_INIT_END = "runtime.init.end"
    RUNTIME_MODEL_LOAD_START = "runtime.model.load.start"
    RUNTIME_MODEL_LOAD_END = "runtime.model.load.end"
    RUNTIME_PROMPT_BUILT = "runtime.prompt.built"
    RUNTIME_MODEL_CALL_START = "runtime.model.call.start"
    RUNTIME_MODEL_CALL_END = "runtime.model.call.end"
    RUNTIME_STREAM_START = "runtime.stream.start"
    RUNTIME_STREAM_END = "runtime.stream.end"
    RUNTIME_TOOL_CALL_PARSED = "runtime.tool_call.parsed"
    RUNTIME_TOKEN_PRESSURE = "runtime.token_pressure"
    RUNTIME_ERROR = "runtime.error"

    WORKER_DISPATCH_START = "worker.dispatch.start"
    WORKER_SANDBOX_CONFIG = "worker.sandbox.config"
    WORKER_SUBPROCESS_START = "worker.subprocess.start"
    WORKER_SUBPROCESS_END = "worker.subprocess.end"
    WORKER_TOOL_EXEC_START = "worker.tool.exec.start"
    WORKER_TOOL_EXEC_END = "worker.tool.exec.end"
    WORKER_ARTIFACT_EMITTED = "worker.artifact.emitted"
    WORKER_DISPATCH_END = "worker.dispatch.end"
    WORKER_TIMEOUT = "worker.timeout"
    WORKER_SANDBOX_VIOLATION = "worker.sandbox.violation"
    WORKER_ERROR = "worker.error"

    PERSISTENCE_WRITE_START = "persistence.write.start"
    PERSISTENCE_WRITE_END = "persistence.write.end"
    PERSISTENCE_ERROR = "persistence.error"


class TelemetryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(default_factory=uuid4)
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    layer: Layer
    kind: EventKind
    outcome: Outcome = Outcome.OK
    boot_id: UUID | None = None
    session_id: UUID | None = None
    turn_id: UUID | None = None
    step_id: str | None = None
    duration_ms: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
