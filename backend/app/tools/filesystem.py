"""Filesystem tool implementations.

All operations are scoped to the sandbox root — nothing is written outside it.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path, PureWindowsPath
from typing import Optional

from .base import ToolResult

log = logging.getLogger("eden.tools.filesystem")


def resolve_within(root: Path, relative: str) -> Optional[Path]:
    """Resolve ``relative`` under ``root``, or None if it would escape ``root``.

    Guards LLM-supplied paths: rejects absolute paths, drive letters, and any
    ``..`` traversal that lands outside the workspace.
    """
    # Check both path flavours so a Windows drive path ("C:/...") is refused on
    # Linux too, where it would otherwise read as a relative folder "C:".
    win = PureWindowsPath(relative)
    if not relative or Path(relative).is_absolute() or win.drive or win.is_absolute():
        return None
    base = root.resolve()
    target = (base / relative).resolve()
    if target != base and base not in target.parents:
        return None
    return target


async def create_directory(path: Path) -> ToolResult:
    """Create a directory (including all parents) if it does not already exist."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        log.debug("created directory: %s", path)
        return ToolResult(success=True, output=f"Created {path}")
    except Exception as exc:  # noqa: BLE001
        log.error("create_directory failed: %s — %s", path, exc)
        return ToolResult(success=False, output="", error=str(exc))


async def create_file(path: Path, content: str) -> ToolResult:
    """Write ``content`` to ``path``, creating parent directories as needed."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        # Verify the file was actually written
        if not path.exists():
            log.error("File does not exist immediately after write: %s", path)
            return ToolResult(
                success=False,
                output="",
                error="File was not created",
            )

        size = path.stat().st_size

        log.info(
            "create_file succeeded: %s (%d bytes)",
            path,
            size,
        )

        return ToolResult(
            success=True,
            output=f"Written {path.name} ({size:,} bytes)",
        )

    except Exception as exc:  # noqa: BLE001
        log.exception("create_file failed: %s", path)

        return ToolResult(
            success=False,
            output="",
            error=str(exc),
        )

async def read_file(path: Path) -> ToolResult:
    """Read and return the text content of a file."""
    try:
        if not path.exists():
            return ToolResult(success=False, output="", error=f"{path} does not exist")
        content = path.read_text(encoding="utf-8")
        return ToolResult(success=True, output=content)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(success=False, output="", error=str(exc))


async def list_files(root: Path, relative: bool = True) -> ToolResult:
    """Return a newline-separated list of all files under ``root``."""
    try:
        if not root.exists():
            return ToolResult(success=False, output="", error=f"{root} does not exist")
        paths = sorted(root.rglob("*"))
        files = [p for p in paths if p.is_file()]
        lines = [str(p.relative_to(root)) if relative else str(p) for p in files]
        return ToolResult(success=True, output="\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        return ToolResult(success=False, output="", error=str(exc))
