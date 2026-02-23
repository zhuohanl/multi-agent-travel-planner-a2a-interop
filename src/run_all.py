""" Runs each agent server and starts the client """

import asyncio
import subprocess
import sys
import time
import signal
import httpx
import os
import threading
from dotenv import load_dotenv

load_dotenv()

server_url = os.environ["SERVER_URL"]
servers = [
    # Intake/Clarification Agent
    {
        "name": "intake_clarifier_agent_server",
        "module": "src.agents.intake_clarifier_agent.server:app",
        "port": os.environ["INTAKE_CLARIFIER_AGENT_PORT"]
    },
    # Discovery Agents
    {
        "name": "poi_search_agent_server",
        "module": "src.agents.poi_search_agent.server:app",
        "port": os.environ["POI_SEARCH_AGENT_PORT"]
    },
    {
        "name": "stay_agent_server",
        "module": "src.agents.stay_agent.server:app",
        "port": os.environ["STAY_AGENT_PORT"]
    },
    {
        "name": "transport_agent_server",
        "module": "src.agents.transport_agent.server:app",
        "port": os.environ["TRANSPORT_AGENT_PORT"]
    },
    {
        "name": "events_agent_server",
        "module": "src.agents.events_agent.server:app",
        "port": os.environ["EVENTS_AGENT_PORT"]
    },
    {
        "name": "dining_agent_server",
        "module": "src.agents.dining_agent.server:app",
        "port": os.environ["DINING_AGENT_PORT"]
    },
    # Planning Agents
    {
        "name": "aggregator_agent_server",
        "module": "src.agents.aggregator_agent.server:app",
        "port": os.environ["AGGREGATOR_AGENT_PORT"]
    },
    {
        "name": "budget_agent_server",
        "module": "src.agents.budget_agent.server:app",
        "port": os.environ["BUDGET_AGENT_PORT"]
    },
    {
        "name": "route_agent_server",
        "module": "src.agents.route_agent.server:app",
        "port": os.environ["ROUTE_AGENT_PORT"]
    },
    {
        "name": "validator_agent_server",
        "module": "src.agents.validator_agent.server:app",
        "port": os.environ["VALIDATOR_AGENT_PORT"]
    },
    # Booking Agent
    {
        "name": "booking_agent_server",
        "module": "src.agents.booking_agent.server:app",
        "port": os.environ["BOOKING_AGENT_PORT"]
    },
]

server_procs = []

async def wait_for_server_ready(server, timeout=30):
    async with httpx.AsyncClient() as client:
        start = time.time()
        while True:
            try:
                health_url = f"http://{server_url}:{server['port']}/health"
                r = await client.get(health_url, timeout=2)
                if r.status_code == 200:
                    print(f"✅ {server['name']} is healthy and ready!")
                    return True
            except Exception:
                pass
            if time.time() - start > timeout:
                print(f"❌ Timeout waiting for server health at {health_url}")
                return False
            await asyncio.sleep(1)

def stream_subprocess_output(process):
    while True:
        line = process.stdout.readline()
        if not line:
            break
        print(line.rstrip())


# async def run_client_main():
#     from client import main as client_main
#     await client_main()

async def main():
    print("🚀 Starting server subprocesses...")
    for server in servers:
        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            server["module"],
            "--host",
            server_url,
            "--port",
            str(server["port"]),
            "--log-level",
            "info"
        ]
        
        print(f"🚀 Starting {server['name']} on port {server['port']}")
        process = subprocess.Popen(
            cmd,
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            universal_newlines=True,
        )
        server_procs.append(process)

        thread = threading.Thread(target=stream_subprocess_output, args=(process,), daemon=True)
        thread.start()

        ready = await wait_for_server_ready(server)
        if not ready:
            print(f"❌ Server '{server['name']}' failed to start, killing process...")
            process.kill()
            sys.exit(1)

    print("✅ All servers started successfully!")
    print("Press Ctrl+C to stop all servers...")
    
    # Keep the main process alive
    try:
        # Wait indefinitely until interrupted
        while True:
            await asyncio.sleep(1)
            # Optional: check if any server died
            for process in server_procs:
                if process.poll() is not None:
                    print(f"❌ A server process died unexpectedly (exit code: {process.returncode})")
                    sys.exit(1)
    except KeyboardInterrupt:
        print("\n🛑 Stopping all servers...")
    finally:
        # Terminate all server subprocesses gracefully
        for process in server_procs:
            if process.poll() is None:  # Still running
                if sys.platform == "win32":
                    process.terminate()  # Use terminate on Windows
                else:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        print("✅ All servers stopped.")

if __name__ == "__main__":
    asyncio.run(main())
