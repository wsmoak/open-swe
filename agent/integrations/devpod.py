"""DevPod sandbox backend implementation."""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
import uuid

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox

logger = logging.getLogger(__name__)

DEFAULT_DEVPOD_IMAGE = "bracelangchain/deepagents-sandbox:v1"
DEFAULT_DEVPOD_PROVIDER = "aws"
DEVPOD_UP_TIMEOUT = 300  # 5 minutes for workspace creation
_provider_installed = False


def _ensure_provider(provider: str) -> None:
    """Install the DevPod provider if not already present."""
    global _provider_installed  # noqa: PLW0603
    if _provider_installed:
        return

    result = subprocess.run(
        ["devpod", "provider", "list", "--output", "json", "--debug"],
        capture_output=True, text=True, timeout=30,
    )
    logger.info("devpod provider list stdout: %s", result.stdout)
    logger.info("devpod provider list stderr: %s", result.stderr)
    if result.returncode == 0 and provider in result.stdout:
        _provider_installed = True
        return

    region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-2"))
    logger.info("Installing DevPod provider '%s' (region=%s)", provider, region)
    result = subprocess.run(
        [
            "devpod", "provider", "add", provider,
            "-o", f"AWS_REGION={region}",
            "-o", f"AWS_AMI={os.getenv('DEVPOD_AWS_AMI', 'ami-096a2911074929e0b')}",
            "--debug",
        ],
        capture_output=True, text=True, timeout=60,
    )
    logger.info("devpod provider add stdout: %s", result.stdout)
    logger.info("devpod provider add stderr: %s", result.stderr)
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to add DevPod provider '{provider}': {result.stderr or result.stdout}"
        )
    _provider_installed = True
    logger.info("DevPod provider '%s' installed", provider)


def create_devpod_sandbox(sandbox_id: str | None = None) -> "DevPodBackend":
    """Create or reconnect to a DevPod workspace sandbox.

    If sandbox_id is provided, reconnects to an existing workspace by name.
    Otherwise, creates a new workspace using `devpod up`.

    Reads configuration from environment variables:
        DEVPOD_PROVIDER: Provider name (default: aws)
        DEVPOD_WORKSPACE_IMAGE: Base container image (default: bracelangchain/deepagents-sandbox:v1)

    Args:
        sandbox_id: Optional existing workspace name to reconnect to.

    Returns:
        DevPodBackend instance implementing SandboxBackendProtocol.
    """
    if sandbox_id:
        logger.info("Reconnecting to existing DevPod workspace: %s", sandbox_id)
        backend = DevPodBackend(workspace_name=sandbox_id)
        return backend

    provider = os.getenv("DEVPOD_PROVIDER", DEFAULT_DEVPOD_PROVIDER)
    image = os.getenv("DEVPOD_WORKSPACE_IMAGE", DEFAULT_DEVPOD_IMAGE)

    # Diagnostic: log credential and environment info for debugging Fargate issues
    logger.info(
        "DevPod pre-flight: AWS_ACCESS_KEY_ID=%s, AWS_CONTAINER_CREDENTIALS_RELATIVE_URI=%s, "
        "AWS_REGION=%s, HOME=%s, DEVPOD_PROVIDER=%s",
        "set" if os.getenv("AWS_ACCESS_KEY_ID") else "unset",
        os.getenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "unset"),
        os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "unset")),
        os.getenv("HOME", "unset"),
        provider,
    )

    _ensure_provider(provider)
    workspace_name = _generate_workspace_name()

    logger.info(
        "Creating new DevPod workspace: %s (provider=%s, image=%s)",
        workspace_name, provider, image,
    )

    result = subprocess.run(
        [
            "devpod", "up", workspace_name,
            "--provider", provider,
            "--ide", "none",
            "--source", f"image:{image}",
            "--debug",
        ],
        capture_output=True,
        text=True,
        timeout=DEVPOD_UP_TIMEOUT,
    )
    logger.info("devpod up stdout: %s", result.stdout)
    logger.info("devpod up stderr: %s", result.stderr)

    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to create DevPod workspace '{workspace_name}': "
            f"{result.stderr or result.stdout}"
        )

    logger.info("DevPod workspace created: %s", workspace_name)
    backend = DevPodBackend(workspace_name=workspace_name)
    _update_thread_sandbox_metadata(workspace_name)
    return backend


