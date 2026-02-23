# Interoperability Design Document

## Overview

**Goal:** Demonstrate multi-platform agent interoperability across the Microsoft ecosystem using this existing travel planner as the foundation.

**Approach:** Three platform-specific mini-demos, each self-contained but using shared agent logic where possible. Minimal changes to the existing Orchestrator (Demo B adds a Copilot Studio handler; Demos A and C are config-only).

---

## Glossary

| Term | Full Name | Description |
|------|-----------|-------------|
| MF | Microsoft Foundry | Microsoft's AI agent platform (formerly Azure AI Foundry) |
| Native Agent | Microsoft Foundry Agent | Prompt-based agent type in Microsoft Foundry (configured via instructions + model) |
| Microsoft Agent Framework | — | Open-source development kit for building AI agents and multi-agent workflows |
| HA / Hosted Agent | Hosted Agents | Custom code agents (built with Microsoft Agent Framework, LangGraph, etc.) running as managed container services on MF |
| LG | LangGraph | Open-source framework for building stateful, multi-agent LLM applications (built on LangChain) |
| CS | Copilot Studio | Microsoft's no-code/low-code agent builder |
| M365 | Microsoft 365 | Microsoft's productivity suite and platform |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        EXISTING (unchanged)                     │
│  Frontend (future) → Orchestrator → AgentRegistry (config only) │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐   ┌─────────────────┐   ┌─────────────────────┐
│   Demo A      │   │     Demo B      │   │       Demo C        │
│   FOUNDRY     │   │  PRO CODE →     │   │  COPILOT STUDIO →   │
│               │   │  COPILOT STUDIO │   │  FOUNDRY            │
├───────────────┤   ├─────────────────┤   ├─────────────────────┤
│ [NEW] Intake  │   │ [EXISTING]      │   │ [NEW] Q&A Parent    │
│       Form    │   │   Orchestrator  │   │       Agent (CS)    │
│ [NEW] Workflow│   │ [NEW] Approval  │   │                     │
│ [NEW] Hosted  │   │       Agent(CS) │   │ 6 Connected Agents: │
│   Agents      │   │ [NEW] CS Handler│   │   (5 Foundry +      │
│ [REUSE] Agent │   │       + SDK     │   │    1 CS Weather)    │
│   logic       │   └─────────────────┘   │ [REUSE] Agent logic │
└───────────────┘                         └─────────────────────┘
```

**Legend:**
- `[EXISTING]` - Already built in this repo, no changes needed
- `[REUSE]` - Existing agent logic wrapped/deployed to new platform
- `[NEW]` - New code/configuration to be created

**Key Principles:**
- Orchestrator core logic unchanged; Demo B adds a small Copilot Studio handler (~50-100 lines in `src/orchestrator/handlers/`) that uses the M365 SDK client
- Each demo independently deployable and testable
- Foundry: programmatic deployment via config + deployer; Copilot Studio: manual creation (portal) + verification script
- Reuse existing agent logic (wrap, don't rewrite)
- Reuse existing output models and schemas from `src/shared/models.py`

---

## Agent Distribution

All 6 agents are deployed once to Foundry/Copilot Studio and reused across demos.

| Agent | Platform | Hosting Type | Used In |
|-------|----------|--------------|---------|
| Transport | Foundry | Microsoft Foundry Agent | Demo A, C |
| POI | Foundry | Microsoft Foundry Agent | Demo A, C |
| Events | Foundry | Microsoft Foundry Agent | Demo A, C |
| Stay | Foundry | Hosted Agent (Microsoft Agent Framework) | Demo A, C |
| Dining | Foundry | Hosted Agent (LangGraph) | Demo A, C |
| Weather | Copilot Studio | CS Agent | Demo A, C |

**Tool Mapping:**

The existing agents in `src/agents/` use `HostedWebSearchTool()` from the Microsoft Agent Framework. When deploying as Microsoft Foundry Agents, this maps to the `bing_grounding` tool kind:

| Current Code | Foundry Agent YAML Equivalent | Agents Using |
|--------------|---------------------|--------------|
| `HostedWebSearchTool()` | `kind: bing_grounding` | Transport, POI, Events, Stay, Dining |
| `[]` (no tools) | `tools: []` | Aggregator, Route |

**Native Agent Instruction Extraction:**

For native agents (Transport, POI, Events), the deployer extracts configuration from the existing Agent Framework code:

1. **Instructions**: Extracted from the agent's `SYSTEM_PROMPT` or `instructions` attribute in `src/agents/<agent>/agent.py`
2. **Tools**: Translated from `get_tools()` return value to YAML tool definitions (e.g., `HostedWebSearchTool()` → `kind: bing_grounding`)
3. **Model**: Configured via `foundry/config.yaml` (can differ from local development model)

The deployer (`foundry/deploy.py`) reads the source agent code, extracts these elements, and generates the native agent YAML definition. The original Python code is **not executed** on Foundry—only the extracted instructions and tool configuration are used.

---

## Demo A: Foundry Features

**Purpose:** Showcase Microsoft Foundry's multi-agent workflow and hosted agent capabilities.

**Flow:**

```
User → Foundry Intake Form → Discovery Workflow → Draft Itinerary
                                    │
       ┌──────────┬──────────┬──────┼──────┬──────────┐
       ▼          ▼          ▼      ▼      ▼          ▼
 ┌──────────┐┌──────────┐┌───────┐┌─────┐┌────────┐┌─────────┐
 │Transport ││   POI    ││Events ││Stay ││ Dining ││ Weather │
 │ (native) ││ (native) ││(native)││(HA) ││  (HA)  ││  (CS)   │
 └──────────┘└──────────┘└───────┘└─────┘└────────┘└─────────┘
       │          │          │      │      │            │
       └──────────┴──────────┴──────┼──────┴────────────┘
                                    ▼
                       ┌────────────────────────┐
                       │  Aggregator (Foundry)  │
                       │  → Combined results    │
                       └────────────────────────┘
                                    │
                                    ▼
                       ┌────────────────────────┐
                       │   Route Agent (Foundry)│
                       │  → Creates itinerary   │
                       └────────────────────────┘
                                    │
                                    ▼
                            Draft Itinerary
```

**Components:**

| Component | Platform | Type | Description |
|-----------|----------|------|-------------|
| Intake Form | Foundry | UI | Collects: destination, dates, budget, interests |
| Discovery Agents | — | — | *See Agent Distribution table above* |
| Aggregator | Foundry | Microsoft Foundry Agent | Combines discovery results |
| Route Agent | Foundry | Microsoft Foundry Agent | Creates itinerary |
| Discovery Workflow | Foundry | Workflow / Hosted Agent | Orchestrates parallel calls + aggregation (see integration options below) |
| Weather Proxy (Option B) | Foundry | Hosted Agent | Bridges Foundry → CS for weather calls (if using declarative workflow) |

**Cross-Platform Call:** Foundry workflow calls Weather agent in Copilot Studio (demonstrates Foundry → CS integration).

### Foundry → Copilot Studio Integration Patterns

The Discovery Workflow needs to call the Weather agent hosted in Copilot Studio. Since Foundry workflows can only directly invoke Foundry-registered agents, we provide **two implementation options** to demonstrate different integration patterns:

> **📌 Design Decision: Both Options Are Required Deliverables (Final — Not Subject to Review)**
>
> **⚠️ CLOSED DECISION: This decision has been explicitly reviewed, the validation risk has been acknowledged and accepted, and it is not subject to further architectural review or modification.**
>
> This interoperability project is experimental/demo-focused. We are **deliberately building both** Option A (Pro-Code Workflow) and Option B (Declarative Workflow + Weather Proxy) to make an informed recommendation. This is not scope ambiguity—both options are explicit, required deliverables.
>
> **Rationale:**
> - Stakeholders have explicitly approved building both options to evaluate trade-offs through hands-on implementation
> - Option B's "needs validation" status is **intentionally accepted**—for an experimental project, validating unproven patterns during implementation is the purpose, not a risk to be avoided
> - Demonstrating multiple integration patterns is a core project goal
>
> **Evaluation Criteria (post-implementation):**
>
> | Criterion | Description |
> |-----------|-------------|
> | Developer Experience | Setup complexity, debugging ease, code maintainability |
> | Flexibility | Ability to handle edge cases, modify workflow logic |
> | Platform Alignment | How well each approach aligns with Foundry's roadmap |
> | Operational Overhead | Deployment complexity, monitoring, troubleshooting |
>
> **Outcome:** After building both options, the team will document a recommendation in `interoperability/RECOMMENDATION.md` with findings for each criterion.
>
> **Contingency:** If Option B validation fails during implementation (i.e., `InvokeAzureAgent` cannot invoke hosted agents as expected), the team will:
> 1. Complete Demo A using Option A only
> 2. Document the validation findings in `interoperability/RECOMMENDATION.md`
> 3. Move Option B to Phase 2 for further investigation
>
> This ensures the project delivers a working Demo A regardless of Option B's validation outcome.

#### Option A: Pro-Code Workflow (Primary - Verified)

Build the entire Discovery Workflow using Microsoft Agent Framework and deploy it as a Hosted Agent in Foundry.

**Architecture:**
```
┌─────────────────────────────────────────────────────────────────┐
│                    FOUNDRY (Hosted Agent)                        │
│                                                                  │
│  Discovery Workflow (Agent Framework)                            │
│       │                                                          │
│       ├── TransportAgent (Foundry)                               │
│       ├── POIAgent (Foundry)                                     │
│       ├── EventsAgent (Foundry)                                  │
│       ├── StayAgent (Foundry)                                    │
│       ├── DiningAgent (Foundry)                                  │
│       └── WeatherStep ──── CopilotStudioAgent ───→ CS Weather    │
│                                   │                              │
│                                   └── M365 Agents SDK            │
└─────────────────────────────────────────────────────────────────┘
```

**Implementation:**
- Use `WorkflowBuilder` from Microsoft Agent Framework
- Include a workflow step that uses `CopilotStudioAgent` to call CS Weather
- Deploy the workflow as a Hosted Agent via `azd ai agent` extension
- Location: `interoperability/foundry/workflows/discovery_workflow_procode/`

**Key Code Pattern:**
```python
from agent_framework import WorkflowBuilder
from agent_framework.microsoft import CopilotStudioAgent

# Weather step using CopilotStudioAgent
weather_agent = CopilotStudioAgent(
    name="WeatherAgent",
    # Configured via environment variables:
    # COPILOTSTUDIOAGENT__ENVIRONMENTID, COPILOTSTUDIOAGENT__SCHEMANAME, etc.
)

