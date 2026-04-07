import asyncio
import logging
import os
from typing import Any

from langgraph.config import get_config

from ..utils.github_app import get_github_app_installation_token
from ..utils.github_comments import post_github_comment

logger = logging.getLogger(__name__)


def github_comment(message: str, issue_number: int = 0) -> dict[str, Any]:
    """Post a comment to a GitHub issue or pull request."""
    config = get_config()
    configurable = config.get("configurable", {})

    repo_config = configurable.get("repo", {})
    # Always prefer the issue number from config (set by the webhook handler)
    # over the LLM-provided argument, which may be wrong.
    config_issue_number = configurable.get("github_issue", {}).get("number")
    logger.info(
        "github_comment: LLM issue_number=%s, config issue_number=%s, configurable keys=%s",
        issue_number, config_issue_number, list(configurable.keys()),
    )
    if config_issue_number:
        issue_number = config_issue_number
    if not issue_number:
        return {"success": False, "error": "Missing issue_number argument"}
    if not repo_config:
        return {"success": False, "error": "No repo config found in config"}
    if not message.strip():
        return {"success": False, "error": "Message cannot be empty"}

    token = asyncio.run(get_github_app_installation_token())
    if not token:
        token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return {"success": False, "error": "Failed to get GitHub App installation token"}

    success = asyncio.run(post_github_comment(repo_config, issue_number, message, token=token))
    return {"success": success}