def _generate_workspace_name() -> str:
    """Generate a unique workspace name from the LangGraph thread_id or a UUID.

    DevPod workspace names must be valid as SSH hostnames: lowercase
    alphanumerics and hyphens, starting with a letter.
    """
    try:
        from langgraph.config import get_config
        config = get_config()
        thread_id = config.get("configurable", {}).get("thread_id")
        if thread_id:
            sanitized = thread_id.replace("_", "-").lower()
            return f"openswe-{sanitized}"
    except Exception:
        pass
    return f"openswe-{uuid.uuid4()}"


def _update_thread_sandbox_metadata(sandbox_id: str) -> None:
    """Store the workspace name in LangGraph thread metadata for reconnection."""
    try:
        import asyncio

        from langgraph.config import get_config
        from langgraph_sdk import get_client

        config = get_config()
        thread_id = config.get("configurable", {}).get("thread_id")
        if not thread_id:
            return
        client = get_client()

        async def _update() -> None:
            await client.threads.update(
                thread_id=thread_id,
                metadata={"sandbox_id": sandbox_id},
            )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_update())
        else:
            loop.create_task(_update())
    except Exception:
        pass


class DevPodBackend(BaseSandbox):
    """DevPod workspace backend implementing SandboxBackendProtocol.

    Executes commands inside a DevPod workspace via SSH.
    All file operations are inherited from BaseSandbox and delegate to execute().
    """

    def __init__(self, workspace_name: str) -> None:
        self._workspace_name = workspace_name
        self._default_timeout: int = 30 * 5  # 5 minutes

    @property
    def id(self) -> str:
        return self._workspace_name

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        """Execute a shell command inside the DevPod workspace via SSH."""
        effective_timeout = timeout if timeout is not None else self._default_timeout

        # Redirect command stderr to stdout inside the shell so DevPod's own
        # status messages (written to subprocess stderr) stay separate and
        # can be ignored.
        wrapped = f"{{ {command}; }} 2>&1"
        result = subprocess.run(
            ["devpod", "ssh", self._workspace_name, "--command", wrapped],
            capture_output=True,
            text=True,
            timeout=effective_timeout,
        )

        # result.stderr contains only DevPod's own status messages — ignore it.
        return ExecuteResponse(
            output=result.stdout or "",
            exit_code=result.returncode,
            truncated=False,
        )

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload files to the DevPod workspace by piping bytes via stdin."""
        responses: list[FileUploadResponse] = []
        for path, content in files:
            try:
                quoted = shlex.quote(path)
                result = subprocess.run(
                    [
                        "devpod", "ssh", self._workspace_name,
                        "--command", f"mkdir -p $(dirname {quoted}) && tee {quoted} > /dev/null",
                    ],
                    input=content,
                    capture_output=True,
                    timeout=self._default_timeout,
                )
                if result.returncode != 0:
                    responses.append(FileUploadResponse(path=path, error="invalid_path"))
                else:
                    responses.append(FileUploadResponse(path=path, error=None))
            except Exception:
                logger.exception("Failed to upload file to DevPod workspace '%s': %s", self._workspace_name, path)
                responses.append(FileUploadResponse(path=path, error="invalid_path"))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download files from the DevPod workspace via cat."""
        responses: list[FileDownloadResponse] = []
        for path in paths:
            try:
                quoted = shlex.quote(path)
                result = subprocess.run(
                    [
                        "devpod", "ssh", self._workspace_name,
                        "--command", f"cat {quoted}",
                    ],
                    capture_output=True,
                    timeout=self._default_timeout,
                )
                if result.returncode != 0:
                    responses.append(FileDownloadResponse(path=path, content=None, error="file_not_found"))
                else:
                    responses.append(FileDownloadResponse(path=path, content=result.stdout, error=None))
            except Exception:
                logger.exception("Failed to download file from DevPod workspace '%s': %s", self._workspace_name, path)
                responses.append(FileDownloadResponse(path=path, content=None, error="file_not_found"))
        return responses

    def delete(self) -> None:
        """Force-delete the DevPod workspace and its resources."""
        result = subprocess.run(
            ["devpod", "delete", self._workspace_name, "--force"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.warning(
                "Failed to delete DevPod workspace '%s': %s",
                self._workspace_name,
                result.stderr or result.stdout,
            )
        else:
            logger.info("DevPod workspace deleted: %s", self._workspace_name)
