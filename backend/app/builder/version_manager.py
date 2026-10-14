"""Version history — lightweight project snapshots for undo / redo.

A ProjectSnapshot is a copy of the app's source files (everything under src/) at
a point in time. The VersionManager keeps an ordered list of these on the active
project with a cursor pointing at the current version, giving a simple linear
undo/redo timeline:

    v0 (initial build) — v1 (after edit 1) — v2 (after edit 2) ...
                                                  ^ cursor

  - undo  moves the cursor back one and restores that snapshot to disk.
  - redo  moves the cursor forward one and restores it.
  - a new edit after an undo truncates the "redo tail" before recording, exactly
    like an editor's undo stack.

Restoring writes files to disk; Vite hot-reloads them, so undo/redo never
rebuild, reinstall, or restart the dev server. Snapshots are small (a couple of
source files) and kept in memory for the session — this is a demo-scale history,
not a git replacement.

File I/O here is synchronous, mirroring rollback.py: the file set is tiny and
this is not on a latency-critical path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("eden.builder.version_manager")

_SOURCE_SUFFIXES = (".jsx", ".tsx", ".js", ".ts", ".css")


@dataclass
class ProjectSnapshot:
    """The app's source files captured at one moment."""
    label:      str
    files:      dict[str, str]           # project-relative path -> content
    created_at: datetime = field(default_factory=datetime.utcnow)


class VersionManager:
    """Undo/redo timeline for a single active project.

    State (the versions list and cursor) lives on the ActiveProject; this class
    holds the behaviour that operates on it.
    """

    # ------------------------------------------------------------------
    # Capture / restore primitives
    # ------------------------------------------------------------------
    def _capture(self, workspace: Path, label: str) -> ProjectSnapshot:
        files: dict[str, str] = {}
        src = workspace / "src"
        if src.exists():
            for p in sorted(src.rglob("*")):
                if p.is_file() and p.suffix.lower() in _SOURCE_SUFFIXES:
                    rel = p.relative_to(workspace).as_posix()
                    try:
                        files[rel] = p.read_text(encoding="utf-8")
                    except Exception as exc:  # noqa: BLE001
                        log.warning("snapshot read failed for %s: %s", rel, exc)
        return ProjectSnapshot(label=label, files=files)

    def _restore(self, workspace: Path, snapshot: ProjectSnapshot) -> None:
        for rel, content in snapshot.files.items():
            p = workspace / rel
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                log.error("snapshot restore failed for %s: %s", rel, exc)

    # ------------------------------------------------------------------
    # Timeline operations (operate on an ActiveProject)
    # ------------------------------------------------------------------
    def init(self, project) -> None:
        """Seed the timeline with the initial build as v0."""
        snap = self._capture(project.workspace, "initial build")
        project.versions = [snap]
        project.version_cursor = 0
        log.info("version history initialized for %s (v0)", project.app_name)

    def record(self, project, label: str) -> None:
        """Record the current on-disk state as a new version after an edit."""
        if project.version_cursor < len(project.versions) - 1:
            # Discard any redo tail before branching a new edit.
            project.versions = project.versions[: project.version_cursor + 1]
        snap = self._capture(project.workspace, label)
        project.versions.append(snap)
        project.version_cursor = len(project.versions) - 1
        log.info("recorded version v%d (%s) for %s",
                 project.version_cursor, label, project.app_name)

    def can_undo(self, project) -> bool:
        return project.version_cursor > 0

    def can_redo(self, project) -> bool:
        return 0 <= project.version_cursor < len(project.versions) - 1

    def undo(self, project) -> Optional[ProjectSnapshot]:
        if not self.can_undo(project):
            return None
        project.version_cursor -= 1
        snap = project.versions[project.version_cursor]
        self._restore(project.workspace, snap)
        log.info("undo → v%d (%s)", project.version_cursor, snap.label)
        return snap

    def redo(self, project) -> Optional[ProjectSnapshot]:
        if not self.can_redo(project):
            return None
        project.version_cursor += 1
        snap = project.versions[project.version_cursor]
        self._restore(project.workspace, snap)
        log.info("redo → v%d (%s)", project.version_cursor, snap.label)
        return snap


# Module-level singleton
version_manager = VersionManager()
