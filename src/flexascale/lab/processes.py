"""
Managed background processes for the review/demo workflow.

Every process FlexaScale starts (Locust, the operator, port-forwards, the lab
server) is recorded in ``<runtime>/pids/<name>.json`` with its PID, process
group, command line and start time. A process is only ever signalled when the
live process still matches that record (same start time and a command line
containing the recorded marker), so stale PID files can never cause an
unrelated process to be killed, and nothing is killed by port number.

Linux reads the identity from ``/proc/<pid>``. Windows has no ``/proc``, no
process groups in the POSIX sense and no SIGTERM between processes, so there the
identity comes from psutil (creation time in ms, command line), each process
gets its own process group, and a graceful stop is a CTRL_BREAK to that group
(Python receives SIGBREAK) before the process tree is terminated.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

DEFAULT_RUNTIME_DIR = Path(os.environ.get("FLEXASCALE_RUNTIME_DIR", ".runtime"))
WINDOWS = sys.platform == "win32"
SIGTERM = int(signal.SIGTERM)
SIGKILL = int(getattr(signal, "SIGKILL", 9))


def _ps(pid: int):
    try:
        import psutil

        return psutil.Process(pid)
    except Exception:  # psutil missing, no such process, access denied
        return None


def _proc_start_ticks(pid: int) -> Optional[int]:
    if WINDOWS:
        p = _ps(pid)
        try:
            return int(p.create_time() * 1000) if p else None
        except Exception:
            return None
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        # Field 22 (starttime) comes after the ')' that closes the command name.
        return int(stat.rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def _proc_state(pid: int) -> Optional[str]:
    if WINDOWS:
        p = _ps(pid)
        try:
            return None if p is None or not p.is_running() else ("Z" if p.status() == "zombie" else "R")
        except Exception:
            return None
    try:
        return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return None


def _proc_cmdline(pid: int) -> str:
    if WINDOWS:
        p = _ps(pid)
        try:
            return " ".join(p.cmdline()) if p else ""
        except Exception:
            return ""
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return ""


# Sent from a helper so that it works whether or not the target shares our console:
# the helper detaches from its own console, attaches to the target's and raises CTRL_BREAK
# in the target's process group only (the helper ignores the event itself).
_CTRL_BREAK_HELPER = (
    "import ctypes,sys\n"
    "k=ctypes.windll.kernel32\n"
    "k.FreeConsole()\n"
    "ok=k.AttachConsole(int(sys.argv[1]))\n"
    "ok=ok and k.SetConsoleCtrlHandler(None,True)\n"
    "ok=ok and k.GenerateConsoleCtrlEvent(1,int(sys.argv[2]))\n"
    "sys.exit(0 if ok else 1)\n"
)


def _windows_ctrl_break(pid: int, pgid: int) -> bool:
    try:
        out = subprocess.run([sys.executable, "-c", _CTRL_BREAK_HELPER, str(pid), str(pgid)],
                             creationflags=subprocess.CREATE_NO_WINDOW, timeout=10,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _windows_terminate_tree(pid: int) -> None:
    p = _ps(pid)
    if p is None:
        return
    try:
        procs = p.children(recursive=True) + [p]
    except Exception:
        procs = [p]
    for q in procs:
        try:
            q.terminate()  # TerminateProcess on Windows
        except Exception:
            pass


@dataclass
class ProcessRecord:
    name: str
    pid: int
    pgid: int
    cmd: List[str]
    marker: str
    start_ticks: Optional[int]
    started_at: float
    log: str

    def matches_live_process(self) -> bool:
        state = _proc_state(self.pid)
        if state is None or state == "Z":
            return False
        if self.start_ticks is not None and _proc_start_ticks(self.pid) != self.start_ticks:
            return False
        cmdline = _proc_cmdline(self.pid)
        # An exiting process briefly has an empty cmdline; with a matching start time it is still ours.
        return self.marker in cmdline or (cmdline == "" and self.start_ticks is not None)


class ProcessManager:
    def __init__(self, runtime_dir: Path | str = DEFAULT_RUNTIME_DIR) -> None:
        self.runtime_dir = Path(runtime_dir)
        self.pid_dir = self.runtime_dir / "pids"
        self.log_dir = self.runtime_dir / "logs"
        self.pid_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._children: Dict[str, subprocess.Popen] = {}

    def _record_path(self, name: str) -> Path:
        return self.pid_dir / f"{name}.json"

    def get(self, name: str) -> Optional[ProcessRecord]:
        path = self._record_path(name)
        if not path.is_file():
            return None
        try:
            return ProcessRecord(**json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, TypeError):
            return None

    def is_running(self, name: str) -> bool:
        child = self._children.get(name)
        if child is not None:
            # Our own child: authoritative (its /proc cmdline may still be pre-exec).
            return child.poll() is None
        rec = self.get(name)
        return rec is not None and rec.matches_live_process()

    def start(
        self,
        name: str,
        cmd: Sequence[str],
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        marker: Optional[str] = None,
        log_path: Optional[Path] = None,
    ) -> ProcessRecord:
        if self.is_running(name):
            raise RuntimeError(f"process '{name}' is already running")
        log = Path(log_path) if log_path else self.log_dir / f"{name}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        full_env = dict(os.environ)
        full_env.update(env or {})
        full_env["PYTHONUNBUFFERED"] = "1"
        full_env.setdefault("PYTHONIOENCODING", "utf-8")
        # POSIX: own session/process group. Windows: own process group (CTRL_BREAK target) and
        # no console window; a process started from a console-less parent still gets a hidden console.
        # Windows also breaks away from the starter's job object where the job allows it, so the lab, the
        # tunnel and the port-forwards outlive the terminal (or agent) that ran `fsctl start` (observed
        # 2026-10-29: they were killed with the job of the process that started them).
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW if WINDOWS else 0
        attempts = ([{"creationflags": flags | subprocess.CREATE_BREAKAWAY_FROM_JOB}, {"creationflags": flags}]
                    if WINDOWS else [{"start_new_session": True}])
        with log.open("ab") as fh:
            for i, spawn in enumerate(attempts):
                try:
                    proc = subprocess.Popen(
                        list(cmd),
                        stdout=fh,
                        stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL,
                        env=full_env,
                        cwd=cwd,
                        **spawn,
                    )
                    break
                except PermissionError:  # the job forbids breakaway: start inside it
                    if i == len(attempts) - 1:
                        raise
        self._children[name] = proc
        rec = ProcessRecord(
            name=name,
            pid=proc.pid,
            pgid=proc.pid if WINDOWS else os.getpgid(proc.pid),
            cmd=list(cmd),
            marker=marker or " ".join(cmd[:3]),
            start_ticks=_proc_start_ticks(proc.pid),
            started_at=time.time(),
            log=str(log),
        )
        self._record_path(name).write_text(json.dumps(asdict(rec), indent=2), encoding="utf-8")
        return rec

    def stop(self, name: str, timeout: float = 20.0, first_signal: int = int(signal.SIGINT)) -> str:
        """Gracefully stop a managed process group. Returns a short outcome string."""
        rec = self.get(name)
        child = self._children.pop(name, None)
        if rec is None:
            return "not_managed"
        alive = (child.poll() is None) if child is not None else rec.matches_live_process()
        if not alive:
            self._record_path(name).unlink(missing_ok=True)
            return "already_stopped"
        outcome = "stopped"

        def gone() -> bool:
            return child.poll() is not None if child is not None else not rec.matches_live_process()

        # Windows: any graceful first signal becomes CTRL_BREAK (SIGBREAK in Python); SIGTERM has no
        # graceful meaning between Windows processes, so the escalation is a tree terminate.
        for sig, wait in ((int(first_signal), timeout), (SIGTERM, 10.0), (SIGKILL, 5.0)):
            if WINDOWS:
                if sig == SIGKILL or sig == SIGTERM and int(first_signal) != SIGTERM:
                    _windows_terminate_tree(rec.pid)
                elif not _windows_ctrl_break(rec.pid, rec.pgid):
                    continue  # no console to signal: go straight to the next stage
            else:
                try:
                    os.killpg(rec.pgid, sig)
                except ProcessLookupError:
                    break
            deadline = time.time() + wait
            while time.time() < deadline and not gone():
                time.sleep(0.2)
            if gone():
                break
            outcome = "killed" if sig == SIGKILL else outcome
        if child is not None:
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        self._record_path(name).unlink(missing_ok=True)
        return outcome

    def exit_code(self, name: str) -> Optional[int]:
        child = self._children.get(name)
        return child.poll() if child is not None else None

    def list(self) -> List[Dict[str, object]]:
        out = []
        for path in sorted(self.pid_dir.glob("*.json")):
            rec = self.get(path.stem)
            if rec:
                out.append({"name": rec.name, "pid": rec.pid, "running": rec.matches_live_process(),
                            "started_at": rec.started_at, "log": rec.log})
        return out
