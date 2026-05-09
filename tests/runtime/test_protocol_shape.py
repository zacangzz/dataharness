import inspect
from runtime.protocol import Runtime


def test_protocol_methods_async_only():
    expected = {"stream", "context_window", "token_pressure", "validate_request", "status"}
    members = {name for name in vars(Runtime) if not name.startswith("_")}
    assert expected.issubset(members)
    assert "complete" not in members


def test_protocol_methods_have_async_signatures():
    for name in ("context_window", "token_pressure", "validate_request", "status"):
        method = getattr(Runtime, name)
        assert inspect.iscoroutinefunction(method), f"{name} should be a coroutine function"
    # stream must be declared async (coroutine or async generator)
    stream_method = getattr(Runtime, "stream")
    assert inspect.iscoroutinefunction(stream_method) or inspect.isasyncgenfunction(stream_method), \
        "stream should be async (coroutine or async generator function)"
