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
from agent.utils.sandbox_errors import SandboxUnavailableError

logger = logging.getLogger(__name__)

DEFAULT_DEVPOD_IMAGE = "bracelangchain/deepagents-sandbox:v1"
DEFAULT_DEVPOD_PROVIDER = "aws"
DEVPOD_UP_TIMEOUT = 300  # 5 minutes for workspace creation
_provider_installed = False

_UNREACHABLE_ERROR_SNIPPETS = (
    "agent is not running",
    "workspace doesn't exist",
    "workspace does not exist",
    "unable to find",
    "no such host",
    "no route to host",
    "network is unreachable",
    "connection refused",
    "connection timed out",
    "i/o timeout",
    "broken pipe",
    "use of closed network connection",
)


def _is_workspace_unreachable(*parts: str | bytes | None) -> bool:
    """Best-effort detection for DevPod connection-level failures."""
    text = " ".join(
        part.decode(errors="ignore") if isinstance(part, bytes) else str(part or "")
        for part in parts
    ).lower()
    return any(snippet in text for snippet in _UNREACHABLE_ERROR_SNIPPETS)


def _ensure_aws_config(region: str) -> None:
    """Create a minimal ~/.aws/config so the AWS Go SDK can resolve [default]."""
    import pathlib

    aws_dir = pathlib.Path.home() / ".aws"
    config_file = aws_dir / "config"
    if config_file.exists():
        return
    aws_dir.mkdir(parents=True, exist_ok=True)
    config_file.write_text(f"[default]\nregion = {region}\n")
    logger.info("Created minimal %s for AWS SDK shared config", config_file)


def _fetch_fargate_credentials() -> dict | None:
    """Fetch temporary AWS credentials from the Fargate container credential endpoint."""
    import urllib.request

    relative_uri = os.getenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
    if not relative_uri:
        logger.debug("No AWS_CONTAINER_CREDENTIALS_RELATIVE_URI set, skipping Fargate credential fetch")
        return None

    url = f"http://169.254.170.2{relative_uri}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            import json
            creds = json.loads(resp.read())
            logger.info("Fetched Fargate credentials (AccessKeyId=%s...)", creds.get("AccessKeyId", "")[:8])
            return creds
    except Exception:
        logger.exception("Failed to fetch Fargate credentials from %s", url)
        return None


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
    ami = os.getenv("DEVPOD_AWS_AMI", "ami-044f1545c3936f4c7")
    subnet_id = os.getenv("DEVPOD_AWS_SUBNET_ID", "")
    vpc_id = os.getenv("DEVPOD_AWS_VPC_ID", "")
    access_key_id = os.getenv("AWS_ACCESS_KEY_ID", "")
    secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    session_token = os.getenv("AWS_SESSION_TOKEN", "")

    # On Fargate, credentials come from the container credential endpoint,
    # not environment variables. Fetch them so we can pass to DevPod.
    if not access_key_id:
        creds = _fetch_fargate_credentials()
        if creds:
            access_key_id = creds.get("AccessKeyId", "")
            secret_access_key = creds.get("SecretAccessKey", "")
            session_token = creds.get("Token", "")
    logger.info(
        "Installing DevPod provider '%s' (region=%s, ami=%s, creds=%s)",
        provider, region, ami, "set" if access_key_id else "unset",
    )

    # The default AMI is a copy of Canonical's Ubuntu 22.04 into our AWS account with a
    # description matching what devpod-provider-aws expects ("Canonical, Ubuntu, 22.04 LTS").
    # This works around https://github.com/loft-sh/devpod-provider-aws/issues/50 where the
    # provider's init searches owner:"amazon" instead of Canonical (099720109477) and uses a
    # description filter that doesn't match real Ubuntu AMIs.
    # skevetter's fork fixes this upstream, but we keep the workaround for now.
    cmd = [
        "devpod", "provider", "add", provider,
        "-o", f"AWS_REGION={region}",
        "-o", f"AWS_AMI={ami}",
        "--debug",
    ]
    if subnet_id:
        cmd.extend(["-o", f"AWS_SUBNET_ID={subnet_id}"])
    if vpc_id:
        cmd.extend(["-o", f"AWS_VPC_ID={vpc_id}"])
    # Pass credentials both as -o options (stored in provider config for later
    # use by devpod up/ssh) AND in the subprocess environment (so the provider's
    # init command can resolve them via its shell command:
    #   command: printf "%s" "${AWS_ACCESS_KEY_ID:-}"
    # which reads from the process environment, not from stored options).
    if access_key_id:
        cmd.extend(["-o", f"AWS_ACCESS_KEY_ID={access_key_id}"])
    if secret_access_key:
        cmd.extend(["-o", f"AWS_SECRET_ACCESS_KEY={secret_access_key}"])
    if session_token:
        cmd.extend(["-o", f"AWS_SESSION_TOKEN={session_token}"])
    env = os.environ.copy()
    if access_key_id:
        env["AWS_ACCESS_KEY_ID"] = access_key_id
        env["AWS_SECRET_ACCESS_KEY"] = secret_access_key
    if session_token:
        env["AWS_SESSION_TOKEN"] = session_token
    # The AWS Go SDK's LoadDefaultConfig expects ~/.aws/config to exist when
    # resolving the [default] profile. On Fargate there is no config file,
    # causing "failed to get shared config profile, default". Create a
    # minimal one so the SDK is satisfied.
    _ensure_aws_config(region)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
    logger.info("devpod provider add stdout: %s", result.stdout)
    logger.info("devpod provider add stderr: %s", result.stderr)
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to add DevPod provider '{provider}': {result.stderr or result.stdout}"
        )
    _provider_installed = True
    logger.info("DevPod provider '%s' installed and configured", provider)


def _disable_git_credential_injection() -> None:
    """Disable DevPod's built-in git credential proxy.

    DevPod's credential proxy tunnels git credential requests back to the host
    machine's credential store. On ECS Fargate there is no credential store,
    so the proxy fails. We manage credentials ourselves via setup_git_credentials.
    """
    result = subprocess.run(
        ["devpod", "context", "set-options", "default",
         "-o", "SSH_INJECT_GIT_CREDENTIALS=false"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        logger.warning(
            "Failed to disable git credential injection: %s",
            result.stderr or result.stdout,
        )
    else:
        logger.info("Disabled DevPod git credential injection")


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
        # Verify the workspace is actually reachable
        result = backend.execute("echo ok")
        if result.exit_code != 0 or "ok" not in result.output:
            raise SandboxUnavailableError(
                f"DevPod workspace '{sandbox_id}' is not reachable (exit_code={result.exit_code})"
            )
        logger.info("DevPod workspace '%s' is alive", sandbox_id)
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
    _disable_git_credential_injection()
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
        client = get_client(url=os.environ.get("LANGGRAPH_URL", "http://localhost:2026"))

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

        if _is_workspace_unreachable(result.stdout, result.stderr):
            raise SandboxUnavailableError(
                f"DevPod workspace '{self._workspace_name}' is no longer reachable: "
                f"{(result.stderr or result.stdout or '').strip()}"
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
