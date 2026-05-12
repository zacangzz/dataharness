from runtime.llama_cpp_runtime import (
    EOS_TOKENS,
    _SeqGen,
    emit_content_events,
    eos_prefix_suffix,
    strip_full_eos,
)


def _drain(chunks: list[str]) -> tuple[list[str], str]:
    seq = _SeqGen()
    buffer = ""
    texts: list[str] = []
    for chunk in chunks:
        events, buffer = emit_content_events(chunk, buffer, "rid", seq)
        for ev in events:
            if ev.type == "text_delta" and ev.text:
                texts.append(ev.text)
    return texts, buffer


def test_strip_full_eos_preserves_surrounding_text():
    assert strip_full_eos("hello<end_of_turn>") == "hello"
    assert strip_full_eos("hello") == "hello"
    assert strip_full_eos("a<eos>b</s>c") == "abc"


def test_eos_prefix_suffix_detects_partial_token():
    assert eos_prefix_suffix("hello<end_of") == "<end_of"
    assert eos_prefix_suffix("hello") == ""
    assert eos_prefix_suffix("done<") == "<"


def test_split_eos_across_chunks_does_not_leak_into_text():
    # llama-cpp may split "<end_of_turn>" across chunk boundaries.
    chunks = ["hello", " world", "<end_of", "_turn>"]
    texts, buffer = _drain(chunks)
    combined = "".join(texts)
    for tok in EOS_TOKENS:
        assert tok not in combined
    assert "<end_of" not in combined
    assert combined.startswith("hello world")
    assert buffer == ""


def test_full_eos_in_single_chunk_is_stripped():
    chunks = ["answer.<end_of_turn>"]
    texts, buffer = _drain(chunks)
    combined = "".join(texts)
    assert "<end_of_turn>" not in combined
    assert combined == "answer."
    assert buffer == ""


def test_eos_prefix_at_end_buffered_until_finish():
    # If stream stops with a partial EOS prefix in buffer, no text_delta should leak it.
    chunks = ["ok ", "<end_of"]
    texts, buffer = _drain(chunks)
    assert "".join(texts) == "ok "
    assert buffer == "<end_of"


def test_doubled_eos_fully_stripped():
    chunks = ["bye<end_of_turn><end_of_turn>"]
    texts, _ = _drain(chunks)
    assert "".join(texts) == "bye"
