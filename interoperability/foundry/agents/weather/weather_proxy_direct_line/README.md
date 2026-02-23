# Weather Proxy - Hosted Agent for Copilot Studio Integration

The Weather Proxy is a hosted agent that bridges Azure AI Foundry workflows to the Copilot Studio Weather Agent. It receives weather requests via the `/responses` protocol, calls the CS Weather Agent using the Direct Line API, and returns structured `WeatherResponse` data.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Azure AI Foundry                                      │
│  ┌─────────────────┐     ┌─────────────────────────────────────────────┐    │
│  │ Discovery       │     │ Weather Proxy (Hosted Agent)                │    │
│  │ Workflow        │────▶│                                             │    │
│  │                 │     │  1. Receive request via /responses          │    │
│  └─────────────────┘     │  2. Parse location, start_date, end_date    │    │
│                          │  3. Call CS Weather Agent via Direct Line   │    │
│                          │  4. Parse JSON response                     │    │
│                          │  5. Return WeatherResponse                  │    │
│                          └──────────────────┬──────────────────────────┘    │
└─────────────────────────────────────────────┼───────────────────────────────┘
                                              │ Direct Line API
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

## Prerequisites

1. **Copilot Studio Weather Agent** - Deploy the Weather agent following [Weather Agent README](../../../../copilot_studio/agents/weather/README.md)

