"""
Self-healing ``kubectl port-forward`` (the cross-platform replacement of keep_port_forward.sh).

    python -m flexascale.lab.portforward NAMESPACE TARGET LOCAL:REMOTE

``kubectl port-forward`` exits when its pod is replaced (e.g. after a Prometheus
restart). This supervisor restarts it with a short back-off until it is told to
stop (SIGINT/SIGTERM, or CTRL_BREAK on Windows, which also reaches the kubectl
child in the same process group). It binds to the loopback interfaces only (127.0.0.1 and ::1).
"""

from __future__ import annotations

import signal
import subprocess
import sys
import time

_stop = False


def _on_signal(_signum, _frame) -> None:
    global _stop
    _stop = True


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    namespace, target, ports = argv
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _on_signal)
    # "localhost" = 127.0.0.1 and ::1. Binding only 127.0.0.1 makes every http://localhost request on Windows
    # wait ~2 s for the IPv6 attempt to fail first (measured: 2.04 s vs 0.01 s per Prometheus query).
    cmd = ["kubectl", "-n", namespace, "port-forward", "--address", "localhost", target, ports]
    backoff = 1.0
    while not _stop:
        started = time.time()
        print(f"{time.strftime('%H:%M:%S')} starting: {' '.join(cmd)}", flush=True)
        try:
            child = subprocess.Popen(cmd, stdin=subprocess.DEVNULL)
        except OSError as exc:
            print(f"cannot start kubectl: {exc}", flush=True)
            return 1
        while child.poll() is None and not _stop:
            time.sleep(0.5)
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
            break
        backoff = 1.0 if time.time() - started > 30 else min(backoff * 2, 15.0)
        print(f"{time.strftime('%H:%M:%S')} kubectl port-forward exited ({child.returncode}); retrying in {backoff:.0f} s", flush=True)
        deadline = time.time() + backoff
        while time.time() < deadline and not _stop:
            time.sleep(0.2)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
