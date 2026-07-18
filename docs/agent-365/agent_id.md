
# Microsoft Entra Agent ID research

> **Scope and currency:** reviewed July 18, 2026. Post-Build 2026 Microsoft Learn
> pages are the primary evidence. “Not documented” means the published documentation
> does not establish the relationship; it does not prove that no internal identity exists.

## Read this first

An **Entra Agent ID** is the per-agent identity. An **agent identity blueprint** is
the parent/template that can create and govern agent identities. These are separate
from:

- An **Agent 365 registry entry**, which is inventory and governance metadata. The
  registry can show agents that do not have an Entra Agent ID.
- A host's **managed identity**, service account, or AWS/GCP workload identity. Those
  authenticate the workload; they are not automatically an Entra Agent ID.

| Platform / agent type | Entra Agent ID and blueprint behavior | Important qualification |
| --- | --- | --- |
| Agent Builder | **No.** Agent Builder agents currently don't use or require app registration IDs or Entra Agent IDs; consequently, they have no agent identity blueprint relationship. | This applies to the Agent Builder lifecycle, not just private creation. Sharing, org-catalog submission, and admin publication do not document an identity-provisioning event. Copying the agent to Copilot Studio creates a new Copilot Studio agent, which then follows the Copilot Studio identity model. |
| Copilot Studio | **Automatic on creation, including draft status.** Immediately after a new agent is created, Copilot Studio creates its Entra Agent ID and, when needed, the Microsoft Copilot Studio blueprint/principal; publishing is not required. | Agents created before the July 2026 rollout use legacy app registrations and are to be migrated later. Updating or republishing does not backfill them. |
| Microsoft agents (Researcher, Analyst, Cowork) | **Researcher and Cowork are observed without an Entra Agent ID or identity data in this tenant.** Researcher/Analyst are core Microsoft 365 Copilot experiences and do not fall under agent-related settings. | The Agent 365 records for Researcher and Cowork show **Entra agent ID —** and **No identity data available**. Microsoft has not published an identity/blueprint mapping for any of these Microsoft-built agents. |
| Marketplace agents (Workday, Genspark) | **Conditional, vendor-driven.** First sign-in consent can add the vendor's agent identity blueprint principal to the tenant; that principal can create Entra Agent IDs. | Registry presence does not prove the agent has an Entra Agent ID. No Genspark-specific Microsoft identity documentation was found. Workday ASOR is documented as consuming the Entra identities of agents built on Microsoft platforms; this does not establish a Workday-native agent identity. |
| Microsoft Foundry prompt agents | **New object model:** a newly created agent gets a unique Entra Agent Blueprint and Entra Agent Identity. | A legacy agent has `instance_identity`/`agent.identity` null and uses the project-shared identity and blueprint. It cannot be upgraded in place yet; recreate it with the same definition. |
| Microsoft Foundry hosted agent: source code | **Automatic at deploy/version creation.** The hosted-agent flow creates the blueprint and agent identity. | Source-code hosted agents remain preview as of the current Foundry documentation. |
| Microsoft Foundry hosted agent: container | **Automatic at deploy/version creation.** The runtime agent identity is an Entra Agent ID, not the project managed identity. | The project managed identity is used for infrastructure operations such as pulling the image; RBAC for external resources must target the agent identity. |
| Pro-code agent on Azure Functions, Container Apps, AKS, or another host | **Not automatic merely because of the host.** Create/register a blueprint and agent identity through Entra/Graph or use a Microsoft product integration. | Use the host workload identity as a federated credential where appropriate. The documented sidecar pattern applies to Container Apps, Kubernetes, Docker, and similar container hosts; Microsoft has not published a Functions-specific automatic-provisioning path. |
| Connected agent platform (AWS, GCP) | **No automatic Entra Agent ID from Agent 365 registry sync.** Agent 365 can inventory Amazon Bedrock and Google Vertex AI agents. | Registry sync is separate from identity. To call Microsoft resources with Entra governance, integrate an agent identity using the Entra Auth SDK sidecar or workload-identity federation (AWS STS or GCP Workload Identity). |

## Agent Builder

Microsoft's current Copilot Studio identity FAQ explicitly states:

> **Agent Builder agents: Currently don't use or require app registration IDs or Agent IDs.**

