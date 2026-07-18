# Packing & Preparation Agent - Microsoft 365 Copilot Agent Builder Setup Guide

This guide provides step-by-step instructions for creating the Packing & Preparation Agent in Microsoft 365 Copilot Agent Builder.

The agent creates a personalized packing and departure checklist for ordinary tourists based on their destination, dates, trip duration, planned activities, known weather, baggage plan, laundry access, and personal needs.

## Agent Overview

| Property | Value |
|----------|-------|
| **Name** | Packing & Preparation |
| **Purpose** | Produce a personalized packing and departure checklist |
| **Journey phase** | Pre-trip preparation |
| **Input** | Destination, dates, duration, activities, known weather, baggage plan, laundry, personal needs |
| **Output** | Categorized checklist with carry-on and checked-baggage items plus official-rule confirmation items |
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
3. Select **New agent**.
4. Enter these values:
   - **Name:** `Packing & Preparation`
   - **Description:** `Creates a personalized packing and departure checklist from the traveler's destination, dates, trip duration, planned activities, baggage plan, laundry access, and personal needs. Separates carry-on and checked-baggage items and flags airline or customs rules that require official confirmation.`
   - **Instructions:** See the next section.
5. Save the agent.

Use this exact metadata if you prefer to paste it into notes or a checklist:

```text
Name: Packing & Preparation

Description: Creates a personalized packing and departure checklist from the traveler's destination, dates, trip duration, planned activities, baggage plan, laundry access, and personal needs. Separates carry-on and checked-baggage items and flags airline or customs rules that require official confirmation.
```

## Step 2: Configure Agent Instructions

Use this instruction block:

```text
You are a Packing & Preparation Agent for ordinary tourists.

Your goal is to create a practical, personalized packing and before-departure checklist without inventing trip conditions or official rules.

Collect:
- destination
- departure and return dates
- trip duration
- planned activities
- expected weather, if the traveler already knows it
- carry-on, checked-baggage, and personal-item plan
- laundry availability
- accommodation type
- mobility, medical, dietary, sensory, family, or childcare needs

Ask concise follow-up questions when missing details would materially change the recommendations. Do not invent weather, baggage allowances, customs rules, or prohibited-item rules.

Use the uploaded Packing and Departure Preparation Reference Guide as the checklist framework.

Organize the response into exactly these 10 sections:
1. Trip assumptions and missing information
2. Essential documents and money
3. Carry-on checklist
4. Checked-baggage checklist
5. Clothing and footwear
6. Health and personal care
7. Electronics and charging
8. Activity-specific gear
9. Before-departure tasks
10. Items requiring official confirmation

Keep the list proportionate to the trip duration and laundry access. Explain unusual or activity-specific recommendations briefly. Suggest renting specialist gear when that is more practical than carrying it.

Do not duplicate weather discovery. Use weather information only when the traveler provides it or it is available from a configured reliable source. If weather is unknown, ask the traveler to provide it or clearly mark weather-dependent recommendations as provisional.

Never state baggage allowances, liquid limits, battery rules, medicine rules, dangerous-goods rules, or customs restrictions unless they are supported by a configured official source. Direct the traveler to the operating carrier, airport security authority, destination customs authority, and a qualified health professional where appropriate.

Do not recommend placing passports, money, critical medicine, keys, irreplaceable items, or unapproved batteries in checked baggage.

Be concise, practical, and easy to scan. Use checkboxes or bullet lists. Respond in natural traveler language; no JSON is required.
```

## Step 3: Add Knowledge

Use the prebuilt knowledge source in this repository:

- Markdown source: `interoperability/agent_builder/agents/packing_preparation/knowledge/packing_reference_guide.md`
- PDF upload artifact: `interoperability/agent_builder/agents/packing_preparation/knowledge/packing_reference_guide.pdf`

Recommended knowledge setup:

1. Upload `knowledge/packing_reference_guide.pdf` directly in Agent Builder, or
2. Upload the PDF to SharePoint and select it as a SharePoint knowledge source

Use the Markdown file as the maintainable source of truth. Use the PDF as the upload-ready artifact.

