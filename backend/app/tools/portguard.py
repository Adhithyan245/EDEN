"""Guards against multiple backend processes binding the same port.

Root cause this fixes: on Windows, when a previous `uvicorn --reload` process
is not cleanly stopped (closed terminal, crash, a forgotten background run),
its socket can remain in a LISTENING state on the same port a freshly started
backend also binds to. `netstat` can then show two or three distinct PIDs all
LISTENING on :8000 simultaneously (observed live during this project's testing
— three separate uvicorn processes, each with its own reload worker, all bound
to port 8000). Windows does not guarantee which process receives a given
connection in that state, and an already-established WebSocket stays pinned to
whichever process originally accepted it. In practice this means the frontend
can silently talk to a STALE backend process running code from before a fix
was made, while the log output everyone is watching belongs to a different,
newer process — making a fixed bug look like it "still happens sometimes."

This runs once at import time, before the new process binds its own socket.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

log = logging.getLogger("eden.tools.portguard")


def kill_stale_backend_on_port(port: int) -> None:
    """Force-kill any *other* process already LISTENING on ``port``.

    Only acts on Windows (the platform this was observed on) and only targets
    processes that are not this process or its direct parent (the uvicorn
    --reload supervisor, when present), so a normal reload cycle is not
    disrupted.
    """
    if sys.platform != "win32":
        return

    my_pid = os.getpid()
    my_parent_pid = os.getppid()

    try:
        result = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=10
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("portguard: netstat unavailable (%s); skipping stale-port check", exc)
        return

    victims: set[int] = set()
    needle = f":{port} "
    for line in result.stdout.splitlines():
        if "LISTENING" not in line or needle not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        try:
            pid = int(parts[-1])
        except ValueError:
            continue
        if pid in (my_pid, my_parent_pid):
            continue
        victims.add(pid)

    for pid in victims:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
            )
            log.warning(
                "portguard: killed a stale backend process still holding port %d (pid=%d) — "
                "it would otherwise silently receive some requests meant for this process",
                port, pid,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("portguard: could not kill pid=%d (%s)", pid, exc)
