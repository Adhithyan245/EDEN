"""Shell command tool implementations.

run_command   — executes a command and waits for it to finish (with timeout).
start_background — starts a long-running process without waiting (e.g. dev server).

Windows note: run_command uses run_in_executor + subprocess.run rather than
asyncio.create_subprocess_shell because the ProactorEventLoop subprocess path
is fragile in the uvicorn server context (handle-inheritance quirks, IOCP
edge cases). Synchronous subprocess in a thread-pool worker is reliable.

Process-tree kill note: on Windows, shell=True spawns cmd.exe which in turn
spawns node/vite. Calling _ProcWrapper.kill() on the cmd.exe PID leaves the
node process alive as an orphan. We use taskkill /F /T to kill the entire
tree so orphan Vite processes don't accumulate between builds.

Cross-restart leak note: the orchestrator only kills the *previous build's*
dev server for the *same* session. If the backend process itself is restarted
(crash, --reload, a fresh `uvicorn` launch) or a session is simply abandoned,
that dev server has no session left to kill it and survives as an orphan on
its port indefinitely — confirmed live (22 accumulated node.exe processes
during this project's testing). ``_REGISTRY_PATH`` is a small on-disk PID list
that survives backend restarts; ``kill_orphaned_dev_servers()`` is called once
at startup to sweep anything left over from the previous run.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from .base import ToolResult

log = logging.getLogger("eden.tools.shell")

# Maximum output captured from a command (avoids huge log payloads).
_MAX_OUTPUT = 3000

# Persists across backend restarts (unlike an in-memory list) so a crashed or
# reloaded server can still find and kill dev servers it orphaned last run.
_REGISTRY_PATH = Path(tempfile.gettempdir()) / "eden_dev_servers.json"


def _read_registry() -> list[int]:
    try:
        return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _write_registry(pids: list[int]) -> None:
    try:
        _REGISTRY_PATH.write_text(json.dumps(pids), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        log.warning("could not write dev-server registry: %s", exc)


def _register_pid(pid: int) -> None:
    pids = _read_registry()
    if pid not in pids:
        pids.append(pid)
    _write_registry(pids)


def _unregister_pid(pid: int) -> None:
    pids = [p for p in _read_registry() if p != pid]
    _write_registry(pids)


def kill_orphaned_dev_servers() -> None:
    """Kill dev-server processes left running by a previous backend process.

    Call once at startup. Anything still alive from the last run's registry
    is a Vite server nobody can reach anymore (its session is gone), so it is
    always safe to force-kill.
    """
    pids = _read_registry()
    for pid in pids:
        try:
            result = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                log.info("startup cleanup: killed orphaned dev server (pid=%s)", pid)
        except Exception as exc:  # noqa: BLE001
            log.debug("startup cleanup: pid=%s already gone (%s)", pid, exc)
    _write_registry([])


def _run_sync(
    command: str,
    cwd: str,
    timeout: int,
    env: Optional[dict],
) -> subprocess.CompletedProcess:
    """Blocking subprocess.run — called from a thread pool via run_in_executor."""
    return subprocess.run(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=True,
        env=env,
        timeout=timeout,
    )


async def run_command(
    command: str,
    cwd: Path,
    timeout: int = 90,
    env: Optional[dict] = None,
) -> ToolResult:
    """Execute ``command`` inside ``cwd`` and return its combined stdout/stderr.

    Runs the subprocess synchronously in a thread-pool worker so we stay clear
    of asyncio's Windows subprocess machinery (ProactorEventLoop edge cases).
    """
    log.info("run_command: %r (cwd=%s)", command, cwd)
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _run_sync, command, str(cwd), timeout, env),
            timeout=timeout + 10,  # outer guard: thread scheduling overhead
        )
        output = result.stdout.decode(errors="replace").strip()
        if len(output) > _MAX_OUTPUT:
            output = output[-_MAX_OUTPUT:]  # keep tail (most relevant part)
        if result.returncode != 0:
            log.warning("command failed (exit %d): %r", result.returncode, output[-200:])
            return ToolResult(
                success=False,
                output=output,
                error=f"exit code {result.returncode}",
            )
        return ToolResult(success=True, output=output)
    except asyncio.TimeoutError:
        log.warning("command timed out after %ds: %r", timeout, command)
        return ToolResult(success=False, output="", error=f"timed out after {timeout}s")
    except subprocess.TimeoutExpired:
        log.warning("subprocess timed out after %ds: %r", timeout, command)
        return ToolResult(success=False, output="", error=f"timed out after {timeout}s")
    except Exception as exc:  # noqa: BLE001
        log.error(
            "run_command error type=%s repr=%r str=%r",
            type(exc).__name__, exc, str(exc),
        )
        return ToolResult(
            success=False,
            output="",
            error=str(exc) or f"[{type(exc).__name__}]",
        )


async def start_background(
    command: str,
    cwd: Path,
    env: Optional[dict] = None,
) -> asyncio.subprocess.Process:
    """
    Start a long-running background process (Vite dev server).

    Uses subprocess.Popen directly on Windows and launches npm.cmd without
    shell=True so the working directory is preserved correctly.
    """

    cwd_str = str(cwd)

    log.info("start_background: %r", command)
    log.info("  cwd=%s", cwd_str)
    log.info("  cwd exists=%s", cwd.exists())

    if sys.platform == "win32":

        log_path = cwd / "vite.log"
        log_file = open(
            log_path,
            "w",
            encoding="utf-8",
            buffering=1,   # line buffered
        )

        if command.startswith("npm "):
            args = ["npm.cmd"] + shlex.split(command)[1:]
        else:
            args = shlex.split(command)

        proc_sync = subprocess.Popen(
            args,
            cwd=cwd_str,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
            shell=False,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )

        log.info("launched pid=%s", proc_sync.pid)
        await asyncio.sleep(1)

        if proc_sync.poll() is not None:
            log.error(
                "Dev server exited immediately with return code %s",
                proc_sync.returncode,
            )
        log.info("vite.log=%s", log_path)

        _register_pid(proc_sync.pid)

        return _ProcWrapper(proc_sync)

    proc = await asyncio.create_subprocess_exec(
        *command.split(),
        cwd=cwd_str,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        env=env,
    )

    log.info("launched pid=%s", proc.pid)

    return proc


class _ProcWrapper:
    """Minimal shim so Windows Popen looks like asyncio.subprocess.Process.

    IMPORTANT: shell=True on Windows spawns cmd.exe → node/vite. Calling
    _p.kill() only kills cmd.exe; the node child survives as an orphan and
    keeps occupying its port. We use taskkill /F /T to kill the *entire tree*.
    """

    def __init__(self, p: subprocess.Popen) -> None:
        self._p = p
        self.pid = p.pid
        self.returncode = p.returncode

    def kill(self) -> None:
        pid = self._p.pid
        log.info("killing process tree (pid=%s)", pid)
        try:
            # /F = force, /T = include child processes (the whole tree)
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("taskkill failed (%s); falling back to _p.kill()", exc)
            try:
                self._p.kill()
            except Exception:
                pass
        finally:
            _unregister_pid(pid)

    def terminate(self) -> None:
        self.kill()  # on Windows terminate == kill for our purposes

    async def wait(self) -> int:
        loop = asyncio.get_event_loop()
        rc = await loop.run_in_executor(None, self._p.wait)
        self.returncode = rc
        return rc
