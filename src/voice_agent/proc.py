from __future__ import annotations

import os
import signal
import subprocess
from typing import Sequence


def popen(cmd: Sequence[str], *, env: dict[str, str] | None = None) -> subprocess.Popen:
    """
    Start a process in its own process group so we can kill the full tree (reloaders, watchers).
    - On Linux/macOS: start_new_session=True -> new process group.
    - On Windows: start_new_session works too, but killpg isn't available; we fall back.
    """
    return subprocess.Popen(
        list(cmd),
        env=env,
        start_new_session=True,
    )


def terminate_tree(proc: subprocess.Popen, timeout_s: float = 5.0) -> None:
    if proc is None or proc.poll() is not None:
        return

    # Prefer killing the entire process group on POSIX
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                return
    else:
        # Windows fallback (not perfect; if you want full tree kill on Windows, use taskkill)
        try:
            proc.terminate()
        except Exception:
            return

    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        else:
            try:
                proc.kill()
            except Exception:
                pass
