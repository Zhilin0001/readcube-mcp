import asyncio
import subprocess
from pathlib import Path

from readcube_client.auth import LoginFailure
from readcube_mcp import login_gui, terminal_login
from readcube_mcp.server import create_server


def test_dialog_uses_hidden_password_without_command_arguments(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout="synthetic-value\n")

    monkeypatch.setattr(login_gui.subprocess, "run", run)
    assert login_gui._dialog(login_gui._PASSWORD) == "synthetic-value"
    args, kwargs = calls[0]
    assert "with hidden answer" in args[-1]
    assert "synthetic-value" not in repr(args)
    assert kwargs["stderr"] is subprocess.DEVNULL


def test_login_cancel_and_failure_do_not_replace_existing_session(monkeypatch, tmp_path):
    path = tmp_path / "session.json"
    path.write_text("existing")
    config = tmp_path / "config.toml"
    config.write_text('[readcube]\nsession_file = "' + str(path) + '"\n')
    dialogs = iter(["synthetic@example.org", None])
    monkeypatch.setattr(login_gui, "_dialog", lambda script: next(dialogs))
    monkeypatch.setattr(
        login_gui,
        "password_login",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected login")),
    )
    assert not login_gui.run_login(str(config))
    assert path.read_text() == "existing"
    calls = []
    dialogs = iter(["synthetic@example.org", "synthetic-secret", ""])
    monkeypatch.setattr(login_gui, "_dialog", lambda script: calls.append(script) or next(dialogs))

    def failed(*args, **kwargs):
        raise LoginFailure("credentials_rejected", "safe failure")

    monkeypatch.setattr(login_gui, "password_login", failed)
    assert not login_gui.run_login(str(config))
    assert calls[-1] == login_gui._FAILED
    assert path.read_text() == "existing"


def test_login_success_uses_configured_session_and_shows_result(monkeypatch, tmp_path):
    config = tmp_path / "config.toml"
    session = tmp_path / "private-session.json"
    config.write_text('[readcube]\nsession_file = "' + str(session) + '"\n')
    prompts = []
    replies = iter(["fake@example.org", "fake-secret", ""])
    monkeypatch.setattr(
        login_gui, "_dialog", lambda script: prompts.append(script) or next(replies)
    )
    called = []
    monkeypatch.setattr(
        login_gui, "password_login", lambda *args, **kwargs: called.append((args, kwargs))
    )
    assert login_gui.run_login(str(config)) is True
    assert called[0][0] == ("fake@example.org", "fake-secret", session)
    assert prompts == [login_gui._EMAIL, login_gui._PASSWORD, login_gui._SUCCESS]


def test_local_only_tool_does_not_accept_or_return_credentials(monkeypatch):
    calls = []
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(terminal_login, "open_terminal", lambda command: calls.append(command))

    async def check():
        cloud = create_server()
        assert "readcube_open_login" not in {t.name for t in await cloud.list_tools()}
        local = create_server(local_login_enabled=True, local_login_config="example.toml")
        tool = next(t for t in await local.list_tools() if t.name == "readcube_open_login")
        assert set(tool.input_schema["properties"]) == {"mode"}
        assert tool.input_schema["properties"]["mode"]["default"] == "terminal"
        result = await local.call_tool("readcube_open_login", {})
        assert result.structured_content["status"] == "started"
        assert result.structured_content["authenticated"] is False
        assert calls[0][-1] == str(Path("example.toml").resolve())
        assert "readcube_mcp.terminal_login" in calls[0]
        await local.call_tool("readcube_open_login", {"mode": "dialog"})
        args, kwargs = calls[1]
        assert args[0][-1] == str(Path("example.toml").resolve())
        assert kwargs["stdout"] is subprocess.DEVNULL and kwargs["stderr"] is subprocess.DEVNULL

    asyncio.run(check())


def test_terminal_launcher_has_no_password_and_is_private(monkeypatch):
    seen = []

    def run(args, **kwargs):
        launcher = Path(args[-1])
        text = launcher.read_text()
        assert launcher.stat().st_mode & 0o777 == 0o700
        assert launcher.parent.stat().st_mode & 0o777 == 0o700
        assert "readcube_mcp.terminal_login" in text
        assert "fake-password" not in text
        seen.append(launcher)

    monkeypatch.setattr(terminal_login.subprocess, "run", run)
    terminal_login.open_terminal(["python", "-m", "readcube_mcp.terminal_login"])
    assert len(seen) == 1
    seen[0].unlink()
    seen[0].parent.rmdir()
