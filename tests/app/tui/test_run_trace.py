from datetime import UTC, datetime

import pytest

from app.events import (
    AppDoctorFinding,
    AppDoctorReportReady,
    AppFinalMessage,
    AppRuntimeDelta,
    AppTurnCancelled,
    AppTurnFailed,
)
from app.tui.app import DataHarnessApp
from app.tui.run_trace import RunTrace
from app.tui.widgets import SidebarPane, WorkspaceBar


def test_run_trace_records_bounded_phase_lines():
    trace = RunTrace(max_lines=2)

    trace.command_started("doctor")
    trace.command_progress("doctor", "scan", 1, 2)
    trace.command_completed("doctor", {"ok": True})

    assert trace.current_phase == "doctor complete"
    assert trace.lines == ["doctor: scan 1/2", "doctor: complete"]


def test_workspace_bar_includes_chat_and_phase():
    bar = WorkspaceBar()

    bar.update_from(
        workspace_id="w_0001",
        chat_id="chat_1",
        run_state="idle",
        active_mode="analyst",
        runtime_status="not_loaded",
        phase="doctor complete",
    )

    rendered = str(bar.render())
    assert "chat: chat_1" in rendered
    assert "phase: doctor complete" in rendered


def test_sidebar_renders_trace_lines():
    sidebar = SidebarPane()

    sidebar.update_trace(["doctor: scan 1/2", "doctor: complete"])

    rendered = sidebar.text_buffer()
    assert "TRACE" in rendered
    assert "doctor: complete" in rendered


@pytest.mark.asyncio
async def test_app_consumer_routes_final_cancelled_and_doctor_events(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")

    async with app.run_test() as pilot:
        await pilot.pause()
        consumer = app._build_consumer()
        ts = datetime.now(UTC)

        consumer.dispatch(
            AppFinalMessage(
                ts=ts,
                workspace_id="w_0001",
                chat_id="chat_1",
                run_id="run_1",
                assistant_message_id="a_1",
                text="final answer",
                usage={},
            )
        )
        consumer.dispatch(
            AppTurnCancelled(
                ts=ts,
                workspace_id="w_0001",
                chat_id="chat_1",
                run_id="run_1",
                reason="user stopped",
                cancelled_at=ts,
            )
        )
        consumer.dispatch(
            AppDoctorFinding(
                ts=ts,
                workspace_id="w_0001",
                chat_id="chat_1",
                run_id="run_1",
                report_id="report_1",
                category="runtime",
                severity="warning",
                summary="model missing",
                details={},
            )
        )
        consumer.dispatch(
            AppDoctorReportReady(
                ts=ts,
                workspace_id="w_0001",
                chat_id="chat_1",
                run_id="run_1",
                report_id="report_1",
                summary_counts={"warning": 1},
                recommendations=["download a model"],
            )
        )

        conversation = app.query_one("#conversation").text_buffer()
        sidebar = app.query_one("#sidebar").text_buffer()

        assert "final answer" in conversation
        assert "[cancelled: user stopped]" in conversation
        assert "model missing" in sidebar
        assert "download a model" in sidebar


@pytest.mark.asyncio
async def test_final_message_updates_trace_phase_after_runtime_delta(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")

    async with app.run_test() as pilot:
        await pilot.pause()
        consumer = app._build_consumer()
        ts = datetime.now(UTC)

        consumer.dispatch(
            AppRuntimeDelta(
                ts=ts,
                workspace_id="w_0001",
                chat_id="chat_1",
                run_id="run_1",
                delta_type="text",
                text="partial",
                tool_call=None,
            )
        )
        assert "phase: runtime text" in str(app.query_one("#workspace_bar").render())

        consumer.dispatch(
            AppFinalMessage(
                ts=ts,
                workspace_id="w_0001",
                chat_id="chat_1",
                run_id="run_1",
                assistant_message_id="a_1",
                text="final answer",
                usage={},
            )
        )

        rendered = str(app.query_one("#workspace_bar").render())
        assert "phase: runtime text" not in rendered
        assert "phase: final response" in rendered


@pytest.mark.asyncio
async def test_turn_cancelled_updates_trace_phase_after_runtime_delta(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")

    async with app.run_test() as pilot:
        await pilot.pause()
        consumer = app._build_consumer()
        ts = datetime.now(UTC)

        consumer.dispatch(
            AppRuntimeDelta(
                ts=ts,
                workspace_id="w_0001",
                chat_id="chat_1",
                run_id="run_1",
                delta_type="text",
                text="partial",
                tool_call=None,
            )
        )
        assert "phase: runtime text" in str(app.query_one("#workspace_bar").render())

        consumer.dispatch(
            AppTurnCancelled(
                ts=ts,
                workspace_id="w_0001",
                chat_id="chat_1",
                run_id="run_1",
                reason="user stopped",
                cancelled_at=ts,
            )
        )

        rendered = str(app.query_one("#workspace_bar").render())
        sidebar = app.query_one("#sidebar", SidebarPane).text_buffer()
        assert "phase: runtime text" not in rendered
        assert "phase: cancelled" in rendered
        assert "cancelled: user stopped" in sidebar


@pytest.mark.asyncio
async def test_turn_failed_discards_partial_stream_before_later_delta(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")

    async with app.run_test() as pilot:
        await pilot.pause()
        consumer = app._build_consumer()
        ts = datetime.now(UTC)

        consumer.dispatch(
            AppRuntimeDelta(
                ts=ts,
                workspace_id="w_0001",
                chat_id="chat_1",
                run_id="run_1",
                delta_type="text",
                text="partial",
                tool_call=None,
            )
        )
        consumer.dispatch(
            AppTurnFailed(
                ts=ts,
                workspace_id="w_0001",
                chat_id="chat_1",
                run_id="run_1",
                failure_summary="model crashed",
                error_code="runtime_error",
                details={},
            )
        )
        consumer.dispatch(
            AppRuntimeDelta(
                ts=ts,
                workspace_id="w_0001",
                chat_id="chat_2",
                run_id="run_2",
                delta_type="text",
                text="new",
                tool_call=None,
            )
        )

        rendered = app.query_one("#conversation").text_buffer()
        assert "new" in rendered
        assert "partialnew" not in rendered
        assert "partial" not in rendered
