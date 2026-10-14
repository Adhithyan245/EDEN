"""Active-project memory — what EDEN is currently working on.

After a successful build the application becomes the ACTIVE PROJECT for the
session: its workspace path, type, framework, the files that make it up, the
plan that produced it, and a running history of what has happened to it. Every
subsequent edit refers to this project until another build replaces it.

The workspace directory is the project's primary identity — nothing is
launched or served, so there is no running process, port, or URL to track.
``port``, ``url``, and ``dev_process`` are retained only as legacy fields (see
below) so any code still constructing or reading them does not break.

One active project per session, tracked by the same session key the sandbox
manager uses (``str(id(session))``). This mirrors ``sandbox_manager`` so the two
lifecycles stay aligned: a new build replaces both the sandbox and the active
project for that session.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("eden.builder.active_project")


@dataclass
class ActiveProject:
    """Everything EDEN remembers about the app it is currently working on."""

    task_id:      str
    app_name:     str
    app_type:     str
    framework:    str                 # e.g. "react-vite"
    workspace:    Path                 # sandbox root on disk — the project's identity
    files:        list[str]            # project-relative file paths on disk

    # --- legacy fields from the pre-workspace architecture ------------------
    # No build launches a dev server anymore: port is always 0, url is always
    # "", and dev_process is always None. Kept only so existing constructors
    # and any lingering serializers don't break; nothing reads them as
    # meaningful state. Safe to delete once all call sites stop passing them.
    port:         int          = 0
    url:          str          = ""
    dev_process:  Optional[Any] = None

    plan:         Optional[Any] = None # the Plan that produced the build
    history:      list[str]     = field(default_factory=list)  # human-readable event log
    created_at:   datetime      = field(default_factory=datetime.utcnow)
    updated_at:   datetime      = field(default_factory=datetime.utcnow)

    # The app-owned source files EDEN edits (as opposed to fixed scaffold files).
    # These are the files the planner generated and the editor is allowed to touch.
    editable:     list[str]     = field(default_factory=lambda: ["src/App.jsx", "src/styles.css"])

    # Undo/redo timeline. Populated by VersionManager: a list of ProjectSnapshot
    # with a cursor pointing at the current version. -1 until initialized.
    versions:       list        = field(default_factory=list)
    version_cursor: int         = -1

    def note(self, message: str) -> None:
        """Append a line to the project history."""
        self.history.append(message)
        self.updated_at = datetime.utcnow()

    def abspath(self, relative: str) -> Path:
        return self.workspace / relative

    def summary(self) -> str:
        """A one-line description used to give the intent classifier context."""
        return f"{self.app_name} ({self.app_type}, {self.framework}) saved at {self.workspace}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id":    self.task_id,
            "app_name":   self.app_name,
            "app_type":   self.app_type,
            "framework":  self.framework,
            "workspace":  str(self.workspace),
            "port":       self.port,
            "url":        self.url,
            "files":      self.files,
            "editable":   self.editable,
            "history":    self.history,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class ProjectManager:
    """Tracks the active project for each session."""

    def __init__(self) -> None:
        self._projects: dict[str, ActiveProject] = {}

    def set(self, session_id: str, project: ActiveProject) -> None:
        self._projects[session_id] = project
        log.info("active project set for session %s: %s", session_id, project.summary())

    def get(self, session_id: str) -> Optional[ActiveProject]:
        return self._projects.get(session_id)

    def has(self, session_id: str) -> bool:
        return session_id in self._projects

    def clear(self, session_id: str) -> None:
        self._projects.pop(session_id, None)

    def __repr__(self) -> str:
        return f"ProjectManager({len(self._projects)} active)"


# Module-level singleton shared across the application
project_manager = ProjectManager()