# Build workflow with all agents using fan-out/fan-in for parallel execution
# Reference: https://learn.microsoft.com/en-us/agent-framework/tutorials/workflows/simple-concurrent-workflow
workflow = (
    WorkflowBuilder()
    .set_start_executor(intake_processor)
    .add_fan_out_edges(intake_processor, [transport, poi, events, stay, dining, weather_agent])
    .add_fan_in_edges([transport, poi, events, stay, dining, weather_agent], aggregator)
    .add_edge(aggregator, route_agent)
    .build()
)
```

> **Note:** The Microsoft Agent Framework uses `add_fan_out_edges()` and `add_fan_in_edges()` for parallel execution. Alternatively, use `ConcurrentBuilder().participants([...]).build()` for simpler concurrent workflows.

**References:**
- [Microsoft Agent Framework](https://github.com/microsoft/agent-framework)
- [CopilotStudioAgent samples](https://github.com/microsoft/agent-framework/tree/main/python/samples/getting_started/agents/copilotstudio)
- [Agents-in-workflow sample](https://github.com/microsoft-foundry/foundry-samples/tree/main/samples/python/hosted-agents/agent-framework/agents-in-workflow)
- [Deploy workflows as hosted agents](https://devblogs.microsoft.com/foundry/introducing-multi-agent-workflows-in-foundry-agent-service/)

#### Option B: Declarative Workflow + Weather Proxy (Alternative - Needs Validation)

Use Foundry's declarative (YAML/visual) workflow with a Weather Proxy Hosted Agent that bridges to Copilot Studio.

**Architecture:**
```
┌─────────────────────────────────────────────────────────────────┐
│                         FOUNDRY                                  │
│                                                                  │
│  Discovery Workflow (Declarative YAML)                           │
│       │                                                          │
│       ├── InvokeAzureAgent: TransportAgent                       │
│       ├── InvokeAzureAgent: POIAgent                             │
│       ├── InvokeAzureAgent: EventsAgent                          │
│       ├── InvokeAzureAgent: StayAgent                            │
│       ├── InvokeAzureAgent: DiningAgent                          │
│       └── InvokeAzureAgent: WeatherProxyAgent ─┐                 │
│                                                │                 │
│  ┌─────────────────────────────────────────────┘                 │
│  │                                                               │
│  ▼                                                               │
│  WeatherProxyAgent (Hosted Agent)                                │
│       │                                                          │
│       └── M365 Agents SDK ───→ Copilot Studio Weather Agent      │
└─────────────────────────────────────────────────────────────────┘
```

**Implementation:**
- Create `WeatherProxyAgent` as a Hosted Agent (container with M365 SDK)
- Declarative workflow uses `InvokeAzureAgent` to call the proxy by name
- Location: `interoperability/foundry/agents/weather_proxy/`

**Weather Proxy Agent Code:**
```python
# interoperability/foundry/agents/weather_proxy/main.py
from agent_framework.microsoft import CopilotStudioAgent
from azure.ai.agentserver import AgentServer

weather_cs_agent = CopilotStudioAgent()

@AgentServer.handler
async def handle_weather_request(request: WeatherRequest) -> WeatherResponse:
    """Proxy weather requests to Copilot Studio Weather agent."""
    result = await weather_cs_agent.run(
        f"Weather forecast for {request.location} from {request.start_date} to {request.end_date}"
    )
    return parse_weather_response(result)
```

**Declarative Workflow YAML:**
```yaml
kind: workflow
id: discovery-workflow
name: Discovery Workflow
trigger:
  kind: OnConversationStart
  id: trigger_discovery
  actions:
    # Initialize local variables from user input.
    # The Intake Form outputs a structured JSON object (see schema below) which is
    # serialized to System.LastMessageText as a raw JSON string.
    #
    # TYPE HANDLING:
    # - Local.TripRequestJson: Raw JSON string for use in Concatenate() expressions
    # - Local.TripRequestMsg: Message-wrapped version for InvokeAzureAgent input
    #
    # This separation ensures correct types: agents receive message objects,
    # while string concatenation uses raw JSON text.
    - kind: SetVariable
      id: init_trip_request_json
      variable: Local.TripRequestJson
      value: =System.LastMessageText

    - kind: SetVariable
      id: init_trip_request_msg
      variable: Local.TripRequestMsg
      value: =UserMessage(Local.TripRequestJson)

    # Invoke discovery agents (parallel execution needs validation)
    # Each agent receives the message-wrapped trip request and stores its result
    # as raw text (via output.text) for later concatenation.
    - kind: InvokeAzureAgent
      id: invoke_transport
      conversationId: =System.ConversationId
      agent:
        name: transport
      input:
        messages: =Local.TripRequestMsg
      output:
        text: Local.TransportResult
        autoSend: false

    - kind: InvokeAzureAgent
      id: invoke_poi
      conversationId: =System.ConversationId
      agent:
        name: poi
      input:
        messages: =Local.TripRequestMsg
      output:
        text: Local.POIResult
        autoSend: false

    - kind: InvokeAzureAgent
      id: invoke_events
      conversationId: =System.ConversationId
      agent:
        name: events
      input:
        messages: =Local.TripRequestMsg
      output:
        text: Local.EventsResult
        autoSend: false

    - kind: InvokeAzureAgent
      id: invoke_stay
      conversationId: =System.ConversationId
      agent:
        name: stay
      input:
        messages: =Local.TripRequestMsg
      output:
        text: Local.StayResult
        autoSend: false

    - kind: InvokeAzureAgent
      id: invoke_dining
      conversationId: =System.ConversationId
      agent:
        name: dining
      input:
        messages: =Local.TripRequestMsg
      output:
        text: Local.DiningResult
        autoSend: false

    - kind: InvokeAzureAgent
      id: invoke_weather
      conversationId: =System.ConversationId
      agent:
        name: WeatherProxyAgent  # Hosted agent that calls CS
      input:
        messages: =Local.TripRequestMsg
      output:
        text: Local.WeatherResult
        autoSend: false

    # Combine all discovery results into a single payload for aggregation.
    # All variables used here are raw JSON strings (not message objects):
    # - Local.TripRequestJson: Raw JSON from intake form
    # - Local.*Result: Raw JSON text from agent outputs (via output.text)
    #
    # ASSUMPTION: Each agent returns valid JSON text. Agent instructions
    # must specify structured JSON output (see agent output schemas in shared/models.py).
    # Note: Double-quotes ("") are YAML escaping for literal quotes in the output.
    - kind: SetVariable
      id: combine_results
      variable: Local.CombinedResultsJson
      value: |
        =Concatenate(
          "{""trip_request"":", Local.TripRequestJson,
          ",""discovery_results"":{",
          """transport"":", Local.TransportResult, ",",
          """poi"":", Local.POIResult, ",",
          """events"":", Local.EventsResult, ",",
          """stay"":", Local.StayResult, ",",
          """dining"":", Local.DiningResult, ",",
          """weather"":", Local.WeatherResult,
          "}}"
        )

    # Wrap combined results as a message for aggregator invocation
    - kind: SetVariable
      id: wrap_combined_results
      variable: Local.CombinedResultsMsg
      value: =UserMessage(Local.CombinedResultsJson)

    # Invoke aggregator with combined results (message-wrapped)
    - kind: InvokeAzureAgent
      id: invoke_aggregator
      conversationId: =System.ConversationId
      agent:
        name: aggregator
      input:
        messages: =Local.CombinedResultsMsg
      output:
        text: Local.AggregatedResult
        autoSend: false

    # Wrap aggregated result as a message for route agent invocation
    - kind: SetVariable
      id: wrap_aggregated_result
      variable: Local.AggregatedResultMsg
      value: =UserMessage(Local.AggregatedResult)

    # Invoke route agent to create final itinerary
    - kind: InvokeAzureAgent
      id: invoke_route
      conversationId: =System.ConversationId
      agent:
        name: route
      input:
        messages: =Local.AggregatedResultMsg
      output:
        autoSend: true
```

**Intake Form Output Schema:**

The Foundry Intake Form collects user input and outputs a structured JSON object:

```json
{
  "destination": "Paris, France",
  "start_date": "2025-06-15",
  "end_date": "2025-06-20",
  "budget": "moderate",
  "interests": ["museums", "food", "history"]
}
```

This JSON is serialized to `System.LastMessageText`. The workflow then:
1. Stores the raw JSON in `Local.TripRequestJson` (for string concatenation)
2. Wraps it as a message in `Local.TripRequestMsg` (for agent invocations)

**Aggregator Input Payload Schema:**

The aggregator receives a JSON payload combining the original trip request with all discovery results:

```json
{
  "trip_request": {
    "destination": "Paris, France",
    "start_date": "2025-06-15",
    "end_date": "2025-06-20",
    "budget": "moderate",
    "interests": ["museums", "food", "history"]
  },
  "discovery_results": {
    "transport": { "flights": [...], "summary": "..." },
    "poi": { "points_of_interest": [...], "summary": "..." },
    "events": { "events": [...], "summary": "..." },
    "stay": { "hotels": [...], "summary": "..." },
    "dining": { "restaurants": [...], "summary": "..." },
    "weather": { "forecasts": [...], "summary": "..." }
  }
}
```

**Execution Model:**

- **Fan-out**: The six `InvokeAzureAgent` actions for discovery agents are listed sequentially in YAML, but whether they execute in parallel or sequentially depends on Foundry's workflow engine behavior (needs validation during implementation)
- **Fan-in**: The `SetVariable` action (`combine_results`) waits for all preceding agent invocations to complete before constructing the combined payload
- **Ordering**: Results are combined in a fixed structure; the order of agent completion does not affect the aggregator input format

> **Variable Syntax Reference:**
> - `=System.ConversationId` - Current conversation ID (required for agent invocation)
> - `=System.LastMessageText` - Previous user message (raw text)
> - `=Local.VariableName` - User-defined local variables (must be initialized with `SetVariable`)
> - `=UserMessage(...)` - Function to wrap text as a user message object
>
> **Type Naming Convention (used in this workflow):**
> - `*Json` suffix (e.g., `Local.TripRequestJson`) - Raw JSON string, suitable for `Concatenate()`
> - `*Msg` suffix (e.g., `Local.TripRequestMsg`) - Message-wrapped value, suitable for `input.messages`
> - `*Result` suffix (e.g., `Local.TransportResult`) - Raw text output from agents (via `output.text`)
>
> Reference: [GitHub sample](https://github.com/LazaUK/AIFoundry-AgentsV2-HostedWorkflow)

**⚠️ Validation Required:**
1. Whether multiple `InvokeAzureAgent` actions execute in parallel or sequentially needs validation during implementation
2. Whether `InvokeAzureAgent` can invoke hosted agents (not just native Microsoft Foundry Agents) needs validation

### Development Workflow (Portal-First Approach)

> **Recommended Approach:** Start workflow design in the Foundry portal, then export to VS Code for iteration and automation. This aligns with Microsoft's documented best practice and reduces risk of YAML syntax errors.

**Rationale:**
- Portal generates correct YAML syntax (trigger IDs, variable references, etc.)
- Visual designer enables quick validation of workflow patterns
- "Open in VS Code for Web" provides seamless export
- GitHub Copilot can convert YAML to Agent Framework code when pro-code control is needed

**Development Phases:**

```
┌─────────────────────────────────────────────────────────────────┐
│                     DEVELOPMENT WORKFLOW                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. PORTAL DESIGN PHASE                                          │
│     ├── Create agents in Foundry portal (native, with prompts)   │
│     ├── Design workflow visually (drag-drop nodes/edges)         │
│     ├── Test in portal playground                                │
│     └── Validate parallel execution pattern works                │
│                                                                  │
│  2. EXPORT PHASE                                                 │
│     ├── Select workflow → Build → YAML → "Open in VS Code"       │
│     ├── Pull YAML into local repo (interoperability/foundry/)    │
│     └── (Optional) "Generate Code with Copilot" for pro-code     │
│                                                                  │
│  3. ITERATION PHASE                                              │
│     ├── Edit YAML/code in VS Code with visual preview            │
│     ├── Test in Local Agent Playground (VS Code extension)       │
│     └── Deploy back to Foundry for validation                    │
│                                                                  │
│  4. AUTOMATION PHASE                                             │
│     ├── Exported YAML/code becomes source of truth               │
│     ├── CI/CD deploys via deploy.py / GitHub Actions             │
│     └── Environment promotion (dev → test → prod)                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**References:**
- [Work with Declarative Agent workflows in VS Code](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/vs-code-agents-workflow-low-code?view=foundry)
- [Introducing Multi-Agent Workflows in Foundry](https://devblogs.microsoft.com/foundry/introducing-multi-agent-workflows-in-foundry-agent-service/)

### Weather Request/Response Schema

Both options use a consistent schema for weather data:

**Request:**
```json
{
  "location": "Paris, France",
  "start_date": "2025-06-15",
  "end_date": "2025-06-20"
}
```

**Response:**
```json
{
  "location": "Paris, France",
  "forecasts": [
    {
      "date": "2025-06-15",
      "condition": "Partly Cloudy",
      "high_temp_c": 24,
      "low_temp_c": 16,
      "precipitation_chance": 20
    }
  ],
  "summary": "Generally pleasant weather with mild temperatures."
}
```

**What Gets Reused:**
- Transport, POI, Events agent **instructions and tool config** → extracted and deployed as native Microsoft Foundry Agents (prompt-based, no code execution)
- Stay agent logic → wrapped as Agent Framework hosted agent (code runs in container)
- Dining agent logic → wrapped as LangGraph hosted agent (code runs in container)
- All output models/schemas from `src/shared/models.py`

**Output:** Draft itinerary JSON (can be passed to Demo B for approval)

---

## Demo B: Pro Code → Copilot Studio

**Purpose:** Show Pro Code (this repo's Orchestrator) calling a Copilot Studio agent via M365 Agents SDK.

**Flow:**

```
┌─────────────────────────────────────────────────────────────┐
│                    PRO CODE (this repo)                     │
│                                                             │
│  Orchestrator ──── M365 Agents SDK ───→ Copilot Studio      │
│      │                                        │             │
│      │ (draft itinerary                       ▼             │
│      │  from Demo A                  ┌──────────────────┐   │
│      │  or existing flow)            │  Approval Agent  │   │
│      │                               │                  │   │
│      │                               │ • Shows itinerary│   │
│      │                               │ • Approve/Reject │   │
│      │                               │ • Request changes│   │
│      │                               └──────────────────┘   │
│      │                                        │             │
│      │◄───────── approval decision ───────────┘             │
│      │                                                      │
│      ▼                                                      │
│  Continue to booking or modify itinerary                    │
└─────────────────────────────────────────────────────────────┘
```

**Components:**

| Component | Type | NEW/REUSE | Description |
|-----------|------|-----------|-------------|
| Copilot Studio Handler | Orchestrator | NEW | Agent type handler in `src/orchestrator/handlers/` that invokes M365 SDK client |
| M365 SDK Client | Pro Code | NEW | Wrapper to call CS agents (`interoperability/pro_code/m365_sdk_client.py`) |
| Approval Agent | Copilot Studio | NEW | Displays itinerary, collects approval decision |
| M365 SDK config | Pro Code | NEW | Connection config (env vars or config file) |

**Approval Agent Behavior:**
- Receives: Draft itinerary (JSON, reusing existing schema)
- Displays: Human-readable summary in Copilot Studio UI
- Returns: `{ "decision": "approved" | "rejected" | "modify" | "pending", "feedback": "..." }`
  - Note: `pending` is an orchestrator fallback state used for timeout/error scenarios (see contract below)

### Approval Agent Contract

This section formally defines the response contract between the Approval Agent (Copilot Studio) and the Orchestrator (Pro Code).

#### Event Name

The Approval Agent emits its decision via a Copilot Studio **event** activity:

```
Event Name: approval_decision
```

#### Response Payload Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["decision"],
  "properties": {
    "decision": {
      "type": "string",
      "enum": ["approved", "rejected", "modify", "pending"],
      "description": "The approval decision. 'pending' indicates awaiting human response or error/timeout fallback."
    },
    "feedback": {
      "type": "string",
      "description": "Optional human feedback or modification instructions",
      "default": ""
    },
    "timestamp": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 timestamp of the decision"
    }
  }
}
```

**Example Responses:**

```json
// Approved
{"decision": "approved", "feedback": "", "timestamp": "2025-06-15T10:30:00Z"}

