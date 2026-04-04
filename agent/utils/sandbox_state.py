"""Shared sandbox state used by server and middleware."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from langgraph_sdk import get_client

from .sandbox import create_sandbox

logger = logging.getLogger(__name__)

# Thread ID -> SandboxBackend mapping, shared between server.py and middleware
SANDBOX_BACKENDS: dict[str, Any] = {}

_LANGGRAPH_URL = os.environ.get("LANGGRAPH_URL", "http://localhost:2026")
client = get_client(url=_LANGGRAPH_URL)


async def get_sandbox_id_from_metadata(thread_id: str) -> str | None:
    """Fetch sandbox_id from thread metadata via the API."""
    try:
        thread = await client.threads.get(thread_id)
        return thread.get("metadata", {}).get("sandbox_id")
    except Exception:
        logger.exception("Failed to read thread metadata for sandbox")
        return None


async def get_sandbox_backend(thread_id: str) -> Any | None:
    """Get sandbox backend from cache, or connect using thread metadata."""
    sandbox_backend = SANDBOX_BACKENDS.get(thread_id)
    if sandbox_backend:
        return sandbox_backend

    sandbox_id = await get_sandbox_id_from_metadata(thread_id)
    if not sandbox_id:
        raise ValueError(f"Missing sandbox_id in thread metadata for {thread_id}")

    sandbox_backend = await asyncio.to_thread(create_sandbox, sandbox_id)
    SANDBOX_BACKENDS[thread_id] = sandbox_backend
    return sandbox_backend


def get_sandbox_backend_sync(thread_id: str) -> Any | None:
    """Sync wrapper for get_sandbox_backend."""
    return asyncio.run(get_sandbox_backend(thread_id))
