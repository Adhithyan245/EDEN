"""Access control and rate limits for a publicly reachable backend.

All of this is off by default, so local development is unchanged. A public
deployment sets:

  EDEN_ACCESS_CODE          shared code a visitor must enter in the UI. The
                            browser sends it as a WebSocket subprotocol
                            (``code.<base64url>``) so it never appears in a URL
                            or an access log. Unset = no code required.
  EDEN_ALLOWED_ORIGINS      comma-separated origins allowed to open the socket
                            (e.g. https://eden.vercel.app). Unset = any.
  EDEN_MAX_MESSAGES_PER_MINUTE   per connection (default 12)
  EDEN_MAX_AGENT_TASKS_PER_HOUR  builds + edits across all visitors (default 30)
  EDEN_MAX_AGENT_TASKS_PER_IP_PER_HOUR  builds + edits per visitor IP (default 6)

Agent tasks (build / edit) also run one at a time across the whole server:
each runs npm, which is the expensive part on a small instance.
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import WebSocket

from . import config  # noqa: F401  (loads backend/.env before we read os.environ)

# Close code the frontend treats as "ask for the access code".
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN_ORIGIN = 4403
SUBPROTOCOL = "eden"


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


class Guard:
    def __init__(self) -> None:
        self.access_code: Optional[str] = os.environ.get("EDEN_ACCESS_CODE") or None
        origins = os.environ.get("EDEN_ALLOWED_ORIGINS") or ""
        self.allowed_origins = {o.strip().rstrip("/") for o in origins.split(",") if o.strip()}
        self.max_messages_per_minute = _int("EDEN_MAX_MESSAGES_PER_MINUTE", 12)
        self.max_agent_tasks_per_hour = _int("EDEN_MAX_AGENT_TASKS_PER_HOUR", 30)
        self.max_agent_tasks_per_ip = _int("EDEN_MAX_AGENT_TASKS_PER_IP_PER_HOUR", 6)
        self._ip_starts: dict[str, deque[float]] = {}
        self._agent_lock = asyncio.Lock()
        self._agent_starts: deque[float] = deque()

    # ------------------------------------------------------------------
    # Handshake
    # ------------------------------------------------------------------
    def origin_allowed(self, origin: Optional[str]) -> bool:
        if not self.allowed_origins:
            return True
        return (origin or "").rstrip("/") in self.allowed_origins

    @staticmethod
    def _offered(websocket: WebSocket) -> list[str]:
        raw = websocket.headers.get("sec-websocket-protocol") or ""
        return [p.strip() for p in raw.split(",") if p.strip()]

    def subprotocol(self, websocket: WebSocket) -> Optional[str]:
        """The subprotocol to echo back on accept (browsers require it)."""
        return SUBPROTOCOL if SUBPROTOCOL in self._offered(websocket) else None

    def authorized(self, websocket: WebSocket) -> bool:
        if self.access_code is None:
            return True
        for proto in self._offered(websocket):
            if proto.startswith("code."):
                try:
                    enc = proto[5:]
                    given = base64.urlsafe_b64decode(enc + "=" * (-len(enc) % 4)).decode("utf-8")
                except Exception:  # noqa: BLE001
                    return False
                return hmac.compare_digest(given.encode(), self.access_code.encode())
        return False

    # ------------------------------------------------------------------
    # Rate limits
    # ------------------------------------------------------------------
    def message_limiter(self) -> "SlidingWindow":
        return SlidingWindow(self.max_messages_per_minute, 60.0)

    @asynccontextmanager
    async def agent_slot(self, client: Optional[str] = None) -> AsyncIterator[Optional[str]]:
        """Yield None when a build/edit may run, else the reason it may not.

        ``client`` is the visitor's IP (behind a proxy, uvicorn's
        --proxy-headers resolves it from X-Forwarded-For).
        """
        now = time.monotonic()
        _expire(self._agent_starts, now)
        mine = self._ip_starts.setdefault(client or "unknown", deque())
        _expire(mine, now)
        if len(mine) >= self.max_agent_tasks_per_ip:
            yield ("You've used your builds for this hour. Try again a little later, "
                   "and I'm happy to keep talking in the meantime.")
            return
        if len(self._agent_starts) >= self.max_agent_tasks_per_hour:
            yield "I've hit this hour's build limit. Try again a little later."
            return
        if self._agent_lock.locked():
            yield "I'm in the middle of another build right now. Give me a minute and ask again."
            return
        async with self._agent_lock:
            self._agent_starts.append(now)
            mine.append(now)
            yield None


def _expire(hits: deque, now: float) -> None:
    while hits and now - hits[0] > 3600:
        hits.popleft()


class SlidingWindow:
    def __init__(self, limit: int, seconds: float) -> None:
        self.limit, self.seconds = limit, seconds
        self._hits: deque[float] = deque()

    def allow(self) -> bool:
        now = time.monotonic()
        while self._hits and now - self._hits[0] > self.seconds:
            self._hits.popleft()
        if len(self._hits) >= self.limit:
            return False
        self._hits.append(now)
        return True


guard = Guard()