// Rejected with reason
{"decision": "rejected", "feedback": "Budget exceeds limit", "timestamp": "2025-06-15T10:32:00Z"}

// Modification requested
{"decision": "modify", "feedback": "Change hotel to 4-star instead of 5-star", "timestamp": "2025-06-15T10:35:00Z"}

// Pending (timeout or error fallback)
{"decision": "pending", "feedback": "Awaiting human response", "timestamp": "2025-06-15T10:40:00Z"}
```

#### Error and Timeout Handling

| Scenario | Behavior | Response |
|----------|----------|----------|
| No response within timeout (default: 5 minutes) | Treat as pending | `{"decision": "pending", "feedback": "Awaiting human response"}` |
| Copilot Studio connection error | Retry once, then fail | Raise `ApprovalAgentConnectionError` |
| Invalid/malformed response | Log warning, treat as pending | `{"decision": "pending", "feedback": "Invalid response received"}` |
| Agent returns unexpected decision value | Log warning, treat as pending | `{"decision": "pending", "feedback": "Unrecognized decision value"}` |

#### Orchestrator Handler Contract

The Copilot Studio handler in the Orchestrator must implement the following interface:

```python
# src/orchestrator/handlers/copilot_studio_handler.py

from dataclasses import dataclass
from enum import Enum
from typing import Optional

class ApprovalDecision(Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFY = "modify"
    PENDING = "pending"  # Fallback state

@dataclass
class ApprovalResponse:
    decision: ApprovalDecision
    feedback: str
    timestamp: Optional[str] = None

async def request_approval(itinerary_json: str, timeout_seconds: int = 300) -> ApprovalResponse:
    """
    Send itinerary to Approval Agent and await decision.

    Args:
        itinerary_json: Serialized itinerary to approve
        timeout_seconds: Max wait time for human response (default: 5 min)

    Returns:
        ApprovalResponse with decision and optional feedback

    Raises:
        ApprovalAgentConnectionError: If connection fails after retry
    """
    ...
```

**What Gets Reused:**
- Itinerary schema from `src/shared/models.py`
- Existing approval flow logic pattern from current booking phase

---

## Demo C: Copilot Studio → Foundry

**Purpose:** Show Copilot Studio as the entry point, calling multiple Foundry agents (mix of native and Hosted Agents) as connected agents.

**Flow:**

```
┌─────────────────────────────────────────────────────────────────┐
│                      COPILOT STUDIO                             │
│                                                                 │
│  User Question ───→ Q&A Parent Agent                            │
│  "What hotels are       │                                       │
│   near the Eiffel       │ (routes to relevant                   │
│   Tower with good       │  connected agents)                    │
│   restaurants?"         │                                       │
│                         ▼                                       │
│              ┌─────────────────────┐                            │
│              │   Connected Agents  │                            │
│              │   (see Agent        │                            │
│              │    Distribution)    │                            │
│              └─────────────────────┘                            │
│                         │                                       │
│    ┌────────┬───────┬───┼───┬────────┬─────────┐                │
│    ▼        ▼       ▼   ▼   ▼        ▼         ▼                │
│ ┌──────┐┌─────┐┌──────┐┌────┐┌──────┐┌───────┐                  │
│ │Trans.││ POI ││Events││Stay││Dining││Weather│                  │
│ │native││native││native││ HA ││  HA  ││  CS   │                  │
│ └──────┘└─────┘└──────┘└────┘└──────┘└───────┘                  │
│    │        │       │    │      │        │                      │
│    └────────┴───────┴────┼──────┴────────┘                      │
│                          ▼                                      │
│                 Aggregated Answer                               │
│                 returned to user                                │
└─────────────────────────────────────────────────────────────────┘
```

**Connection Types:**

| Agent | Connection |
|-------|------------|
| Transport, POI, Events, Stay, Dining | CS → Foundry |
| Weather | CS → CS (internal) |

**Components:**

| Component | Type | NEW/REUSE |
|-----------|------|-----------|
| Q&A Parent Agent | Copilot Studio | NEW |
| Connected Agent config | Copilot Studio | NEW |
| All 6 discovery agents | Various | REUSE from Demo A |

**Q&A Parent Agent Behavior:**
- Receives: Natural language question from user
- Decides: Which connected agent(s) to call based on question topic
- Calls: One or more connected agents
- Returns: Aggregated natural language answer

### Copilot Studio → Foundry API Contract

When Copilot Studio calls a Foundry agent via "Connected Agents," it uses the Foundry Responses API. This section defines the exact contract for implementers.

#### Endpoint Format

```
POST https://{foundry-resource}.services.ai.azure.com/api/projects/{project}/agents/{agent-name}/responses
```

**Example for Stay Agent:**
```
POST https://interop-demo.services.ai.azure.com/api/projects/travel-planner/agents/StayAgent/responses
```

#### Request Format

Copilot Studio sends requests in the OpenAI-compatible Responses API format:

```json
{
  "input": [
    {
      "role": "user",
      "content": "Find hotels near the Eiffel Tower with good restaurants nearby"
    }
  ],
  "conversation_id": "conv_abc123",  // Optional: for multi-turn conversations
  "metadata": {
    "source": "copilot_studio",
    "parent_agent": "travel_planning_parent"
  }
}
```

**Request Headers:**
```
Content-Type: application/json
Authorization: Bearer {oauth_token}
```

Authentication is handled via Microsoft Entra ID User Login (delegated auth) — the signed-in user's RBAC permissions on the Foundry project grant access. No separate app registration is required for this direction.

#### Response Format

Foundry agents return responses in the standard Responses API format:

```json
{
  "id": "resp_67cb32528d6881909eb2859a55e18a85",
  "status": "completed",
  "output": [
    {
      "type": "message",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "I found 3 hotels near the Eiffel Tower..."
        }
      ]
    }
  ],
  "output_text": "I found 3 hotels near the Eiffel Tower...",
  "usage": {
    "input_tokens": 45,
    "output_tokens": 120,
    "total_tokens": 165
  }
}
```

#### Structured Output (Recommended)

For better interoperability, Foundry agents should return structured JSON that Copilot Studio can parse:

**Stay Agent Response Example:**
```json
{
  "id": "resp_...",
  "status": "completed",
  "output_text": "{\"hotels\": [{\"name\": \"Hotel Eiffel\", \"rating\": 4.5, \"price_per_night\": 250, \"distance_km\": 0.3}], \"summary\": \"Found 3 hotels within 1km of the Eiffel Tower.\"}",
  "metadata": {
    "agent": "StayAgent",
    "result_count": 3
  }
}
```

**POI Agent Response Example:**
```json
{
  "id": "resp_...",
  "status": "completed",
  "output_text": "{\"points_of_interest\": [{\"name\": \"Eiffel Tower\", \"type\": \"landmark\", \"rating\": 4.8}], \"summary\": \"Top attractions near your location.\"}",
  "metadata": {
    "agent": "POIAgent",
    "result_count": 5
  }
}
```

#### Error Handling

**Error Response Format:**
```json
{
  "id": "resp_...",
  "status": "failed",
  "error": {
    "code": "invalid_request",
    "message": "Missing required parameter: location"
  }
}
```

**Common Error Codes:**

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `invalid_request` | 400 | Malformed request or missing parameters |
| `unauthorized` | 401 | Invalid or expired OAuth token |
| `forbidden` | 403 | App not authorized to call this agent |
| `not_found` | 404 | Agent not found |
| `rate_limited` | 429 | Too many requests |
| `internal_error` | 500 | Agent execution failed |

#### Portal Configuration Mapping

When configuring Connected Agents in Copilot Studio portal, the following fields map to API parameters:

| Portal Field | API Mapping |
|--------------|-------------|
| Endpoint URL | Base URL for API calls |
| Agent ID | `{agent-name}` in URL path |
| Authentication (OAuth) | `Authorization` header with Bearer token |
| Scope | Token audience (`https://cognitiveservices.azure.com/.default`) |

#### Alternative: Custom Adapter Service

If direct Connected Agents integration doesn't meet requirements (e.g., need request transformation), deploy a lightweight adapter:

**Adapter Architecture:**
```
Copilot Studio → Adapter API (Azure Function) → Foundry Agent
```

**Adapter Responsibilities:**
1. Receive CS request format
2. Transform to Foundry Responses API format
3. Forward to Foundry agent
4. Transform response back to CS-expected format
5. Return to Copilot Studio

