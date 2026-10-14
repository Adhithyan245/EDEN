"""Browser tool implementation.

UNUSED — no caller invokes ``open_browser_url`` anymore; the build/edit
pipeline no longer opens a browser (see ``agents/orchestrator.py``). Kept
dormant in case a future live-preview feature needs to open one again.

Opens a URL in the user's default system browser.
Platform-aware: tries webbrowser first, then a platform-specific subprocess
fallback so Windows demos don't silently skip the browser open.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import webbrowser

from .base import ToolResult

log = logging.getLogger("eden.tools.browser")


async def open_browser_url(url: str) -> ToolResult:
    """Open ``url`` in the default system browser.

    Tries ``webbrowser.open`` first. If that returns False or raises, falls
    back to a platform-specific shell command so the demo browser always opens.
    """
    try:
        opened = webbrowser.open(url, new=2)  # new=2 → new tab if possible
        if opened:
            log.info("browser opened: %s", url)
            return ToolResult(success=True, output=f"Opened {url}")
        log.warning("webbrowser.open returned False; trying platform fallback")
    except Exception as exc:  # noqa: BLE001
        log.warning("webbrowser.open raised (%s); trying platform fallback", exc)

    # Platform-specific fallback — more reliable when the default browser
    # association isn't registered with Python's webbrowser registry.
    try:
        if sys.platform == "win32":
            subprocess.Popen(["cmd", "/c", "start", "", url])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", url])
        else:
            subprocess.Popen(["xdg-open", url])
        log.info("browser opened via platform fallback: %s", url)
        return ToolResult(success=True, output=f"Opened {url}")
    except Exception as exc2:  # noqa: BLE001
        log.error("browser fallback also failed: %s", exc2)
        return ToolResult(success=False, output="", error=str(exc2))
