### Docker Authentication (Azure OpenAI)

When running locally (outside Docker), `DefaultAzureCredential` picks up your `az login` session automatically via `AzureCliCredential`. Inside a Docker container, this fails because the container has no Azure CLI installed and no access to the host's credential cache.

This section documents the three approaches we evaluated, why the first two failed, and how to set up the working solution (service principal).

#### Option A: API Key fallback — does NOT work

We added code in `chat_services.py` to read `AZURE_OPENAI_API_KEY` from the environment and use API key auth when set, falling back to `DefaultAzureCredential` otherwise. This was the simplest fix — just set a key in `.env` and the container would authenticate without any identity chain.

**Why it failed:** Our Azure OpenAI resource (`foundry-resource-20260112`) has `disableLocalAuth: true`, which is an Azure-level policy that rejects all API key authentication. This is a security best practice for production resources — it ensures only Entra ID (identity-based) auth is accepted.

We confirmed this by running:
```shell
az cognitiveservices account keys list \
  --name foundry-resource-20260112 \
  --resource-group rg-foundry
# ERROR: Failed to list key. disableLocalAuth is set to be true
```

The API key fallback code remains in `chat_services.py` for environments where `disableLocalAuth` is `false`, but it cannot work with our current resource.

#### Option B: Mount host `~/.azure` into container — does NOT work

We added a read-only volume mount in `docker-compose.demo.yml` to share the host's Azure CLI credentials with the container:

```yaml
volumes:
  - ${HOME}/.azure:/root/.azure:ro
```

**Why it failed:** Two reasons:
1. **`AzureCliCredential` needs the `az` binary**, not just the config files. It runs `az account get-access-token` as a subprocess — without the CLI installed in the container, it reports "Azure CLI not found on path".
2. **`SharedTokenCacheCredential` cannot decrypt the Windows MSAL cache.** On Windows, the token cache (`msal_token_cache.bin`) is encrypted using DPAPI (Data Protection API). A Linux container cannot decrypt DPAPI-protected data, so it reports "No accounts were found in the cache".

Installing the full Azure CLI in the container (~700MB+) would fix issue 1, but is impractical for a slim demo image.

#### Option C: Service Principal (current solution)

This is the industry best practice: a dedicated identity with scoped permissions, an audit trail, and rotatable secrets. `DefaultAzureCredential` picks up the credentials automatically via `EnvironmentCredential` — no code changes needed.

**Prerequisites:**
- Azure CLI installed on your host: `az --version`
- Logged in: `az login`
- Correct subscription selected: `az account show`

**Step-by-step setup using `az` CLI:**

1. **Set shell variables** (adjust if your resource names differ):
   ```shell
   RESOURCE_GROUP="rg-foundry"
   COGNITIVE_ACCOUNT="foundry-resource-20260112"
   SP_NAME="sp-a2a-travel-planner-docker"
   ```

2. **Get the resource ID of your Azure OpenAI resource:**
   ```shell
   RESOURCE_ID=$(az cognitiveservices account show \
     --name "$COGNITIVE_ACCOUNT" \
     --resource-group "$RESOURCE_GROUP" \
     --query id -o tsv)
   echo "$RESOURCE_ID"
   ```

3. **Create a service principal with the "Cognitive Services OpenAI User" role scoped to that resource:**
   ```shell
   az ad sp create-for-rbac \
     --name "$SP_NAME" \
     --role "Cognitive Services OpenAI User" \
     --scopes "$RESOURCE_ID"
   ```
   This outputs JSON with `appId`, `password`, and `tenant`. **Save these values** — the password is only shown once.

   Example output:
   ```json
   {
     "appId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
     "displayName": "sp-a2a-travel-planner-docker",
     "password": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
     "tenant": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
   }
   ```

   > **Git Bash on Windows pitfall:** Git Bash auto-converts arguments starting with `/` to Windows paths (e.g., `/subscriptions/...` becomes `C:/Program Files/Git/subscriptions/...`), causing a `MissingSubscription` error. To prevent this, prefix the command with `MSYS_NO_PATHCONV=1`:
   > ```shell
   > MSYS_NO_PATHCONV=1 az ad sp create-for-rbac \
   >   --name "$SP_NAME" \
   >   --role "Cognitive Services OpenAI User" \
   >   --scopes "$RESOURCE_ID"
   > ```

   > **Stale token error:** If you get `TokenCreatedWithOutdatedPolicies`, re-run `az login` before retrying.

4. **Add the credentials to your `.env` file** (at the repo root):
   ```shell
   # Map the output values:
   #   tenant  → AZURE_TENANT_ID
   #   appId   → AZURE_CLIENT_ID
   #   password → AZURE_CLIENT_SECRET
   AZURE_TENANT_ID=<tenant>
   AZURE_CLIENT_ID=<appId>
   AZURE_CLIENT_SECRET=<password>
   ```

5. **Verify the credentials work** (optional, from host):
   ```shell
   az login --service-principal \
     -u <appId> \
     -p <password> \
     --tenant <tenant>

   az account get-access-token \
     --resource https://cognitiveservices.azure.com
   ```
   If this returns a token, the service principal is correctly configured. Log back in as yourself afterwards:
   ```shell
   az login
   ```

6. **Rebuild and run Docker:**
   ```shell
   docker compose -f src/deploy/docker-compose.demo.yml up --build
   ```
   `DefaultAzureCredential` inside the container will find `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, and `AZURE_CLIENT_SECRET` via `EnvironmentCredential` and authenticate automatically.

**Security notes:**
- The service principal has **only** the "Cognitive Services OpenAI User" role on the specific Azure OpenAI resource — it cannot access anything else.
- Never commit `.env` to git (it is in `.gitignore`).
- Rotate the secret periodically: `az ad sp credential reset --id <appId>`.
- For CI/CD, store the three values in your pipeline's secret store (GitHub Actions secrets, Azure Key Vault, etc.) instead of `.env`.

#### Summary

| Approach | Works with `disableLocalAuth=true`? | Status | Why |
|----------|--------------------------------------|--------|-----|
| A: API Key (`AZURE_OPENAI_API_KEY`) | No | Failed | Resource policy blocks key-based auth |
| B: Mount `~/.azure` volume | No | Failed | Container has no `az` binary; Windows DPAPI cache unreadable on Linux |
| C: Service Principal (env vars) | Yes | **Current** | Industry best practice — scoped, auditable, works everywhere |

#### What we actually ran (for reference)

The following commands were executed to set up Option C on this project:

```shell
# 1. Confirmed az login was active
az account show

# 2. Got the resource ID
az cognitiveservices account show \
  --name foundry-resource-20260112 \
  --resource-group rg-foundry \
  --query id -o tsv
# → /subscriptions/7b687301-.../Microsoft.CognitiveServices/accounts/foundry-resource-20260112

# 3. Created the service principal (MSYS_NO_PATHCONV=1 needed on Git Bash / Windows)
MSYS_NO_PATHCONV=1 az ad sp create-for-rbac \
  --name "sp-a2a-travel-planner-docker" \
  --role "Cognitive Services OpenAI User" \
  --scopes "/subscriptions/7b687301-2a67-4579-ae2d-b3b1df9ab21b/resourceGroups/rg-foundry/providers/Microsoft.CognitiveServices/accounts/foundry-resource-20260112"

# 4. Added AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET to .env

# 5. Rebuilt and started containers
docker compose -f src/deploy/docker-compose.demo.yml up --build
```

**Result:** `EnvironmentCredential` inside the container successfully authenticated using the service principal. Chat messages are processed end-to-end. Verified working on 2026-02-24.