"""Run the demo backend stack inside Docker.

Starts:
1) src/run_all.py (all 11 downstream agents)
2) src.run_frontend (orchestrator FastAPI API for the UI)
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterable

AGENT_PORT_VARS = [
    "INTAKE_CLARIFIER_AGENT_PORT",
    "POI_SEARCH_AGENT_PORT",
    "STAY_AGENT_PORT",
    "TRANSPORT_AGENT_PORT",
    "EVENTS_AGENT_PORT",
    "DINING_AGENT_PORT",
    "AGGREGATOR_AGENT_PORT",
    "BUDGET_AGENT_PORT",
    "ROUTE_AGENT_PORT",
    "VALIDATOR_AGENT_PORT",
    "BOOKING_AGENT_PORT",
]


def _wait_for_health(host: str, port: int, timeout_seconds: int = 240) -> bool:
    deadline = time.time() + timeout_seconds
    url = f"http://{host}:{port}/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:
            time.sleep(1)
    return False


def _wait_for_agents(host: str, env: dict[str, str]) -> bool:
    for port_var in AGENT_PORT_VARS:
        raw_port = env.get(port_var)
        if not raw_port:
            print(f"[demo] missing required env var: {port_var}", flush=True)
            return False
        if not _wait_for_health(host, int(raw_port)):
            print(f"[demo] timeout waiting for agent health on {host}:{raw_port}", flush=True)
            return False
    return True


def _terminate_all(processes: Iterable[subprocess.Popen[bytes]]) -> None:
    for proc in processes:
        if proc.poll() is None:
            proc.terminate()
    for proc in processes:
        if proc.poll() is None:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def main() -> int:
    env = os.environ.copy()
    python_exe = sys.executable
    bind_host = env.get("SERVER_URL", "localhost")
    health_host = env.get("DEMO_HEALTHCHECK_HOST", "127.0.0.1")
    if not health_host:
        health_host = "127.0.0.1"

    print("[demo] starting downstream agents...", flush=True)
    agents_proc = subprocess.Popen(
        [python_exe, "src/run_all.py"],
        env=env,
    )

    def _signal_handler(signum: int, _frame: object) -> None:
        print(f"[demo] received signal {signum}, shutting down...", flush=True)
        _terminate_all([agents_proc])
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    print(f"[demo] bind host: {bind_host}, health host: {health_host}", flush=True)

    if not _wait_for_agents(health_host, env):
        _terminate_all([agents_proc])
        return 1

    print("[demo] all agents healthy, starting orchestrator API...", flush=True)
    frontend_api_proc = subprocess.Popen(
        [python_exe, "-m", "src.run_frontend"],
        env=env,
    )

    try:
        frontend_exit_code = frontend_api_proc.wait()
        return frontend_exit_code
    finally:
        _terminate_all([frontend_api_proc, agents_proc])


if __name__ == "__main__":
    raise SystemExit(main())