2. **Direct Line Secret** - Get the secret from Copilot Studio (see [Environment Variables](#environment-variables) section)

## Environment Variables

Create a `.env` file in the project root or set this environment variable:

```bash
# Direct Line secret from Copilot Studio Web channel security
COPILOTSTUDIOAGENT__DIRECTLINE_SECRET=your-direct-line-secret
```

### Finding the Direct Line Secret

1. Open **Copilot Studio** and select your Weather Agent
2. Go to **Settings** > **Security** > **Web channel security**
3. Copy **Secret 1** or **Secret 2**
4. Add it to your `.env` file as `COPILOTSTUDIOAGENT__DIRECTLINE_SECRET`

### Why Direct Line vs CopilotClient?

There are two ways to call Copilot Studio agents programmatically:

| Aspect | CopilotClient SDK | Direct Line API |
|--------|-------------------|-----------------|
| **Auth type** | User-delegated (interactive login) | App secret (no user needed) |
| **Best for** | Desktop/CLI apps with users | Backend services, hosted agents |
| **Setup** | Azure AD App + API permissions | Just copy secret from Copilot Studio |
| **Token** | Short-lived, requires user | Long-lived secret |

**CopilotClient** (from `microsoft-agents-copilotstudio-client`) is a Python SDK that requires user-delegated permissions via Azure AD. It uses `PublicClientApplication` with interactive login where a user signs in via browser. This works great for CLI tools and desktop apps, but **not for hosted agents** that run without user interaction.

**Direct Line API** is a REST API provided by Bot Framework for server-to-server communication. It uses a secret key from Copilot Studio's "Web channel security" - no user identity required. This is the right choice for the Weather Proxy because it's a hosted agent running in Azure AI Foundry without user interaction.

## 1. Local Run

### Install Dependencies

Create a local virtual environment for the Weather Proxy (separate from the root project):

**Linux/macOS:**

```bash
# Navigate to weather_proxy_direct_line directory
cd interoperability/foundry/agents/weather/weather_proxy_direct_line

# Create and activate virtual environment
uv venv
source .venv/bin/activate

# Install dependencies (--prerelease=allow needed for azure-ai-agentserver-core)
uv pip install --prerelease=allow -r requirements.txt
```

**Windows PowerShell:**

```powershell
# Navigate to weather_proxy_direct_line directory
cd interoperability/foundry/agents/weather/weather_proxy_direct_line

# Create and activate virtual environment
uv venv
.\.venv\Scripts\Activate.ps1

# Install dependencies (--prerelease=allow needed for azure-ai-agentserver-core)
uv pip install --prerelease=allow -r requirements.txt
```

To activate the virtual environment in future sessions:

```bash
# Linux/macOS
cd interoperability/foundry/agents/weather/weather_proxy_direct_line
source .venv/bin/activate
```

```powershell
# Windows PowerShell
cd interoperability/foundry/agents/weather/weather_proxy_direct_line
.\.venv\Scripts\Activate.ps1
```

### Run the Server

Ensure environment variables are set (see [Environment Variables](#environment-variables) section), then run from project root:

**Linux/macOS:**

```bash
# Activate venv if not already active
cd interoperability/foundry/agents/weather/weather_proxy_direct_line
source .venv/bin/activate

# Run from project root
cd ../../../../..
python interoperability/foundry/agents/weather/weather_proxy_direct_line/main.py
```

**Windows PowerShell:**

```powershell
# Activate venv if not already active
cd interoperability/foundry/agents/weather/weather_proxy_direct_line
.\.venv\Scripts\Activate.ps1

# Run from project root as a module
cd ../../../../..
python -m interoperability.foundry.agents.weather.weather_proxy_direct_line.main
```

The server starts on port 8088 by default. You can override with `PORT` environment variable:

```bash
# Linux/macOS
PORT=8080 python interoperability/foundry/agents/weather/weather_proxy_direct_line/main.py
```

```powershell
# Windows PowerShell
$env:PORT = "8080"
python -m interoperability.foundry.agents.weather.weather_proxy_direct_line.main
```

### Test the Endpoint

```bash
# Text format request
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

# JSON format request
curl -X POST http://localhost:8088/responses \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "messages": [
        {
          "role": "user",
          "content": "{\"location\": \"Tokyo, Japan\", \"start_date\": \"2025-07-01\", \"end_date\": \"2025-07-10\"}"
        }
      ]
    }
  }'
```

### Expected Response

```json
{
  "response": {
    "location": "Paris, France",
    "start_date": "2025-06-15",
    "end_date": "2025-06-20",
    "climate_summary": {
      "average_high_temp_c": 24.0,
      "average_low_temp_c": 14.0,
      "average_precipitation_chance": 25,
      "typical_conditions": "Mostly sunny with occasional afternoon clouds"
    },
    "summary": "June in Paris is typically warm and pleasant with long sunny days."
  }
}
```

## 2. Local Testing

### Run Unit Tests

```bash
# From project root
uv run pytest tests/unit/interoperability/foundry/test_weather_proxy.py -v
```

### Test Coverage

The unit tests cover:

| Test Class | Description |
|------------|-------------|
| `TestWeatherProxyYaml` | Validates agent.yaml structure, env vars, protocol config |
| `TestWeatherProxyRequirements` | Verifies required packages in requirements.txt |
| `TestWeatherProxyDockerfile` | Checks Dockerfile base image, copies, port exposure |
| `TestWeatherProxyImportsSharedSchemas` | Ensures WeatherResponse is from src/shared/models.py |
| `TestWeatherProxyExtractUserMessage` | Tests user message extraction from request payload formats |
| `TestWeatherProxyParsesResponseSchema` | Tests JSON extraction from various response formats |
| `TestWeatherProxyCallsAgent` | Verifies `call_weather_agent` signature and async behavior |
| `TestWeatherProxyConfigYaml` | Validates integration with foundry/config.yaml |

### Run All Tests

```bash
# All Weather Proxy tests
uv run pytest tests/unit/interoperability/foundry/test_weather_proxy.py -v

# All Foundry tests
uv run pytest tests/unit/interoperability/foundry/ -v

# All interoperability tests
uv run pytest tests/unit/interoperability/ -v
```

### Test Request Parsing

```python
# Quick tests of helper parsing functions
from interoperability.foundry.agents.weather.weather_proxy_direct_line.main import (
    extract_user_message,
    extract_json_from_response,
)

# Message extraction from string content
messages = [{"role": "user", "content": "Get weather for Paris, France"}]
print(extract_user_message(messages))  # "Get weather for Paris, France"

# JSON extraction from markdown response
response_text = "```json\n{\"location\":\"Tokyo\",\"summary\":\"Warm\"}\n```"
print(extract_json_from_response(response_text))  # {'location': 'Tokyo', 'summary': 'Warm'}
```

## 3. Docker Deploy

Use `latest` for local validation, and a pinned tag for deployment/rollback.

```bash
# Example values (replace as needed)
IMAGE_REPO=<your-azure-container-registry-repo> e.g.travelplannerdev-xxxxx.azurecr.io/weather-proxy
IMAGE_TAG=<your-image-tag> e.g.2026-02-20-a1b2c3
```

```powershell
# Example values (replace as needed)
$IMAGE_REPO = "<your-azure-container-registry-repo>"  # e.g. travelplannerdev-xxxxx.azurecr.io/weather-proxy
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

### Build the Image

```bash
# From project root (required for COPY src/ to work)
docker build -t weather-proxy:latest -f interoperability/foundry/agents/weather/weather_proxy_direct_line/Dockerfile .
```

### Run Locally with Docker

```bash
# Using .env file
docker run -p 8088:8088 --env-file .env weather-proxy:latest

# Or passing env vars directly
docker run -p 8088:8088 \
  -e COPILOTSTUDIOAGENT__DIRECTLINE_SECRET=your-direct-line-secret \
  weather-proxy:latest
```

### Push to Azure Container Registry

```bash
# Login to ACR
az acr login --name travelplannerdev

# Tag for ACR (`latest` for convenience + pinned tag for deployment)
docker tag weather-proxy:latest $IMAGE_REPO:latest
docker tag weather-proxy:latest $IMAGE_REPO:$IMAGE_TAG

# Push to ACR
docker push $IMAGE_REPO:latest
docker push $IMAGE_REPO:$IMAGE_TAG
```

```powershell
# Login to ACR
az acr login --name travelplannerdev

# Tag for ACR (`latest` for convenience + pinned tag for deployment)
docker tag weather-proxy:latest ${IMAGE_REPO}:latest
docker tag weather-proxy:latest ${IMAGE_REPO}:${IMAGE_TAG}

# Push to ACR
docker push ${IMAGE_REPO}:latest
docker push ${IMAGE_REPO}:${IMAGE_TAG}
```

### Deploy to Azure AI Foundry

1. **Add deployment variables to `.env`** (deploy.py loads `.env` and agent.yaml uses `${...}` substitution):

```bash
# Container image
WEATHER_PROXY_IMAGE=travelplannerdev-xxxxx.azurecr.io/weather-proxy:2026-02-20-a1b2c3

# Direct Line secret (from Copilot Studio > Settings > Security > Web channel security)
COPILOTSTUDIOAGENT__DIRECTLINE_SECRET=your-direct-line-secret
```

> **Production: Use Azure Key Vault**
>
> For production deployments, avoid passing secrets as environment variables. Instead, use Key Vault references in `agent.yaml`:
> ```yaml
> environment:
>   COPILOTSTUDIOAGENT__DIRECTLINE_SECRET: "@Microsoft.KeyVault(SecretUri=https://your-vault.vault.azure.net/secrets/directline-secret)"
> ```
> This way, Foundry resolves the secret at runtime from Key Vault, and the secret is never stored in the image or deployment config.

2. **Deploy using deploy.py**:

```bash
# Dry run first
uv run python interoperability/foundry/deploy.py --dry-run --agent weather-proxy

# Actual deployment
uv run python interoperability/foundry/deploy.py --deploy --agent weather-proxy
```
OR
```PowerShell
uv run python -m interoperability.foundry.deploy --deploy --agent weather-proxy
```

### Verify Deployment

```bash
# Check agent status in Foundry
az ai agent show --name weather-proxy --project your-project-name

# Test via Foundry API
curl -X POST "https://your-foundry-endpoint/api/responses" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "weather-proxy",
    "input": {
      "messages": [{"role": "user", "content": "location: Paris, start_date: 2025-06-15, end_date: 2025-06-20"}]
    }
  }'
```

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError: No module named 'src'` | Run from project root, ensure PYTHONPATH=/app in Docker |
| `Failed to start conversation: 403` | Check Direct Line secret is valid; regenerate in Copilot Studio if needed |
| `IntegratedAuthenticationNotSupportedInChannel` | Set Copilot Studio agent authentication to "No authentication" and republish |
| `Usage limit reached` | Wait for quota reset or check your Copilot Studio plan |
| `Could not extract JSON from response` | Weather Agent may not be returning structured JSON; check agent instructions |
| `Missing required parameter: location` | Ensure request message contains `location:` or valid JSON |

### Debug Logging

Enable debug logging:

```bash
LOG_LEVEL=DEBUG python interoperability/foundry/agents/weather/weather_proxy_direct_line/main.py
```

### Check Environment Variables

```python
import os
print(f"DIRECTLINE_SECRET: {'SET' if os.getenv('COPILOTSTUDIOAGENT__DIRECTLINE_SECRET') else 'NOT SET'}")
```

### Check Hosted Agent logs
```
curl -N "https://{endpoint}/api/projects/{projectName}/agents/{agentName}/versions/{agentVersion}/containers/default:logstream?kind=console&tail=500&api-version=2025-11-15-preview" \
  -H "Authorization: Bearer $(az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv)"
```

## Related Documentation

- [Weather Agent README](../../../../copilot_studio/agents/weather/README.md) - Copilot Studio Weather Agent setup
- [SETUP.md](../../../../copilot_studio/SETUP.md) - Azure AD App Registration and environment setup
- [Design Doc](../../../../../docs/interoperability-design.md) - INTEROP-011B implementation details
- [Foundry Config](../../../config.yaml) - Agent configuration
- [Approach Comparison](../README.md) - Comparison of all three integration approaches
