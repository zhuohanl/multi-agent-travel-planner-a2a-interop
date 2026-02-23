# A2A Multi-Agent Travel Planner

A distributed multi-agent system for AI-powered travel planning using the Microsoft Agent Framework, A2A Protocol, and LLM-driven orchestration.

## Architecture Overview

For the full-version architectural design, refer to:
- [docs/application-design.md](../docs/application-design.md)
- [docs/a2a-orchestrator-design.md](../docs/a2a-orchestrator-design.md)

```
User → Orchestrator (10000)
        ├→ Clarifier (10007)          [Gather trip requirements]
        ├→ Parallel Discovery Agents  [5 agents simultaneously]
        │  ├→ POI Search (10008)
        │  ├→ Stay (10009)
        │  ├→ Transport (10010)
        │  ├→ Events (10011)
        │  └→ Dining (10017)
        ├→ Sequential Planning Agents
        │  ├→ Aggregator (10015)
        │  ├→ Budget (10013)
        │  ├→ Route (10012)
        │  └→ Validator (10016)
        └→ Booking (10014)
```

**Key Features:**
- 11 specialized microservices communicating via A2A protocol
- Centralized Orchestrator with LLM-driven intent classification
- Human-in-the-loop approval at 3 checkpoints
- Parallel discovery phase execution
- Full session lifecycle support (resume, edit pending, modify confirmed bookings)

## Prerequisites

- Python 3.13+
- `uv` package manager
- Azure OpenAI API access (endpoint, deployment name)
- Azure AI Agent Service project (for orchestrator LLM routing)

## Environment Variables

Copy `.env.example` to `.env` at the project root and fill in the **A2A Orchestration** section. The key variables are:

