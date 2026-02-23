# Weather Proxy - M365 Agents SDK with Client Credentials Flow

> **Note:** S2S is not yet supported by Copilot Studio's Direct-to-Engine API. See the [parent README](../README.md) for details and current status.

Hosted agent that calls Copilot Studio Weather Agent using the **M365 Agents SDK `CopilotClient`** with **client credentials flow** (app-only, no interactive user authentication).

This approach combines:
- **M365 Agents SDK** (`CopilotClient`) for richer Copilot Studio integration (vs Direct Line REST API)
- **Client credentials flow** for headless/backend deployment (vs interactive user sign-in)

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Azure AI Foundry                                      │
│  ┌─────────────────┐     ┌─────────────────────────────────────────────┐    │
│  │ Discovery        │     │ Weather Proxy (Hosted Agent)                │    │
│  │ Workflow         │────▶│                                             │    │
│  │                  │     │  1. Receive request via /responses          │    │
│  └──────────────────┘     │  2. Acquire app-only token (MSAL client    │    │
│                           │     credentials flow)                       │    │
│                           │  3. Call CS Weather Agent via CopilotClient │    │
│                           │  4. Parse JSON response                     │    │
│                           │  5. Return WeatherResponse                  │    │
│                           └──────────────────┬──────────────────────────┘    │
└──────────────────────────────────────────────┼──────────────────────────────┘
                                               │ M365 Agents SDK (CopilotClient)
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

## How It Differs from Other Approaches

| Aspect | Direct Line | Interactive Flow | **Client Credentials (this)** |
|--------|-------------|-----------------|-------------------------------|
| **SDK** | Direct Line REST API | CopilotClient | **CopilotClient** |
| **Auth** | Shared secret | User-delegated (interactive) | **App-only (client credentials)** |
| **User required** | No | Yes (browser sign-in) | **No** |
| **Permission type** | N/A | Delegated | **Application** |
| **MSAL client** | N/A | PublicClientApplication | **ConfidentialClientApplication** |
| **Best for** | Simple backend | CLI/desktop apps | **Backend services, hosted agents** |

## Prerequisites

1. **Copilot Studio Weather Agent** deployed and published
2. **Azure AD App Registration** with:
   - **Application permission** (not Delegated) for `CopilotStudio.Copilots.Invoke` on Power Platform API
   - **Admin consent** granted for the permission
   - **Client secret** (or certificate) configured

## Azure AD App Registration Setup

