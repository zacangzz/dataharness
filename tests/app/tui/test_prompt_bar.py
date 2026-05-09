import pytest
from textual.widgets import Input, OptionList, Static

from app.tui.app import DataHarnessApp
from app.tui.prompt_bar import PromptBar


@pytest.mark.asyncio
async def test_prompt_bar_replaces_plain_user_input(tmp_path):
    app = DataHarnessApp(workspace_dir=tmp_path / "w" / "w_0001")
    async with app.run_test() as pilot:
        await pilot.pause()

        prompt = app.query_one("#prompt_bar", PromptBar)
        assert prompt.input.id == "user_input"


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

        assert prompt.input.value.startswith("/challenge_conclusion")


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