This is a product distinction, not a private-agent-only restriction. The current Agent
Builder lifecycle documentation describes creation, sharing, organization-catalog
submission, and admin publication without any identity-provisioning event:

| Lifecycle event | Entra Agent ID / blueprint provisioned? | Evidence |
| --- | --- | --- |
| Create a private agent | **No** | Direct tenant evidence and the quoted Microsoft statement. |
| Share with named users or the organization | **No** | The sharing documentation describes link access and knowledge-source sharing, but no Entra identity creation. |
| Submit to the organization catalog | **No** | The submission documentation describes metadata and admin review, but no identity creation. Tenant testing also found no identity after submission and publication. |
| Admin approval and publication to the Agent Store | **No** | The publication documentation describes distribution and availability, but no identity creation. Tenant testing found a separate **Your org** record with no Entra Agent ID or identity data. |
| Copy to Copilot Studio | **Yes, for the new copy only** | This creates a separate Copilot Studio agent; it does not add an identity to the original Agent Builder agent. |

### Tenant evidence: private Agent Builder agent

The tenant's **Packing & Preparation** Agent Builder agent, created July 18, 2026
and not yet shared or submitted to the organization catalog, shows:

- **Entra agent ID:** `—`
- **Identity:** **No identity data available**
- **Security:** **This agent doesn't have an Entra ID. Entra policies don't apply to this agent.**

Screenshots: [Details view](images/agent_builder_post_creation_before_share_1.png)
and [Security view](images/agent_builder_post_creation_before_share_2.png).

### Tenant evidence: organization-catalog publication

The subsequent test submitted and published an Agent Builder agent to the organization
catalog. It establishes two important facts:

1. Agent 365 keeps **two registry records** for the same Agent Builder agent:
   - the maker-managed record, with publisher type **Your users**; and
   - the organization-catalog record, with publisher type **Your org**.
2. The **Your org** record still shows **Entra agent ID —** and **No identity data
   available**. Catalog publication did not provision an Entra Agent ID or blueprint.

This supports the documented distinction between the shared/maker version and the
Agent Store version: they are separate registry entries rather than a conversion of
one record into the other. It also confirms that the no-Entra-ID behavior persists
through the tested organization-catalog lifecycle stage.

Screenshots:

- [Registry entries](images/agent_builder_post_submitted_to_org_1.png) — two Agent Builder records.
- [Your users record](images/agent_builder_post_submitted_to_org_2.png) — Entra agent ID `—`.
- [Your org record](images/agent_builder_post_submitted_to_org_3.png) — Entra agent ID `—` and no identity data.

The word **“currently”** is significant: Microsoft has not published a roadmap or
date for Agent Builder to receive Entra Agent ID integration. Recheck this behavior
after material Agent Builder releases.

## Copilot Studio

Copilot Studio's cutoff is a **July 2026 rollout**, not a documented universal
July 1 boundary. The rollout is a draft-creation-time provisioning change:

- Drafting/creating a new agent automatically creates its Entra Agent ID, before the
  agent is published.
- The first draft/agent identity establishes the **Microsoft Copilot Studio agent
  identity blueprint** and blueprint principal in the tenant.
- Existing agents remain on app registrations during transition. Microsoft states that
  their migration is future work, with no date published.
- From July 2026, creating a new agent cannot opt out of automatic identity creation.

Publishing does not create the identity. It can add connector API permissions to the
already-created Entra Agent ID for connectors configured on the published agent.

The documented Copilot Studio global blueprint ID is
`25664c89-cea5-4ab6-b924-a54fd8a19ae0`.

## Tenant observations: Microsoft-built agents

Screenshots from this tenant's Agent 365 app provide direct evidence for the two
Microsoft-built agent records below:

| Agent | Created | Entra agent ID | Identity section |
| --- | --- | --- | --- |
| Cowork | March 7, 2026 | `—` | **No identity data available** |
| Researcher | April 10, 2025 | `—` | **No identity data available** |

Screenshots: [Cowork](images/cowork.png) and [Researcher](images/researcher.png).
They support the current tenant state, while the Microsoft Learn sources establish
that Researcher/Analyst are outside agent-related settings. Neither source
establishes the hidden internal implementation for these first-party experiences.

## Microsoft Foundry: newer model vs. legacy model

The Foundry documentation has an important transition of its own, and its behavior
should not be inferred from Copilot Studio:

