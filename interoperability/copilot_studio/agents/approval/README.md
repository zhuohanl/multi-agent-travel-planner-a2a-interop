# Approval Agent - Copilot Studio Setup Guide

This guide provides detailed step-by-step instructions for creating the Approval Agent in Microsoft Copilot Studio.

The Approval Agent handles human-in-the-loop approval for travel itineraries. It is called from the Foundry Discovery Workflow (Demo B) via the Approval Proxy hosted agent, which uses the M365 Agents SDK to communicate with this Copilot Studio agent.

## Architecture

```
TripSpec → Discovery Workflow → Draft Itinerary
              ↓
    [6 Discovery Agents + Weather Proxy]
              ↓
    [Aggregator + Route Agent]
              ↓
    Approval Proxy (Hosted Agent in Foundry)
         ↓ M365 Agents SDK
    Approval Agent (This agent - Copilot Studio)
         ↓
    Final Output (approved/rejected/modify)
```

> **Note:** The Approval Proxy hosted agent (INTEROP-015) bridges the Foundry workflow and this Copilot Studio agent using the M365 Agents SDK. See `interoperability/foundry/agents/approval_proxy/` for the proxy implementation.

## Prerequisites

- Access to Microsoft Copilot Studio (https://copilotstudio.microsoft.com)
- Azure AD tenant with appropriate permissions
- Azure AD app registration (see main SETUP.md Step 1.1 for `interop-foundry-to-cs`)
- Understanding of the Approval Agent contract (see `docs/interoperability-design.md`)

## Agent Overview

| Property | Value |
|----------|-------|
| **Name** | Approval Agent |
| **Purpose** | Human-in-the-loop approval for travel itineraries |
| **Used In** | Demo B (called from Foundry Discovery Workflow via Approval Proxy) |
| **Input** | Draft itinerary (JSON matching Itinerary schema) |
| **Output** | `approval_decision` event with decision and feedback |

## Step 1: Create the Agent

1. Go to [Copilot Studio](https://copilotstudio.microsoft.com)
2. Click **Create** in the top navigation
3. Select **New agent**
4. Enter the following details:
   - **Name:** `Approval Agent`
   - **Description:** `Human-in-the-loop approval for travel itineraries. Displays itineraries, collects user decisions (approve/reject/modify), and emits approval_decision events.`
   - **Instructions:** See the Agent Instructions section below
5. Click **Create**

## Step 2: Configure Agent Instructions

In the agent settings, set the following instructions (system prompt):

```
You are an Approval Agent that helps travelers review and approve their travel itineraries.

Your responsibilities:
1. Display the itinerary clearly and professionally
2. Highlight key details: destination, dates, daily plans, estimated costs
3. Ask the user for their decision: Approve, Reject, or Request Modifications
4. Collect feedback when the user rejects or requests modifications
5. Emit an approval_decision event with the decision and feedback

Response Guidelines:
- Be professional but friendly
- Summarize the itinerary in an easy-to-read format
- Present the approve/reject/modify options clearly
- When collecting rejection reasons or modification requests, be specific about what information you need
- Confirm the user's decision before emitting the approval event

Decision Types:
- approved: User approves the itinerary as-is
- rejected: User rejects the itinerary (feedback required)
- modify: User wants changes (feedback required with specific modifications)
```

## Step 3: Create the "Review Itinerary" Topic

This is the main topic that handles itinerary approval requests.

### 3.1 Create the Topic

1. In the agent, go to **Topics** in the left sidebar
2. Click **+ New topic** > **From blank**
3. Name the topic: `Review Itinerary`

### 3.2 Add Trigger Phrases

Click on the trigger node and add these phrases:

```
review itinerary
approve this itinerary
review and approve
check this itinerary
approval needed
approve travel plan
review my trip
decision needed
```

### 3.3 Build the Conversation Flow

**Node 1: Parse Incoming Itinerary**

Add a **Message** node that acknowledges receipt:
```
I've received your itinerary for review. Let me display the details for you.
```

**Node 2: Display Itinerary Summary**

Add a **Message** node with an **Adaptive Card** to display the itinerary. Use this template:

```json
{
  "type": "AdaptiveCard",
  "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
  "version": "1.5",
  "body": [
    {
      "type": "TextBlock",
      "text": "Trip Itinerary Review",
      "weight": "Bolder",
      "size": "Large"
    },
    {
      "type": "FactSet",
      "facts": [
        {
          "title": "Destination",
          "value": "${destination}"
        },
        {
          "title": "Dates",
          "value": "${start_date} - ${end_date}"
        },
        {
          "title": "Total Days",
          "value": "${total_days}"
        },
        {
          "title": "Estimated Cost",
          "value": "${total_estimated_cost} ${currency}"
        }
      ]
    },
    {
      "type": "TextBlock",
      "text": "Daily Plans",
      "weight": "Bolder",
      "size": "Medium",
      "separator": true
    },
    {
      "type": "Container",
      "$data": "${days}",
      "items": [
        {
          "type": "TextBlock",
          "text": "${date}: ${day_summary}",
          "wrap": true
        }
      ]
    }
  ]
}
```

**Node 3: Ask for Decision**

Add a **Question** node:
- **Question text:**
  ```
  Please review the itinerary above. What would you like to do?
  ```
- **Identify:** Multiple choice options
- **Options:**
  - Approve - Proceed with booking
  - Reject - Cancel this itinerary
  - Request modifications - I want changes
- **Save response as:** `user_decision` (variable)

**Node 4: Branch on Decision**

Add a **Condition** node to branch based on `user_decision`:

#### Branch 4a: If "Approve"

Add a **Message** node:
```
Excellent! I'm marking this itinerary as approved. The booking process will proceed.
```

Add an **Event** node to emit `approval_decision`:
- **Event name:** `approval_decision`
- **Event value (JSON):**
```json
{
  "request_id": "${request_id}",
  "decision": "approved",
  "feedback": null,
  "timestamp": "${current_timestamp}"
}
```

Add a **Message** node:
```
Your itinerary has been approved successfully.
```

#### Branch 4b: If "Reject"

Add a **Question** node:
- **Question text:**
  ```
  I understand you want to reject this itinerary. Could you please provide a reason? This helps us create better itineraries in the future.
  ```
- **Identify:** User's entire response
- **Save response as:** `rejection_reason` (variable)

Add a **Message** node:
```
Thank you for your feedback. I'm marking this itinerary as rejected.
```

Add an **Event** node to emit `approval_decision`:
- **Event name:** `approval_decision`
- **Event value (JSON):**
```json
{
  "request_id": "${request_id}",
  "decision": "rejected",
  "feedback": "${rejection_reason}",
  "timestamp": "${current_timestamp}"
}
```

Add a **Message** node:
```
The itinerary has been rejected. The planning team will be notified of your feedback.
```

#### Branch 4c: If "Request modifications"

Add a **Question** node:
- **Question text:**
  ```
  I'd be happy to help with modifications. Please describe the changes you'd like to make:

  For example:
  - Change dates
  - Different hotel preferences
  - Add or remove activities
  - Budget adjustments
  - Specific requirements
  ```
- **Identify:** User's entire response
- **Save response as:** `modification_request` (variable)

Add a **Message** node:
```
Got it! I'll pass these modification requests to the planning team.
```

Add an **Event** node to emit `approval_decision`:
- **Event name:** `approval_decision`
- **Event value (JSON):**
```json
{
  "request_id": "${request_id}",
  "decision": "modify",
  "feedback": "${modification_request}",
  "timestamp": "${current_timestamp}"
}
```

Add a **Message** node:
```
Your modification request has been submitted. The itinerary will be revised based on your feedback.
```

## Step 4: Configure Timeout Handling (Optional)

For timeout scenarios, the Approval Proxy hosted agent handles the fallback (returning a `pending` decision). However, you can add a topic to handle status checks:

1. Create a new topic: `Check Approval Status`
2. Add trigger phrases: `status`, `check status`, `what's happening`
3. Add a message explaining the current state

## Step 5: Publish the Agent

1. Click **Publish** in the top right corner
2. Review the changes summary
3. Click **Publish** to make the agent live

### After Publishing

1. Go to **Settings** > **Agent details**
2. Note these values for environment configuration:
   - **Environment ID**: Found in the URL (`/environments/{id}/...`)
   - **Schema Name**: Listed in agent details

## Approval Decision Schema Reference

### Event Name

The Approval Agent emits decisions via:
```
Event Name: approval_decision
```

### Event Payload Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["request_id", "decision"],
  "properties": {
    "request_id": {
      "type": "string",
      "description": "Unique identifier matching the original ApprovalRequest"
    },
    "decision": {
      "type": "string",
      "enum": ["approved", "rejected", "modify", "pending"],
      "description": "The approval decision"
    },
    "feedback": {
      "type": "string",
      "description": "Optional human feedback or modification instructions",
      "default": null
    },
    "timestamp": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 timestamp of the decision"
    }
  }
}
```

### Example Payloads

**Approved:**
```json
{
  "request_id": "req_abc123",
  "decision": "approved",
  "feedback": null,
  "timestamp": "2025-06-15T10:30:00Z"
}
```

**Rejected:**
```json
{
  "request_id": "req_abc123",
  "decision": "rejected",
  "feedback": "Budget exceeds my limit. I need options under $3000.",
  "timestamp": "2025-06-15T10:32:00Z"
}
```

**Modification Requested:**
```json
{
  "request_id": "req_abc123",
  "decision": "modify",
  "feedback": "Please change the hotel to a 4-star instead of 5-star, and add a day trip to the countryside.",
  "timestamp": "2025-06-15T10:35:00Z"
}
```

**Pending (timeout/error fallback - set by Approval Proxy):**
```json
{
  "request_id": "req_abc123",
  "decision": "pending",
  "feedback": "Awaiting human response",
  "timestamp": "2025-06-15T10:40:00Z"
}
```

## Environment Variables

After creating the agent, set these environment variables:

```bash
# In your .env file or Azure Key Vault
COPILOTSTUDIOAGENT__APPROVAL__SCHEMANAME="your-approval-agent-schema-name"
```

The following variables are shared across all CS agents:
```bash
COPILOTSTUDIOAGENT__TENANTID="your-azure-tenant-id"
COPILOTSTUDIOAGENT__AGENTAPPID="your-interop-foundry-to-cs-app-id"
COPILOTSTUDIOAGENT__AGENTAPPSECRET="your-client-secret"
COPILOTSTUDIOAGENT__ENVIRONMENTID="your-power-platform-environment-id"
```

## Testing

### Manual Testing in Portal

1. In Copilot Studio, click **Test** to open the test pane
2. Trigger the topic with: "review itinerary"
3. When prompted, paste a sample itinerary JSON
4. Test each decision path:
   - Approve flow
   - Reject flow (provide feedback)
   - Modify flow (provide modification requests)
5. Verify the event payload in the test logs

### Programmatic Testing

Use the verification script:

```bash
# From project root
uv run python interoperability/copilot_studio/verify.py --verbose
```

## Troubleshooting

### Event Not Emitted

1. Verify the Event node is configured with name `approval_decision`
2. Check that the JSON payload is valid (no syntax errors)
3. Ensure variables like `${request_id}` are properly defined

### Decision Not Captured

1. Check that the Question node is saving to the correct variable
2. Verify the Condition node is matching the exact option text
3. Test each branch individually

### Adaptive Card Not Rendering

1. Validate the Adaptive Card JSON at https://adaptivecards.io/designer/
2. Ensure all variable references use the correct syntax
3. Check that the variables are populated before the card is displayed

## Integration with Foundry Workflow (Demo B)

The Approval Agent is called from the Foundry Discovery Workflow via the **Approval Proxy** hosted agent (INTEROP-015). The flow is:

1. The Discovery Workflow generates a draft itinerary (via discovery agents + aggregator + route agent)
2. The workflow invokes the Approval Proxy hosted agent with the itinerary JSON
3. The Approval Proxy uses the M365 Agents SDK to call this Copilot Studio Approval Agent
4. This agent presents the itinerary to the human user and collects their decision
5. The decision (`approved`/`rejected`/`modify`) is returned to the Approval Proxy
6. The Approval Proxy returns the decision to the Foundry workflow

The `ApprovalRequest`/`ApprovalDecision` schemas define the contract between the Approval Proxy and this agent. The schemas are unchanged regardless of who calls the agent.

## Related Files

- Schema definitions: `src/shared/models.py` (ApprovalRequest, ApprovalDecision)
- Re-exports: `interoperability/shared/schemas/approval.py`
- Topic definitions: `topics.yaml` (in this directory)
- Approval Proxy: `interoperability/foundry/agents/approval_proxy/` (INTEROP-015)
- Main setup guide: `interoperability/copilot_studio/SETUP.md`
- Design doc: `docs/interoperability-design.md`
