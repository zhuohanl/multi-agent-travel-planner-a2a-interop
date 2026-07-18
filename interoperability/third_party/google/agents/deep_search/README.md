# Deep Search

This guide owns the provenance, deployment, smoke test, and constraints for the
Deep Search agent. Complete the
[shared Google Cloud prerequisites](../../README.md) first. Registry Sync setup
and status are maintained in the
[Agent 365 Registry Sync record](../../agent365_registry_sync.md).

## Provenance and scope

Deep Search is Google's official upstream ADK sample for a multi-step research
agent. This evaluation deploys the Agent Garden sample to Agent Runtime without
changing its agent logic, tools, or data sources.

## Create the sample project

1. In **Agent Platform > Agent Garden > Deep Search**, select **Deploy > Quick
   deploy**, then **Deploy in Cloud Shell**. Do not select **Deploy to Gemini
   Enterprise**, which is a different distribution path.
2. Authorize Cloud Shell and verify the active project:

   ```bash
   gcloud config get-value project
   ```

   Cloud Shell uses a system-managed Google Cloud CLI. Do not run
   `gcloud components update` or a broad operating-system upgrade.

3. Create the official sample-derived source folder:

   ```bash
   uvx google-agents-cli setup
   # If agents-cli is not found, open a new Cloud Shell tab.
   agents-cli create deep-search-agent \
     --agent adk@deep-search \
     --deployment-target agent_runtime \
     --region us-central1 \
     --interactive
   cd deep-search-agent
   ```

   `deep-search-agent` is a source folder, not a Google Cloud project. The
   explicit deployment target and region prevent the CLI from selecting its
   defaults. Choose **simple** for CI/CD, approve the displayed base-template
   dependencies, and continue after account and project verification.

## Deploy

From the generated project directory:

```bash
agents-cli deploy --project <PROJECT_ID>
cat deployment_metadata.json
```

The deployment creates or updates an Agent Runtime `reasoningEngines` resource.
`deployment_metadata.json` contains its resource ID; keep that file and its
values out of this repository.

## Smoke test

Use the Agent Runtime portal:

1. Open **View in Console** from the successful deployment output.
2. Select **Playground** and start a new session.
3. Submit:

   ```text
   Compare three public sources on the best month to visit Kyoto for autumn
   foliage. Return source links and clearly distinguish conflicting information.
   ```

4. Confirm that the result is a research response and does not request personal
   data. If live search is unavailable, the sample must disclose that limitation
   rather than fabricate source links.

The same test can be run from the CLI:

```bash
agents-cli run \
  --url "https://us-central1-aiplatform.googleapis.com/v1/<REASONING_ENGINE_RESOURCE_ID>" \
  --mode adk \
  "Compare three public sources on the best month to visit Kyoto for autumn foliage. Return source links and clearly distinguish conflicting information."
```

## Constraints

- Keep the upstream sample's agent logic unchanged.
- Do not add tools, private data sources, credentials, or production data.
- Do not commit deployment metadata, resource URLs, endpoints, or transcripts.
