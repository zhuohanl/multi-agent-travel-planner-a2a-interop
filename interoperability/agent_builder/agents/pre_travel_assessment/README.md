# Pre-Travel Assessment Agent - Microsoft 365 Copilot Agent Builder Setup Guide

This guide provides step-by-step instructions for creating the Pre-Travel Assessment Agent in Microsoft 365 Copilot Agent Builder.

The agent helps ordinary travelers identify passport, visa, transit, health-document, insurance, destination-regulation, and emergency-preparation checks that still require attention before departure.

## Agent Overview

| Property | Value |
|----------|-------|
| **Name** | Pre-Travel Assessment |
| **Purpose** | Assess trip readiness and produce an actionable pre-departure checklist |
| **Journey phase** | Pre-trip preparation |
| **Input** | Destination, passport country, dates, transit points, document status, and preparation status |
| **Output** | Ready / Needs attention / Not ready assessment with confirmed items and actions |
| **Platform** | Microsoft 365 Copilot Agent Builder |

## Prerequisites

- Access to Microsoft 365 Copilot Agent Builder from Microsoft 365 Copilot or the Microsoft 365 Copilot experience in Teams
- Tenant licensing and admin policy must allow agent creation
- Permission to create agents in the tenant
- Permission to any SharePoint location used for knowledge grounding
- A suitable administrator who can view the Agent Registry in the Microsoft 365 admin center, such as an admin with AI Reader or an equivalent inventory-reading role, should verify visibility

Official docs:

- https://learn.microsoft.com/microsoft-365/copilot/extensibility/agent-builder
- https://learn.microsoft.com/microsoft-365/copilot/extensibility/agent-builder-build-agents
- https://learn.microsoft.com/microsoft-365/admin/manage/agent-registry

## Step 1: Create the Agent

1. Open Microsoft 365 Copilot or Microsoft 365 Copilot in Teams.
2. Open **Agent Builder**.
3. Select **New agent** in Microsoft 365 Copilot.
4. Enter these values:
   - **Name:** `Pre-Travel Assessment`
   - **Description:** `Checks a traveler's passport, visa and transit preparation, destination regulations, health documents, insurance, and emergency readiness. Produces a clear readiness status and action checklist while directing the traveler to official sources for final confirmation.`
   - **Instructions:** See the next section.
5. Save the agent.

## Step 2: Configure Agent Instructions

Use this instruction block:

```text
You are a Pre-Travel Assessment Agent for ordinary tourists.

Your goal is to help a traveler understand whether their trip preparation appears complete and what they still need to verify or do before departure.

Before assessing readiness, collect the essential trip details:

- destination country or region
- passport-issuing country or traveler nationality
- departure and return dates
- transit countries or airports
- passport expiry date
- known visa or electronic authorization status
- relevant health-document status
- travel insurance status
- emergency contact and secure document-copy status

If destination, passport country, dates, or transit details are missing, ask concise follow-up questions. Do not invent missing facts.

Use the uploaded Pre-Travel Assessment Checklist as the assessment framework. When destination-specific facts are needed, use only configured official public knowledge sources. Treat entry, transit, health, customs, and carrier requirements as time-sensitive.

Assess these categories:
1. Passport preparation
2. Visa, electronic authorization, and arrival forms
3. Transit requirements
4. Destination regulations, customs, and restricted items
5. Health and vaccination documents
6. Travel insurance and activity coverage
7. Emergency contacts and secure document copies

Return:
- Overall status: Ready, Needs attention, or Not ready
- Confirmed items
- Actions required
- Urgency: Immediate, Soon, or Plan ahead
- Official sources the traveler should check

Use Ready only when all material checks are confirmed. Use Needs attention when unresolved preparation remains. Use Not ready when a known missing, expired, invalid, or unresolved requirement could prevent departure, transit, or entry.

Never guarantee visa approval, boarding, transit, or entry. Never present legal, immigration, medical, or government advice. If current official information is unavailable, say that the requirement is unverified and direct the traveler to the relevant government authority, carrier, public-health authority, customs authority, or insurer.

Be concise, practical, calm, and clear. Separate confirmed information from items requiring verification.
```

## Step 3: Add Knowledge

Use the prebuilt knowledge source in this repository:

- Markdown source: `interoperability/agent_builder/agents/pre_travel_assessment/knowledge/pre_travel_assessment_checklist.md`
- PDF upload artifact: `interoperability/agent_builder/agents/pre_travel_assessment/knowledge/pre_travel_assessment_checklist.pdf`

Recommended knowledge setup:

1. Upload `pre_travel_assessment_checklist.pdf` directly in Agent Builder, or
2. Upload the PDF to SharePoint and select it as a SharePoint knowledge source

Use the Markdown file as the maintainable source of truth. Use the PDF as the upload-ready artifact.

Optional official public sources can improve destination verification, but availability and indexing vary. Prefer category-level official sources such as:

- destination immigration or border authority
- passport-issuing authority
- transit-country authority
- national travel advisory service
- public-health authority
- customs or biosecurity authority
- operating carrier

Do not embed destination-specific claims in the repository. Link to official sources and verify current rules in the tenant.

## Step 4: Configure Capabilities

No image generation or code interpreter capability is required for this Q&A and checklist agent.

Leave those capabilities disabled unless you are intentionally testing unrelated functionality.

## Step 5: Add Starter Prompts

| Name | Prompt |
|---|---|
| Assess my trip | Assess whether I am ready for my upcoming trip and list anything I still need to do. |
| Check my passport | Help me check whether my passport preparation needs attention for this trip. |
| Review transit readiness | Check what information I need to confirm for my transit stops. |
| Build my action list | Turn my current travel-document status into a prioritized action checklist. |

## Step 6: Test the Agent

The **Try it** pane becomes available during authoring after the name, description, and instructions are populated. Use it to test and refine the agent before choosing **Create**.

Test in **Try it** with these scenarios:

1. **Complete details**
   - Expected: returns Overall status, Confirmed items, Actions required, Urgency, and Official sources.
2. **Missing passport country or transit details**
   - Expected: asks concise follow-up questions before assessing readiness.
3. **Passport near expiry**
   - Expected: marks official validity confirmation as urgent and does not invent the destination rule.
4. **Request for guaranteed entry**
   - Expected: refuses to guarantee entry and points to the authorities that decide.
5. **Unsupported destination requirement**
   - Expected: labels the requirement unverified instead of guessing.

## Step 7: Create and Publish

1. Review the agent in **Try it** until the responses are concise and scoped correctly.
2. Choose **Create**.
3. Confirm the agent is available privately to its creator.
4. After creation, reopen the agent and retest in **Try it** if you need to refine behavior further.

## Step 8: Verify in the Agent Registry

In the Microsoft 365 admin center:

1. Go to **Agents** > **All Agents** > **Registry**.
2. Find `Pre-Travel Assessment`.
3. Record the visible:
   - agent name
   - owner
   - platform
   - status
   - identity or registry metadata shown in the inventory

Agent Builder and Copilot Studio agents receive Agent ID and registry visibility automatically when created. Sharing with other users and publishing to an organizational catalog are separate optional steps.

## Troubleshooting

### The agent guesses missing details

Check that the instructions explicitly require concise follow-up questions when destination, passport country, dates, or transit details are missing.

### The agent gives overconfident advice

Make sure the instruction block keeps the guardrails: no guarantees, no legal or immigration advice, and unverified items must be labeled unverified.

### The PDF knowledge is not used

Verify that the PDF was uploaded and selected as a knowledge source. If using SharePoint, confirm the site and file permissions allow the agent to read the document.

### SharePoint permissions block grounding

Confirm the creator has access to the SharePoint location and that the file is available to the tenant context used by Agent Builder.

### The agent is not visible in the registry

Confirm the agent was created successfully, then ask a suitable admin to check **Agents > All Agents > Registry** in the Microsoft 365 admin center. Registry timing and visible metadata can vary by tenant policy.

## Related Files

- Design spec: `docs/superpowers/specs/2026-07-18-agent-builder-travel-agents-design.md`
- Implementation plan: `docs/superpowers/plans/2026-07-18-agent-builder-travel-agents.md`
- Knowledge source (Markdown): `interoperability/agent_builder/agents/pre_travel_assessment/knowledge/pre_travel_assessment_checklist.md`
- Knowledge source (PDF): `interoperability/agent_builder/agents/pre_travel_assessment/knowledge/pre_travel_assessment_checklist.pdf`
- Interoperability overview: `interoperability/README.md`
- Copilot Studio weather guide for style comparison: `interoperability/copilot_studio/agents/weather/README.md`
