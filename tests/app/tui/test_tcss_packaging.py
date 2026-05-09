from pathlib import Path

from app.tui.app import DataHarnessApp


def test_app_uses_dataharness_tcss_file():
    css_path = DataHarnessApp.CSS_PATH

    assert str(css_path).endswith("dataharness.tcss")
    assert Path(css_path).name == "dataharness.tcss"


def test_dataharness_tcss_defines_interaction_classes():
    tcss = Path("src/app/tui/dataharness.tcss").read_text()

    assert ".textual-jump-label" in tcss
    assert ".status-error" in tcss
    assert "HelpScreen" in tcss
    assert "CommandPalette" in tcss
