"""Sandbox manager — isolated working directories for build tasks.

Every build request receives its own sandbox directory. The SandboxManager
tracks one sandbox per session; a new build for the same session replaces
the previous one, cleaning it up first.

Phase 1: create / cleanup / reuse logic. No code generation happens here yet.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Optional

log = logging.getLogger("eden.builder.sandbox")

# All EDEN build sandboxes share this root. Using the system temp directory
# means they are cleaned up automatically on reboot if EDEN forgets to.
_BASE = Path(tempfile.gettempdir()) / "eden_builds"


# ---------------------------------------------------------------------------
# Sandbox
# ---------------------------------------------------------------------------

class Sandbox:
    """An isolated working directory for a single build task."""

    def __init__(self, session_id: str, app_name: str) -> None:
        self.session_id = session_id
        self.app_name   = app_name
        # Sanitize app_name so it is safe as a directory component.
        safe_name  = "".join(c if c.isalnum() or c in "-_" else "_" for c in app_name).strip("_") or "app"
        self.root: Path = _BASE / session_id / safe_name

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def create(self) -> Path:
        """Create the sandbox directory tree and return the root path."""
        self.root.mkdir(parents=True, exist_ok=True)
        log.info("sandbox created: %s", self.root)
        return self.root

    def destroy(self) -> None:
        """Remove the entire sandbox directory tree, ignoring errors."""
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
            log.info("sandbox destroyed: %s", self.root)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def path(self, relative: str) -> Path:
        """Resolve a relative path within the sandbox root."""
        return self.root / relative

    def exists(self) -> bool:
        """True if the sandbox directory currently exists on disk."""
        return self.root.exists()

    def __repr__(self) -> str:
        return f"Sandbox(session={self.session_id!r}, root={self.root})"


# ---------------------------------------------------------------------------
# SandboxManager
# ---------------------------------------------------------------------------

class SandboxManager:
    """Manages the sandbox lifecycle across sessions.

    Keeps at most one active sandbox per session. Creating a new sandbox
    for a session that already has one destroys the old one first.
    """

    def __init__(self) -> None:
        self._sandboxes: dict[str, Sandbox] = {}

    def create(self, session_id: str, app_name: str) -> Sandbox:
        """Create a new sandbox for this session, replacing any existing one."""
        self.cleanup(session_id)
        sb = Sandbox(session_id=session_id, app_name=app_name)
        sb.create()
        self._sandboxes[session_id] = sb
        return sb

    def get(self, session_id: str) -> Optional[Sandbox]:
        """Return the active sandbox for a session, or None."""
        return self._sandboxes.get(session_id)

    def get_or_create(self, session_id: str, app_name: str) -> Sandbox:
        """Return the existing sandbox or create a new one."""
        sb = self._sandboxes.get(session_id)
        if sb and sb.exists():
            return sb
        return self.create(session_id, app_name)

    def cleanup(self, session_id: str) -> None:
        """Destroy the sandbox for a session if one exists."""
        sb = self._sandboxes.pop(session_id, None)
        if sb:
            sb.destroy()

    def cleanup_all(self) -> None:
        """Destroy all managed sandboxes. Call on server shutdown."""
        for sb in list(self._sandboxes.values()):
            sb.destroy()
        self._sandboxes.clear()
        log.info("all sandboxes cleaned up")

    def list_sessions(self) -> list[str]:
        return list(self._sandboxes.keys())

    def __repr__(self) -> str:
        return f"SandboxManager({len(self._sandboxes)} sessions)"


# Module-level singleton shared across the application
sandbox_manager = SandboxManager()
