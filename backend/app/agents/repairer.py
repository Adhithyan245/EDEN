"""Repairer — fixes a broken React component after render verification fails.

UNUSED — its only caller was the render-verification repair loop, which no
build path invokes anymore (see ``agents/render_verifier.py``'s module note).
No code path calls ``repair_app_jsx``. Kept dormant alongside
``render_verifier.py`` and ``agents/verifier.py`` in case a future
live-preview feature needs this repair loop again.

When render_verifier detects console errors or an empty root, this module:

  1. Reads the current src/App.jsx from the workspace.
  2. Calls the LLM with a focused repair prompt (separate from the personality
     prompt) that includes the console errors and the broken source code.
  3. Writes the fixed App.jsx back to the sandbox.
  4. Waits for Vite's HMR to pick up the change (no server restart needed).
  5. Returns True if a corrected file was written (caller must re-verify).

Only App.jsx is repaired here.  styles.css errors are usually caused by the
component referencing a class that does not exist, which is fixed by repairing
the component itself.  If styles.css genuinely needs fixing, a second iteration
of the repair loop handles it.

The orchestrator caps attempts at MAX_RENDER_REPAIRS (default 2).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import WebSocket

from ..providers.base import LLMProvider
from ..utils import extract_json

log = logging.getLogger("eden.agents.repairer")

# How long to wait after writing the fixed file so Vite HMR can apply it.
_HMR_WAIT_SECONDS = 3.5

_REPAIR_SYSTEM = """\
You are a React expert fixing a broken application component.

The project uses React 18 + Vite (plain JSX, not TypeScript).
A headless browser detected render failures — errors and the broken source are below.
Your job is to return a corrected src/App.jsx that renders without errors.

Hard rules:
- Import ONLY from 'react' (useState, useEffect, useRef, etc.). No other packages.
- Provide exactly one default export: export default function App() { ... }
- Do NOT import the CSS file — the entrypoint (src/main.jsx) already does.
- Fix every error shown. If the root cause is unclear, simplify to a minimal
  but fully functional version of the intended app.
- The fixed component must be complete and runnable — no placeholders, no TODOs.

Return ONLY a valid JSON object with one key:
{"app_jsx": "<complete, corrected contents of src/App.jsx>"}

No markdown, no code fences, no commentary outside the JSON.
"""


async def repair_app_jsx(
    workspace: Path,
    console_errors: list[str],
    error_summary: str,
    llm: LLMProvider,
    attempt: int = 1,
) -> bool:
    """Attempt to rewrite App.jsx so the app renders.

    Returns True if a replacement file was written to disk (not whether it
    renders — that is the caller's job to re-verify).
    """
    app_path = workspace / "src" / "App.jsx"

    try:
        current_jsx = app_path.read_text(encoding="utf-8")
    except OSError as exc:
        log.error("repair attempt %d: cannot read App.jsx: %s", attempt, exc)
        return False

    # Build a concise error block for the LLM
    if console_errors:
        error_lines = "\n".join(f"  • {e}" for e in console_errors[:10])
        error_block = f"Console / browser errors:\n{error_lines}"
    else:
        error_block = f"Symptom: {error_summary or 'React root is empty — nothing rendered.'}"

    prompt = (
        f"Repair attempt {attempt}.\n\n"
        f"{error_block}\n\n"
        f"Current src/App.jsx:\n"
        f"```jsx\n{current_jsx}\n```\n\n"
        f"Return the fixed JSON object."
    )

    log.info("repair attempt %d: calling LLM (%d error(s))", attempt, len(console_errors))

    try:
        raw_parts: list[str] = []
        async for chunk in llm.stream_reply(
            [{"role": "user", "content": prompt}],
            _REPAIR_SYSTEM,
        ):
            raw_parts.append(chunk)
            if len("".join(raw_parts)) > 50_000:
                break

        raw = "".join(raw_parts).strip()
        data = extract_json(raw)
        fixed_jsx = str(data.get("app_jsx") or "").strip()

        if not fixed_jsx or "export default" not in fixed_jsx:
            log.warning("repair attempt %d: LLM returned no usable component", attempt)
            return False

        app_path.write_text(fixed_jsx, encoding="utf-8")
        log.info(
            "repair attempt %d: wrote fixed App.jsx (%d chars) — waiting %.1fs for HMR",
            attempt, len(fixed_jsx), _HMR_WAIT_SECONDS,
        )

        # Give Vite's file watcher time to detect the change and push HMR.
        await asyncio.sleep(_HMR_WAIT_SECONDS)
        return True

    except Exception as exc:  # noqa: BLE001
        log.error("repair attempt %d: LLM call failed: %s", attempt, exc)
        return False
