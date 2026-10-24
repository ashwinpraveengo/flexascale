"""
Managed background processes for the review/demo workflow.

Every process FlexaScale starts (Locust, the operator, port-forwards, the lab
server) is recorded in ``<runtime>/pids/<name>.json`` with its PID, process
group, command line and start time. A process is only ever signalled when the
live ``/proc/<pid>`` entry still matches that record (same start time and a
command line containing the recorded marker), so stale PID files can never
cause an unrelated process to be killed, and nothing is killed by port number.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

DEFAULT_RUNTIME_DIR = Path(os.environ.get("FLEXASCALE_RUNTIME_DIR", ".runtime"))


def _proc_start_ticks(pid: int) -> Optional[int]:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        # Field 22 (starttime) comes after the ')' that closes the command name.
        return int(stat.rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def _proc_state(pid: int) -> Optional[str]:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return None


def _proc_cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return ""


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
            return ProcessRecord(**json.loads(path.read_text()))
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
        with log.open("ab") as fh:
            proc = subprocess.Popen(
                list(cmd),
                stdout=fh,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=full_env,
                cwd=cwd,
                start_new_session=True,
            )
        self._children[name] = proc
        rec = ProcessRecord(
            name=name,
            pid=proc.pid,
            pgid=os.getpgid(proc.pid),
            cmd=list(cmd),
            marker=marker or " ".join(cmd[:3]),
            start_ticks=_proc_start_ticks(proc.pid),
            started_at=time.time(),
            log=str(log),
        )
        self._record_path(name).write_text(json.dumps(asdict(rec), indent=2))
        return rec

    def stop(self, name: str, timeout: float = 20.0, first_signal: int = signal.SIGINT) -> str:
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
        for sig, wait in ((first_signal, timeout), (signal.SIGTERM, 10.0), (signal.SIGKILL, 5.0)):
            try:
                os.killpg(rec.pgid, sig)
            except ProcessLookupError:
                break
            deadline = time.time() + wait
            def gone() -> bool:
                return child.poll() is not None if child is not None else not rec.matches_live_process()

            while time.time() < deadline and not gone():
                time.sleep(0.2)
            if gone():
                break
            outcome = "killed" if sig == signal.SIGKILL else outcome
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
