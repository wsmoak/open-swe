"""Sandbox-specific exception types."""

from __future__ import annotations


class SandboxUnavailableError(RuntimeError):
    """Raised when a sandbox exists logically but is no longer reachable."""
