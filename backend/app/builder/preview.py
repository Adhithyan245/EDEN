"""Compile check + preview hosting for generated projects.

``compile_project`` runs the project's real production build (``vite build``).
This is EDEN's compile verifier: it proves the generated code parses, its
imports resolve, and the bundle can be produced — stronger than the static
checks in ``validator.py``, which run first because they are instant.

A successful build leaves ``dist/`` in the workspace. ``PreviewRegistry`` maps
an unguessable preview id to that folder so the backend can serve the compiled
app over HTTP (see the ``/preview`` route in ``main.py``). Nothing is launched:
the preview is static files, so there is no dev server to leak or kill.
"""

from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..tools import shell

log = logging.getLogger("eden.builder.preview")

_BUILD_TIMEOUT = 120
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


@dataclass
class CompileResult:
    ok:    bool
    error: str = ""   # the tail of the build output, for repair prompts


async def compile_project(workspace: Path) -> CompileResult:
    """Run ``npm run build`` in ``workspace``. Never raises."""
    result = await shell.run_command("npm run build", workspace, timeout=_BUILD_TIMEOUT)
    if result.success and (workspace / "dist" / "index.html").exists():
        return CompileResult(ok=True)
    detail = _ANSI.sub("", (result.output or "") + "\n" + (result.error or "")).strip()
    log.warning("compile failed in %s: %s", workspace, detail[-300:])
    return CompileResult(ok=False, error=_summarize(detail))


def _summarize(output: str) -> str:
    """Keep the lines that explain the failure, capped for prompt size."""
    lines = [l for l in output.splitlines() if l.strip()]
    key = [l for l in lines if re.search(r"error|Error|failed|Unexpected|not found|expected", l)]
    picked = (key or lines)[-12:]
    return "\n".join(picked)[-1500:] or "the build failed"


class PreviewRegistry:
    """preview id -> compiled ``dist/`` folder. One id per workspace."""

    def __init__(self) -> None:
        self._by_id: dict[str, Path] = {}
        self._by_workspace: dict[Path, str] = {}

    def register(self, workspace: Path) -> str:
        workspace = workspace.resolve()
        pid = self._by_workspace.get(workspace)
        if pid is None:
            pid = secrets.token_urlsafe(12)
            self._by_workspace[workspace] = pid
        self._by_id[pid] = workspace / "dist"
        return pid

    def dist(self, pid: str) -> Optional[Path]:
        return self._by_id.get(pid)

    def url(self, pid: str) -> str:
        return f"/preview/{pid}/"


previews = PreviewRegistry()


async def publish(workspace: Path) -> tuple[CompileResult, Optional[str]]:
    """Compile and, on success, register a preview. Returns (result, preview_url)."""
    result = await compile_project(workspace)
    if not result.ok:
        return result, None
    return result, previews.url(previews.register(workspace))
