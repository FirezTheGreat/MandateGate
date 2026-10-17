"""Starts scenario runs for the dashboard's Run buttons: `python -m agents.run_scenario` as a
separate process (the agents stay in the untrusted zone and talk to the gate over HTTP).

`start()` returns the run's session id as soon as the run has created it (the run prints
`[session] <id>`), so the dashboard can follow it live; the run keeps going in the background
and its output goes to backend/data/runs/<session>.log. One run at a time.
"""

import os
import queue
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from app.config import BACKEND_DIR, DATA_DIR

SESSION_PREFIX = "[session] "
Command = Callable[[str, str, str], list[str]]


class RunnerError(Exception):
    def __init__(self, status: int, error: str, detail: str) -> None:
        super().__init__(f"{status} {error}: {detail}")
        self.status, self.error, self.detail = status, error, detail


def run_scenario_command(scenario: str, mode: str, agent: str) -> list[str]:
    return [
        sys.executable, "-m", "agents.run_scenario", "--scenario", scenario, "--mode", mode, "--agent", agent,
        "--on-step-up", "wait", "--approval-timeout", "300",  # the human approves in the dashboard
    ]


class Runner:
    def __init__(self, command: Command = run_scenario_command, *, start_timeout_s: float = 20, log_dir: Path = DATA_DIR / "runs") -> None:
        self.command, self.start_timeout_s, self.log_dir = command, start_timeout_s, log_dir
        self.process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def busy(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, scenario: str, mode: str, agent: str) -> str:
        with self._lock:
            if self.busy():
                raise RunnerError(409, "run_in_progress", "a scenario is already running; wait for it to finish")
            env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
            self.process = proc = subprocess.Popen(
                self.command(scenario, mode, agent), cwd=BACKEND_DIR, env=env, text=True, encoding="utf-8",
                errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            lines: queue.Queue[str | None] = queue.Queue()
            threading.Thread(target=self._pump, args=(proc, lines), daemon=True).start()
            seen: list[str] = []
            while True:
                try:
                    line = lines.get(timeout=self.start_timeout_s)
                except queue.Empty:
                    proc.kill()
                    raise RunnerError(502, "run_failed", "the run did not start a session in time") from None
                if line is None:
                    tail = " | ".join(s.strip() for s in seen[-3:]) or "no output"
                    raise RunnerError(502, "run_failed", f"the run stopped before starting a session: {tail}")
                seen.append(line)
                if line.startswith(SESSION_PREFIX):
                    return line[len(SESSION_PREFIX):].strip()

    def _pump(self, proc: subprocess.Popen[str], lines: "queue.Queue[str | None]") -> None:
        """Forward lines until the session id is known, then keep draining into the run's log file."""
        assert proc.stdout is not None
        log = None
        try:
            for line in proc.stdout:
                if log is not None:
                    log.write(line)
                    continue
                lines.put(line)
                if line.startswith(SESSION_PREFIX):
                    self.log_dir.mkdir(parents=True, exist_ok=True)
                    log = open(self.log_dir / f"{line[len(SESSION_PREFIX):].strip()}.log", "w", encoding="utf-8")  # noqa: SIM115
        finally:
            if log is not None:
                log.close()
            lines.put(None)