| Variable | Description |
|----------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI API endpoint |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | Model deployment name (e.g. `gpt-4.1`) |
| `AZURE_OPENAI_API_VERSION` | API version (e.g. `2025-01-01-preview`) |
| `AZURE_OPENAI_API_KEY` | Optional Azure OpenAI key (only works if `disableLocalAuth` is `false` on the resource — see [Docker Authentication](#docker-authentication-azure-openai) below) |
| `PROJECT_ENDPOINT` | Azure AI Agent Service endpoint for orchestrator routing |
| `ORCHESTRATOR_*_AGENT_ID` | Pre-provisioned agent IDs (see step 2 below) |

See `.env.example` for the full list including server ports, session config, and Cosmos DB settings.

## Installation & Running

### 1. Common Setup (One-Time)

1. **Install Python dependencies**
   ```shell
   uv sync
   ```
2. **Configure `.env`**
   - Copy `.env.example` to `.env`.
   - Fill all required A2A values (Azure OpenAI + orchestrator IDs + ports).
3. **Configure Azure AI Agent Service**
   - Create an Azure AI project and model deployment (e.g. `gpt-4.1`).
   - Set `PROJECT_ENDPOINT` in `.env`:
     ```
     PROJECT_ENDPOINT="https://<resource>.services.ai.azure.com/api/projects/<project>"
     ```
   - Provision orchestrator agents:
     ```shell
     uv run python scripts/provision_azure_agents.py --dry-run
     uv run python scripts/provision_azure_agents.py
     ```
   - Copy generated agent IDs into `.env`.
4. **Verify Azure config**
   ```shell
   uv run python -m infrastructure.azure_agent_setup
   ```

### 2. Run the Web App (UI Demo)

#### 2.1. Local Run
Use three terminals.

1. **Terminal A - start agent cluster (11 agents)**
   ```shell
   uv run python src/run_all.py
   ```
2. **Terminal B - start orchestrator API for frontend**
   ```shell
   uv run python -m src.run_frontend
   ```
   - API health: `http://localhost:10000/health`
   - Serves frontend endpoints: `/chat`, `/sessions`, `/agents`
3. **Terminal C - start React frontend**
   ```shell
   cd src/frontend
   npm install
   npm run dev
   ```
   - Open: `http://localhost:5173`
   - Vite proxy forwards `/chat`, `/sessions`, `/agents` to `http://localhost:10000`.

#### 2.1. Docker Run

Prerequisites:
- Docker Desktop (or Docker Engine + Compose plugin)
- A valid `.env` at repo root

From repo root:

1. **Build images**
   ```shell
   docker compose -f src/deploy/docker-compose.demo.yml build
   ```
2. **Run containers from built images**
   ```shell
   docker compose -f src/deploy/docker-compose.demo.yml up
   ```
   - If code changed since the last build, run:
     ```shell
     docker compose -f src/deploy/docker-compose.demo.yml up --build
     ```
3. **Optional: run in detached mode**
   ```shell
   docker compose -f src/deploy/docker-compose.demo.yml up -d
   ```
4. **Optional: follow logs**
   ```shell
   docker compose -f src/deploy/docker-compose.demo.yml logs -f
   ```

This brings up:
- `backend` container: all 11 agents + orchestrator API (`http://localhost:10000`)
- `frontend` container: Vite dev server (`http://localhost:5173`)

**Important:** Docker containers cannot use your host's `az login` session.
You must set up a service principal for authentication — see [Docker Authentication](#docker-authentication-azure-openai) below.

5. **Stop and remove containers**
   ```shell
   docker compose -f src/deploy/docker-compose.demo.yml down
   ```

If you run containers manually with `docker run` instead of Compose, bind the frontend API on all interfaces:

```shell
-e ORCHESTRATOR_BIND_HOST=0.0.0.0
```

Keep `SERVER_URL=localhost` for internal agent-to-agent calls.  
Without this split (`ORCHESTRATOR_BIND_HOST` for bind + `SERVER_URL` for routing), chat requests can stall while downstream A2A calls time out.

Example:

```shell
docker run --rm --name a2a-backend --env-file .env -e ORCHESTRATOR_BIND_HOST=0.0.0.0 -p 10000:10000 <backend-image>
docker run --rm --name a2a-frontend -e VITE_API_BASE_URL=http://localhost:10000 -p 5173:5173 <frontend-image>
```

### 3. Run the CLI

Use three terminals.

1. **Terminal A - start agent cluster**
   ```shell
   uv run python src/run_all.py
   ```
2. **Terminal B - start A2A orchestrator server**
   ```shell
   uv run python -m src.run_orchestrator
   ```
3. **Terminal C - start CLI**
   ```shell
   uv run python -m src.run_orchestrator_cli
   ```
   - Verbose mode:
     ```shell
     uv run python -m src.run_orchestrator_cli --verbose
     ```

### 4. Running Tests

```shell
# Run all tests with coverage
uv run pytest --cov=src --cov-report=term-missing

# Run a specific test directory
uv run pytest tests/unit/ -v
```

## Workflow States

```
DRAFT → PLANNING → READY_TO_BOOK → PARTIALLY_BOOKED → FULLY_BOOKED
         ↓                                 ↓
      CANCELLED                       (can modify/cancel)
         ↑
    Any state → EXPIRED (TTL hit)
    FULLY_BOOKED → ARCHIVED (post-trip)
```

**3 Human Approval Checkpoints:**
1. After Clarification — Confirm TripSpec
2. After Planning — Approve final itinerary
3. During Booking — Confirm each item + final checkout

## API Documentation

All agents implement the **A2A Protocol**. The primary endpoint for sending messages is:

```
POST http://localhost:{PORT}/
```

### Common Endpoints (All Agents)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/` | A2A JSON-RPC endpoint (streaming response) |
| `GET` | `/.well-known/agent-card.json` | Get agent card |

### Request Format

```json
{
  "message": {
    "role": "user",
    "parts": [
      {
        "kind": "text",
        "text": "Your message here"
      }
    ],
    "messageId": "unique-uuid-here"
  }
}
```

**For multi-turn conversations:**
- First message: Omit `taskId` and `contextId`
- Follow-up messages: Include `taskId` from the previous response

```json
{
  "message": {
    "role": "user",
    "parts": [{"kind": "text", "text": "Follow-up message"}],
    "messageId": "msg-002",
    "taskId": "task-id-from-previous-response"
  }
}
```

### Response Format (Streaming)

Responses are streamed as JSON events. Each event is one of:

**Task Status Update:**
```json
{
  "id": "event-id",
  "kind": "taskStatusUpdate",
  "taskId": "task-uuid",
  "contextId": "context-uuid",
  "status": {
    "state": "working|input_required|completed|failed",
    "message": {
      "role": "assistant",
      "parts": [{"text": "Agent response"}]
    }
  },
  "final": false
}
```

**Task Artifact Update (Final Result):**
```json
{
  "id": "event-id",
  "kind": "taskArtifactUpdate",
  "taskId": "task-uuid",
  "contextId": "context-uuid",
  "artifact": {
    "name": "current_result",
    "parts": [{"text": "JSON result"}]
  },
  "lastChunk": true
}
```

## Agent Endpoints & Examples

### 1. Orchestrator Agent (Port 10000)

The main entry point for all user interactions. Routes messages based on LLM-classified intent.

**Request:**
```json
{
  "message": {
    "role": "user",
    "parts": [{"kind": "text", "text": "I want to plan a trip to Tokyo"}],
    "messageId": "msg-001"
  }
}
```

**Response Artifact:**
```json
{
  "orchestrator_output": {
    "action": "call_agents",
    "agents": ["clarifier"],
    "message": "Routing to Clarifier...",
    "available_actions": ["approve", "modify", "cancel"]
  },
  "response": "I'd be happy to help plan your Tokyo trip! Let me gather some details."
}
```

### 2. Intake Clarifier Agent (Port 10007)

Gathers trip requirements through multi-turn conversation.

**First Request:**
```json
{
  "message": {
    "role": "user",
    "parts": [{"kind": "text", "text": "I want to plan a trip to Tokyo"}],
    "messageId": "msg-001"
  }
}
```

**First Response (needs more info):**
```json
{
  "trip_spec": null,
  "response": "Great! I'd love to help. How many people will be traveling?"
}
```

**Follow-up Request:**
```json
{
  "message": {
    "role": "user",
    "parts": [{"kind": "text", "text": "2 people, March, 7 days, $5000/person budget"}],
    "messageId": "msg-002",
    "taskId": "task-from-first-response"
  }
}
```

**Final Response (complete TripSpec):**
```json
{
  "destination_city": "Japan (multiple cities)",
  "start_date": "2026-04-01",
  "end_date": "2026-04-10",
  "num_travelers": 3,
  "budget_per_person": 2000,
  "budget_currency": "USD",
  "origin_city": "San Francisco",
  "interests": [
    "food",
    "shopping",
    "cherry blossom"
  ],
  "constraints": [
    "one traveller is a vegetarian"
  ]
}
```

### 3. POI Search Agent (Port 10008)

Finds attractions and points of interest.

**Request:**
```json
{
  "message": {
    "role": "user",
    "parts": [{"kind": "text", "text": "Find top attractions in Tokyo for culture lovers"}],
    "messageId": "msg-001"
  }
}
```

**Response:**
```json
{
  "search_output": {
    "pois": [
      {
        "name": "Tokyo National Museum",
        "area": "Ueno",
        "tags": ["art", "history", "culture"],
        "estCost": 1000.0,
        "currency": "JPY",
        "openHint": "09:30-17:00"
      }
    ],
    "notes": ["Plan 2-3 hours per museum"]
  },
  "response": "Found 8 top attractions"
}
```

### 4. Stay Agent (Port 10009)

Finds hotels and accommodations.

**Request:**
```json
{
  "message": {
    "role": "user",
    "parts": [{"kind": "text", "text": "Find mid-range hotels in Shinjuku for March"}],
    "messageId": "msg-001"
  }
}
```

**Response:**
```json
{
  "stay_output": {
    "neighborhoods": [
      {"name": "Shinjuku", "reasons": ["Central", "Nightlife"]}
    ],
    "stays": [
      {
        "name": "Hotel Gracery Shinjuku",
        "area": "Shinjuku",
        "pricePerNight": 180.0,
        "currency": "USD"
      }
    ]
  },
  "response": "Found 5 mid-range options"
}
```

### 5. Transport Agent (Port 10010)

Finds flights, trains, and local transit.

**Request:**
```json
{
  "message": {
    "role": "user",
    "parts": [{"kind": "text", "text": "Find flights from SF to Tokyo in March"}],
    "messageId": "msg-001"
  }
}
```

**Response:**
```json
{
  "transport_output": {
    "transportOptions": [
      {
        "mode": "flight",
        "route": "SFO -> NRT",
        "provider": "ANA",
        "price": 1247.0,
        "currency": "USD"
      }
    ],
    "localPasses": [
      {"name": "7-day JR Pass", "price": 280.0, "currency": "USD"}
    ]
  },
  "response": "Found flights around $1247"
}
```

### 6. Events Agent (Port 10011)

Finds events and activities.

**Request:**
```json
{
  "message": {
    "role": "user",
    "parts": [{"kind": "text", "text": "What events in Tokyo in March?"}],
    "messageId": "msg-001"
  }
}
```

**Response:**
```json
{
  "events_output": {
    "events": [
      {
        "name": "Tokyo Cherry Blossom Festival",
        "date": "2025-03-15",
        "area": "Shinjuku Gyoen"
      }
    ]
  },
  "response": "Found 12 events"
}
```

### 7. Dining Agent (Port 10017)

Finds restaurants.

**Request:**
```json
{
  "message": {
    "role": "user",
    "parts": [{"kind": "text", "text": "Find vegetarian restaurants in Tokyo"}],
    "messageId": "msg-001"
  }
}
```

**Response:**
```json
{
  "dining_output": {
    "restaurants": [
      {
        "name": "Vegetarian Ramen Yokocho",
        "area": "Shibuya",
        "cuisine": "Ramen",
        "priceRange": "$$",
        "dietaryOptions": ["vegan", "gluten-free"]
      }
    ]
  },
  "response": "Found 8 vegetarian-friendly restaurants"
}
```

### 8. Aggregator Agent (Port 10015)

Combines all discovery results into a unified summary.

### 9. Budget Agent (Port 10013)

Manages budget allocation and validation.

**Request (PROPOSE mode):**
```json
{
  "message": {
    "role": "user",
    "parts": [{"kind": "text", "text": "Propose budget: 2 people, $5000/person, 7 days Tokyo"}],
    "messageId": "msg-001"
  }
}
```

**Response:**
```json
{
  "mode": "propose",
  "proposal": {
    "total_budget": 10000.0,
    "currency": "USD",
    "allocations": {
      "flights": 2500.0,
      "accommodation": 3000.0,
      "meals": 2000.0,
      "activities": 1500.0,
      "transport": 1000.0
    }
  },
  "response": "Proposed allocation above"
}
```

### 10. Route Agent (Port 10012)

Creates day-by-day itinerary.

**Request:**
```json
{
  "message": {
    "role": "user",
    "parts": [{"kind": "text", "text": "Create 7-day itinerary for Tokyo"}],
    "messageId": "msg-001"
  }
}
```

**Response:**
```json
{
  "itinerary": {
    "days": [
      {
        "date": "2025-03-01",
        "slots": [
          {
            "start_time": "14:00",
            "end_time": "18:00",
            "activity": "Arrive at Tokyo",
            "location": "Narita",
            "category": "transport",
            "estimated_cost": 30.0
          }
        ],
        "day_summary": "Arrival day"
      }
    ],
    "total_estimated_cost": 4454.0
  },
  "response": "Created 7-day itinerary"
}
```

### 11. Validator Agent (Port 10016)

Validates itinerary against TripSpec.

**Response:**
```json
{
  "validation_result": {
    "passed": true,
    "issues": [],
    "warnings": ["Budget 90% utilized"]
  },
  "response": "Itinerary validated successfully"
}
```

### 12. Booking Agent (Port 10014)

Creates, modifies, and cancels bookings.

**Request (CREATE):**
```json
{
  "message": {
    "role": "user",
    "parts": [{"kind": "text", "text": "Create hotel booking: Hotel Gracery, 7 nights"}],
    "messageId": "msg-001"
  }
}
```

**Response:**
```json
{
  "action": "create",
  "result": {
    "success": true,
    "booking_id": "book_abc123",
    "status": "confirmed",
    "details": {
      "hotel": "Hotel Gracery Shinjuku",
      "check_in": "2025-03-01",
      "check_out": "2025-03-08",
      "total_cost": 1260.0
    }
  },
  "response": "Hotel booking confirmed"
}
```

## Project Structure

```
src/
├── agents/                          # 11 agent implementations
│   ├── orchestrator_agent/          # Central coordinator
│   ├── intake_clarifier_agent/      # TripSpec gathering
│   ├── poi_search_agent/            # Attractions/POI
│   ├── stay_agent/                  # Hotels
│   ├── transport_agent/             # Flights/transit
│   ├── events_agent/                # Events
│   ├── dining_agent/                # Restaurants
│   ├── aggregator_agent/            # Combine results
│   ├── budget_agent/                # Budget management
│   ├── route_agent/                 # Itinerary creation
│   ├── validator_agent/             # Validation
│   └── booking_agent/               # Booking management
├── orchestrator/                    # Orchestrator LLM routing logic
├── shared/                          # Shared utilities
│   ├── a2a/                         # A2A protocol base classes
│   ├── models.py                    # Pydantic models
│   └── storage/                     # Storage layer (in-memory + Cosmos DB)
├── prompts/                         # LLM system prompts (.txt files)
├── run_all.py                       # Start all agents
├── run_orchestrator.py              # Start orchestrator
└── run_orchestrator_cli.py          # Interactive CLI
```