| Foundry state | Identity behavior |
| --- | --- |
| New agent object model | Creating the agent is enough to obtain a stable endpoint, a unique blueprint, and a unique agent identity. No separate publishing step is required for the endpoint. |
| Legacy agent | Uses the Foundry project's shared blueprint and identity. `instance_identity` is null. Existing Agent Applications continue to work. |
| Legacy-agent migration | There is no in-place upgrade to a unique identity. Create a replacement agent with the same definition, then reassign downstream RBAC. An in-place path is planned but not dated. |

For hosted agents, do not assign external-resource RBAC to the Foundry project managed
identity. The Foundry agent identity is the principal that must receive the role.

## Connected platforms: two integrations, not one

| Capability | What it does | Does it create an Entra Agent ID? |
| --- | --- | --- |
| Agent 365 registry sync | Imports/inventories supported external-platform agents in the Microsoft 365 admin center. Supported preview sources include Amazon Bedrock and Google Vertex AI. | **No.** It provides centralized discovery and platform-management actions. |
| Entra Agent ID integration | Gives the externally hosted agent a governed Entra identity for Microsoft/custom APIs. Use an Entra Auth SDK sidecar or workload-identity federation. | **Yes, but only after explicit Entra setup.** The blueprint/identity and permissions must be configured. |

## Evidence and primary references

### Post-Build 2026 Microsoft Learn

- [Automatically create Microsoft Entra Agent IDs for Copilot Studio agents](https://learn.microsoft.com/en-us/microsoft-copilot-studio/admin-use-entra-agent-identities) — updated July 2026; Copilot Studio creation behavior, legacy transition, blueprint ID, and removal of opt-out.
- [App registration, agent identities, and authentication for Copilot Studio](https://learn.microsoft.com/en-us/microsoft-copilot-studio/requirements-certificates-configuration-values) — legacy app-registration behavior and planned migration.
- [Share and manage agents](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/agent-builder-share-manage-agents) — Agent Builder private creation and sharing lifecycle.
- [Submit agents from Agent Builder to your org catalog](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/agent-builder-submit-to-org-catalog) — Agent Builder submission and approval lifecycle.
- [Migrate from Agent Applications to the new agent endpoint and publishing experience](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/migrate-agent-applications) — updated July 2026; current Foundry new/legacy identity model and no in-place legacy upgrade.
- [Agent identity concepts in Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/agent-identity) — updated July 2026; agent identity versus project managed identity.
- [Hosted agent permissions reference](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agent-permissions) — updated July 2026; hosted-agent RBAC and identity behavior.
- [How are agent identities created?](https://learn.microsoft.com/en-us/entra/agent-id/agent-id-creation-channels) — updated June 15, 2026; manual, product-integration, and external-consent creation channels.
- [Integrate third-party agents with Microsoft Entra Agent ID](https://learn.microsoft.com/en-us/entra/agent-id/configure-third-party-agents) — post-Build 2026; sidecar and federation patterns for AWS/GCP and other external platforms.
- [Agent Registry convergence with Microsoft Agent 365](https://learn.microsoft.com/en-us/entra/agent-id/agent-registry-convergence) — updated June 17, 2026; registry inventory versus Entra identity management.
- [Registry sync in the Microsoft 365 agent registry](https://learn.microsoft.com/en-us/microsoft-agent-365/admin/agent-registry) — preview; Amazon Bedrock and Google Vertex AI registry sync.

### Other relevant authoritative references

- [Manage agents in the Microsoft 365 admin center](https://learn.microsoft.com/en-us/microsoft-365/admin/manage/manage-copilot-agents-integrated-apps) — Agent Builder as a shared-agent creation channel, plus the Researcher and Analyst governance exclusion.
- [Copilot Cowork overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/cowork/) — no Entra identity or blueprint behavior documented.
- [Microsoft Entra Agent ID blueprints](https://learn.microsoft.com/en-us/entra/agent-id/agent-blueprint) — the underlying blueprint model; updated before Build 2026 but still the specific reference for blueprint architecture.
- [Workday and Microsoft unified agent experience announcement](https://newsroom.workday.com/2025-09-16-Workday-and-Microsoft-to-Deliver-Unified-AI-Agent-Experience-for-the-Enterprise) — pre-Build 2026 announcement of Workday ASOR consuming identities from Microsoft-built agent platforms.