"""Verifier — confirms an application is actually running and serving correctly.

UNUSED as of the workspace-only edit/build architecture: builds no longer
launch a dev server and the edit pipeline no longer verifies one (see
``agents/edit_orchestrator.py``, which now calls
``builder.validator.validate_workspace`` instead of ``verify_app``). Nothing
in the codebase currently calls ``verify_app``. Left in place rather than
deleted in case a future "live preview" feature reintroduces a running server
to check against — if that never happens, this module is safe to remove.

Two-stage check:

  Stage 1 — HTTP liveness: polls the root URL until it returns a non-5xx status.
             This confirms the dev server process is up.

  Stage 2 — JS module content: fetches /src/main.jsx and verifies the response
             is JavaScript, NOT HTML.  This is the critical gate that catches
             "Vite returning index.html as SPA fallback" — which happens when
             Vite's working directory doesn't match where the files were written.

Without Stage 2, verify_app returns True even when the browser will show a
blank white screen with:
    Uncaught SyntaxError: Unexpected token '<'  (at /src/main.jsx)
"""

from __future__ import annotations

import asyncio
import logging

import httpx

log = logging.getLogger("eden.agents.verifier")

_POLL_INTERVAL = 1.0    # seconds between liveness attempts
_REQUEST_TIMEOUT = 2.0  # seconds per individual HTTP request
_CONTENT_TIMEOUT = 5.0  # seconds for the JS content check


async def verify_app(url: str, timeout_seconds: int = 20) -> bool:
    """Return True only when the app is up AND serving JavaScript for /src/main.jsx.

    Stage 1 — liveness: poll ``url`` until HTTP < 500.
    Stage 2 — JS content: verify /src/main.jsx is not HTML (Vite SPA fallback).
    """
    log.info("verifying app at %s (timeout=%ds)", url, timeout_seconds)

    # ------------------------------------------------------------------
    # Stage 1: liveness poll
    # ------------------------------------------------------------------
    async with httpx.AsyncClient(follow_redirects=False) as client:
        for attempt in range(timeout_seconds):
            try:
                resp = await client.get(url, timeout=_REQUEST_TIMEOUT)
                if resp.status_code < 500:
                    log.info("liveness verified on attempt %d: HTTP %d", attempt + 1, resp.status_code)
                    break
            except (httpx.ConnectError, httpx.TimeoutException):
                pass  # server not up yet
            except Exception as exc:  # noqa: BLE001
                log.debug("verify attempt %d error: %s", attempt + 1, exc)
            await asyncio.sleep(_POLL_INTERVAL)
        else:
            log.warning("app did not respond at %s within %ds", url, timeout_seconds)
            return False

    # ------------------------------------------------------------------
    # Stage 2: JS module content check
    # Fetch /src/main.jsx — if Vite is running from the wrong directory it
    # returns index.html (text/html) instead of the compiled module.
    # ------------------------------------------------------------------
    jsx_url = url.rstrip("/") + "/src/main.jsx"
    log.info("JS content check: GET %s", jsx_url)
    try:
        async with httpx.AsyncClient(follow_redirects=False) as client:
            jsx_resp = await client.get(jsx_url, timeout=_CONTENT_TIMEOUT)

        content_type = jsx_resp.headers.get("content-type", "")
        body_start   = jsx_resp.text[:120].strip()

        log.info(
            "  /src/main.jsx → HTTP %d  content-type=%r  body_start=%r",
            jsx_resp.status_code, content_type, body_start,
        )

        # Vite serving the file correctly → content-type contains javascript
        # Vite SPA fallback (wrong cwd / missing file) → content-type is text/html
        if "html" in content_type.lower() or body_start.startswith("<!"):
            log.error(
                "CRITICAL: Vite returned HTML for /src/main.jsx — "
                "working directory mismatch or file not found in Vite root. "
                "content-type=%r  body_start=%r",
                content_type, body_start,
            )
            return False

        if "javascript" in content_type.lower() or "text/plain" in content_type.lower():
            log.info("  JS content check passed")
            return True

        # Unknown content-type: be permissive if body looks like JS
        if not body_start.startswith("<!"):
            log.info("  JS content check passed (non-HTML body, content-type=%r)", content_type)
            return True

        log.error("JS content check failed: unexpected content-type=%r", content_type)
        return False

    except Exception as exc:  # noqa: BLE001
        # If we can't fetch the module file, treat as failure so the repair
        # loop has a chance to fix it rather than opening a blank browser.
        log.error("JS content check error (%s) — treating as liveness failure", exc)
        return False