**Adapter Location:** `interoperability/adapters/cs_to_foundry/`

This approach provides more control but adds operational complexity. Use only if the native Connected Agents feature is insufficient.

---

## Cross-Platform Authentication

This section specifies how agents authenticate when calling across platforms.

### Azure AD App Registrations Required

| App Name | Purpose | API Permissions |
|----------|---------|-----------------|
| `interop-foundry-to-cs` | Foundry/Pro Code calling CS agents | `https://api.powerplatform.com/.default` |

> **Note:** The `interop-cs-to-foundry` app registration is no longer required. Copilot Studio connects to Foundry agents via Microsoft Entra ID User Login (delegated auth), using the signed-in user's RBAC permissions.

### Foundry → Copilot Studio (Demo A)

Used when the Discovery Workflow calls the Weather agent in Copilot Studio.

**Mechanism:** M365 Agents SDK (`microsoft-agents-copilotstudio-client`)

**Authentication Flow:**
1. Foundry workflow invokes the Copilot Studio handler
2. Handler acquires token using `interop-foundry-to-cs` app registration
3. Token scope: `https://api.powerplatform.com/.default`
4. Handler calls Copilot Studio agent via M365 Agents SDK

**Environment Variables (Foundry side):**

> **Note:** Environment variable names follow the M365 Agents SDK convention (`COPILOTSTUDIOAGENT__*` with double underscores) for consistency across all components.

```bash
COPILOTSTUDIOAGENT__TENANTID="your-azure-tenant-id"
COPILOTSTUDIOAGENT__AGENTAPPID="interop-foundry-to-cs-app-id"
COPILOTSTUDIOAGENT__AGENTAPPSECRET="@Microsoft.KeyVault(SecretUri=https://your-vault.vault.azure.net/secrets/cs-client-secret)"
COPILOTSTUDIOAGENT__ENVIRONMENTID="your-power-platform-environment-id"
COPILOTSTUDIOAGENT__SCHEMANAME="weather-agent-schema-name"
```

**Secret Storage:** Client secret stored in Azure Key Vault; Foundry accesses via Key Vault reference (managed identity).

### Pro Code → Copilot Studio (Demo B)

Used when the Orchestrator calls the Approval Agent.

**Mechanism:** M365 Agents SDK (same as Foundry → CS, but called from Pro Code)

**Environment Variables (Pro Code side):**
```bash
COPILOTSTUDIOAGENT__TENANTID="your-azure-tenant-id"
COPILOTSTUDIOAGENT__AGENTAPPID="interop-foundry-to-cs-app-id"  # Can reuse same app
COPILOTSTUDIOAGENT__AGENTAPPSECRET="your-client-secret"        # From Key Vault or .env (local dev)
COPILOTSTUDIOAGENT__ENVIRONMENTID="your-power-platform-environment-id"
COPILOTSTUDIOAGENT__SCHEMANAME="approval-agent-schema-name"
```

### Copilot Studio → Foundry (Demo C)

Used when Travel Planning Parent agent routes questions to Foundry agents.