Optional official public sources can improve verification, but availability and indexing vary. Prefer category-level official sources such as:

- operating airline baggage page
- operating airline dangerous-goods page
- airport security authority
- destination customs or biosecurity authority
- destination tourism authority for cultural or seasonal guidance

Do not embed destination-specific claims in the repository. Link to official sources and verify current rules in the tenant.

## Step 4: Configure Capabilities

No image generation or code interpreter capability is required for this checklist agent.

Leave those capabilities disabled unless you are intentionally testing unrelated functionality.

## Step 5: Add Starter Prompts

| Name | Prompt |
|---|---|
| Pack for my trip | Create a complete packing list for my upcoming trip. |
| Carry-on only | Help me pack for this trip using carry-on baggage only. |
| Prepare for activities | Build a packing list around my planned activities. |
| Final departure check | Give me a before-departure checklist for tomorrow. |

## Step 6: Test the Agent

The **Try it** pane becomes available during authoring after the name, description, and instructions are populated. Use it to test and refine the agent before choosing **Create**.

Test in **Try it** with these scenarios:

1. **Three-day carry-on city trip**
   - Expected: returns a compact, practical checklist with carry-on items prioritized.
2. **Ten-day trip with checked baggage and laundry access**
   - Expected: adjusts clothing quantities for laundry and separates checked-baggage items.
3. **Hiking and swimming trip**
   - Expected: includes activity-specific gear and explains unusual items briefly.
4. **Missing dates or baggage plan**
   - Expected: asks concise follow-up questions before finalizing the checklist.
5. **Medicine, battery, liquid, or prohibited-item question**
   - Expected: refuses to invent a rule and directs the traveler to official sources for confirmation.

## Step 7: Create and Publish

1. Review the agent in **Try it** until the responses are concise and scoped correctly.
2. Choose **Create**.
3. Confirm the agent is available privately to its creator.
4. After creation, reopen the agent and retest in **Try it** if you need to refine behavior further.

## Step 8: Verify in the Agent Registry

In the Microsoft 365 admin center:

1. Go to **Agents > All Agents > Registry**. Menu labels can vary by tenant or product rollout; the linked official Agent Registry documentation is authoritative.
2. Find `Packing & Preparation`.
3. Record the visible:
   - agent name
   - owner
   - platform
   - status
   - identity or registry metadata shown in the inventory

Agent Builder agents receive Agent ID and registry visibility automatically when created. Sharing with other users and publishing to an organizational catalog are separate optional steps.

## Troubleshooting

### Recommendations are too generic

Check that the instructions require the traveler’s destination, dates, duration, activities, baggage plan, laundry access, and personal needs before generating the checklist.

### The list is excessively long

Confirm the instruction block says to keep recommendations proportionate to trip duration and laundry access.

### The agent invents weather

Make sure the instructions only allow weather information when the traveler provides it or a configured reliable source supplies it.

### The agent invents baggage limits

Verify the guardrails prohibit invented baggage allowances, liquid limits, battery rules, medicine rules, dangerous-goods rules, and customs restrictions.

### PDF or SharePoint knowledge is unavailable

Confirm the PDF was uploaded or the SharePoint source is reachable and readable by the tenant context used in Agent Builder.

### The agent is missing from Agent Registry

Confirm the agent was created successfully, then ask a suitable admin to check **Agents > All Agents > Registry** in the Microsoft 365 admin center. Registry timing and visible metadata can vary by tenant policy.

## Related Files

- Design spec: `docs/superpowers/specs/2026-07-18-agent-builder-travel-agents-design.md`
- Implementation plan: `docs/superpowers/plans/2026-07-18-agent-builder-travel-agents.md`
- Knowledge source (Markdown): `interoperability/agent_builder/agents/packing_preparation/knowledge/packing_reference_guide.md`
- Knowledge source (PDF artifact): `interoperability/agent_builder/agents/packing_preparation/knowledge/packing_reference_guide.pdf`
- Interoperability overview: `interoperability/README.md`
- Sibling Pre-Travel Assessment Agent setup guide: `interoperability/agent_builder/agents/pre_travel_assessment/README.md`
