# Foundry Agent Deployment Guide

This document describes how to deploy agents and workflows to Azure AI Foundry.

## Prerequisites

Before deploying, ensure you have:

1. **Azure CLI logged in**: `az login`
2. **Resource group exists**: Create via Azure Portal or `az group create`
3. **Foundry project created**: Create in Azure AI Foundry portal
4. **Environment variables set** (see below)

## Environment Variables

### Required for All Deployments

```bash
export AZURE_RESOURCE_GROUP="your-resource-group"
export PROJECT_ENDPOINT="https://<resource>.services.ai.azure.com/api/projects/<project>"
```

### Required for Hosted Agents (Stay, Dining)

Hosted agents require Azure Container Registry access:

```bash
export ACR_NAME="your-acr-name"
export ACR_LOGIN_SERVER="your-acr.azurecr.io"
```

### Required for Cross-Platform Calls (Weather Proxy)

The Weather Proxy agent calls Copilot Studio and requires M365 SDK credentials:

```bash
# For local development - use actual values
export COPILOTSTUDIOAGENT__TENANTID="your-azure-tenant-id"
export COPILOTSTUDIOAGENT__AGENTAPPID="your-app-registration-id"
export COPILOTSTUDIOAGENT__AGENTAPPSECRET="your-client-secret"
export COPILOTSTUDIOAGENT__ENVIRONMENTID="your-power-platform-env-id"
export COPILOTSTUDIOAGENT__SCHEMANAME="weather-agent-schema-name"

# For production - use Key Vault references
# In config.yaml, the AGENTAPPSECRET is:
# @Microsoft.KeyVault(SecretUri=https://your-vault.vault.azure.net/secrets/cs-client-secret)
```

## Usage

### Validate Configuration

Check your config.yaml for errors without deploying:

```bash
cd interoperability/foundry
python deploy.py --validate
```

### Preview Deployment (Dry Run)

See what would be deployed without making any changes:

```bash
python deploy.py --dry-run
```

### Deploy Everything

Deploy all agents and workflows:

```bash
python deploy.py --deploy
```

### Deploy Specific Agent

Deploy a single agent by name:

```bash
python deploy.py --deploy --agent transport
python deploy.py --deploy --agent stay
```

### Deploy Specific Workflow

Deploy a single workflow:

```bash
python deploy.py --workflow discovery_procode --deploy
```

## Agent Types

### Native Agents (Transport, POI, Events, Aggregator, Route)

Native agents use `PromptAgentDefinition` and are deployed directly to Foundry.
The deployer extracts instructions from the source agent's `SYSTEM_PROMPT` and
maps tools (e.g., `HostedWebSearchTool()` → `bing_grounding`).

Deployment steps:
1. Parse config.yaml for agent definition
2. Extract SYSTEM_PROMPT from source agent
3. Map tools to Foundry tool kinds
4. Call `agents.create_version()` with `PromptAgentDefinition`

### Hosted Agents (Stay, Dining, Weather Proxy)

Hosted agents are containerized and deployed to Foundry's managed runtime.

Deployment steps:
1. Build Docker container from agent's Dockerfile
2. Push to Azure Container Registry
3. Register with Foundry using `ImageBasedHostedAgentDefinition`
4. Configure environment variables

## Troubleshooting

### "Missing required env vars" Error

The agent requires environment variables that aren't set. Check the agent's
`env_vars` list in config.yaml and ensure all are exported.

### "Agent not found in config" Error

The agent name doesn't match any entry in config.yaml. Check spelling and
ensure the agent is defined under the `agents:` section.

### "Invalid type" Error

The agent type must be "native" or "hosted". Hosted agents also require a
`framework` field with value "agent_framework" or "langgraph".

## Related Documentation

- Design doc: `docs/interoperability-design.md`
- Appendix A.1: Microsoft Foundry Agents SDK patterns
- Appendix A.2: Hosted Agents deployment patterns
