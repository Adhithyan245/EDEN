"""Dynamic port selection for launched applications.

UNUSED — the build pipeline no longer launches a dev server, so nothing calls
``find_free_port`` today (see ``agents/orchestrator.py``). Kept dormant in
case a future live-preview feature needs to launch and verify a running
server again, alongside ``builder/generator.py``'s ``set_launch`` and
``agents/executor.py``'s ``launch`` phase.

Each build used to launch its dev server on a free port chosen at runtime, so
repeated builds never collided and the URL EDEN verified was the URL that was
actually serving.
"""

from __future__ import annotations

import socket


def find_free_port(preferred: int | None = None) -> int:
    """Return a free TCP port on localhost.

    If ``preferred`` is given and available, it is returned; otherwise the OS
    assigns any free port. Binding to port 0 asks the kernel for an unused port,
    which we then release — a brief race window exists before the dev server
    claims it, but in practice it is reliable for a single-machine demo.
    """
    if preferred is not None and _is_available(preferred):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _is_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False
