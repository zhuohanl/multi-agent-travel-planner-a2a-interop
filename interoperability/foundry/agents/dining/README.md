## Run locally

Note that running locally might require setting up a sub-folder virtual env. `azure-ai-agentserver-langgraph==1.0.0b10` required by this langgraph agent "dining" is not compatible with "azure-ai-projects>=2.0.0b2" which is a required lib at the whole repo level.

Create a dedicated venv under `interoperability/foundry/agents/dining`:
```PowerShell
cd interoperability\foundry\agents\dining
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Activate the virtual env:
```PowerShell
.venv\Scripts\Activate.ps1
```

Run the main.py:
```
python main.py
```

Logs are written to `interoperability/foundry/agents/dining/logs/` with a timestamped filename.

To test, try these HTTP requests:
```
@baseUrl = http://localhost:8088


POST {{baseUrl}}/responses
Content-Type: application/json

{
  "input": [
    {
      "role": "user",
      "content": "{\"mode\":\"qa\",\"question\":\"What's the dress code at Sukiyabashi Jiro?\",\"context\":{\"destination\":\"Tokyo\"}}"
    }
  ]
}
```
OR
```
@baseUrl = http://localhost:8088


POST {{baseUrl}}/responses
Content-Type: application/json

{
  "input": [
    { "role": "user", "content": "Find great vegetarian ramen in Tokyo." }
  ]
}
```

## Create a hosted agent by using the Foundry SDK

Follow [Create a hosted agent by using the Foundry SDK](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/concepts/hosted-agents?view=foundry#create-a-hosted-agent-by-using-the-foundry-sdk).

### Required environment variables for deployment

Set these before running `deploy.py` (for example in `.env`):

- `AZURE_AI_PROJECT_ENDPOINT` (or `PROJECT_ENDPOINT`)
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_DEPLOYMENT_NAME`
- `AZURE_OPENAI_API_VERSION`
- `BING_PROJECT_CONNECTION_ID`
- `DINING_AGENT_IMAGE` (note: this can be added after you build and push the container image according to the process below)

### Build and push the container image

Make sure you run below from the root of the repo.
Use `latest` for local validation, and a pinned tag for deployment/rollback.

```bash
# Example values (replace as needed)
IMAGE_REPO=<your-azure-container-registry-repo> e.g.travelplannerdev-xxxxx.azurecr.io/dining-agent
IMAGE_TAG=<your-image-tag> e.g.2026-02-20-a1b2c3
```

```powershell
# Example values (replace as needed)
$IMAGE_REPO = "<your-azure-container-registry-repo>"  # e.g. travelplannerdev-xxxxx.azurecr.io/dining-agent
$IMAGE_TAG = "<your-image-tag>"                        # e.g. 2026-02-20-a1b2c3
```

Best practice for `IMAGE_TAG`:
- Format: `YYYY-MM-DD-<git-sha12>` (UTC date + 12-char commit hash), e.g. `2026-02-20-3f8c1a9b7d2e`
- Use `:latest` only for local runs; use `:$IMAGE_TAG` in `DINING_AGENT_IMAGE` for deployment

```bash
# Bash
IMAGE_TAG="$(date -u +%F)-$(git rev-parse --short=12 HEAD)"
```

```powershell
# PowerShell
$IMAGE_TAG = "$(Get-Date -AsUTC -Format yyyy-MM-dd)-$(git rev-parse --short=12 HEAD)"
```

1. Build container (must be linux/amd64):

If you're already on a linux/amd64 machine, a normal `docker build` is fine:
```
docker build -t dining-agent:latest -f interoperability/foundry/agents/dining/Dockerfile .
```

If you are on Apple Silicon or other ARM64 machines:
```
docker buildx build --platform linux/amd64 -t dining-agent:latest -f interoperability/foundry/agents/dining/Dockerfile . --load
```

**Important:** [Images built on Apple Silicon or other ARM64 machines do not work for the hosted agent](https://github.com/microsoft-foundry/foundry-samples/blob/main/samples/python/hosted-agents/agent-framework/web-search-agent/README.md#troubleshooting)

2. Sign into Azure Container Registry:
```
az acr login --name travelplannerdev
```

3. Tag image for the registry (`latest` for convenience + pinned tag for deployment):
```
docker tag dining-agent:latest $IMAGE_REPO:latest
docker tag dining-agent:latest $IMAGE_REPO:$IMAGE_TAG
```

```powershell
# PowerShell
az acr login --name travelplannerdev
docker tag dining-agent:latest ${IMAGE_REPO}:latest
docker tag dining-agent:latest ${IMAGE_REPO}:${IMAGE_TAG}
```

4. Push the images to Azure Container Registry:
```
docker push $IMAGE_REPO:latest
docker push $IMAGE_REPO:$IMAGE_TAG
```

```powershell
# PowerShell
docker push ${IMAGE_REPO}:latest
docker push ${IMAGE_REPO}:${IMAGE_TAG}
```

5. If this have not been done before, follow this to [Configure Azure Container Registry permissions](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/concepts/hosted-agents?view=foundry#create-a-hosted-agent-by-using-the-foundry-sdk)

6. If this have not been done before, create an account-level capability host:
```
az rest --method put --url "https://management.azure.com//subscriptions/7b687301-2a67-4579-ae2d-b3b1df9ab21b/resourceGroups/rg-foundry/providers/Microsoft.CognitiveServices/accounts/foundry-resource-20260112/capabilityHosts/accountcaphost?api-version=2025-10-01-preview" --headers "content-type=application/json" --body '{
        "properties": {
            "capabilityHostKind": "Agents",
            "enablePublicHostingEnvironment": true
        }
    }'
```

### Deploy the hosted agent

7. Update `.env`:
```
DINING_AGENT_IMAGE=travelplannerdev-xxxxx.azurecr.io/dining-agent:2026-02-20-a1b2c3
```

8. Create the hosted agent version:
```
uv run python interoperability/foundry/deploy.py --deploy --agent dining
```
OR
```PowerShell
uv run python -m interoperability.foundry.deploy --deploy --agent dining
```


## Troubleshooting

```
curl -N "https://foundry-resource-20260112.services.ai.azure.com/api/projects/proj-20260112/agents/dining/versions/5/containers/default:logstream?kind=console&tail=500&api-version=2025-11-15-preview" `
  -H "Authorization: Bearer $(az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv)"
```
