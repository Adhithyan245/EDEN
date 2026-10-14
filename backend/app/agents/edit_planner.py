"""Edit planner — turns a natural-language change into a minimal set of file edits.

This is the editing counterpart to planner.py. It never regenerates the whole
application. Given the current contents of the app's source files and the
requested change, it returns the COMPLETE new content for only the files that
actually need to change.

It also understands intent behind vague requests. "Make it prettier" is a design
request, not a code request — the planner infers concrete changes to layout,
spacing, colour, typography, or motion rather than asking questions.

Returns None on failure, and an EditPlan with no file edits when the request
does not actually require a code change (EDEN then responds naturally instead of
editing blindly). Reality wins — it never claims an edit it did not make.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from ..config import settings
from ..providers.base import LLMProvider
from ..utils import extract_json

log = logging.getLogger("eden.agents.edit_planner")


@dataclass
class FileEdit:
    path:    str   # project-relative path
    content: str   # complete new file content


@dataclass
class EditPlan:
    summary:   str                    # short human description of the change
    edits:     list[FileEdit] = field(default_factory=list)
    narration: str            = ""    # optional model-written line EDEN can say

    @property
    def touches(self) -> list[str]:
        return [e.path for e in self.edits]

    @property
    def is_empty(self) -> bool:
        return not self.edits


_EDIT_SYSTEM = """\
You are a senior front-end engineer editing an existing, already-running React +
Vite application. Respond with ONE valid JSON object and nothing else — no
markdown, no commentary, no code fences.

You are given the current contents of the project's source files and a requested
change. Make the SMALLEST set of edits that satisfies the request. Do NOT rewrite
the whole app when a focused change will do. Only return files you actually
change.

Understand intent, do not ask questions:
  - Vague design requests ("make it prettier", "more modern", "cleaner", "mobile
    friendly") are design work: adjust layout, spacing, colour, contrast,
    typography, and motion. Infer sensible choices.
  - Functional requests ("add dark mode", "add a reset button", "sort the list")
    change behaviour: edit the component logic and its styles.
  - If the request genuinely needs no code change, return an empty "files" list
    and explain why in "summary".

Return this exact JSON shape:

{
  "summary": "<one short sentence describing what you changed>",
  "narration": "<one natural sentence EDEN could say about the change>",
  "files": [
    { "path": "src/App.jsx", "content": "<the COMPLETE new file content>" }
  ]
}

Hard rules for any src/*.jsx you return:
  - Provide the COMPLETE file, not a diff and not a fragment.
  - Keep a single default export: export default function App() { ... }.
  - Import only from 'react'. Do NOT import any other package.
  - Do NOT import the CSS file — the entrypoint already imports it. Use className.
  - The code must run as-is. No placeholders, no TODO, no ellipses.

Hard rules for src/styles.css:
  - Return the COMPLETE stylesheet, styling class names the component actually uses.

Preserve everything the request did not ask to change.
"""


async def generate_edit_plan(
    project_summary: str,
    request:         str,
    current_files:   dict[str, str],
    llm:             LLMProvider,
    repair_error:    Optional[str] = None,
) -> Optional[EditPlan]:
    """Generate an EditPlan for ``request`` against ``current_files``.

    ``current_files`` maps project-relative paths to their current contents.
    When ``repair_error`` is set, the planner is asked to fix that specific
    validation error in its previous attempt.
    """
    files_block = "\n\n".join(
        f"--- {path} ---\n{content}" for path, content in current_files.items()
    )

    parts = [
        f"Active project: {project_summary}",
        f"Requested change: {request}",
        "",
        "Current source files:",
        files_block,
    ]
    if repair_error:
        parts += [
            "",
            "Your previous edit failed validation with this error:",
            repair_error,
            "Return corrected file(s) that fix this specific problem.",
        ]
    user_prompt = "\n".join(parts)

    try:
        raw_parts: list[str] = []
        async for chunk in llm.stream_reply(
            [{"role": "user", "content": user_prompt}],
            _EDIT_SYSTEM,
            model=settings.model_builder,
        ):
            raw_parts.append(chunk)
            if len("".join(raw_parts)) > 60000:
                break
        raw = "".join(raw_parts).strip()
        data = extract_json(raw)
    except Exception as exc:  # noqa: BLE001
        log.warning("edit planning failed (%s)", exc)
        return None

    edits: list[FileEdit] = []
    for f in data.get("files") or []:
        path = str(f.get("path") or "").replace("\\", "/").strip().lstrip("/")
        content = str(f.get("content") or "")
        if path and content.strip():
            edits.append(FileEdit(path=path, content=content))

    return EditPlan(
        summary   = str(data.get("summary") or "").strip() or "Updated the project.",
        narration = str(data.get("narration") or "").strip(),
        edits     = edits,
    )