**Mechanism:** Copilot Studio [Add Agents](https://learn.microsoft.com/en-gb/microsoft-copilot-studio/add-agent-foundry-agent) feature (portal configuration)

**Authentication Flow:**
1. Travel Planning Parent agent invokes an added agent (e.g., Stay agent)
2. Copilot Studio uses Microsoft Entra ID User Login (delegated auth)
3. The signed-in user's RBAC permissions on the Foundry project grant access
4. Copilot Studio calls Foundry agent via the configured connection

**Configuration (Copilot Studio portal):**
1. Navigate to Travel Planning Parent Agent → **Agents** section → **+ Add agent**
2. Click **Connect to an external agent** → **Microsoft Foundry**
3. Create a connection with the Azure AI Project Endpoint (one-time setup)
4. For each Foundry agent, enter **Name**, **Description**, and **Agent Id** (the agent's name from the Foundry portal)

**Foundry Agent Permissions:**
- The signed-in user must have RBAC access to the Azure AI Foundry project (e.g., Contributor or Cognitive Services User role)

### Secret Management Summary

| Secret | Storage | Access Method |
|--------|---------|---------------|
| `interop-foundry-to-cs` client secret | Azure Key Vault | Key Vault reference (Foundry), env var (local dev) |

### Verification Checklist

Before running cross-platform demos, verify:

- [ ] Azure AD app `interop-foundry-to-cs` registered with correct API permissions
- [ ] Admin consent granted for API permissions
- [ ] Client secret created and stored in Key Vault
- [ ] Signed-in user has RBAC access to the Azure AI Foundry project
- [ ] Copilot Studio agents added via the Agents section (Foundry connection + Agent Ids configured)
- [ ] Environment variables set (or Key Vault references configured)

Run `python interoperability/verify_auth.py` to validate configuration.

---

## Directory Structure

```
interoperability/
├── README.md                     # Overview and quick start
├── verify_auth.py                # Validates cross-platform auth configuration
├── shared/
│   ├── schemas/                  # Reused from src/shared/models.py
│   └── agent_wrappers/           # Common wrapper logic for reusing agent code
│       ├── base_wrapper.py
│       ├── foundry_agent_wrapper.py
│       ├── maf_hosted_wrapper.py      # Microsoft Agent Framework
│       └── langgraph_hosted_wrapper.py
│
├── foundry/
│   ├── config.yaml               # Agent definitions for Foundry
│   ├── deploy.py                 # Deploys all Foundry agents + workflow
│   ├── agents/
│   │   ├── transport/            # Native agent config
│   │   ├── poi/                  # Native agent config
│   │   ├── events/               # Native agent config
│   │   ├── stay/                 # Hosted agent (Microsoft Agent Framework)
│   │   ├── dining/               # Hosted agent (LangGraph)
│   │   ├── aggregator/           # Native agent config
│   │   ├── route/                # Native agent config
│   │   └── weather_proxy/        # Hosted agent bridging to CS Weather (Option B)
│   │       ├── agent.yaml        # Agent definition for azd
│   │       ├── main.py           # M365 SDK client calling CS
│   │       ├── Dockerfile
│   │       └── requirements.txt
│   └── workflows/
│       ├── discovery_workflow_procode/   # Option A: Agent Framework workflow
│       │   ├── agent.yaml                # Hosted agent definition
│       │   ├── workflow.py               # WorkflowBuilder implementation
│       │   ├── steps/                    # Workflow step definitions
│       │   │   └── weather_step.py       # CopilotStudioAgent integration
│       │   ├── Dockerfile
│       │   └── requirements.txt
│       └── discovery_workflow_declarative/  # Option B: YAML workflow
│           └── workflow.yaml             # Declarative workflow definition
│
├── copilot_studio/
│   ├── SETUP.md                  # Step-by-step manual creation guide
│   ├── config.yaml               # Agent definitions (for reference/validation)
│   ├── verify.py                 # Validates agents exist and are configured correctly
│   └── agents/
│       ├── weather/              # Weather agent config/topics
│       ├── approval/             # Human approval agent (Demo B)
│       └── travel_planning_parent/            # Q&A orchestrator (Demo C)
│
├── .github/
│   └── workflows/
│       └── copilot-studio-ci.yml # CI/CD using Power Platform CLI
│
└── pro_code/
    ├── config.yaml               # M365 SDK connection config
    └── m365_sdk_client.py        # Wrapper for calling CS agents
```

**Example `foundry/config.yaml`:**

```yaml
platform: azure_ai_foundry
resource_group: ${AZURE_RESOURCE_GROUP}
project: interoperability-demo

agents:
  # Discovery agents (native - prompt-based)
  # The deployer extracts instructions from the source agent's SYSTEM_PROMPT
  # and translates get_tools() to YAML tool definitions. The Python code
  # itself is NOT executed—only the extracted configuration is used.
  transport:
    type: native
    source: src/agents/transport   # Extracts SYSTEM_PROMPT and tools
    model: gpt-4.1-mini
    # Deployer generates:
    #   instructions: <extracted from agent.py SYSTEM_PROMPT>
    #   tools: [{ kind: bing_grounding }]

  poi:
    type: native
    source: src/agents/poi
    model: gpt-4.1-mini

  events:
    type: native
    source: src/agents/events
    model: gpt-4.1-mini

  # Discovery agents (Hosted - custom code)
  stay:
    type: hosted
    framework: agent_framework
    source: src/agents/stay

  dining:
    type: hosted
    framework: langgraph
    source: src/agents/dining

  # Workflow support agents
  aggregator:
    type: native
    source: interoperability/foundry/agents/aggregator

  route:
    type: native
    source: interoperability/foundry/agents/route

  # Weather Proxy (Option B only - bridges to CS Weather agent)
  weather_proxy:
    type: hosted
    framework: agent_framework
    source: interoperability/foundry/agents/weather_proxy
    description: "Proxy agent that calls Copilot Studio Weather agent via M365 SDK"
    env_vars:
      - COPILOTSTUDIOAGENT__ENVIRONMENTID
      - COPILOTSTUDIOAGENT__SCHEMANAME
      - COPILOTSTUDIOAGENT__AGENTAPPID
      - COPILOTSTUDIOAGENT__TENANTID

workflows:
  # Option A: Pro-code workflow (deployed as hosted agent)
  # - Entire workflow including CS Weather call is in the hosted agent
  # - Uses CopilotStudioAgent directly in workflow steps
  discovery_procode:
    type: hosted_workflow
    source: interoperability/foundry/workflows/discovery_workflow_procode
    description: "Pro-code workflow using Agent Framework with CopilotStudioAgent"

  # Option B: Declarative workflow (YAML-based)
  # - Uses InvokeAzureAgent to call Foundry agents including weather_proxy
  # - weather_proxy handles the CS Weather call
  discovery_declarative:
    type: declarative
    source: interoperability/foundry/workflows/discovery_workflow_declarative
    agents: [transport, poi, events, stay, dining, weather_proxy, aggregator, route]
    description: "Declarative YAML workflow with Weather Proxy for CS integration"
```

---

## Testing Strategy

**Approach:** Each demo tested independently before integration. Focus on verifying cross-platform communication works.

**Test Levels:**

| Level | Purpose | Location |
|-------|---------|----------|
| Unit | Wrapper logic, config parsing | `tests/unit/interoperability/` |
| Integration (Mock) | Mock platform APIs, verify request/response formats | `tests/integration/mock/interoperability/` |
| Integration (Live) | Actual deployed agents, end-to-end verification | `tests/integration/live/interoperability/` |

### Demo A - Foundry

| Test | Type | Validates |
|------|------|-----------|
| Intake form accepts valid TripSpec | Mock | Input validation |
| Workflow calls all 6 agents in parallel | Mock | Parallel execution |
| Workflow calls Weather agent in CS | Live | Foundry → CS integration |
| Aggregator combines results correctly | Mock | Schema compliance |
| Route agent produces valid itinerary | Mock | Output schema |

### Demo B - Pro Code → Copilot Studio

| Test | Type | Validates |
|------|------|-----------|
| M365 SDK client connects to CS | Live | SDK configuration |
| Approval agent receives itinerary | Live | Data passed correctly |
| Approval agent returns decision | Live | Response schema |
| Orchestrator handles approve/reject/modify | Mock | Decision handling |

### Demo C - Copilot Studio → Foundry

| Test | Type | Validates |
|------|------|-----------|
| Q&A Parent routes to correct agent(s) | Mock | Intent routing |
| Q&A Parent calls single agent | Live | CS → Foundry connection |
| Q&A Parent calls multiple agents | Live | Multi-agent aggregation |
| Q&A Parent calls Weather (internal) | Live | CS → CS routing |

**Quick Validation Script:**

```bash
# After deployment, run quick smoke tests
python interoperability/test_smoke.py --demo a  # Test Demo A
python interoperability/test_smoke.py --demo b  # Test Demo B
python interoperability/test_smoke.py --demo c  # Test Demo C
python interoperability/test_smoke.py --all     # Test all demos
```

---

## CI/CD Reference Pattern

> **Source:** This CI/CD pattern is adapted from a community-shared repository ([DeeplyDiligent/foundry-devops](https://github.com/DeeplyDiligent/foundry-devops)) and is provided for reference only. Validate and adapt as needed for your environment.

### Directory Structure for CI/CD

```
interoperability/
├── .github/
│   └── workflows/
│       ├── deploy-dev.yml       # Triggered on push to dev branch
│       ├── deploy-test.yml      # Triggered on push to test branch
│       └── deploy-prod.yml      # Triggered on push to main branch
├── config/
│   └── environments.yaml        # Environment-specific endpoints
└── foundry/
    ├── agents/                  # Agent YAML definitions
    ├── workflows/               # Workflow YAML definitions
    └── deploy.py                # Deployment script
```

### Environment Configuration

```yaml
# config/environments.yaml
environments:
  dev:
    endpoint: https://<resource>.services.ai.azure.com/api/projects/<dev-project>
    resource_group: rg-foundry-dev
  test:
    endpoint: https://<resource>.services.ai.azure.com/api/projects/<test-project>
    resource_group: rg-foundry-test
  prod:
    endpoint: https://<resource>.services.ai.azure.com/api/projects/<prod-project>
    resource_group: rg-foundry-prod
```

### GitHub Actions Workflow (Example)

```yaml
# .github/workflows/deploy-dev.yml
name: Deploy to Dev
on:
  push:
    branches: [dev]
  workflow_dispatch:

env:
  AZURE_SUBSCRIPTION_ID: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
  AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
  AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
  ENVIRONMENT: dev

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Azure Login
        uses: azure/login@v2
        with:
          client-id: ${{ secrets.AZURE_CLIENT_ID }}
          tenant-id: ${{ secrets.AZURE_TENANT_ID }}
          subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}

      - name: Validate YAML files
        run: python scripts/validate_yamls.py

      - name: Deploy Agents
        run: python foundry/deploy.py --environment ${{ env.ENVIRONMENT }} --type agents

      - name: Deploy Workflows
        run: python foundry/deploy.py --environment ${{ env.ENVIRONMENT }} --type workflows

      - name: Run Smoke Tests
        run: python interoperability/test_smoke.py --demo a
```

### GitHub Secrets Required

| Secret | Description |
|--------|-------------|
| `AZURE_SUBSCRIPTION_ID` | Azure subscription ID |
| `AZURE_TENANT_ID` | Azure AD tenant ID |
| `AZURE_CLIENT_ID` | Service principal client ID |
| `PROJECT_ENDPOINT_DEV` | Dev environment project endpoint |
| `PROJECT_ENDPOINT_TEST` | Test environment project endpoint |
| `PROJECT_ENDPOINT_PROD` | Prod environment project endpoint |

---

## Implementation Task Breakdown

> **Note:** This breakdown is for reference only. For real implementation, please refer to `prd.json` file.

### Priority 1: Foundation + Foundry Agents (Day 1)

| Task | Description | Output |
|------|-------------|--------|
| 1.1 | Set up `interoperability/` directory structure | Folders + empty configs |
| 1.2 | Create base wrapper classes (`shared/agent_wrappers/`) | Reusable wrapper logic |
| 1.3 | Set up Foundry deployer skeleton (`foundry/deploy.py`) | Can deploy empty agents |
| 1.4 | Create Copilot Studio setup guide (`copilot_studio/SETUP.md`) + verification script (`verify.py`) | Manual setup docs + validation ready |
| 1.5 | Deploy Transport, POI, Events as native agents | 3 agents in Foundry |
| 1.6 | Deploy Stay as hosted agent (Microsoft Agent Framework) | 1 hosted agent |
| 1.7 | Deploy Dining as hosted agent (LangGraph) | 1 hosted agent |
| 1.8 | Deploy Aggregator + Route agents | 2 workflow agents |
| 1.9 | Verify all Foundry agents respond | Smoke tests pass |

### Priority 2: Copilot Studio Agents + Demo A Workflow (Day 2)

| Task | Description | Output |
|------|-------------|--------|
| 2.1 | Deploy Weather agent in Copilot Studio | 1 CS agent |
| 2.2 | **Create Foundry Discovery workflow (Portal-First Approach)** | Demo A working |
| 2.2a | *Portal Design:* Create workflow visually in Foundry portal (Intake → 6 agents → Aggregator → Route) | Workflow in portal |
| 2.2b | *Portal Design:* Test parallel execution pattern in portal playground | Pattern validated |
| 2.2c | *Export:* Export YAML via "Open in VS Code for Web", pull to local repo | YAML in `interoperability/foundry/` |
| 2.2d | *Iteration:* Edit YAML/convert to pro-code if needed, test in Local Agent Playground | Code validated locally |
| 2.2e | *Automation:* Configure CI/CD deployment via `deploy.py` / GitHub Actions | Automated deployment ready |
| 2.3 | Test Foundry → CS call (Weather) | Cross-platform verified |
| 2.4 | Deploy Approval agent in Copilot Studio | 1 CS agent |

### Priority 3: Demo B + Demo C (Day 3)

| Task | Description | Output |
|------|-------------|--------|
| 3.1 | Implement M365 SDK client (`pro_code/m365_sdk_client.py`) | SDK wrapper ready |
| 3.2 | Integrate Orchestrator → Approval Agent | Demo B working |
| 3.3 | Deploy Q&A Parent agent in Copilot Studio | 1 CS agent |
| 3.4 | Configure 6 connected agents in Q&A Parent | Demo C working |

### Priority 4: Documentation (Day 4)

| Task | Description | Output |
|------|-------------|--------|
| 4.1 | Run all smoke tests, fix issues | All tests green |
| 4.2 | Create demo scripts (step-by-step for each demo) | Demo runbooks |
| 4.3 | Write `interoperability/README.md` | Setup + usage docs |
| 4.4 | Record quick demo video or screenshots | Demo artifacts |

---

## Deferred to Phase 2

The following features were discussed but deferred to keep scope manageable:

| Feature | Description |
|---------|-------------|
| MCP Tools / Word doc | Route Agent using Agent365 MCP Tools to generate Word documents |
| Demo C triggers Demo A | Q&A Parent detecting "create me a plan" intent and triggering Foundry workflow |

## Deferred to Phase 3

| Feature | Description |
|---------|-------------|
| Agent 365 Integration | Enterprise control plane with unified identity, security, and M365 integration. Requires frontier preview enrollment. See [Agent 365 docs](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/agent-365?view=foundry). |

---

## Summary

| Demo | Integration Pattern | Key Platforms |
|------|---------------------|---------------|
| **A** | Foundry workflow with mixed hosting | Foundry (native + hosted) + CS (Weather) |
| **B** | Pro Code calls Copilot Studio | This repo + CS via M365 SDK |
| **C** | Copilot Studio orchestrates Foundry | CS + Foundry (5 agents) |

All three demos share the same 6 deployed agents, demonstrating true multi-platform interoperability.

---

## Appendix: SDK Reference

This appendix contains detailed SDK documentation for implementers. For conceptual understanding, see the demo sections above.

### A.1 Microsoft Foundry Agents

> **Important:** The 2.x preview SDK targets the new Foundry portal and API. The 1.x GA SDK targets Foundry classic. Code samples must match your installed package version.

**Reference Documentation:**
- [SDK Overview](https://learn.microsoft.com/en-us/azure/ai-foundry/how-to/develop/sdk-overview?view=foundry&pivots=programming-language-python)
- [Quickstart](https://learn.microsoft.com/en-us/azure/ai-foundry/quickstarts/get-started-code?view=foundry&tabs=python)
- [Code Samples](https://github.com/microsoft-foundry/foundry-samples/tree/main/samples/python/quickstart)

**Installation:**
```bash
pip install azure-ai-projects --pre   # 2.x preview for new Foundry portal
pip install azure-identity openai python-dotenv
```

**Environment Variables:**
```bash
PROJECT_ENDPOINT="https://<resource-name>.services.ai.azure.com/api/projects/<project-name>"
MODEL_DEPLOYMENT_NAME="gpt-4.1-mini"
AGENT_NAME="MyAgent"
```

**Key Code Patterns:**

```python
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.identity import DefaultAzureCredential
import os

# Initialize client (uses project endpoint, NOT connection string)
project_client = AIProjectClient(
    endpoint=os.environ["PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential(),
)

# Get OpenAI client for chat/responses
openai_client = project_client.get_openai_client()

# Simple chat (no agent)
response = openai_client.responses.create(
    model=os.environ["MODEL_DEPLOYMENT_NAME"],
    input="What is the size of France?",
)
print(response.output_text)

# Create an agent
agent = project_client.agents.create_version(
    agent_name=os.environ["AGENT_NAME"],
    definition=PromptAgentDefinition(
        model=os.environ["MODEL_DEPLOYMENT_NAME"],
        instructions="You are a helpful travel assistant",
    ),
)
print(f"Agent created: id={agent.id}, name={agent.name}, version={agent.version}")

# Chat with agent using conversations (replaces threads)
conversation = openai_client.conversations.create()

response = openai_client.responses.create(
    conversation=conversation.id,
    extra_body={"agent": {"name": agent.name, "type": "agent_reference"}},
    input="Find flights from NYC to Tokyo",
)
print(response.output_text)

# Follow-up in same conversation
response = openai_client.responses.create(
    conversation=conversation.id,
    extra_body={"agent": {"name": agent.name, "type": "agent_reference"}},
    input="What about hotels near the airport?",
)
print(response.output_text)
```

**Key Differences from This Repo's Current Pattern:**

| Aspect | Current Repo (Classic/Hub) | New Foundry (2.x) |
|--------|---------------------------|-------------------|
| Connection | Connection string | Project endpoint |
| Client init | `AIProjectClient.from_connection_string()` | `AIProjectClient(endpoint=...)` |
| Agent creation | `agents.create_agent()` returns assistant_id | `agents.create_version()` returns agent with id, name, version |
| Conversation | Thread ID (`threads.create()`) | Conversation ID (`conversations.create()`) |
| Run agent | `runs.create_and_process(thread_id, agent_id)` | `responses.create(conversation=..., extra_body={"agent": ...})` |
| API pattern | Assistants API | Responses API |

### A.2 Hosted Agents (Agent Framework & LangGraph)

> **⚠️ Needs Validation:** The hosted agents pattern documented below is based on official Microsoft documentation but has not been validated by community examples. The Stay (Agent Framework) and Dining (LangGraph) agents using `ImageBasedHostedAgentDefinition` should be validated during implementation.

Hosted agents let you deploy custom-code agents built with Microsoft Agent Framework, LangGraph, or other frameworks into a fully managed runtime—no container orchestration required.

**Reference Documentation:**
- [Hosted Agents Concepts](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/concepts/hosted-agents?view=foundry)

**Supported Frameworks:**

| Framework | Python | C# |
|-----------|--------|-----|
| Microsoft Agent Framework | Yes | Yes |
| LangGraph | Yes | No |
| Custom code | Yes | Yes |

**Installation:**
```bash
pip install azure-ai-projects --pre              # >=2.0.0b2 required
pip install azure-ai-agentserver-core            # Core server package
pip install azure-ai-agentserver-agentframework  # For Microsoft Agent Framework agents (Stay)
pip install azure-ai-agentserver-langgraph       # For LangGraph agents (Dining)
pip install azure-identity
```

**Prerequisites:**
- Container image hosted in Azure Container Registry (ACR)
- ACR pull permissions granted to project's managed identity
- Account-level capability host enabled

**Deploying a Hosted Agent:**

```python
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    ImageBasedHostedAgentDefinition,
    ProtocolVersionRecord,
    AgentProtocol,
)
from azure.identity import DefaultAzureCredential
import os

client = AIProjectClient(
    endpoint=os.environ["PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential(),
)

# Deploy hosted agent from container image
agent = client.agents.create_version(
    agent_name="stay-agent",
    description="Hotel search agent using Agent Framework",
    definition=ImageBasedHostedAgentDefinition(
        container_protocol_versions=[
            ProtocolVersionRecord(protocol=AgentProtocol.RESPONSES, version="v1")
        ],
        cpu="1",
        memory="2Gi",
        image="your-registry.azurecr.io/stay-agent:latest",
        environment_variables={
            "AZURE_AI_PROJECT_ENDPOINT": os.environ["PROJECT_ENDPOINT"],
            "MODEL_NAME": "gpt-4o",
        },
    ),
)
print(f"Deployed: {agent.name} v{agent.version}")
```

**Invoking a Hosted Agent:**

```python
from azure.ai.projects.models import AgentReference

# Retrieve deployed agent
agent = client.agents.retrieve(agent_name="stay-agent")

# Get OpenAI client and invoke
openai_client = client.get_openai_client()
response = openai_client.responses.create(
    input=[{"role": "user", "content": "Find hotels in Tokyo near Shibuya"}],
    extra_body={"agent": AgentReference(name=agent.name, version="1").as_dict()},
)
print(response.output_text)
```

**Local Testing (before deployment):**

```bash
# Test your agent locally on port 8088
curl -X POST http://localhost:8088/responses \
  -H "Content-Type: application/json" \
  -d '{"input": {"messages": [{"role": "user", "content": "Your prompt"}]}}'
```

**Using Azure Developer CLI (alternative deployment):**

```bash
# Initialize with agent definition
azd ai agent init -m <path-to-agent.yaml>

# Deploy infrastructure and agent
azd up

# Cleanup
azd down
```

**Preview Limitations:**

| Dimension | Limit |
|-----------|-------|
| Hosted agents per Foundry resource | 200 |
| Max `min_replica` count | 2 |
| Max `max_replica` count | 5 |
| Region | North Central US (primary) + 20 other regions |

**Security Notes:**
- Don't put secrets in container images or environment variables
- Use managed identities and Key Vault connections
- No private networking support during preview

### A.3 Copilot Studio (M365 Agents SDK)

> **Important:** Copilot Studio is a no-code/low-code platform. Agents should be **created manually** via the Copilot Studio portal. There is no Python SDK to programmatically create agents. However, once created, you can use the Copilot Studio client library to interact with them.

**Reference Documentation:**
- [Integrate with Copilot Studio](https://learn.microsoft.com/en-us/microsoft-365/agents-sdk/integrate-with-mcs)
- [Python Sample](https://github.com/microsoft/Agents/tree/main/samples/python/copilotstudio-client)

**Agent Creation (Manual Steps):**
1. Create agent in Copilot Studio portal
2. Configure topics and triggers
3. Publish the agent
4. Register Azure AD app for authentication
5. Note the Environment ID and Schema Name

**Automation Pattern (CI/CD):**
- Manual creation via portal (one-time setup, documented in `copilot_studio/SETUP.md`)
- Use `copilot_studio/verify.py` to validate agents exist and are configured correctly
- Use Power Platform CLI in GitHub Actions (`.github/workflows/copilot-studio-ci.yml`) for:
  - Exporting agent definitions for version control
  - Importing updates to agents (topics/triggers)
  - Environment promotion (dev → staging → prod)

**Installation (for client interaction):**
```bash
pip install microsoft-agents-copilotstudio-client  # v0.7.0+
pip install microsoft-agents-authentication-msal   # For token acquisition
```

**Requirements:** Python 3.10+

**Environment Variables:**
```bash
COPILOTSTUDIOAGENT__ENVIRONMENTID="your-power-platform-environment-id"
COPILOTSTUDIOAGENT__SCHEMANAME="your-agent-schema-name"
COPILOTSTUDIOAGENT__TENANTID="your-azure-tenant-id"
COPILOTSTUDIOAGENT__AGENTAPPID="your-azure-app-client-id"
```

**Code Example - Calling a Copilot Studio Agent:**

```python
from os import environ
from microsoft_agents_copilotstudio_client import CopilotClient, ConnectionSettings
from microsoft_agents_copilotstudio_client.models import ActivityTypes

def acquire_token(settings, app_client_id, tenant_id):
    """Acquire token using MSAL - implement based on your auth flow"""
    # Use interactive auth, client credentials, or cached token
    # Scope: https://api.powerplatform.com/.default
    pass

def create_client():
    settings = ConnectionSettings(
        environment_id=environ.get("COPILOTSTUDIOAGENT__ENVIRONMENTID"),
        agent_identifier=environ.get("COPILOTSTUDIOAGENT__SCHEMANAME"),
    )
    token = acquire_token(
        settings,
        app_client_id=environ.get("COPILOTSTUDIOAGENT__AGENTAPPID"),
        tenant_id=environ.get("COPILOTSTUDIOAGENT__TENANTID"),
    )
    return CopilotClient(settings, token)

async def call_approval_agent(itinerary_json: str) -> dict:
    """Demo B: Call Approval Agent in Copilot Studio"""
    client = create_client()

    # Start conversation
    conversation_id = await client.start_conversation(emit_start_event=True)

    # Send itinerary for approval
    prompt = f"Please review and approve this itinerary:\n{itinerary_json}"

    async for reply in client.ask_question(prompt, conversation_id):
        if reply.type == ActivityTypes.message:
            print(f"Agent: {reply.text}")
        elif reply.type == ActivityTypes.event:
            if reply.name == "approval_decision":
                return reply.value  # {"decision": "approved", "feedback": "..."}

    return {"decision": "pending", "feedback": "No response"}

async def ask_weather(location: str, date: str) -> str:
    """Demo A: Call Weather Agent in Copilot Studio"""
    client = create_client()
    conversation_id = await client.start_conversation(emit_start_event=True)

    async for reply in client.ask_question(
        f"What's the weather forecast for {location} on {date}?",
        conversation_id
    ):
        if reply.type == ActivityTypes.message:
            return reply.text

    return "Weather data unavailable"
```

**Authentication Flow:**
1. Register Azure AD app with `https://api.powerplatform.com/.default` scope
2. Configure app permissions for Power Platform access
3. Use MSAL for token acquisition (interactive, client credentials, or cached)
4. Tokens cached locally in `.local_token_cache.json` for reuse

**Agents to Create in Copilot Studio:**

| Agent | Purpose | Demo |
|-------|---------|------|
| Weather Agent | Provides weather forecasts | Demo A (called from Foundry) |
| Approval Agent | Human approval for itineraries | Demo B (called from Pro Code) |
| Q&A Parent Agent | Routes questions to connected agents | Demo C (entry point) |

### A.4 Publishing Agents to M365 Copilot and Teams

Foundry agents can be published to Microsoft 365 Copilot and Microsoft Teams for broader distribution.

**Reference Documentation:**
- [Publish to M365 Copilot and Teams](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/publish-copilot?view=foundry)

**Prerequisites:**
- Tested agent version in Foundry project
- Publishing permissions in your project
- Azure subscription for Azure Bot Service and Entra ID app registration

**Publishing Steps:**
1. Select agent version in Foundry portal → **Publish** → **Publish to Teams and Microsoft 365 Copilot**
2. Create/select Azure Bot Service resource
3. Complete metadata (name, description, icons, privacy policy)
4. Click **Prepare Agent** to start packaging
5. Download package for testing or continue in-product publishing
6. Upload to Microsoft Teams for testing

**Scope Options:**
- **Shared scope**: Appears under "Your agents"
- **Organization scope**: Appears under "Built by your org" (requires admin approval)

### A.5 Agent 365 Integration (Phase 3)

> **Deferred to Phase 3:** Agent 365 is Microsoft's enterprise control plane for AI agents. Integration requires frontier preview program enrollment and is recommended for production enterprise deployments.

**Reference Documentation:**
- [Publish to Agent 365](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/agent-365?view=foundry)

**What is Agent 365?**
- Enterprise control plane for AI agents at scale
- Unified identity and lifecycle management
- Security controls via Microsoft Defender, Entra, and Purview
- Integration with Microsoft 365 apps and services
- Centralized monitoring and compliance

**Prerequisites (for Phase 3):**
- Frontier preview program enrollment
- Azure subscription with resources in **North Central US only**
- Owner role on Azure subscription + Tenant admin role
- Docker, .NET 9.0 SDK, Azure CLI, Azure Developer CLI

---

## Update on 2026-02-02: Implementation Task Breakdown for Option A (Pro-Code Workflow)

> **Note:** The main "Implementation Task Breakdown" section (lines 1356-1405) is primarily for Option B (Declarative Workflow + Weather Proxy). This appendix provides the corresponding breakdown for Option A (Pro-Code Workflow using Microsoft Agent Framework).

### Option A Overview

Option A builds the Discovery Workflow entirely in Python using the Microsoft Agent Framework, deploying it as a single Hosted Agent. This approach:
- Uses `WorkflowBuilder` with fan-out/fan-in for parallel agent execution
- Calls Copilot Studio Weather agent directly via `CopilotStudioAgent` (no proxy needed)
- Deploys as a containerized Hosted Agent in Foundry

### Priority 2A: Pro-Code Discovery Workflow (Day 2 - Option A)

| Task | Description | Output |
|------|-------------|--------|
| 2A.1 | Create workflow directory structure (`foundry/workflows/discovery_workflow_procode/`) | Directory + init files |
| 2A.2 | Implement `intake_processor.py` to parse TripSpec from input | Intake step ready |
| 2A.3 | Create agent invocation steps for Transport, POI, Events, Stay, Dining | 5 agent steps |
| 2A.4 | Implement Weather step using `CopilotStudioAgent` | CS cross-platform call |
| 2A.5 | Implement `aggregator_step.py` to combine agent results | Aggregation logic |
| 2A.6 | Implement `route_step.py` to produce final Route output | Route generation |
| 2A.7 | Build workflow using `WorkflowBuilder` with fan-out/fan-in pattern | `workflow.py` complete |
| 2A.8 | Create `main.py` with `AgentServer.handler` for hosted deployment | Entry point ready |
| 2A.9 | Create `Dockerfile` and `requirements.txt` for container build | Container config |
| 2A.10 | Update `deploy.py` to support pro-code workflow deployment | Deployment script |
| 2A.11 | Deploy and test workflow in Foundry | Demo A working |

### Option A File Structure

```
interoperability/foundry/workflows/discovery_workflow_procode/
├── __init__.py
├── main.py                    # AgentServer entry point
├── workflow.py                # WorkflowBuilder definition
├── steps/
│   ├── __init__.py
│   ├── intake_processor.py    # TripSpec parsing
│   ├── transport_step.py      # Call Transport agent
│   ├── poi_step.py            # Call POI agent
│   ├── events_step.py         # Call Events agent
│   ├── stay_step.py           # Call Stay agent
│   ├── dining_step.py         # Call Dining agent
│   ├── weather_step.py        # CopilotStudioAgent → CS Weather
│   ├── aggregator_step.py     # Combine results
│   └── route_step.py          # Generate route
├── Dockerfile
├── requirements.txt
└── agent.yaml                 # Hosted agent definition
```

### Key Differences from Option B

| Aspect | Option A (Pro-Code) | Option B (Declarative + Proxy) |
|--------|---------------------|-------------------------------|
| **Workflow definition** | Python code with `WorkflowBuilder` | YAML with `InvokeAzureAgent` actions |
| **Weather integration** | Direct `CopilotStudioAgent` in workflow | Separate Weather Proxy hosted agent |
| **Deployment units** | 1 hosted agent (workflow) | 2 components (YAML workflow + proxy agent) |
| **Parallel execution** | `add_fan_out_edges()` / `add_fan_in_edges()` | YAML parallel actions (needs validation) |
| **Debugging** | Python debugging, local testing | Portal playground, YAML inspection |
| **Flexibility** | Full programmatic control | Visual design, easier portal iteration |

### Option A Code Sample: workflow.py

```python
from agent_framework import WorkflowBuilder
from agent_framework.microsoft import CopilotStudioAgent
from steps.intake_processor import IntakeProcessor
from steps.transport_step import TransportStep
from steps.poi_step import POIStep
from steps.events_step import EventsStep
from steps.stay_step import StayStep
from steps.dining_step import DiningStep
from steps.weather_step import WeatherStep
from steps.aggregator_step import AggregatorStep
from steps.route_step import RouteStep

def build_discovery_workflow():
    """Build the Discovery Workflow using fan-out/fan-in pattern."""

    # Initialize steps
    intake = IntakeProcessor()
    transport = TransportStep()
    poi = POIStep()
    events = EventsStep()
    stay = StayStep()
    dining = DiningStep()
    weather = WeatherStep()  # Uses CopilotStudioAgent internally
    aggregator = AggregatorStep()
    route = RouteStep()

    # Discovery agents (parallel execution)
    discovery_agents = [transport, poi, events, stay, dining, weather]

    # Build workflow with fan-out/fan-in
    workflow = (
        WorkflowBuilder()
        .set_start_executor(intake)
        .add_fan_out_edges(intake, discovery_agents)
        .add_fan_in_edges(discovery_agents, aggregator)
        .add_edge(aggregator, route)
        .build()
    )

    return workflow
```

### Option A Code Sample: weather_step.py

```python
from agent_framework.microsoft import CopilotStudioAgent
from shared.schemas.weather import WeatherRequest, WeatherResponse

class WeatherStep:
    """Weather step that calls Copilot Studio Weather agent directly."""

    def __init__(self):
        # CopilotStudioAgent uses environment variables:
        # COPILOTSTUDIOAGENT__ENVIRONMENTID
        # COPILOTSTUDIOAGENT__SCHEMANAME
        # COPILOTSTUDIOAGENT__DIRECTLINECLIENTID (optional)
        self.cs_agent = CopilotStudioAgent(name="WeatherAgent")

    async def execute(self, trip_spec: dict) -> WeatherResponse:
        """Execute weather lookup for the trip destination."""
        request = WeatherRequest(
            location=trip_spec["destination_city"],
            start_date=trip_spec["start_date"],
            end_date=trip_spec["end_date"],
        )

        result = await self.cs_agent.run(
            f"Weather forecast for {request.location} "
            f"from {request.start_date} to {request.end_date}"
        )

        return WeatherResponse.model_validate_json(result.content)
```

### Option A Deployment

```bash
# Build container image
cd interoperability/foundry/workflows/discovery_workflow_procode
docker build -t discovery-workflow-procode:latest .

# Push to ACR
az acr login --name <acr-name>
docker tag discovery-workflow-procode:latest <acr-name>.azurecr.io/discovery-workflow-procode:latest
docker push <acr-name>.azurecr.io/discovery-workflow-procode:latest

# Deploy as hosted agent
uv run python interoperability/foundry/deploy.py --agent discovery_workflow_procode
```

### Option A vs Option B: When to Use Each

| Scenario | Recommended Option |
|----------|-------------------|
| Need full programmatic control over workflow logic | **Option A** |
| Want to iterate visually in Foundry portal | **Option B** |
| Complex branching or conditional logic | **Option A** |
| Team prefers low-code/no-code | **Option B** |
| Need to debug with Python debugger | **Option A** |
| Want portal playground testing | **Option B** |
| Single deployment unit preferred | **Option A** |
| Separate concerns (workflow vs proxy) | **Option B** |

---

## Appendix: Phase Schedule Updates

### Demo A Option A Deferred to Phase 2

> **Update:** Implementation of Demo A using **Option A (Pro-Code Workflow)** has been deferred to Phase 2.

**Phase 1 Scope:**
- Demo A will be implemented using **Option B (Declarative Workflow + Weather Proxy)** only
- This allows faster iteration using the Foundry portal's visual workflow designer
- Weather Proxy agent bridges the cross-platform call to Copilot Studio

**Phase 2 Scope:**
- Implement Demo A using **Option A (Pro-Code Workflow)** as an alternative
- Full Microsoft Agent Framework workflow with `WorkflowBuilder`
- Direct `CopilotStudioAgent` integration (no proxy needed)
- Provides programmatic control for advanced use cases

**Rationale:**
- Option B aligns with the Portal-First Approach recommended in the design
- Reduces Phase 1 complexity by focusing on one workflow implementation
- Option A can be added in Phase 2 once Option B is validated and stable

---

## Appendix: Demo B Design Amendment (2026-02-07)

> **Design Change:** Demo B flow has been revised to call the Copilot Studio Approval Agent directly from the Demo A Foundry workflow, rather than from the existing code orchestrator. This creates a smoother end-to-end story where itinerary generation and approval happen within the same Foundry workflow.

### Previous Demo B Design (Deprecated)

The original Demo B design called the Approval Agent from the existing code orchestrator:

```
┌─────────────────────────────────────────────────────────────┐
│                    PRO CODE (this repo)                     │
│                                                             │
│  Orchestrator ──── M365 Agents SDK ───→ Copilot Studio      │
│      │                                        │             │
│      │ (draft itinerary                       ▼             │
│      │  from Demo A                  ┌──────────────────┐   │
│      │  or existing flow)            │  Approval Agent  │   │
│      │                               └──────────────────┘   │
│      │◄───────── approval decision ───────────┘             │
└─────────────────────────────────────────────────────────────┘
```

**Status:** This approach is **parked**. The existing code orchestrator is not used for Demo B.

### New Demo B Design: Foundry Workflow → Copilot Studio Approval

Demo B now extends the Demo A Foundry workflow to include an approval step. After generating the draft itinerary, the workflow calls the Copilot Studio Approval Agent via M365 Agents SDK.

**Flow:**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FOUNDRY                                         │
│                                                                              │
│  TripSpec ───→ Discovery Workflow ───→ Draft Itinerary                      │
│       │               │                        │                             │
│       │    ┌──────────┴──────────┐            │                             │
│       │    ▼                     ▼            │                             │
│       │  [6 Discovery    [Aggregator +        │                             │
│       │   Agents...]      Route Agent]        │                             │
│       │                                       │                             │
│       │                                       ▼                             │
│       │                          ┌────────────────────────────┐             │
│       │                          │   Approval Step            │             │
│       │                          │   (Hosted Agent or         │             │
│       │                          │    Pro-Code Workflow Step) │             │
│       │                          └────────────────────────────┘             │
│       │                                       │                             │
│       │                                       │ M365 Agents SDK             │
│       │                                       ▼                             │
│       │                          ┌────────────────────────────┐             │
│       │                          │   Approval Agent (CS)      │             │
│       │                          │   • Shows itinerary        │             │
│       │                          │   • Approve/Reject/Modify  │             │
│       │                          └────────────────────────────┘             │
│       │                                       │                             │
│       │                                       ▼                             │
│       │                          ┌────────────────────────────┐             │
│       │                          │   Final Output             │             │
│       │                          │   • Approved itinerary, OR │             │
│       │                          │   • Rejection + feedback   │             │
│       │                          └────────────────────────────┘             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Implementation Options

The approval step can be implemented in two ways, depending on whether Demo A uses Option A (Pro-Code) or Option B (Declarative):

#### With Option A (Pro-Code Workflow)

Add an approval step to the workflow that uses `CopilotStudioAgent` directly:

```python
from agent_framework.microsoft import CopilotStudioAgent

class ApprovalStep:
    """Approval step that calls Copilot Studio Approval Agent."""

    def __init__(self):
        # Configure for Approval Agent (different schema than Weather)
        self.cs_agent = CopilotStudioAgent(
            name="ApprovalAgent",
            # Uses COPILOTSTUDIOAGENT__* env vars for connection
        )

    async def execute(self, itinerary: dict) -> ApprovalResponse:
        """Send itinerary to Approval Agent and await decision."""
        result = await self.cs_agent.run(
            f"Please review and approve this itinerary:\n{json.dumps(itinerary, indent=2)}"
        )
        return ApprovalResponse.model_validate_json(result.content)

# Updated workflow with approval step
workflow = (
    WorkflowBuilder()
    .set_start_executor(intake)
    .add_fan_out_edges(intake, discovery_agents)
    .add_fan_in_edges(discovery_agents, aggregator)
    .add_edge(aggregator, route)
    .add_edge(route, approval_step)  # NEW: approval after route
    .build()
)
```

#### With Option B (Declarative Workflow)

Create an **Approval Proxy Hosted Agent** (similar to Weather Proxy) that bridges the M365 SDK call:

```
interoperability/foundry/agents/
├── weather_proxy/          # Existing: bridges to CS Weather
└── approval_proxy/         # NEW: bridges to CS Approval Agent
    ├── agent.yaml
    ├── main.py             # M365 SDK client calling CS Approval Agent
    ├── Dockerfile
    └── requirements.txt
```

**Declarative Workflow YAML Addition:**

```yaml
# After invoke_route action...
- kind: InvokeAzureAgent
  id: invoke_approval
  conversationId: =System.ConversationId
  agent:
    name: ApprovalProxyAgent  # Hosted agent that calls CS
  input:
    messages: =Local.RouteResultMsg  # Itinerary from route agent
  output:
    text: Local.ApprovalResult
    autoSend: true  # Show final result to user
```

### Approval Agent Contract (Unchanged)

The Approval Agent contract remains the same as defined in the original Demo B section (lines 632-740). The agent:

- **Receives:** Draft itinerary JSON
- **Displays:** Human-readable summary in Copilot Studio UI
- **Returns:** `{ "decision": "approved" | "rejected" | "modify", "feedback": "..." }`

### Updated Demo Summary

| Demo | Integration Pattern | Key Platforms |
|------|---------------------|---------------|
| **A** | Foundry workflow with mixed hosting | Foundry (native + hosted) + CS (Weather) |
| **B** | **Foundry workflow calls CS Approval** | Foundry + CS (Approval Agent) via M365 SDK |
| **C** | Copilot Studio orchestrates Foundry | CS + Foundry (5 agents) |

### What This Changes

| Aspect | Before | After |
|--------|--------|-------|
| Demo B entry point | Existing code orchestrator | Foundry Discovery Workflow |
| Approval call location | `src/orchestrator/handlers/` | Foundry workflow step |
| Dependency on existing orchestrator | Required | Not required (parked) |
| End-to-end flow | Separate Demo A + Demo B | Unified workflow in Foundry |

### Benefits of New Design

1. **Simpler demo story**: Itinerary generation and approval happen in one Foundry workflow
2. **No orchestrator changes needed**: Existing code remains untouched
3. **Consistent cross-platform pattern**: Both Weather and Approval use the same M365 SDK integration from Foundry
4. **Cleaner architecture**: TripSpec → Discovery → Approval → Final Output in a single workflow

### Ticket Impact

The following tickets from `prd.json` may need updates:

| Ticket | Original Scope | Updated Scope |
|--------|----------------|---------------|
| Demo B tickets | Pro Code Orchestrator → CS | Foundry Workflow → CS |
| Copilot Studio Handler | New handler in `src/orchestrator/handlers/` | Approval Proxy agent in Foundry (Option B) or workflow step (Option A) |
| M365 SDK Client | `interoperability/pro_code/m365_sdk_client.py` | Reused in Approval Proxy or workflow step |

> **Note:** Specific ticket updates to `prd.json` will be made in a separate change to keep this design amendment focused.

---

## INTEROP-011B Implementation Details

This section provides detailed implementation guidance for the Weather Proxy hosted agent, which bridges Azure AI Foundry workflows to the Copilot Studio Weather Agent.

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Azure AI Foundry                                      │
│  ┌─────────────────┐     ┌─────────────────────────────────────────────┐    │
│  │ Discovery       │     │ Weather Proxy (Hosted Agent)                │    │
│  │ Workflow        │────▶│                                             │    │
│  │                 │     │  1. Receive request via /responses          │    │
│  └─────────────────┘     │  2. Parse location, start_date, end_date    │    │
│                          │  3. Acquire token via MSAL                  │    │
│                          │  4. Call CS Weather Agent via CopilotClient │    │
│                          │  5. Parse JSON response                     │    │
│                          │  6. Return WeatherResponse                  │    │
│                          └──────────────────┬──────────────────────────┘    │
└─────────────────────────────────────────────┼───────────────────────────────┘
                                              │
                                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Microsoft Copilot Studio                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ Weather Agent                                                        │    │
│  │ - Receives prompt with location and date range                       │    │
│  │ - Generates climate summary based on historical patterns             │    │
│  │ - Returns JSON response with climate_summary                         │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Reference Implementations

| Reference | Location | Purpose |
|-----------|----------|---------|
| Copilot Studio Client Sample | https://github.com/microsoft/Agents/tree/main/samples/python/copilotstudio-client | CopilotClient usage, MSAL auth |
| Stay Agent (Hosted Agent) | `interoperability/foundry/agents/stay/` | Hosted agent structure, Dockerfile |
| Hosted Agents Docs | https://learn.microsoft.com/en-us/azure/ai-foundry/agents/concepts/hosted-agents | Azure AI Foundry hosting |

### Directory Structure

```
interoperability/foundry/agents/weather_proxy/
├── agent.yaml          # Hosted agent definition
├── main.py             # Agent implementation with CopilotClient
├── Dockerfile          # Container configuration
├── requirements.txt    # Python dependencies
└── README.md           # Setup and testing instructions
```

### Key Components

#### 1. agent.yaml

```yaml
name: weather-proxy
description: Proxy agent that calls Copilot Studio Weather Agent
type: hosted
framework: custom  # Not using ChatAgent, using custom CopilotClient logic

container:
  image: ${WEATHER_PROXY_IMAGE}
  cpu: "1"
  memory: "2Gi"

protocol:
  - protocol: responses
    version: v1

environment:
  # Copilot Studio connection (from SETUP.md Step 1.1)
  COPILOTSTUDIOAGENT__TENANTID: ${COPILOTSTUDIOAGENT__TENANTID}
  COPILOTSTUDIOAGENT__ENVIRONMENTID: ${COPILOTSTUDIOAGENT__ENVIRONMENTID}
  COPILOTSTUDIOAGENT__AGENTAPPID: ${COPILOTSTUDIOAGENT__AGENTAPPID}
  COPILOTSTUDIOAGENT__AGENTAPPSECRET: ${COPILOTSTUDIOAGENT__AGENTAPPSECRET}
  COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME: ${COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME}
```

#### 2. requirements.txt

```txt
# Azure AI hosted agent server (for /responses endpoint)
azure-ai-agentserver-core

# Copilot Studio client (to call CS Weather Agent)
microsoft-agents-copilotstudio-client

# Authentication
msal

# Async HTTP
aiohttp

# Schema validation (shared models)
pydantic>=2.0.0

# Environment variables
python-dotenv

# Azure identity (for managed identity in production)
azure-identity
```

#### 3. main.py Implementation Pattern

```python
"""
Weather Proxy - Hosted Agent that calls Copilot Studio Weather Agent

This agent:
1. Receives requests via the /responses protocol
2. Extracts location, start_date, end_date from the message
3. Acquires a token using MSAL client credentials flow
4. Calls the CS Weather Agent using CopilotClient
5. Parses the JSON response and returns WeatherResponse
"""

import asyncio
import json
import logging
import os
import re
from typing import Optional

from dotenv import load_dotenv
from msal import ConfidentialClientApplication

# Import from microsoft-agents-copilotstudio-client
from microsoft.agents.copilotstudio.client import CopilotClient

# Import shared schema (do NOT duplicate)
from src.shared.models import WeatherResponse

load_dotenv()
logger = logging.getLogger(__name__)

# Environment variables
TENANT_ID = os.getenv("COPILOTSTUDIOAGENT__TENANTID")
ENVIRONMENT_ID = os.getenv("COPILOTSTUDIOAGENT__ENVIRONMENTID")
AGENT_APP_ID = os.getenv("COPILOTSTUDIOAGENT__AGENTAPPID")
AGENT_APP_SECRET = os.getenv("COPILOTSTUDIOAGENT__AGENTAPPSECRET")
WEATHER_SCHEMA_NAME = os.getenv("COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME")

# Token scope for Power Platform API
TOKEN_SCOPE = "https://api.powerplatform.com/.default"


def acquire_token() -> str:
    """Acquire access token using MSAL client credentials flow."""
    app = ConfidentialClientApplication(
        client_id=AGENT_APP_ID,
        client_credential=AGENT_APP_SECRET,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
    )
    result = app.acquire_token_for_client(scopes=[TOKEN_SCOPE])
    if "access_token" not in result:
        raise RuntimeError(f"Token acquisition failed: {result.get('error_description')}")
    return result["access_token"]


def create_copilot_client() -> CopilotClient:
    """Create CopilotClient with acquired token."""
    token = acquire_token()
    return CopilotClient(
        environment_id=ENVIRONMENT_ID,
        agent_schema_name=WEATHER_SCHEMA_NAME,
        token=token,
    )


def parse_weather_request(message: str) -> dict:
    """Extract location, start_date, end_date from message."""
    # Example message: "Get weather for location: Paris, France, start_date: 2025-06-15, end_date: 2025-06-20"
    location_match = re.search(r"location:\s*([^,]+(?:,\s*[^,]+)?)", message, re.IGNORECASE)
    start_match = re.search(r"start_date:\s*(\d{4}-\d{2}-\d{2})", message, re.IGNORECASE)
    end_match = re.search(r"end_date:\s*(\d{4}-\d{2}-\d{2})", message, re.IGNORECASE)

    return {
        "location": location_match.group(1).strip() if location_match else None,
        "start_date": start_match.group(1) if start_match else None,
        "end_date": end_match.group(1) if end_match else None,
    }


async def call_weather_agent(location: str, start_date: str, end_date: str) -> WeatherResponse:
    """Call CS Weather Agent and parse response."""
    client = create_copilot_client()

    # Format prompt for CS Weather Agent
    prompt = f"Get weather for location: {location}, start_date: {start_date}, end_date: {end_date}"

    # Start conversation and send message
    conversation = await client.start_conversation()
    response = await client.send_message(conversation.id, prompt)

    # Parse JSON from response
    response_text = response.messages[-1].content if response.messages else ""
    weather_data = json.loads(response_text)

    # Validate against schema
    return WeatherResponse(**weather_data)


# Handler for hosted agent framework
async def handle_request(request: dict) -> dict:
    """Handle incoming request from Foundry workflow."""
    messages = request.get("input", {}).get("messages", [])
    if not messages:
        return {"error": "No messages in request"}

    user_message = messages[-1].get("content", "")
    params = parse_weather_request(user_message)

    if not all([params["location"], params["start_date"], params["end_date"]]):
        return {"error": "Missing required parameters: location, start_date, end_date"}

    try:
        weather = await call_weather_agent(
            params["location"],
            params["start_date"],
            params["end_date"]
        )
        return {"response": weather.model_dump()}
    except Exception as e:
        logger.exception("Weather agent call failed")
        return {"error": str(e)}


def main():
    """Start the hosted agent server."""
    from azure.ai.agentserver.core import AgentServer

    port = int(os.getenv("PORT", "8088"))
    logger.info(f"Starting Weather Proxy on port {port}")

    server = AgentServer(handler=handle_request)
    server.run(port=port)


if __name__ == "__main__":
    main()
```

#### 4. Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY interoperability/foundry/agents/weather_proxy/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the interoperability module
COPY interoperability/ interoperability/

# Copy the source shared models (for WeatherResponse schema)
COPY src/ src/

# Copy the main entry point
COPY interoperability/foundry/agents/weather_proxy/main.py main.py

# Set Python path to include the project root
ENV PYTHONPATH=/app

# Expose the agent server port
EXPOSE 8088

# Run the agent server
CMD ["python", "main.py"]
```

### Environment Variables

| Variable | Description | Source |
|----------|-------------|--------|
| `COPILOTSTUDIOAGENT__TENANTID` | Azure AD tenant ID | Azure Portal |
| `COPILOTSTUDIOAGENT__ENVIRONMENTID` | Power Platform environment ID | Copilot Studio URL |
| `COPILOTSTUDIOAGENT__AGENTAPPID` | App registration client ID | SETUP.md Step 1.1 |
| `COPILOTSTUDIOAGENT__AGENTAPPSECRET` | App registration client secret | SETUP.md Step 1.1 |
| `COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME` | Weather Agent schema name | Copilot Studio agent settings |

### Authentication Flow

1. **Client Credentials Flow**: Weather Proxy uses MSAL `ConfidentialClientApplication` with client ID and secret
2. **Token Scope**: `https://api.powerplatform.com/.default` (Power Platform API)
3. **Token Caching**: MSAL handles token caching automatically
4. **Production**: Use Azure Key Vault for secrets, managed identity where possible

### Request/Response Flow

**Input (from Foundry Workflow):**
```json
{
  "input": {
    "messages": [
      {
        "role": "user",
        "content": "Get weather for location: Paris, France, start_date: 2025-06-15, end_date: 2025-06-20"
      }
    ]
  }
}
```

**Output (to Foundry Workflow):**
```json
{
  "response": {
    "location": "Paris, France",
    "start_date": "2025-06-15",
    "end_date": "2025-06-20",
    "climate_summary": {
      "average_high_temp_c": 24,
      "average_low_temp_c": 14,
      "average_precipitation_chance": 25,
      "typical_conditions": "Mostly sunny with occasional afternoon clouds"
    },
    "summary": "June in Paris is typically warm and pleasant with long sunny days."
  }
}
```

### Local Testing

```bash
# 1. Set environment variables
export COPILOTSTUDIOAGENT__TENANTID="your-tenant-id"
export COPILOTSTUDIOAGENT__ENVIRONMENTID="your-env-id"
export COPILOTSTUDIOAGENT__AGENTAPPID="your-app-id"
export COPILOTSTUDIOAGENT__AGENTAPPSECRET="your-secret"
export COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME="your-schema-name"

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run locally
python main.py

# 4. Test with curl
curl -X POST http://localhost:8088/responses \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "messages": [
        {"role": "user", "content": "Get weather for location: Paris, France, start_date: 2025-06-15, end_date: 2025-06-20"}
      ]
    }
  }'
```

### Key Differences from Stay Agent

| Aspect | Stay Agent | Weather Proxy |
|--------|------------|---------------|
| Framework | Microsoft Agent Framework (ChatAgent) | Custom CopilotClient |
| AI Model | Azure OpenAI via AzureAIAgentClient | Copilot Studio Weather Agent |
| Response Format | StayResponse (Pydantic) | WeatherResponse (Pydantic) |
| External Calls | Bing Search (optional) | Copilot Studio API |
| Auth | DefaultAzureCredential | MSAL client credentials |

### Error Handling

1. **Missing parameters**: Return error if location, start_date, or end_date not extracted
2. **Token acquisition failure**: Log error and return failure response
3. **CS Agent timeout**: Implement timeout and return partial/error response
4. **Invalid JSON response**: Log raw response and return parsing error
5. **Schema validation failure**: Log and return validation error details
