import asyncio
from datetime import UTC, datetime

import pytest

from harness.status import HarnessStatusSnapshot, StatusBroker


def make_snapshot(**overrides):
    base = dict(
        workspace_id="w1", chat_id="c1", chat_title="t",
        workspace_health="ready", active_mode="analyst",
        run_id=None, run_state="idle", runtime_status="ready",
        execution_tasks={}, approval_state="idle", clarification_state="idle",
        chat_turn_count=0, chat_token_estimate=0,
        last_compacted_at=None, compaction_count=0,
        doctor_warning_count=0, last_event=None,
    )
    base.update(overrides)
    return HarnessStatusSnapshot(**base)


def test_snapshot_schema_fields():
    s = make_snapshot()
    assert s.workspace_id == "w1"
    assert s.execution_tasks == {}


async def test_watch_status_yields_initial_snapshot():
    broker = StatusBroker(make_snapshot(), heartbeat_seconds=10.0)
    agen = broker.watch()
    first = await asyncio.wait_for(agen.__anext__(), timeout=1.0)
    assert first.workspace_id == "w1"
    await broker.close()


async def test_watch_status_yields_on_change_with_coalesce():
    broker = StatusBroker(make_snapshot(), heartbeat_seconds=10.0, coalesce_seconds=0.05)
    agen = broker.watch()
    await agen.__anext__()  # initial
    # Burst three updates within coalesce window
    broker.publish(make_snapshot(active_mode="m2"))
    broker.publish(make_snapshot(active_mode="m3"))
    broker.publish(make_snapshot(active_mode="m4"))
    coalesced = await asyncio.wait_for(agen.__anext__(), timeout=1.0)
    assert coalesced.active_mode == "m4"
    await broker.close()


async def test_watch_status_heartbeat_re_yields():
    broker = StatusBroker(make_snapshot(), heartbeat_seconds=0.1, coalesce_seconds=0.01)
    agen = broker.watch()
    await agen.__anext__()
    tick = await asyncio.wait_for(agen.__anext__(), timeout=1.0)
    assert tick.workspace_id == "w1"
    await broker.close()


async def test_publish_no_change_no_yield_until_heartbeat():
    broker = StatusBroker(make_snapshot(), heartbeat_seconds=10.0, coalesce_seconds=0.05)
    agen = broker.watch()
    await agen.__anext__()
    # Publish identical snapshots
    broker.publish(make_snapshot())
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(agen.__anext__(), timeout=0.3)
    await broker.close()
