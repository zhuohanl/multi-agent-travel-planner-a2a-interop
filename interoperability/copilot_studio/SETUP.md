# Copilot Studio Setup Guide

This guide provides step-by-step instructions for manually creating the Copilot Studio agents used in the interoperability demos.

> **Important:** Copilot Studio is a no-code/low-code platform. Agents must be **created manually** via the Copilot Studio portal. There is no SDK to programmatically create agents. Once created, you can use the M365 Agents SDK to interact with them programmatically.

## Prerequisites

- Access to Microsoft Copilot Studio (https://copilotstudio.microsoft.com)
- Azure AD tenant with appropriate permissions
- Azure Key Vault for storing secrets (production) or local .env file (development)
- Python 3.10+ with the following packages installed:
  ```bash
  pip install microsoft-agents-copilotstudio-client  # v0.7.0+
  pip install microsoft-agents-authentication-msal   # For token acquisition
  ```

## Agents to Create

| Agent | Purpose | Used In |
|-------|---------|---------|
| Weather Agent | Provides weather forecasts for travel destinations | Demo A (called from Foundry), Demo C |
| Approval Agent | Human-in-the-loop approval for travel itineraries | Demo B (called from Pro Code) |
| Travel Planning Parent Agent | Routes travel questions to appropriate discovery agents | Demo C (entry point) |

---

## Step 1: Azure AD App Registration

Before creating agents, register the required Azure AD apps for cross-platform authentication.

### 1.1 Create interop-foundry-to-cs App

This app is used when Foundry calls Copilot Studio agents (Demo A).

1. Go to [Azure Portal](https://portal.azure.com) > **Azure Active Directory** > **App registrations**
2. Click **New registration**
3. Enter the following:
   - **Name:** `interop-foundry-to-cs`
   - **Supported account types:** Single tenant
   - **Redirect URI:** Leave blank
4. Click **Register**
5. Note the **Application (client) ID** - save this to your `.env` file as `COPILOTSTUDIOAGENT__AGENTAPPID` (see [Step 5: Environment Variables](#step-5-environment-variables))

**Configure API Permissions:**
1. Go to **API permissions** > **Add a permission**
2. Select **APIs my organization uses** > search for **Power Platform API**
   > **Note:** If "Power Platform API" doesn't appear, follow [these steps](https://learn.microsoft.com/en-us/power-platform/admin/programmability-authentication-v2?tabs=powershell#step-2-configure-api-permissions) to register it in your tenant first.
3. Choose **Delegated permissions**
4. Select **`CopilotStudio.Copilots.Invoke`** (Invoke Copilots)
   > For a full list of available permissions, see the [Permission Reference](https://learn.microsoft.com/en-us/power-platform/admin/programmability-permission-reference).
5. Click **Add permissions**
6. Click **Grant admin consent for [your tenant]**

> **Note:** When acquiring tokens in your code, use the scope `https://api.powerplatform.com/.default`. This is a special OAuth 2.0 scope that requests all granted permissions for the resource.

**Create Client Secret:**
1. Go to **Certificates & secrets** > **New client secret**
2. Enter the following:
   - **Description:** `Foundry to Copilot Studio interop secret`
   - **Expires:** Choose an appropriate expiry (e.g., 6 months, 12 months, or 24 months)
3. Click **Add**
4. Copy the secret **Value** immediately (it won't be shown again)
5. Save the secret value:
   - **For local development:** Add to your `.env` file as `COPILOTSTUDIOAGENT__AGENTAPPSECRET`
   - **For production:** Store in Azure Key Vault as `interop-foundry-to-cs-secret`

---

## Step 2: Create Weather Agent

The Weather Agent provides climate summaries for travel destinations based on historical weather patterns. It's called from the Foundry Discovery Workflow (Demo A) and from Q&A Parent Agent (Demo C).

> **Detailed Guide:** See [`agents/weather/README.md`](agents/weather/README.md) for complete step-by-step instructions.

### Quick Summary

1. **Create the agent** in Copilot Studio with name `Weather Agent`
2. **Configure agent instructions** with the climate summary schema (no custom topics needed)
3. **Publish** and note the Schema Name

### Key Design Decisions

- **No custom topics** - The agent relies entirely on system instructions to handle requests
- **Climate summaries** - Returns historical climate patterns (avg temps, precipitation) rather than daily forecasts
- **Why?** Trip planning typically involves dates months in advance; real weather APIs only forecast 7-16 days

### Response Schema

```json
{
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
```

### After Publishing

Note the **Schema Name** and **Agent ID** from agent settings and set:
```bash
COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME="your-weather-agent-schema-name"
COPILOTSTUDIOAGENT__WEATHER__AGENTID="your-weather-agent-id"
```

---

## Step 3: Create Approval Agent

The Approval Agent handles human-in-the-loop approval for travel itineraries. It's called from the Pro Code Orchestrator (Demo B).

### 3.1 Create the Agent

1. Go to [Copilot Studio](https://copilotstudio.microsoft.com)
2. Click **Create** > **New agent**
3. Enter the following:
   - **Name:** `Approval Agent`
   - **Description:** `Human-in-the-loop approval for travel itineraries`
4. Click **Create**

### 3.2 Configure the "Request Approval" Topic

1. Go to **Topics** > **Create** > **From blank**
2. Set the topic name: `Request Approval`

**Add Trigger Phrases:**
```
review itinerary
approve this
review and approve
check this itinerary
approval needed
```

**Define the Conversation Flow:**

1. Add a **Message** node to display the itinerary:
   - Show the itinerary details passed in the request
   - Display trip destination, dates, and daily plans

2. Add a **Question** node for decision:
   - **Question text:** `Please review the itinerary above. What would you like to do?`
   - **Options:** (Multiple choice)
     - Approve as-is
     - Reject
     - Request modifications
   - **Save response as:** `decision` (variable)

3. Add a **Condition** node to branch on decision:

   **If "Approve as-is":**
   - Add a **Message** node: `Great! The itinerary has been approved.`
   - Add an **Event** node to emit `approval_decision`:
     ```json
     {
       "decision": "approved",
       "feedback": "Itinerary approved as submitted"
     }
     ```

   **If "Reject":**
   - Add a **Question** node: `Please provide a reason for rejection:`
   - Save response as `rejection_reason`
   - Add an **Event** node to emit `approval_decision`:
     ```json
     {
       "decision": "rejected",
       "feedback": "{rejection_reason}"
     }
     ```

   **If "Request modifications":**
   - Add a **Question** node: `What modifications would you like?`
   - Save response as `modification_request`
   - Add an **Event** node to emit `approval_decision`:
     ```json
     {
       "decision": "modify",
       "feedback": "{modification_request}"
     }
     ```

### 3.3 Configure the "Get Approval Status" Topic

This topic allows checking the status of a pending approval.

1. Go to **Topics** > **Create** > **From blank**
2. Set the topic name: `Get Approval Status`

**Add Trigger Phrases:**
```
approval status
check status
what's the decision
is it approved
```

**Define the Conversation Flow:**
1. Query the approval status from your data store
2. Return the current status and any feedback

### 3.4 Approval Decision Schema Reference

**Event Payload (emitted by agent):**
```json
{
  "decision": "approved" | "rejected" | "modify" | "pending",
  "feedback": "User's feedback or reason"
}
```

The Pro Code Orchestrator listens for the `approval_decision` event type.

### 3.5 Publish the Agent

1. Click **Publish**
2. Note the **Schema Name** for use in environment variables

---

## Step 4: Create Travel Planning Parent Agent

The Travel Planning Parent Agent routes travel questions to the appropriate discovery agents (Demo C). It uses Copilot Studio's [Add Agents](https://learn.microsoft.com/en-gb/microsoft-copilot-studio/add-agent-foundry-agent) feature to call Foundry agents via Microsoft Entra ID User Login (delegated auth) — no separate app registration is required.

> **Detailed Guide:** See [`agents/travel_planning_parent/README.md`](agents/travel_planning_parent/README.md) for complete step-by-step instructions with screenshots.

### Quick Summary

1. **Create the agent** in Copilot Studio with name `Travel Planning Parent Agent`
2. **Add Foundry agents** via the **Agents** section on the overview page:
   - Click **+ Add agent** > **Connect to an external agent** > **Microsoft Foundry**
   - Create a connection with your Azure AI Project Endpoint (one-time setup)
   - Add each Foundry agent by entering its **Name**, **Description**, and **Agent Id** (the agent's name from the Foundry portal)
3. **Add Weather Agent** as an internal agent from the environment
4. **Publish** and note the Environment ID and Schema Name

---

## Step 5: Environment Variables

Set up the required environment variables for the M365 Agents SDK to communicate with Copilot Studio agents.

### For Local Development (.env file)

Create a `.env` file in your project root:

```bash
# Azure AD Configuration
AZURE_TENANT_ID="your-azure-tenant-id"

# Foundry -> Copilot Studio (Demo A, Demo B)
COPILOTSTUDIOAGENT__TENANTID="your-azure-tenant-id"
COPILOTSTUDIOAGENT__AGENTAPPID="your-interop-foundry-to-cs-app-id"
COPILOTSTUDIOAGENT__AGENTAPPSECRET="your-client-secret"
COPILOTSTUDIOAGENT__ENVIRONMENTID="your-power-platform-environment-id"

# Weather Agent
COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME="weather-agent-schema-name"
COPILOTSTUDIOAGENT__WEATHER__AGENTID="weather-agent-id"

# Approval Agent
COPILOTSTUDIOAGENT__APPROVAL__SCHEMANAME="approval-agent-schema-name"

# Travel Planning Parent Agent
COPILOTSTUDIOAGENT__TRAVEL_PLANNING_PARENT__SCHEMANAME="travel-planning-parent-schema-name"
```

### For Production (Azure Key Vault)

Use Key Vault references for secrets:

```bash
COPILOTSTUDIOAGENT__AGENTAPPSECRET="@Microsoft.KeyVault(SecretUri=https://your-vault.vault.azure.net/secrets/interop-foundry-to-cs-secret)"
```

### Finding Environment ID and Schema Name

1. In Copilot Studio, go to **Settings** > **Agent details**
2. The **Environment ID** is shown in the URL: `https://copilotstudio.microsoft.com/environments/{environment-id}/...`
3. The **Schema Name** is listed under the agent's technical details (sometimes called "Schema name" or "Unique name")

---

## Verification

After creating all agents, run the verification script to confirm everything is configured correctly:

```bash
# From the project root
cd interoperability/copilot_studio
python verify.py

# For verbose output
python verify.py --verbose

# To skip network checks (offline mode)
python verify.py --offline
```

The verification script checks:
- Agent configurations in config.yaml
- Required environment variables
- Agent reachability (when not in offline mode)
- Authentication configuration

---

## Troubleshooting

### Agent Not Responding

1. Verify the agent is published (not in draft state)
2. Check the Environment ID and Schema Name are correct
3. Ensure the Azure AD app has the correct API permissions with admin consent
4. Verify the client secret is valid and not expired

### Authentication Errors

1. Confirm the tenant ID is correct
2. Check that admin consent was granted for the API permissions
3. Verify the client secret matches what's in Key Vault or env vars
4. Ensure the token scope is correct:
   - Foundry -> CS: `https://api.powerplatform.com/.default`

### Added Agents Not Working (Demo C)

1. In Copilot Studio, verify all agents are listed in the **Agents** section on the agent overview page
2. Check that the Azure AI Foundry connection is active and the project endpoint is correct
3. Verify each Foundry agent's **Agent Id** matches the agent's name exactly as it appears in the Foundry project's agent list
4. Ensure the signed-in user has RBAC access to the Azure AI Foundry project
5. Test each agent individually before testing the full flow

### Event Not Emitted (Demo B)

1. Ensure the Approval Agent's topic has the Event node configured correctly
2. Verify the event name is exactly `approval_decision`
3. Check that the event payload matches the expected schema

### Foundry -> CS Weather Call Fails (Demo A)

The pro-code workflow's weather step calls the CS Weather agent via the M365 Agents SDK. Common issues:

1. **Missing environment variables** - Verify all `COPILOTSTUDIOAGENT__*` vars are set:
   ```bash
   # Check required vars are set (should print values, not blank)
   echo $COPILOTSTUDIOAGENT__TENANTID
   echo $COPILOTSTUDIOAGENT__ENVIRONMENTID
   echo $COPILOTSTUDIOAGENT__AGENTAPPID
   echo $COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME
   ```
2. **Token acquisition fails** - Check `COPILOTSTUDIOAGENT__AGENTAPPSECRET` is correct and not expired. For Key Vault references, verify the managed identity has access.
3. **Weather agent not responding** - Verify the Weather agent is published in CS portal (not in draft). Check the schema name matches exactly.
4. **Timeout errors** - The default timeout is 30 seconds. If the CS agent is slow to respond, increase `timeout_seconds` parameter. Check CS agent health in the portal.
5. **Schema mismatch** - The weather step expects `WeatherResponse` JSON format (see `src/shared/models.py`). If the CS agent returns a different format, update the agent instructions in CS portal to match the expected schema.
6. **Partial results** - The weather step degrades gracefully. If the CS call fails, the workflow continues without weather data. Check workflow logs for `"Weather unavailable"` messages.

---

## References

- [Copilot Studio Documentation](https://learn.microsoft.com/en-us/microsoft-copilot-studio/)
- [M365 Agents SDK - Integrate with Copilot Studio](https://learn.microsoft.com/en-us/microsoft-365/agents-sdk/integrate-with-mcs)
- [Python Sample for Copilot Studio Client](https://github.com/microsoft/Agents/tree/main/samples/python/copilotstudio-client)
- [Design Document](../../docs/interoperability-design.md) - Interoperability architecture and setup context
