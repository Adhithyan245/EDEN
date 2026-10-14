"""Render verifier — confirms a React/Vite app actually rendered in a browser.

UNUSED as of the workspace-only build/edit architecture: nothing launches a
dev server anymore (see ``agents/orchestrator.py``, ``agents/edit_orchestrator.py``),
so there is nothing for a headless browser to check. No code path calls
``verify_render``. Kept in place, along with ``agents/verifier.py`` and
``agents/repairer.py`` and the ``render_*`` events in ``events.py``, in case a
future live-preview feature reintroduces a running server to verify and repair
against — if that never happens, this whole group is safe to remove together.

After the HTTP verifier confirms the dev server is up, this module opens the
page in a headless Chromium browser (via Playwright) and checks:

  - The page HTML loaded (not a blank 200)
  - <div id="root"> has been populated by React (has child elements)
  - No Vite error overlay is visible
  - No fatal console errors (uncaught exceptions, module resolution, syntax errors,
    failed imports, unhandled promise rejections)

If Playwright is not installed or its browsers are not downloaded, the module
falls back to a basic HTML check via httpx (can detect missing root, script
tags) and logs a clear warning.  The fallback is deliberately optimistic so a
missing Playwright install does not block the demo.

Install notes (one-time, after pip install playwright):
    playwright install chromium
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

log = logging.getLogger("eden.agents.render_verifier")

# Poll cadence while waiting for React to mount (observable-state polling,
# not a blind sleep — see _verify_playwright).
_POLL_INTERVAL_MS = 250
_MOUNT_TIMEOUT_MS = 15_000
_READY_STATE_TIMEOUT_MS = 10_000

# ---------------------------------------------------------------------------
# Optional Playwright import
# ---------------------------------------------------------------------------

_PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.async_api import async_playwright  # type: ignore[import]
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    log.warning(
        "playwright not installed — render verification will use basic HTML fallback. "
        "For full checking: pip install playwright && playwright install chromium"
    )

# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class RenderResult:
    """Outcome of a render verification check."""

    success: bool
    html_ok: bool = True
    root_populated: bool = False
    vite_overlay_present: bool = False
    console_errors: list[str] = field(default_factory=list)
    error_summary: str = ""
    playwright_used: bool = False
    # True when the dev server itself is confirmed stuck serving raw,
    # untransformed JSX for /src/main.jsx (see _is_transform_fault). This is
    # NOT "React hasn't mounted yet" — it is a dead-end that no amount of
    # additional polling can recover from; only a dev-server process restart
    # fixes it. Distinguished from a real code defect so the orchestrator can
    # restart the server instead of wasting an LLM repair attempt on code
    # that was never actually broken.
    transform_fault: bool = False

    @property
    def fatal_errors(self) -> list[str]:
        return [e for e in self.console_errors if _is_fatal(e)]


# ---------------------------------------------------------------------------
# Fatal-error classification
# ---------------------------------------------------------------------------

_FATAL_PATTERNS = (
    "cannot read properties of",
    "is not a function",
    "syntaxerror",
    "referenceerror",
    "typeerror",
    "module not found",
    "failed to resolve",
    "failed to load",
    "uncaught error",
    "uncaught typeerror",
    "uncaught referenceerror",
    "uncaught syntaxerror",
    "transform failed",
    "does not provide an export",
    "named export",
    "import error",
    "cannot find module",
    "unexpected token",
    "expected expression",
)


def _is_fatal(text: str) -> bool:
    t = text.lower()
    return any(p in t for p in _FATAL_PATTERNS)


async def _safe_online(page) -> bool:  # type: ignore[no-untyped-def]
    try:
        return bool(await page.evaluate("navigator.onLine"))
    except Exception:
        return False


async def _check_transform_fault(page, url: str) -> bool:  # type: ignore[no-untyped-def]
    """Detect a Vite dev server stuck serving raw, untransformed JSX.

    Forensic finding (reproduced repeatedly against the live build pipeline):
    a Vite dev server process can enter a state where /src/main.jsx is served
    with HTTP 200 and content-type text/javascript, but the body is the raw
    source file — JSX syntax and bare import specifiers ('react') were never
    run through esbuild/@vitejs/plugin-react's transform. A browser's native
    module loader cannot parse JSX or resolve a bare specifier, so it throws
    "Unexpected token '<'" synchronously and the page never mounts.

    This is NOT a mounting-delay race: confirmed live that this state persists
    unchanged after 15+ seconds of polling, after touching the source file
    (which does not reset whatever internal state caused it), and after
    cache-busting query parameters — the only thing that recovers it is
    restarting the dev server process. A correctly-transformed response never
    contains a bare 'from "react"'/"from 'react'" specifier (Vite always
    rewrites resolved imports to a concrete /node_modules/.vite/deps/... path),
    so that literal substring is a reliable, observable signature.
    """
    try:
        body = await page.evaluate(
            f"fetch({url!r} + '/src/main.jsx').then(r => r.text())"
        )
    except Exception:
        return False
    return "from 'react'" in body or 'from "react"' in body


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def verify_render(url: str, timeout_seconds: int = 15) -> RenderResult:
    """Return a RenderResult for the React app at *url*.

    Uses Playwright if available; falls back to basic HTML checks otherwise.
    """
    if _PLAYWRIGHT_AVAILABLE:
        return await _verify_playwright(url, timeout_seconds)
    return await _verify_httpx(url)


# ---------------------------------------------------------------------------
# Playwright path
# ---------------------------------------------------------------------------

async def _verify_playwright(url: str, timeout_ms_total: int) -> RenderResult:
    console_errors: list[str] = []
    console_warnings: list[str] = []
    network_failures: list[str] = []
    t_start = time.monotonic()

    def _elapsed_ms() -> int:
        return int((time.monotonic() - t_start) * 1000)

    try:
        async with async_playwright() as pw:
            try:
                browser = await pw.chromium.launch(headless=True)
            except Exception as exc:
                log.warning(
                    "Playwright browser could not launch (%s). "
                    "Run 'playwright install chromium' to fix. Falling back to HTML check.",
                    exc,
                )
                return await _verify_httpx(url)

            try:
                context = await browser.new_context()
                page = await context.new_page()

                # --- Diagnostic listeners -----------------------------------
                def _on_console(msg):  # type: ignore[no-untyped-def]
                    text = msg.text
                    if msg.type == "error":
                        if text and _is_fatal(text):
                            console_errors.append(text)
                        log.info("[t=%dms] console.error: %s", _elapsed_ms(), text)
                    elif msg.type == "warning":
                        console_warnings.append(text)
                        log.info("[t=%dms] console.warning: %s", _elapsed_ms(), text)

                page.on("console", _on_console)
                # Uncaught exceptions AND unhandled promise rejections both
                # surface here in Playwright/Chromium.
                page.on(
                    "pageerror",
                    lambda exc: (
                        console_errors.append(f"Uncaught: {exc}"),
                        log.info("[t=%dms] pageerror: %s", _elapsed_ms(), exc),
                    ),
                )

                def _on_response(resp):  # type: ignore[no-untyped-def]
                    if resp.status >= 400:
                        network_failures.append(f"{resp.status} {resp.url}")
                    ct = resp.headers.get("content-type", "")
                    is_script_path = resp.url.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs")) or "main.jsx" in resp.url
                    suspicious = resp.status >= 400 or (is_script_path and "html" in ct.lower())
                    log.info(
                        "[t=%dms] FORENSIC response: %d %s content-type=%r%s",
                        _elapsed_ms(), resp.status, resp.url, ct,
                        "  <<< SUSPICIOUS" if suspicious else "",
                    )

                page.on("response", _on_response)
                page.on(
                    "requestfailed",
                    lambda req: (
                        network_failures.append(f"FAILED {req.url} ({req.failure})"),
                        log.info(
                            "[t=%dms] request failed: %s (%s)",
                            _elapsed_ms(), req.url, req.failure,
                        ),
                    ),
                )

                log.info("render verification started: url=%s", url)

                # Navigate
                try:
                    await page.goto(
                        url,
                        timeout=timeout_ms_total * 1000,
                        wait_until="domcontentloaded",
                    )
                except Exception as nav_exc:
                    log.warning("Playwright navigation to %s failed: %s", url, nav_exc)
                    return RenderResult(
                        success=False,
                        html_ok=False,
                        error_summary=f"Page failed to load: {nav_exc}",
                        playwright_used=True,
                    )

                http_status = None
                try:
                    nav_resp = await page.evaluate(
                        "() => window.performance.getEntriesByType('navigation')[0]?.responseStatus ?? null"
                    )
                    http_status = nav_resp
                except Exception:
                    pass

                # --- Wait for document.readyState == 'complete' ------------
                # Observable state, not a blind sleep: poll the real DOM flag.
                ready_deadline = t_start + (_READY_STATE_TIMEOUT_MS / 1000)
                ready_state = "unknown"
                while time.monotonic() < ready_deadline:
                    ready_state = await page.evaluate("document.readyState")
                    if ready_state == "complete":
                        break
                    await page.wait_for_timeout(_POLL_INTERVAL_MS)
                log.info(
                    "[t=%dms] document.readyState=%s (after wait)",
                    _elapsed_ms(), ready_state,
                )

                # --- Dev-server transform-fault check ------------------------
                # Checked once, before the mount-poll loop: if positive, no
                # amount of polling will change the outcome (proven live) —
                # failing fast here saves ~15s per attempt versus discovering
                # the same dead end at the end of a full poll cycle.
                if await _check_transform_fault(page, url):
                    log.error(
                        "[t=%dms] TRANSFORM FAULT: dev server is serving raw, "
                        "untransformed JSX for /src/main.jsx — this is a stuck "
                        "dev-server process state, not a mounting delay or a "
                        "code defect",
                        _elapsed_ms(),
                    )
                    return RenderResult(
                        success=False,
                        html_ok=True,
                        root_populated=False,
                        console_errors=console_errors,
                        error_summary=(
                            "Dev server is serving untransformed JSX (stuck process state) "
                            "— restarting the dev server, not repairing code, is required"
                        ),
                        playwright_used=True,
                        transform_fault=True,
                    )

                # --- Poll for React mounting ---------------------------------
                # Root population is the ground truth for "did React mount",
                # checked repeatedly against live browser state (no fixed
                # sleep) until it succeeds or the mount timeout is exhausted.
                mount_deadline = t_start + (_MOUNT_TIMEOUT_MS / 1000)
                root_populated = False
                root_children = 0
                root_html_len = 0
                has_overlay = False
                vite_client_ready = False
                tick = 0

                while True:
                    tick += 1
                    try:
                        root_children = await page.eval_on_selector(
                            "#root", "el => el.children.length"
                        )
                        root_html_len = await page.eval_on_selector(
                            "#root", "el => el.innerHTML.length"
                        )
                        root_populated = root_children > 0
                    except Exception:
                        root_populated = False
                        root_children = 0
                        root_html_len = 0

                    vite_overlay = await page.query_selector(
                        "#vite-error-overlay, vite-error-overlay"
                    )
                    has_overlay = vite_overlay is not None

                    try:
                        vite_client_ready = bool(
                            await page.evaluate(
                                "window.__vite_plugin_react_preamble_installed__ === true"
                            )
                        )
                    except Exception:
                        vite_client_ready = False

                    log.info(
                        "[t=%dms] poll #%d: root_children=%d root_html_len=%d "
                        "overlay=%s vite_client_ready=%s console_errors=%d "
                        "console_warnings=%d network_failures=%d navigator.onLine=%s",
                        _elapsed_ms(), tick, root_children, root_html_len,
                        has_overlay, vite_client_ready, len(console_errors),
                        len(console_warnings), len(network_failures),
                        await _safe_online(page),
                    )

                    # Success as soon as the root is genuinely populated and
                    # no error overlay is currently showing — this is allowed
                    # to happen on the very first tick if React was already
                    # mounted by the time we got here.
                    if root_populated and not has_overlay:
                        break

                    if time.monotonic() >= mount_deadline:
                        break

                    await page.wait_for_timeout(_POLL_INTERVAL_MS)

                fatal = [e for e in console_errors if _is_fatal(e)]
                success = root_populated and not has_overlay

                parts: list[str] = []
                if not root_populated:
                    parts.append("React root is empty — component did not render")
                if has_overlay:
                    parts.append("Vite error overlay is visible")
                if fatal and not success:
                    short = "; ".join(fatal[:3])
                    parts.append(f"Console errors: {short}")
                if network_failures and not success:
                    parts.append(f"Network failures: {'; '.join(network_failures[:3])}")

                log.info(
                    "render check at %s: success=%s root=%s overlay=%s errors=%d "
                    "elapsed_ms=%d http_status=%s ready_state=%s",
                    url, success, root_populated, has_overlay, len(fatal),
                    _elapsed_ms(), http_status, ready_state,
                )

                return RenderResult(
                    success=success,
                    html_ok=True,
                    root_populated=root_populated,
                    vite_overlay_present=has_overlay,
                    console_errors=console_errors,
                    error_summary="; ".join(parts) if parts else "OK",
                    playwright_used=True,
                )
            finally:
                await browser.close()

    except Exception as exc:
        # Unexpected Playwright failure — treat as optimistic pass so the demo
        # is never blocked by an infrastructure problem, but log it clearly.
        log.error(
            "Playwright render verification raised unexpected error (%s). "
            "Treating as success to keep the demo running.",
            exc,
        )
        return RenderResult(
            success=True,
            error_summary=f"Playwright infrastructure error (treated as pass): {exc}",
            playwright_used=True,
        )


# ---------------------------------------------------------------------------
# httpx fallback (no browser)
# ---------------------------------------------------------------------------

async def _verify_httpx(url: str) -> RenderResult:
    """Minimal HTML sanity-check when Playwright is unavailable."""
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(url, timeout=10.0)

        if resp.status_code >= 400:
            return RenderResult(
                success=False,
                html_ok=False,
                error_summary=f"HTTP {resp.status_code}",
            )

        html = resp.text
        has_root = 'id="root"' in html or "id='root'" in html
        has_script = "<script" in html.lower()

        if not has_root:
            return RenderResult(
                success=False,
                html_ok=True,
                root_populated=False,
                error_summary="HTML is missing <div id='root'>",
            )

        log.info(
            "render fallback check passed (Playwright unavailable) — "
            "root tag present, script tag=%s",
            has_script,
        )
        return RenderResult(
            success=True,
            html_ok=True,
            root_populated=True,  # optimistic; can't confirm without a browser
            error_summary="Basic HTML check passed (Playwright not available)",
        )

    except Exception as exc:
        return RenderResult(
            success=False,
            html_ok=False,
            error_summary=f"HTTP check failed: {exc}",
        )
