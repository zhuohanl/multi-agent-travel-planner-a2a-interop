
## Run locally

```
uv run python interoperability/foundry/agents/stay/main.py
``` 

To test, try below http requests:
```
@baseUrl = http://localhost:8088


POST {{baseUrl}}/responses
Content-Type: application/json

{
  "input": [
    {
      "role": "user",
      "content": "{\"mode\":\"qa\",\"question\":\"Does the Park Hyatt Tokyo have a pool?\",\"context\":{\"destination\":\"Tokyo\"}}"
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
    { "role": "user", "content": "Best neighborhoods in Tokyo for tourists" }
  ]
}
```

## Create a hosted agent by using the Foundry SDK

Follow [Create a hosted agent by using the Foundry SDK](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/concepts/hosted-agents?view=foundry#create-a-hosted-agent-by-using-the-foundry-sdk).

Use `latest` for local validation, and a pinned tag for deployment/rollback.

```bash
# Example values (replace as needed)
IMAGE_REPO=<your-azure-container-registry-repo> e.g.travelplannerdev-xxxxx.azurecr.io/stay-agent
IMAGE_TAG=<your-image-tag> e.g.2026-02-20-a1b2c3
```

```powershell
# Example values (replace as needed)
$IMAGE_REPO = "<your-azure-container-registry-repo>"  # e.g. travelplannerdev-xxxxx.azurecr.io/stay-agent
$IMAGE_TAG = "<your-image-tag>"                        # e.g. 2026-02-20-a1b2c3
```

Best practice for `IMAGE_TAG`:
- Format: `YYYY-MM-DD-<git-sha12>` (UTC date + 12-char commit hash), e.g. `2026-02-20-3f8c1a9b7d2e`
- Use `:latest` only for local runs; use `:$IMAGE_TAG` in `STAY_AGENT_IMAGE` for deployment

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
docker build -t stay-agent:latest -f interoperability/foundry/agents/stay/Dockerfile .
```

If you are on Apple Silicon or other ARM64 machines:
```
docker buildx build --platform linux/amd64 -t stay-agent:latest -f interoperability/foundry/agents/stay/Dockerfile . --load
```

**Important:** [Images built on Apple Silicon or other ARM64 machines do not work for the hosted agent](https://github.com/microsoft-foundry/foundry-samples/blob/main/samples/python/hosted-agents/agent-framework/web-search-agent/README.md#troubleshooting)

2. Sign into Azure Container Registry:
```
az acr login --name travelplannerdev
```

3. Tag image for the registry (`latest` for convenience + pinned tag for deployment):
```
docker tag stay-agent:latest $IMAGE_REPO:latest
docker tag stay-agent:latest $IMAGE_REPO:$IMAGE_TAG
```

```powershell
# PowerShell
az acr login --name travelplannerdev
docker tag stay-agent:latest ${IMAGE_REPO}:latest
docker tag stay-agent:latest ${IMAGE_REPO}:${IMAGE_TAG}
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

5. Follow this to [Configure Azure Container Registry permissions](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/concepts/hosted-agents?view=foundry#create-a-hosted-agent-by-using-the-foundry-sdk)

6. Create an account-level capability host following this [Create an account-level capability host](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/concepts/hosted-agents?view=foundry#create-an-account-level-capability-host)

7. Update `.env`:
```
STAY_AGENT_IMAGE=travelplannerdev-xxxxx.azurecr.io/stay-agent:2026-02-20-a1b2c3
```

8. Create the hosted agent version:
```
uv run python interoperability/foundry/deploy.py --deploy --agent stay
```
