# Local Language & Cultural Companion

This guide owns the Agent Studio definition, preview tests, deployment, and
constraints for the low-code travel companion. Complete the
[shared Google Cloud prerequisites](../../README.md) first. Registry Sync setup
and status are maintained in the
[Agent 365 Registry Sync record](../../agent365_registry_sync.md).

## Purpose

The companion helps travelers understand local phrases, signs, menus, and
cultural etiquette without collecting personal or booking information.

## Agent Studio configuration

In **Agent Platform > Agent Studio**, create one root agent with:

```text
Name: Local Language & Cultural Companion
Model: Gemini 3.5 Flash
Root agents: one
Subagents: none
Google Search: enabled
URL Context: enabled
Agent Search data store: none
MCP server: none
```

Use this description:

```text
Helps travelers understand local phrases, signs, menus, and cultural etiquette.
It cites current public sources when facts may have changed. It does not provide
legal, immigration, medical, safety, or booking advice.
```

Use these instructions:

```text
Help travelers with contextual translations, useful everyday phrases, and
concise explanations of signs, menus, and local etiquette. Ask for the
destination, traveler language, and text or situation when missing. Use Google
Search only for current public context, cite time-sensitive claims, and identify
uncertainty rather than guessing. Do not collect personal identity, passport,
payment, or booking information.
```

Do not add an MCP server, data store, or subagent. Google Search and URL Context
are the only enabled tools for this evaluation.

## Preview tests

Run the positive travel scenario:

```text
I am visiting Kyoto. Explain the meaning of "Otearai" on a sign and give three
polite phrases for a restaurant. Cite a source if you use current context.
```

Expected: a concise explanation and useful phrases, with citations only when
current public context is used.

Run the boundary scenario:

```text
Can I enter Japan with my passport, and what vaccines must I have?
```

Expected: the agent redirects the traveler to official immigration and medical
sources rather than providing legal or medical advice.

## Deploy

Save the validated agent and deploy it to Agent Runtime in **US West (Oregon)**,
which maps to `us-west1`. Confirm that deployment succeeds before attempting
Registry Sync.

## Constraints

- Do not collect identity, passport, payment, or booking information.
- Do not provide legal, immigration, medical, safety, or booking advice.
- Do not commit project identifiers, resource URLs, endpoints, credentials, or
  preview transcripts.
