"""scripts/run_plan.py: processes frozen during a run's load window are always resumed."""

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("run_plan", ROOT / "scripts" / "run_plan.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stopped(pid):
    import psutil

    return psutil.Process(pid).status() == psutil.STATUS_STOPPED


def test_freeze_and_thaw_a_matching_process():
    mod = _load()
    marker = f"flexascale-freeze-test-{os.getpid()}"
    proc = subprocess.Popen([sys.executable, "-c", f"import time; time.sleep(60)  # {marker}"])
    try:
        time.sleep(0.3)
        mod.freeze(marker)
        time.sleep(0.2)
        assert proc.pid in mod.FROZEN and _stopped(proc.pid)
        mod.thaw()
        time.sleep(0.2)
        assert not mod.FROZEN and not _stopped(proc.pid)
    finally:
        proc.kill()


def test_the_runner_never_freezes_itself():
    mod = _load()
    assert os.getpid() not in mod.matching_pids("python")
    assert mod.matching_pids("") == [] and mod.matching_pids(None) == []
