import pytest
from textual.widgets import Input, OptionList, Static

from app.tui.app import DataHarnessApp
from app.tui.prompt_bar import PromptBar
from app.tui.prompt_editor import PromptEditor


@pytest.mark.asyncio
async def test_prompt_bar_replaces_plain_user_input(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()

        prompt = app.query_one("#prompt_bar", PromptBar)
        assert prompt.editor.id == "user_input"
        assert isinstance(prompt.editor, PromptEditor)


@pytest.mark.asyncio
async def test_prompt_bar_multiline_editor_submits_to_app(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt_bar", PromptBar)
        prompt.prefill("line one\nline two")
        prompt.editor.submit()
        await pilot.pause()

        buffer = app.query_one("#conversation").text_buffer()
        assert "line one" in buffer
        assert "line two" in buffer


@pytest.mark.asyncio
async def test_prompt_bar_shows_command_hints_after_slash(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        prompt = app.query_one("#prompt_bar", PromptBar)

        await prompt.refresh_hints("/")

        text = prompt.text_buffer()
        assert "/doctor" in text
        assert "/switch_workspace" in text


@pytest.mark.asyncio
async def test_prompt_bar_slash_hints_are_keyboard_selectable(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        await pilot.press("/")
        await pilot.pause()
        prompt = app.query_one("#prompt_bar", PromptBar)
        options = prompt.query_one("#prompt_hint_options", OptionList)

        await pilot.press("down")
        await pilot.pause()

        assert options.highlighted == 1
        await pilot.press("enter")
        await pilot.pause()

        assert prompt.editor.text.startswith("/challenge_conclusion")


@pytest.mark.asyncio
async def test_prompt_bar_shows_workspace_candidates_for_switch_workspace(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        await app._session.create_workspace("w_0002")
        prompt = app.query_one("#prompt_bar", PromptBar)

        await prompt.refresh_hints("/switch_workspace ")

        text = prompt.text_buffer()
        assert "workspace_id" in text
        assert "w_0002" in text


@pytest.mark.asyncio
async def test_prompt_bar_status_updates_from_status_watcher(tmp_path):
    from types import SimpleNamespace

    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()

        async def fake_watch_status():
            yield SimpleNamespace(
                workspace_id="w_0001",
                run_state="executing",
                active_mode="analysis",
                runtime_status="ready",
            )

        app._session.watch_status = fake_watch_status
        await app._subscribe_status()

        status = app.query_one("#prompt_status", Static)
        assert "analysis | executing" in str(status.render())


@pytest.mark.asyncio
async def test_non_prompt_input_submitted_is_ignored(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()
        other_input = Input(value="screen local text", id="workspace_manager_input")
        event = Input.Submitted(other_input, other_input.value)

        await app.on_input_submitted(event)

        assert other_input.value == "screen local text"
        assert "screen local text" not in app.query_one("#conversation").text_buffer()


@pytest.mark.asyncio
async def test_prompt_bar_chat_candidates_follow_replaced_app_state(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        await app._session.create_workspace("w_0002")
        old_chat = await app._session.create_chat("w_0001")
        new_chat = await app._session.create_chat("w_0002")
        prompt = app.query_one("#prompt_bar", PromptBar)

        app.apply_workspace_snapshot(
            {
                "workspace_id": "w_0002",
                "run_state": "idle",
                "active_mode": "interaction",
                "runtime_status": "ready",
            }
        )
        await prompt.refresh_hints("/resume_chat ")

        text = prompt.text_buffer()
        assert new_chat.chat_id in text
        assert old_chat.chat_id not in text


@pytest.mark.asyncio
async def test_prompt_bar_at_opens_file_picker_and_inserts_file(tmp_path):
    workspace_dir = tmp_path / "workspaces" / "w_0001"
    (workspace_dir / "data").mkdir(parents=True)
    (workspace_dir / "data" / "sales.csv").write_text("x")
    app = DataHarnessApp(workspace_dir=workspace_dir)

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt_bar", PromptBar)
        prompt.prefill("analyze @sal")
        await prompt.refresh_hints(prompt.editor.text)
        await pilot.pause()
        from app.tui.file_picker import FilePicker
        picker = prompt.query_one("#prompt_file_picker", FilePicker)
        picker.post_message(FilePicker.Selected("data/sales.csv"))
        await pilot.pause()

        assert "@data/sales.csv" in prompt.editor.text


@pytest.mark.asyncio
async def test_prompt_bar_at_selection_restores_prompt_focus(tmp_path):
    workspace_dir = tmp_path / "workspaces" / "w_0001"
    (workspace_dir / "data").mkdir(parents=True)
    (workspace_dir / "data" / "sales.csv").write_text("x")
    app = DataHarnessApp(workspace_dir=workspace_dir)

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt_bar", PromptBar)
        prompt.prefill("analyze @sal")
        await prompt.refresh_hints(prompt.editor.text)
        await pilot.pause()
        from app.tui.file_picker import FilePicker
        picker = prompt.query_one("#prompt_file_picker", FilePicker)

        picker.post_message(FilePicker.Selected("data/sales.csv"))
        await pilot.pause()

        assert app.focused is prompt.editor


@pytest.mark.asyncio
async def test_prompt_bar_at_makes_picker_visible(tmp_path):
    workspace_dir = tmp_path / "workspaces" / "w_0001"
    (workspace_dir / "data").mkdir(parents=True)
    (workspace_dir / "data" / "sales.csv").write_text("x")
    app = DataHarnessApp(workspace_dir=workspace_dir)
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt_bar", PromptBar)
        from app.tui.file_picker import FilePicker
        picker = prompt.query_one("#prompt_file_picker", FilePicker)
        assert picker.display is False
        await prompt.refresh_hints("@")
        await pilot.pause()
        assert picker.display is True


@pytest.mark.asyncio
async def test_prompt_bar_escape_dismisses_visible_picker(tmp_path):
    workspace_dir = tmp_path / "workspaces" / "w_0001"
    (workspace_dir / "data").mkdir(parents=True)
    (workspace_dir / "data" / "sales.csv").write_text("x")
    app = DataHarnessApp(workspace_dir=workspace_dir)
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt_bar", PromptBar)
        from app.tui.file_picker import FilePicker
        picker = prompt.query_one("#prompt_file_picker", FilePicker)
        await prompt.refresh_hints("@s")
        await pilot.pause()
        assert picker.display is True
        # Simulate the escape via prompt_bar.on_key
        from textual import events
        prompt.on_key(events.Key("escape", None))
        assert picker.display is False


@pytest.mark.asyncio
async def test_prompt_bar_workspace_switch_invalidates_picker_cache(tmp_path):
    workspace_dir = tmp_path / "workspaces" / "w_0001"
    (workspace_dir / "data").mkdir(parents=True)
    (workspace_dir / "data" / "sales.csv").write_text("x")
    app = DataHarnessApp(workspace_dir=workspace_dir)
    async with app.run_test() as pilot:
        await app._session.create_workspace("w_0001")
        await app._session.create_workspace("w_0002")
        prompt = app.query_one("#prompt_bar", PromptBar)
        from app.tui.file_picker import FilePicker
        picker = prompt.query_one("#prompt_file_picker", FilePicker)
        # Prime the cache.
        picker.index.scan()
        assert picker.index._cache is not None
        app.apply_workspace_snapshot(
            {
                "workspace_id": "w_0002",
                "run_state": "idle",
                "active_mode": "interaction",
                "runtime_status": "ready",
            }
        )
        await pilot.pause()
        # Cache should have been invalidated by update_state.
        assert picker.index._cache is None or picker.index.workspace_dir.name == "w_0002"


@pytest.mark.asyncio
async def test_prompt_bar_quotes_file_mentions_with_spaces(tmp_path):
    workspace_dir = tmp_path / "workspaces" / "w_0001"
    (workspace_dir / "data").mkdir(parents=True)
    (workspace_dir / "data" / "monthly sales.csv").write_text("x")
    app = DataHarnessApp(workspace_dir=workspace_dir)

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt_bar", PromptBar)
        prompt.prefill("analyze @monthly")
        await prompt.refresh_hints(prompt.editor.text)
        await pilot.pause()
        from app.tui.file_picker import FilePicker
        picker = prompt.query_one("#prompt_file_picker", FilePicker)
        picker.post_message(FilePicker.Selected("data/monthly sales.csv"))
        await pilot.pause()

        assert '@"data/monthly sales.csv"' in prompt.editor.text
