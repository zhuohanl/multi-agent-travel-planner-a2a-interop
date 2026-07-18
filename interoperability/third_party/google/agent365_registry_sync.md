# Agent 365 Registry Sync for Google Vertex AI

This document is the single source of truth for Google Cloud IAM, credentials,
Microsoft 365 connection configuration, synchronization validation, status, and
Registry Sync teardown. Shared GCP and Agent Runtime prerequisites are in the
[Google Agent Platform interoperability runbook](README.md).

## Current status

| Agent | Source type | Region | Sync status |
| --- | --- | --- | --- |
| Local Language & Cultural Companion | Agent Studio | `us-west1` | Synchronized successfully |
| Deep Search | ADK sample | `us-central1` | Pending final multi-region sync |

The first manual sync validated the connection and imported the Agent Studio
agent from `us-west1` on 2026-07-18. The connection name is intentionally not
recorded until it is confirmed during the final sync. Task 6 remains open until
the same connection includes `us-central1` and both rows are visible in Agent
365.

## Google Cloud identity and permissions

One service account, one custom role, one project-level binding, and one JSON
key support all selected regions in the same Google Cloud project.

Create the dedicated service account:

```powershell
gcloud iam service-accounts create agent365-registry-sync `
  --project=<PROJECT_ID> `
  --display-name="Agent 365 Registry Sync"
```

Create and bind the least-privilege custom role. Keep the comma-separated
permissions quoted in PowerShell:

```powershell
gcloud iam roles create agent365RegistrySync `
  --project=<PROJECT_ID> `
  --title="Agent 365 Registry Sync" `
  --permissions="aiplatform.reasoningEngines.list,aiplatform.reasoningEngines.get,aiplatform.reasoningEngines.delete" `
  --stage=GA

gcloud projects add-iam-policy-binding <PROJECT_ID> `
  --member="serviceAccount:agent365-registry-sync@<PROJECT_ID>.iam.gserviceaccount.com" `
  --role="projects/<PROJECT_ID>/roles/agent365RegistrySync"
```

## Secret access key

Generate a key only in a local, untracked temporary location:

```powershell
gcloud iam service-accounts keys create "$env:TEMP\agent365-registry-sync.json" `
  --iam-account="agent365-registry-sync@<PROJECT_ID>.iam.gserviceaccount.com"
```

The Microsoft 365 **Secret access key** field requires the complete JSON
key-file contents, not only the `private_key` value. Delete the temporary local
file after the connection is saved. Never commit the key, project identifier,
tenant identifier, agent-card URL, endpoint, or full resource URL.

## Create and validate the connection

In **Microsoft 365 admin center > Agents > All Agents > Registry sync > Manage
> Connect a platform**, select **Google Vertex AI** and configure:

```text
Connection name: A descriptive name for this Google Cloud project
Project ID: <PROJECT_ID>
Regions: US West (Oregon) / us-west1
Secret access key: Complete contents of agent365-registry-sync.json
Automatic import: Disabled until the first manual sync succeeds
```

Validate and save the connection, select **Sync agents**, and confirm that
**Local Language & Cultural Companion** appears for `us-west1`. Do not create a
second connection for another region in the same project.

## Final multi-region sync

1. Open the existing Google Vertex AI connection for `<PROJECT_ID>`.
2. Add **US Central (Iowa)** / `us-central1` alongside **US West (Oregon)** /
   `us-west1`.
3. Save the updated connection and select **Sync agents**.
4. Confirm exactly these two distinct resources:

   ```text
   Local Language & Cultural Companion — Agent Studio — us-west1
   Deep Search — ADK sample — us-central1
   ```

5. Replace the pending values below with the confirmed connection name and sync
   date only after both resources are visible:

   ```text
   Connection name: Pending confirmation
   Final sync date: Pending final sync
   Outcome: Pending confirmation of both expected resources
   ```

A missing resource, duplicate record, credential failure, or region mismatch is
a failed sync. Record the administrator-visible error, but never copy secrets,
tenant identifiers, endpoints, or response transcripts into this repository.

## Teardown

1. Delete the Google Vertex AI Registry Sync connection in Microsoft 365 admin
   center and confirm no active connection uses the service account.
2. List and delete the service-account key:

   ```powershell
   gcloud iam service-accounts keys list `
     --iam-account="agent365-registry-sync@<PROJECT_ID>.iam.gserviceaccount.com"

   gcloud iam service-accounts keys delete <KEY_ID> `
     --iam-account="agent365-registry-sync@<PROJECT_ID>.iam.gserviceaccount.com"
   ```

3. Delete the service account:

   ```powershell
   gcloud iam service-accounts delete `
     "agent365-registry-sync@<PROJECT_ID>.iam.gserviceaccount.com"
   ```

The custom role may also be deleted after confirming that no principal uses it.
