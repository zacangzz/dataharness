from harness.control import SessionConfig


def test_defaults():
    c = SessionConfig()
    assert c.status_heartbeat_seconds == 2.0
    assert not hasattr(c, "max_parallel_runs")
