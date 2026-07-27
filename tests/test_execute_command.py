import shutil
import subprocess
from unittest.mock import MagicMock, patch

from harness.config import COMMAND_TIMEOUT_SEC
from harness.runner import _run_shell


def test_run_shell_returns_error_when_no_container() -> None:
    """_run_shell returns error when container is empty."""
    result = _run_shell("", "echo hello")
    assert "[error]" in result
    assert "not running" in result


def test_run_shell_returns_stdout_stderr() -> None:
    """_run_shell should return stdout + stderr concatenated."""
    with patch("harness.runner.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="hello", stderr="world")
        result = _run_shell("fake-container", "echo hello")
        assert "hello" in result
        assert "world" in result
        mock_run.assert_called_once()


def test_run_shell_timeout_returns_error() -> None:
    """When a command hangs, _run_shell catches TimeoutExpired."""
    with patch(
        "harness.runner.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="x", timeout=COMMAND_TIMEOUT_SEC),
    ):
        result = _run_shell("fake-container", "sleep 999")
        assert "[timeout]" in result
        assert f"{COMMAND_TIMEOUT_SEC}s" in result


def test_run_shell_uses_docker_exec() -> None:
    """_run_shell calls docker exec with the container ID."""
    with patch("harness.runner.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr="")
        _run_shell("fake-container", "ls")
        cmd = mock_run.call_args.args[0]
        assert cmd[:2] == ["docker", "exec"]
        assert "fake-container" in cmd
        assert cmd[-1] == "ls"
        assert mock_run.call_args.kwargs["timeout"] == COMMAND_TIMEOUT_SEC


def test_run_shell_passes_command_via_bash() -> None:
    """Commands are wrapped in bash -c for proper shell features."""
    with patch("harness.runner.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr="")
        _run_shell("fake-container", "echo test | grep test")
        cmd = mock_run.call_args.args[0]
        assert "bash" in cmd
        assert "-c" in cmd


# --- Host dependency availability ---


def test_curl_available() -> None:
    assert shutil.which("curl") is not None


def test_python3_available() -> None:
    assert shutil.which("python3") is not None


def test_nc_available() -> None:
    assert shutil.which("nc") is not None


def test_bash_available() -> None:
    assert shutil.which("bash") is not None


def test_base64_available() -> None:
    assert shutil.which("base64") is not None
