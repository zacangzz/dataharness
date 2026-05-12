from harness.orchestrator import _sanitize_assistant_text


def test_sanitize_assistant_text_strips_gemma_turn_markers():
    assert _sanitize_assistant_text("hello\n\nend_of_turn>") == "hello"
    assert _sanitize_assistant_text("data\n[/start_of_turn]") == "data"
    assert _sanitize_assistant_text("ok\n<end_of_turn>") == "ok"
