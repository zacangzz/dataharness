import json

from harness.knowledge import KnowledgeManager


def test_write_and_delete_note(tmp_path):
    km = KnowledgeManager()
    ws = tmp_path / "ws"
    (ws / "memory" / "notes").mkdir(parents=True)

    assert km.write_note(str(ws), "test_formula", "x = y / 2", source_turn_ids=["t1"])
    assert (ws / "memory" / "notes" / "test_formula.md").exists()
    assert (ws / "memory" / "notes" / "test_formula.json").exists()

    assert km.delete_note(str(ws), "test_formula")
    assert not (ws / "memory" / "notes" / "test_formula.md").exists()


def test_echo_dedup(tmp_path):
    km = KnowledgeManager()
    ws = tmp_path / "ws"
    (ws / "memory" / "notes").mkdir(parents=True)
    km.write_note(str(ws), "formula_a", "x=1", source_turn_ids=["t1", "t2"])
    assert km.has_note_for_turns(str(ws), ["t2"])
    assert not km.has_note_for_turns(str(ws), ["t5"])


def test_preferences(tmp_path):
    km = KnowledgeManager()
    ws = tmp_path / "ws"
    (ws / "memory").mkdir(parents=True)
    (ws / "memory" / "preferences.json").write_text("{}")
    km.set_preference(str(ws), "preview_rows", 2)
    prefs = json.loads((ws / "memory" / "preferences.json").read_text())
    assert prefs["preview_rows"] == 2
    km.remove_preference(str(ws), "preview_rows")
    prefs = json.loads((ws / "memory" / "preferences.json").read_text())
    assert "preview_rows" not in prefs
