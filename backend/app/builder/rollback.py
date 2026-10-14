"""Rollback manager — restore files to their state before an edit.

Before the patcher writes anything, it captures a Snapshot of every file it is
about to touch (including the fact that a file did not previously exist). If an
edit cannot be made safe, the snapshot is restored so the running application
returns to exactly its previous working state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("eden.builder.rollback")


@dataclass
class Snapshot:
    """Captured contents of a set of files, keyed by project-relative path.

    A value of ``None`` records that the file did not exist before the edit, so
    restoring removes it.
    """

    workspace: Path
    files:     dict[str, str | None] = field(default_factory=dict)

    @classmethod
    def capture(cls, workspace: Path, relative_paths: list[str]) -> "Snapshot":
        snap = cls(workspace=workspace)
        for rel in relative_paths:
            p = workspace / rel
            if p.exists():
                try:
                    snap.files[rel] = p.read_text(encoding="utf-8")
                except Exception as exc:  # noqa: BLE001
                    log.warning("snapshot read failed for %s: %s", rel, exc)
                    snap.files[rel] = None
            else:
                snap.files[rel] = None
        return snap

    def restore(self) -> None:
        """Return every captured file to its snapshotted state."""
        for rel, content in self.files.items():
            p = self.workspace / rel
            try:
                if content is None:
                    if p.exists():
                        p.unlink()
                else:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(content, encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                log.error("rollback restore failed for %s: %s", rel, exc)
        log.info("rolled back %d file(s)", len(self.files))
