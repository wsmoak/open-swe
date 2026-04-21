import os

from ..integrations.daytona import create_daytona_sandbox
from ..integrations.devpod import create_devpod_sandbox
from ..integrations.langsmith import create_langsmith_sandbox
from ..integrations.local import create_local_sandbox
from ..integrations.modal import create_modal_sandbox
from ..integrations.runloop import create_runloop_sandbox

SANDBOX_FACTORIES = {
    "langsmith": create_langsmith_sandbox,
    "daytona": create_daytona_sandbox,
    "devpod": create_devpod_sandbox,
    "modal": create_modal_sandbox,
    "runloop": create_runloop_sandbox,
    "local": create_local_sandbox,
}


def create_sandbox(sandbox_id: str | None = None, **kwargs):
    """Create or reconnect to a sandbox using the configured provider.

    The provider is selected via the SANDBOX_TYPE environment variable.
    Supported values: langsmith (default), daytona, modal, runloop, local.

    Args:
        sandbox_id: Optional existing sandbox ID to reconnect to.
        **kwargs: Additional arguments forwarded to the factory (e.g. repo_owner, repo_name, github_token).

    Returns:
        A sandbox backend implementing SandboxBackendProtocol.
    """
    sandbox_type = os.getenv("SANDBOX_TYPE", "langsmith")
    factory = SANDBOX_FACTORIES.get(sandbox_type)
    if not factory:
        supported = ", ".join(sorted(SANDBOX_FACTORIES))
        raise ValueError(f"Invalid sandbox type: {sandbox_type}. Supported types: {supported}")
    return factory(sandbox_id, **kwargs)


def validate_sandbox_startup_config() -> None:
    """Validate the configured sandbox provider's env vars at server startup.

    Raises ValueError if the active provider's configuration is invalid.
    Called from the FastAPI lifespan hook so errors surface at boot rather
    than on the first sandbox creation.
    """
    sandbox_type = os.getenv("SANDBOX_TYPE", "langsmith")
    if sandbox_type == "langsmith":
        from ..integrations.langsmith import LangSmithProvider

        LangSmithProvider.validate_startup_config()
