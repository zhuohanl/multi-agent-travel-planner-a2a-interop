
## Agent Builder

```mermaid
flowchart TD
    A[Create] --> B[Private agent]
    B --> C[Share]
    C --> D[Submit to org catalog]
    D --> E[Admin publishes]
    B --> F[Update]
    C --> F
    E --> F
    F --> B
    B --> G[Delete]
```

## Copilot Studio

```mermaid
flowchart TD
    A[Create] --> B[Draft: Agent ID created]
    B --> C[Publish]
    C --> D[Live agent]
    B --> E[Update]
    D --> E
    E --> B
    B --> F[Delete]
    G[Agent identity blueprint<br/>tenant-global; created once] -. parent .-> B

    subgraph CICD[CI/CD: solution promotion]
        direction LR
        H[Dev: unmanaged solution] --> I[CI/CD: export managed package]
        I --> J[Import to Test]
        J --> K[Publish and validate]
        K --> L[Import to Prod]
        L --> M[Publish]
    end

    B --> H
```

Sources:

- [Publish overview for agents](https://learn.microsoft.com/microsoft-copilot-studio/agents-experience/publication-fundamentals-publish-channels)
- [Automatically create Microsoft Entra Agent IDs for Copilot Studio agents](https://learn.microsoft.com/microsoft-copilot-studio/admin-use-entra-agent-identities)
- [Export and import agents using solutions](https://learn.microsoft.com/microsoft-copilot-studio/authoring-solutions-import-export)
- [Establish an application lifecycle management strategy](https://learn.microsoft.com/microsoft-copilot-studio/guidance/alm)
- [Create and delete agents](https://learn.microsoft.com/microsoft-copilot-studio/authoring-first-bot#delete-an-agent)