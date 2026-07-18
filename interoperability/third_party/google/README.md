# Google Agent Platform interoperability

This directory contains the shared Google Cloud setup and lifecycle runbook for
evaluating two Google Agent Platform agents with Microsoft Agent 365:

| Agent | Google authoring path | Agent Runtime region |
| --- | --- | --- |
| [Local Language & Cultural Companion](agents/local_language_cultural_companion/README.md) | Agent Studio | `us-west1` |
| [Deep Search](agents/deep_search/README.md) | Official ADK sample from Agent Garden | `us-central1` |

Agent-specific creation, deployment, and smoke-test instructions live with each
agent and are linked above. Registry Sync IAM, connection, validation, and
status are maintained in [Agent 365 Registry Sync](agent365_registry_sync.md).

## Start here: end-to-end workflow

Follow these steps in order. Each link opens the document section that owns the
detailed procedure.

1. **Create the Google Cloud evaluation boundary.** Set up the Free Trial
   project, project-scoped budget, and cost alerts described in
   [Account and cost boundary](#account-and-cost-boundary).
   **Checkpoint:** the project is linked to billing and budget alerts are active.
2. **Prepare the local CLI and Agent Runtime.** Complete
   [Local CLI and project setup](#local-cli-and-project-setup), then enable the
   services, bucket, service identity, and deployment access under
   [Agent Runtime prerequisites](#agent-runtime-prerequisites).
   **Checkpoint:** `gcloud` returns the project number and all required services
   are enabled.
3. **Create the low-code travel agent first.** Follow the
   [Agent Studio configuration](agents/local_language_cultural_companion/README.md#agent-studio-configuration),
   run its [preview tests](agents/local_language_cultural_companion/README.md#preview-tests),
   and [deploy it](agents/local_language_cultural_companion/README.md#deploy) to
   `us-west1`.
   **Checkpoint:** Local Language & Cultural Companion is available in Agent
   Runtime and passes both preview scenarios.
4. **Establish the first Microsoft connection.** Create the Google identity and
   key under
   [Google Cloud identity and permissions](agent365_registry_sync.md#google-cloud-identity-and-permissions),
   then [create and validate the connection](agent365_registry_sync.md#create-and-validate-the-connection)
   for `us-west1`.
   **Checkpoint:** the first manual sync imports Local Language & Cultural
   Companion.
5. **Deploy the code-first research agent.** Follow Deep Search from
   [sample creation](agents/deep_search/README.md#create-the-sample-project)
   through [deployment](agents/deep_search/README.md#deploy) and its
   [smoke test](agents/deep_search/README.md#smoke-test) in `us-central1`.
   **Checkpoint:** Deep Search returns a research response and never fabricates
   unavailable source links.
6. **Synchronize the complete portfolio.** Add `us-central1` to the existing
   connection and follow the
   [final multi-region sync](agent365_registry_sync.md#final-multi-region-sync).
   Do not create another connection or another service account.
   **Checkpoint:** Agent 365 shows exactly one record for each agent with the
   expected source type and region.
7. **Clean up when the evaluation ends.** Follow the Registry Sync
   [credential teardown](agent365_registry_sync.md#teardown), then complete the
   shared [resource and cost cleanup](#optional-teardown-and-cost-verification).

## Account and cost boundary

Use a dedicated, project-backed Google Cloud Free Trial environment. Express
Mode is suitable for prompt experiments but cannot replace the project required
for Agent Runtime deployment.

1. Create a normal Google Cloud project and link it to the Free Trial billing
   account.
2. Create a project-scoped budget that ends on the Free Trial expiry date. Use
   the remaining Welcome credit as the specified amount and add actual-spend
   alerts at 50%, 75%, and 90%.
3. Enable email notifications for the billing-account administrator.
4. Review billing before each deployment. A budget sends alerts but does not
   stop resources or prevent charges.

Use only synthetic travel prompts. Do not upload credentials, personal
information, production data, or customer content.

## Local CLI and project setup

Install Google Cloud CLI on Windows:

```powershell
winget install --id Google.CloudSDK --exact --source winget `
  --accept-package-agreements `
  --accept-source-agreements
```

Open a new PowerShell window after installation, then authenticate and select
the project:

```powershell
gcloud --version
gcloud auth login
gcloud config set project <PROJECT_ID>
gcloud projects describe <PROJECT_ID> --format="value(projectNumber)"
```

The final command must return a numeric project number without an authentication
or billing error.

## Agent Runtime prerequisites

Enable the shared services:

```powershell
gcloud services enable `
  aiplatform.googleapis.com `
  storage.googleapis.com `
  logging.googleapis.com `
  monitoring.googleapis.com `
  cloudtrace.googleapis.com `
  telemetry.googleapis.com `
  cloudresourcemanager.googleapis.com `
  --project=<PROJECT_ID>
```

Create a regional, uniform-access staging bucket. Use the deployment region
required by the resource that uses the bucket:

```powershell
gcloud storage buckets create gs://<BUCKET_NAME> `
  --project=<PROJECT_ID> `
  --location=<REGION> `
  --uniform-bucket-level-access
```

Generate the Agent Runtime service identity:

```powershell
gcloud beta services identity create `
  --service=aiplatform.googleapis.com `
  --project=<PROJECT_ID>
```

The deploying principal requires `roles/aiplatform.user` and write access to the
staging bucket for object-based deployments. Apply least privilege and do not
store project-specific resource IDs or URLs in this repository.

## Portfolio completion

The evaluation is complete when:

1. Both agents are deployed and pass their agent-specific smoke tests.
2. The single Google Vertex AI Registry Sync connection includes `us-west1` and
   `us-central1`.
3. Agent 365 displays one record for each expected agent with the correct source
   type and region.

The current synchronization state and final-sync procedure are recorded in
[Agent 365 Registry Sync](agent365_registry_sync.md).

## Optional teardown and cost verification

Only perform teardown after the synchronized agents are no longer needed:

1. Follow the connection and credential cleanup in
   [Agent 365 Registry Sync](agent365_registry_sync.md).
2. Delete the Deep Search and Agent Studio resources through Agent Runtime.
3. Delete the staging bucket:

   ```powershell
   gcloud storage rm --recursive gs://<BUCKET_NAME>
   gcloud storage buckets delete gs://<BUCKET_NAME>
   ```

4. Confirm that no evaluation Agent Runtime deployment remains.
5. Review final Free Trial credit usage and any remaining billable resources.
