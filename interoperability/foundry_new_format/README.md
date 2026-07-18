# Foundry New-Format Travel Agents

## Purpose

This parallel track creates eight additive `travel-planner-*` agents with the
current Microsoft Foundry formats: five Prompt agents and three Python-source
Hosted agents. It is an isolated deployment and validation path; it does not
deploy, rename, or delete any existing agent.

## Relationship to interoperability/foundry

`interoperability/foundry/` contains the stable interoperability demos and
their existing agent definitions. This track intentionally uses distinct names
under `interoperability/foundry_new_format/` so the two implementations can
coexist. Do not switch a workflow, Copilot Studio parent agent, or other
consumer to these names until the new agents have been deployed, smoke-tested,
and approved separately.

## Agent Inventory

| Agent | Format | Role |
| --- | --- | --- |
| `travel-planner-transport` | Prompt | Transport discovery with Bing grounding |
| `travel-planner-poi` | Prompt | Point-of-interest discovery with Bing grounding |
| `travel-planner-events` | Prompt | Event discovery with Bing grounding |
| `travel-planner-aggregator` | Prompt | Discovery-result aggregation |
| `travel-planner-route` | Prompt | Itinerary construction |
| `travel-planner-stay` | Hosted | Accommodation discovery using Microsoft Agent Framework |
| `travel-planner-dining` | Hosted | Dining discovery using LangGraph and the Foundry Toolbox |
| `travel-planner-weather-proxy` | Hosted | Copilot Studio Weather-agent proxy through Direct Line |

## Identity and Agent 365

Foundry creates the Entra agent blueprint, dedicated agent identity, and agent-scoped endpoint for both Prompt and Hosted agents. The Agent 365 SDK is not required for identity creation in this track. Agent 365 enablement, licensing, and registry synchronization are tenant prerequisites.

The identity returned for each new agent is distinct from the Foundry project
managed identity. Foundry provisioning does not enable Agent 365 for a tenant
or guarantee when registry synchronization becomes visible.

## Prerequisites

- Python 3.13 and `uv`.
- Azure CLI authenticated to the target tenant and permission to create Foundry
  agent versions.
- Azure Developer CLI (`azd`) with the `azure.ai.agents` extension for the
  Hosted-agent flow.
- An existing Foundry project, model deployment, and Bing project connection.
- A Direct Line secret for `travel-planner-weather-proxy`.
- Agent 365 enabled and licensed in the tenant if registry visibility will be
  checked.

The root `uv` graph has legacy dependency conflicts. Do not modify
`pyproject.toml` or `uv.lock`; install and test Hosted-track dependencies in
the track-local environment:

```powershell
uv venv interoperability\foundry_new_format\.venv --python 3.13
uv pip install --python interoperability\foundry_new_format\.venv\Scripts\python.exe -r interoperability\foundry_new_format\requirements.txt
```

## Configure Prompt Agents

From the repository root, set only local shell environment variables; do not
commit endpoints, connection identifiers, or secrets.

```powershell
$env:PROJECT_ENDPOINT = "https://<account>.services.ai.azure.com/api/projects/<project>"
$env:AZURE_OPENAI_DEPLOYMENT_NAME = "<model-deployment>"
$env:BING_PROJECT_CONNECTION_ID = "<bing-project-connection>"
```

The five definitions are in `prompt_agents/`; `config.yaml` maps their logical
roles to those files. The search connection is required only by Transport, POI,
and Events.

## Validate and Deploy Prompt Agents

Use the track-local environment from the repository root:

```powershell
& interoperability\foundry_new_format\.venv\Scripts\python.exe -m interoperability.foundry_new_format.deploy_prompt_agents --validate
& interoperability\foundry_new_format\.venv\Scripts\python.exe -m interoperability.foundry_new_format.deploy_prompt_agents --dry-run
& interoperability\foundry_new_format\.venv\Scripts\python.exe -m interoperability.foundry_new_format.deploy_prompt_agents --deploy
```

Validation reports `Validated 5 Prompt agent definitions`. Deployment creates a
new version of each named agent and prints the identity and agent-scoped
endpoint when Foundry returns them. Reruns version the same logical names; they
do not alter the legacy agents.

## Configure azd for Hosted Agents

Run these commands from `interoperability\foundry_new_format`:

```powershell
azd extension install azure.ai.agents
azd env new <environment-name>
azd env set AZURE_AI_PROJECT_ENDPOINT "https://<account>.services.ai.azure.com/api/projects/<project>"
azd env set AZURE_AI_MODEL_DEPLOYMENT_NAME "<model-deployment>"
azd env set COPILOTSTUDIOAGENT__DIRECTLINE_SECRET "<direct-line-secret>"
```

