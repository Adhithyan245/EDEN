"""Project Generator — turns a Plan into a ready-to-execute GeneratedProject.

Pipeline position:

  Planner  → Plan (app_name, app_type, the app-specific files, narration)
       ↓
  Generator → GeneratedProject (scaffold + app files, merged and normalized)
       ↓
  Executor → writes files, installs dependencies, saves to the workspace

Separation of concerns:
  - The Planner decides WHAT to build and writes only the app-specific files.
  - The Generator merges those over the fixed React + Vite scaffold and produces
    one concrete, path-normalized project representation.
  - The Executor performs pure I/O — no LLM calls, no build decisions.

``set_launch`` and the ``dev_start_command``/``expected_url``/``port`` fields
below are currently unreachable: the build pipeline no longer launches a dev
server or assigns a port (see ``agents/orchestrator.py`` and
``agents/executor.py``, whose launch phase is likewise dormant). Kept together
as one unit in case a future live-preview feature needs to launch and verify a
running server again — safe to remove alongside ``Executor.launch()`` if that
never happens.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..agents.planner import Plan

log = logging.getLogger("eden.builder.generator")


# ---------------------------------------------------------------------------
# Generated project model
# ---------------------------------------------------------------------------

@dataclass
class GeneratedFile:
    """A single file to be written inside the sandbox."""
    path:    str   # relative to sandbox root, POSIX-style
    content: str   # complete file content


@dataclass
class GeneratedProject:
    """Complete, executable representation of an application to be built.

    All paths are relative to ``workspace``. ``dev_start_command``,
    ``expected_url``, and ``port`` are UNUSED in the live pipeline — nothing
    calls ``set_launch`` anymore (see module docstring). They stay at their
    ``None`` defaults today.
    """
    task_id:            str
    app_type:           str
    app_name:           str
    workspace:          Path
    stack:              str                 = "react-vite"
    directories:        list[str]           = field(default_factory=list)
    files:              list[GeneratedFile] = field(default_factory=list)
    install_command:    Optional[str]       = None
    dev_start_command:  Optional[str]       = None
    expected_url:       Optional[str]       = None
    port:               Optional[int]       = None
    narration_intro:    str                 = ""
    narration_complete: str                 = ""

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def file_paths(self) -> list[str]:
        return [f.path for f in self.files]

    @property
    def has_dependencies(self) -> bool:
        """True if this stack requires a dependency install step."""
        return bool(self.install_command)

    def set_launch(self, port: int) -> None:
        """Fix the runtime port, the launch command, and the URL to verify.

        UNUSED — no caller invokes this anymore; the build pipeline does not
        launch a dev server. Kept for a possible future live-preview feature
        (see module docstring); safe to remove alongside ``Executor.launch()``.

        URL note: use 127.0.0.1 explicitly rather than 'localhost'.  On some
        Windows machines the hosts file maps 'localhost' to ::1 (IPv6) while
        Vite (without --host) listens on 127.0.0.1 (IPv4).  Using the IP
        directly removes that ambiguity in the verifier, the render verifier,
        and the browser-open call.

        Host note: --host is intentionally omitted from the CLI flags; the
        vite.config.js sets host: true which makes Vite listen on all
        interfaces (127.0.0.1 + ::1 + LAN).  This lets the browser reach it
        via either IP family, and lets Vite print its own address to its log
        without us overriding it incorrectly.
        """
        self.port              = port
        self.expected_url      = f"http://127.0.0.1:{port}"
        # --strictPort makes Vite fail loudly rather than silently drifting to
        # another port, so the URL we verify is the URL it must serve on.
        self.dev_start_command = f"npm run dev -- --port {port} --strictPort"


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def from_plan(plan: Plan) -> GeneratedProject:
    """Merge the React + Vite scaffold with the planner's app files.

    Scaffold files are laid down first; the planner's files overwrite on any
    path collision. Planner file paths are normalized so the app component and
    stylesheet always land where the scaffold entrypoint imports them.
    """
    # Lazy import avoids a circular dependency (template imports GeneratedFile).
    from ..builder import template

    merged: dict[str, GeneratedFile] = {}

    for f in template.scaffold(plan.app_name):
        merged[f.path] = f

    app_file_count = 0
    for step in plan.steps:
        if step.action != "create_file" or not step.path:
            continue
        content = step.content or ""
        if not content.strip():
            log.warning("planner file %r is empty — skipping", step.path)
            continue
        norm = _normalize_path(step.path)
        merged[norm] = GeneratedFile(path=norm, content=content)
        app_file_count += 1

    project = GeneratedProject(
        task_id            = plan.task_id,
        app_type           = plan.app_type,
        app_name           = plan.app_name,
        workspace          = plan.workspace or Path("."),
        stack              = "react-vite",
        directories        = ["src"],
        files              = list(merged.values()),
        install_command    = "npm install --no-audit --no-fund --prefer-offline",
        narration_intro    = plan.narration_intro,
        narration_complete = plan.narration_complete,
    )

    log.info(
        "generated project: %s — %d files total (%d from planner)",
        project.app_name, project.file_count, app_file_count,
    )
    return project


# ---------------------------------------------------------------------------
# Path normalization
# ---------------------------------------------------------------------------

def _normalize_path(raw: str) -> str:
    """Map a planner-provided path onto the scaffold's expected layout.

    The scaffold entrypoint imports ./App.jsx and ./styles.css from src/, so the
    planner's app component and stylesheet must land there even if the model
    named them slightly differently (App.tsx, app.jsx, style.css, ...).
    """
    p = raw.replace("\\", "/").lstrip("/")
    name = p.rsplit("/", 1)[-1].lower()

    if name in {"app.jsx", "app.tsx", "app.js", "app.ts"}:
        return "src/App.jsx"
    if name.endswith(".css"):
        return "src/styles.css"

    # Anything else: keep it, but ensure it lives under src/ if it is source.
    if p.startswith("src/") or "/" in p:
        return p
    return f"src/{p}"
