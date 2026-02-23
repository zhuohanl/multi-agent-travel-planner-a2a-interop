# Multi-Agent Travel Planner

A travel planning system built with multiple AI agents across the Microsoft ecosystem. The repo contains two tracks:

## Track 1: Agent Platform Interoperability (`interoperability/`)

Demonstrates cross-platform agent interoperability between **Azure AI Foundry**, **Copilot Studio**, and **Pro Code** — reusing agent logic from the A2A system above.

| Demo | Direction | Status |
|------|-----------|--------|
| Demo 1 | Foundry workflow → Copilot Studio (Weather Agent via proxy) | Stable |
| Demo 2 | Copilot Studio → Foundry agents (via Add Agents) | Stable |
| Demo 3 | Pro Code orchestrator → Copilot Studio | In Progress |

See [`interoperability/README.md`](interoperability/README.md) for demo flows and setup instructions.

Demo 1:
![Workflow run console look](interoperability/foundry/assets/foundry_workflow_run_result.png)

Demo 2:
![Sample run in console](interoperability/copilot_studio/assets/copilot_studio_sample_run_output.png)

## Track 2: A2A Multi-Agent System (`src/`)

A distributed multi-agent system using the Microsoft Agent Framework, A2A Protocol, and LLM-driven orchestration. 11 specialized microservices (transport, stay, dining, events, POI, route, budget, booking, aggregator, validator, intake clarifier) are coordinated by an orchestrator with parallel discovery, human-in-the-loop approval, and full session lifecycle support.

See [`src/README.md`](src/README.md) for architecture, setup, and usage.

Web UI Demo:
![Multi-Agent Travel Planner Web UI Demo](src/assets/multi-agent-travel-planner-frontend.png)


## Repository Structure

| Directory | Description |
|-----------|-------------|
| `src/` | A2A agent implementations, orchestrator, and shared utilities |
| `interoperability/` | Foundry agent definitions, Copilot Studio config, deployment scripts |
| `tests/` | Unit and integration tests for both tracks |
| `scripts/` | Provisioning scripts (e.g. `provision_azure_agents.py`) |
| `infrastructure/` | Azure resource setup (Cosmos DB, Azure Agent Service) |
| `docs/` | Design documents and architecture references |