1. Open [Azure Portal](https://portal.azure.com) > **Entra ID** > **App registrations**
2. Create a new registration (or use existing):
   - Name: e.g., `weather-proxy-client-credentials`
   - Supported account types: "Accounts in this organization directory only"
3. Go to **API Permissions** > **Add a permission**:
   - Select **APIs my organization uses** > search for **Power Platform API**
   - Select **Application permissions** (not Delegated)
   - Check **CopilotStudio** > **CopilotStudio.Copilots.Invoke**
   - Click **Add permissions**
4. Click **Grant admin consent** (requires admin role)
5. Go to **Certificates & secrets** > **New client secret**:
   - Add a description, set expiry
   - Copy the secret **Value** (not the Secret ID)
6. Note down from **Overview**:
   - Application (client) ID
   - Directory (tenant) ID

## Environment Variables

Create a `.env` file:

```bash
COPILOTSTUDIOAGENT__TENANTID=""           # Azure AD Tenant ID
COPILOTSTUDIOAGENT__AGENTAPPID=""         # App Registration Client ID
COPILOTSTUDIOAGENT__AGENTAPPSECRET=""     # App Registration Client Secret
COPILOTSTUDIOAGENT__ENVIRONMENTID=""      # Power Platform Environment ID (from Copilot Studio > Settings > Advanced > Metadata)
COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME="" # Agent Schema Name (from Copilot Studio > Settings > Advanced > Metadata)
```

## 1. Local Test (Console Client)

Test the client credentials flow interactively before deploying as a hosted agent.

### Install Dependencies

```bash
cd interoperability/foundry/agents/weather/weather_proxy_m365_agent_sdk_client_credentials_flow

uv venv
# Linux/macOS: source .venv/bin/activate
# Windows: .\.venv\Scripts\Activate.ps1

uv pip install --prerelease=allow -r requirements.txt
```

### Run Console Client

```bash
python -m src.main
```

This will:
1. Acquire an app-only token (no browser popup)
2. Connect to the Copilot Studio Weather Agent
3. Open an interactive console for testing queries

### Example Session

```
INFO:__main__:Token acquired successfully via client credentials flow

Suggested Actions:
Hello! I can help you with weather information.

>>>: Get weather for Paris, France from 2025-06-15 to 2025-06-20

{"location": "Paris, France", "start_date": "2025-06-15", ...}
```

## 2. Local Run (Hosted Agent Server)

Run the hosted agent server locally for integration testing.

```bash
# From project root
cd interoperability/foundry/agents/weather/weather_proxy_m365_agent_sdk_client_credentials_flow
uv venv
# Activate venv...
uv pip install --prerelease=allow -r requirements.txt

# Run from project root
cd ../../../../..
python interoperability/foundry/agents/weather/weather_proxy_m365_agent_sdk_client_credentials_flow/main.py
```

Test with curl:

```bash
curl -X POST http://localhost:8088/responses \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "messages": [
        {
          "role": "user",
          "content": "Get weather for location: Paris, France, start_date: 2025-06-15, end_date: 2025-06-20"
        }
      ]
    }
  }'
```

## 3. Docker Deploy

Use `latest` for local validation, and a pinned tag for deployment/rollback.

```bash
# Example values (replace as needed)
IMAGE_REPO=<your-azure-container-registry-repo> e.g.travelplannerdev-xxxxx.azurecr.io/weather-proxy-m365sdk
IMAGE_TAG=<your-image-tag> e.g.2026-02-20-a1b2c3
```

```powershell
# Example values (replace as needed)
$IMAGE_REPO = "<your-azure-container-registry-repo>"  # e.g. travelplannerdev-xxxxx.azurecr.io/weather-proxy-m365sdk
$IMAGE_TAG = "<your-image-tag>"                        # e.g. 2026-02-20-a1b2c3
```

Best practice for `IMAGE_TAG`:
- Format: `YYYY-MM-DD-<git-sha12>` (UTC date + 12-char commit hash), e.g. `2026-02-20-3f8c1a9b7d2e`
- Use `:latest` only for local runs; use `:$IMAGE_TAG` in `WEATHER_PROXY_IMAGE` for deployment

```bash
# Bash
IMAGE_TAG="$(date -u +%F)-$(git rev-parse --short=12 HEAD)"
```

```powershell
# PowerShell
$IMAGE_TAG = "$(Get-Date -AsUTC -Format yyyy-MM-dd)-$(git rev-parse --short=12 HEAD)"
```

### Build

```bash
# From project root
docker build -t weather-proxy-m365sdk:latest \
  -f interoperability/foundry/agents/weather/weather_proxy_m365_agent_sdk_client_credentials_flow/Dockerfile .
```

### Run Locally with Docker

```bash
# Using .env file
docker run -p 8088:8088 --env-file .env weather-proxy-m365sdk:latest

# Or passing env vars directly
docker run -p 8088:8088 \
  -e COPILOTSTUDIOAGENT__TENANTID=your-tenant-id \
  -e COPILOTSTUDIOAGENT__AGENTAPPID=your-client-id \
  -e COPILOTSTUDIOAGENT__AGENTAPPSECRET=your-client-secret \
  -e COPILOTSTUDIOAGENT__ENVIRONMENTID=your-environment-id \
  -e COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME=your-schema-name \
  weather-proxy-m365sdk:latest
```

### Push to Azure Container Registry

```bash
# Login to ACR
az acr login --name travelplannerdev

# Tag for ACR (`latest` for convenience + pinned tag for deployment)
docker tag weather-proxy-m365sdk:latest $IMAGE_REPO:latest
docker tag weather-proxy-m365sdk:latest $IMAGE_REPO:$IMAGE_TAG

# Push to ACR
docker push $IMAGE_REPO:latest
docker push $IMAGE_REPO:$IMAGE_TAG
```

```powershell
# Login to ACR
az acr login --name travelplannerdev

# Tag for ACR (`latest` for convenience + pinned tag for deployment)
docker tag weather-proxy-m365sdk:latest ${IMAGE_REPO}:latest
docker tag weather-proxy-m365sdk:latest ${IMAGE_REPO}:${IMAGE_TAG}

# Push to ACR
docker push ${IMAGE_REPO}:latest
docker push ${IMAGE_REPO}:${IMAGE_TAG}
```

### Deploy to Azure AI Foundry

1. **Add deployment variables to `.env`** (deploy.py loads `.env` and agent.yaml uses `${...}` substitution):

```bash
# Container image
WEATHER_PROXY_IMAGE=travelplannerdev-xxxxx.azurecr.io/weather-proxy-m365sdk:2026-02-20-a1b2c3

# Client credentials (from Azure AD App Registration)
COPILOTSTUDIOAGENT__TENANTID=your-tenant-id
COPILOTSTUDIOAGENT__AGENTAPPID=your-client-id
COPILOTSTUDIOAGENT__AGENTAPPSECRET=your-client-secret

# Copilot Studio agent metadata
COPILOTSTUDIOAGENT__ENVIRONMENTID=your-environment-id
COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME=your-schema-name
```

> **Production: Use Azure Key Vault**
>
> For production deployments, avoid passing secrets as environment variables. Instead, use Key Vault references in `agent.yaml`:
> ```yaml
> environment:
>   COPILOTSTUDIOAGENT__AGENTAPPSECRET: "@Microsoft.KeyVault(SecretUri=https://your-vault.vault.azure.net/secrets/agent-app-secret)"
> ```

2. **Deploy using deploy.py**:

```bash
# Dry run first
uv run python -m interoperability.foundry.deploy --dry-run --agent weather-proxy

# Actual deployment
uv run python -m interoperability.foundry.deploy --deploy --agent weather-proxy
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `AADSTS7000215: Invalid client secret` | Regenerate secret in Azure Portal; ensure you copied the **Value**, not the Secret ID |
| `AADSTS700016: Application not found` | Check `COPILOTSTUDIOAGENT__AGENTAPPID` matches the App Registration Client ID |
| `AADSTS65001: The user or administrator has not consented` | Grant admin consent for the Application permission in Azure Portal |
| `Token acquisition failed: invalid_scope` | Ensure Power Platform API is available in your tenant (see README of interactive flow) |
| `Failed to start conversation` | Verify `ENVIRONMENTID` and `SCHEMANAME` are correct; ensure agent is published |