The `azure.yaml` manifest provides the shared `travel-search` toolbox. Keep
the Direct Line secret in the active `azd` environment or an approved secret
store, never in the manifest or source tree.

`azd` automatically publishes the toolbox MCP endpoint as
`TOOLBOX_TRAVEL_SEARCH_MCP_ENDPOINT`; the Dining service maps that value to its
required `TOOLBOX_ENDPOINT` process variable. Do not set either value in the
`azd` environment for normal Hosted-agent runs. When running
`run_dining.py` directly outside `azd`, provide the endpoint explicitly:

```powershell
$env:TOOLBOX_ENDPOINT = "https://<toolbox-mcp-endpoint>"
```

## Run Hosted Agents Locally

From the track directory, run each Hosted agent with the Foundry `azd`
extension before deploying:

```powershell
azd ai agent run travel-planner-stay
azd ai agent run travel-planner-dining
azd ai agent run travel-planner-weather-proxy
```

Provide representative travel requests and verify that each response is
non-placeholder and follows its expected structured contract. If a preview
extension changes the local-run syntax, use `azd ai agent --help`; do not fall
back to the legacy container or image deployment path.

## Deploy Hosted Agents from Source

After local runs succeed, deploy from the track directory:

```powershell
azd up
```

This uploads the self-contained Python source bundle and remotely builds the
three services declared in `azure.yaml`. It does not require Dockerfiles, ACR
images, or manual start/stop commands. Confirm that the latest Hosted-agent
versions are active in Foundry before using them.

## Smoke Tests

For every deployed `travel-planner-*` agent:

1. In Foundry, confirm the latest version is active and copy its
   agent-scoped endpoint from Agent Details.
2. Send a representative request through that agent-scoped endpoint or the
   Foundry test surface; do not invoke a legacy shared endpoint.
3. Confirm a non-placeholder result: a discovery answer for Transport, POI,
   Events, Stay, Dining, or Weather; an aggregate for Aggregator; and an
   itinerary for Route.
4. Record the result without storing endpoint URLs, identities, secrets, or
   request transcripts containing sensitive data in the repository.

## RBAC for New Agent Identities

Grant downstream-resource permissions to the dedicated identity shown for each
new Foundry agent, not to the Foundry project managed identity. Scope each
role as narrowly as possible and verify that the principal is the new agent
identity before assigning access to tools, data stores, or other Azure
resources. Reapply the appropriate RBAC when a consumer is deliberately moved
to a new agent identity.

## Manual Agent 365 Registry Check

After deployment, verify in Foundry that each agent has a new-format identity,
blueprint, and agent-scoped endpoint. Then, in the Microsoft 365 admin center,
verify that Agent 365 is enabled, tenant terms are accepted, Foundry registry
synchronization is available, and the agents appear after the expected sync
period.

If the tenant preview requires a Foundry-to-Agent-365 registration or
publishing action, complete it only to register the Foundry agent for Agent 365
inventory. That registration or publishing action is distinct from distributing
an agent to Microsoft 365 Copilot or Teams. Microsoft 365 Copilot and Teams
distribution are separate product-release decisions and are out of scope for
this track.

## Switching Future Consumers to the New Names

This task makes no consumer changes. In a separately approved rollout, update
one workflow, Copilot Studio parent agent, or pro-code client at a time to use
the corresponding `travel-planner-*` name and agent-scoped endpoint. Verify
the new identity's RBAC and smoke-test the consumer before removing its legacy
reference. Keep the stable `interoperability/foundry/` demos available until
that rollout is complete.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Prompt validation fails | Set `PROJECT_ENDPOINT` to the Foundry project endpoint, provide a model deployment, and set the Bing connection for discovery agents. |
| Hosted build or local run fails | Run from this track, confirm Python 3.13, the `azure.ai.agents` extension, and the track-local requirements. Do not use the root legacy-conflicted dependency graph. |
| Weather Proxy fails | Set `COPILOTSTUDIOAGENT__DIRECTLINE_SECRET` in the active `azd` environment and validate the Copilot Studio Direct Line channel. |
| Tool access is denied | Assign the required least-privilege role to the individual Foundry agent identity, not the project managed identity. |
| Identity or endpoint is absent | Confirm that the agent was created through the new Foundry format and inspect the latest agent version in Foundry. |
| Registry entry is absent | Verify Agent 365 tenant enablement, licensing, Foundry registry sync availability, and any required registration action; registry delay does not invalidate a successful Foundry deployment. |
