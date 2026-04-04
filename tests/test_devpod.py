from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent.integrations.devpod import DevPodBackend, create_devpod_sandbox
from agent.utils.sandbox_errors import SandboxUnavailableError


def _make_result(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> MagicMock:
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


# ---------------------------------------------------------------------------
# DevPodBackend.execute
# ---------------------------------------------------------------------------

def test_execute_builds_correct_cli_args() -> None:
    with patch("subprocess.run", return_value=_make_result(stdout=b"hello\n")) as mock_run:
        backend = DevPodBackend("my-workspace")
        response = backend.execute("echo hello")

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args == ["devpod", "ssh", "my-workspace", "--command", "{ echo hello; } 2>&1"]


def test_execute_wraps_stderr_into_stdout() -> None:
    with patch("subprocess.run", return_value=_make_result(stdout=b"")) as mock_run:
        backend = DevPodBackend("ws")
        backend.execute("ls /nonexistent")

    cmd = mock_run.call_args[0][0][-1]
    assert "2>&1" in cmd


def test_execute_maps_stdout_and_exit_code() -> None:
    # execute() uses text=True so subprocess returns str, not bytes
    result = _make_result(returncode=1)
    result.stdout = "err output\n"
    with patch("subprocess.run", return_value=result):
        backend = DevPodBackend("ws")
        response = backend.execute("false")

    assert response.exit_code == 1
    assert response.output == "err output\n"
    assert response.truncated is False


def test_execute_uses_custom_timeout() -> None:
    with patch("subprocess.run", return_value=_make_result()) as mock_run:
        backend = DevPodBackend("ws")
        backend.execute("sleep 1", timeout=42)

    assert mock_run.call_args[1]["timeout"] == 42


def test_execute_uses_default_timeout_when_none() -> None:
    with patch("subprocess.run", return_value=_make_result()) as mock_run:
        backend = DevPodBackend("ws")
        backend.execute("echo hi")

    assert mock_run.call_args[1]["timeout"] == backend._default_timeout


def test_execute_raises_sandbox_unavailable_for_dead_workspace() -> None:
    result = _make_result(returncode=1)
    result.stdout = ""
    result.stderr = "agent is not running"
    with patch("subprocess.run", return_value=result):
        backend = DevPodBackend("ws")
        with pytest.raises(SandboxUnavailableError, match="no longer reachable"):
            backend.execute("echo hi")


# ---------------------------------------------------------------------------
# DevPodBackend.upload_files
# ---------------------------------------------------------------------------

def test_upload_files_pipes_bytes_via_stdin() -> None:
    with patch("subprocess.run", return_value=_make_result()) as mock_run:
        backend = DevPodBackend("ws")
        responses = backend.upload_files([("/tmp/hello.txt", b"hello world")])

    assert len(responses) == 1
    assert responses[0].error is None
    assert responses[0].path == "/tmp/hello.txt"
    call_kwargs = mock_run.call_args[1]
    assert call_kwargs["input"] == b"hello world"


def test_upload_files_includes_mkdir_in_command() -> None:
    with patch("subprocess.run", return_value=_make_result()) as mock_run:
        backend = DevPodBackend("ws")
        backend.upload_files([("/some/nested/dir/file.txt", b"data")])

    cmd = mock_run.call_args[0][0][-1]
    assert "mkdir -p" in cmd
    assert "tee" in cmd


def test_upload_files_returns_error_on_nonzero_exit() -> None:
    with patch("subprocess.run", return_value=_make_result(returncode=1)):
        backend = DevPodBackend("ws")
        responses = backend.upload_files([("/tmp/f.txt", b"x")])

    assert responses[0].error == "invalid_path"


def test_upload_files_returns_error_on_exception() -> None:
    with patch("subprocess.run", side_effect=OSError("devpod not found")):
        backend = DevPodBackend("ws")
        responses = backend.upload_files([("/tmp/f.txt", b"x")])

    assert responses[0].error == "invalid_path"


def test_upload_files_partial_success() -> None:
    results = [_make_result(returncode=0), _make_result(returncode=1)]
    with patch("subprocess.run", side_effect=results):
        backend = DevPodBackend("ws")
        responses = backend.upload_files([("/tmp/ok.txt", b"ok"), ("/tmp/fail.txt", b"fail")])

    assert responses[0].error is None
    assert responses[1].error == "invalid_path"


# ---------------------------------------------------------------------------
# DevPodBackend.download_files
# ---------------------------------------------------------------------------

def test_download_files_returns_stdout_as_bytes() -> None:
    with patch("subprocess.run", return_value=_make_result(stdout=b"file content")):
        backend = DevPodBackend("ws")
        responses = backend.download_files(["/tmp/hello.txt"])

    assert len(responses) == 1
    assert responses[0].error is None
    assert responses[0].content == b"file content"
    assert responses[0].path == "/tmp/hello.txt"


def test_download_files_uses_cat_command() -> None:
    with patch("subprocess.run", return_value=_make_result(stdout=b"")) as mock_run:
        backend = DevPodBackend("ws")
        backend.download_files(["/tmp/f.txt"])

    cmd = mock_run.call_args[0][0][-1]
    assert cmd.startswith("cat ")


def test_download_files_returns_file_not_found_on_nonzero_exit() -> None:
    with patch("subprocess.run", return_value=_make_result(returncode=1)):
        backend = DevPodBackend("ws")
        responses = backend.download_files(["/tmp/missing.txt"])

    assert responses[0].content is None
    assert responses[0].error == "file_not_found"


def test_download_files_returns_error_on_exception() -> None:
    with patch("subprocess.run", side_effect=OSError("devpod not found")):
        backend = DevPodBackend("ws")
        responses = backend.download_files(["/tmp/f.txt"])

    assert responses[0].content is None
    assert responses[0].error == "file_not_found"


def test_download_files_partial_success() -> None:
    results = [_make_result(stdout=b"data"), _make_result(returncode=1)]
    with patch("subprocess.run", side_effect=results):
        backend = DevPodBackend("ws")
        responses = backend.download_files(["/tmp/ok.txt", "/tmp/missing.txt"])

    assert responses[0].content == b"data"
    assert responses[1].error == "file_not_found"


# ---------------------------------------------------------------------------
# DevPodBackend.delete
# ---------------------------------------------------------------------------

def test_delete_calls_devpod_delete_force() -> None:
    with patch("subprocess.run", return_value=_make_result(stdout=b"", stderr=b"")) as mock_run:
        backend = DevPodBackend("ws-to-delete")
        backend.delete()

    args = mock_run.call_args[0][0]
    assert args == ["devpod", "delete", "ws-to-delete", "--force"]


# ---------------------------------------------------------------------------
# create_devpod_sandbox
# ---------------------------------------------------------------------------

def test_create_devpod_sandbox_reconnects_when_sandbox_id_given() -> None:
    with patch("subprocess.run", return_value=_make_result(stdout="ok\n", returncode=0)):
        backend = create_devpod_sandbox(sandbox_id="existing-workspace")

    assert backend.id == "existing-workspace"


def test_create_devpod_sandbox_reconnect_raises_sandbox_unavailable() -> None:
    result = _make_result(returncode=1, stdout="", stderr="workspace doesn't exist")
    with patch("subprocess.run", return_value=result):
        with pytest.raises(SandboxUnavailableError, match="no longer reachable"):
            create_devpod_sandbox(sandbox_id="existing-workspace")


def test_create_devpod_sandbox_runs_devpod_up() -> None:
    with patch("agent.integrations.devpod._ensure_provider"):
        with patch("subprocess.run", return_value=_make_result()) as mock_run:
            with patch("agent.integrations.devpod._generate_workspace_name", return_value="openswe-abc"):
                with patch("agent.integrations.devpod._update_thread_sandbox_metadata"):
                    backend = create_devpod_sandbox()

    args = mock_run.call_args[0][0]
    assert args[0:3] == ["devpod", "up", "openswe-abc"]
    assert "--ide" in args
    assert "none" in args


def test_create_devpod_sandbox_raises_on_failure() -> None:
    with patch("agent.integrations.devpod._ensure_provider"):
        with patch("subprocess.run", return_value=_make_result(returncode=1, stderr=b"provider error")):
            with patch("agent.integrations.devpod._generate_workspace_name", return_value="openswe-abc"):
                with pytest.raises(RuntimeError, match="provider error"):
                    create_devpod_sandbox()


def test_create_devpod_sandbox_uses_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVPOD_PROVIDER", "docker")
    monkeypatch.setenv("DEVPOD_WORKSPACE_IMAGE", "myimage:latest")

    with patch("agent.integrations.devpod._ensure_provider"):
        with patch("subprocess.run", return_value=_make_result()) as mock_run:
            with patch("agent.integrations.devpod._generate_workspace_name", return_value="openswe-xyz"):
                with patch("agent.integrations.devpod._update_thread_sandbox_metadata"):
                    create_devpod_sandbox()

    args = mock_run.call_args[0][0]
    assert "--provider" in args
    assert "docker" in args
    assert "image:myimage:latest" in args
