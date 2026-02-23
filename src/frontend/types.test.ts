import { describe, expect, it } from "vitest";

import {
  mapWorkflowPhaseToAgentPhase,
  mapWorkflowPhaseToSessionStatus,
  type AgentCard,
  type PendingAction,
  type RegisteredAgent,
  type WorkflowEvent,
} from "./types";

describe("workflow phase mapping", () => {
  it("maps orchestrator phases to session statuses", () => {
    expect(mapWorkflowPhaseToSessionStatus("clarification")).toBe("collecting");
    expect(mapWorkflowPhaseToSessionStatus("discovery_in_progress")).toBe("discovering");
    expect(mapWorkflowPhaseToSessionStatus("discovery_planning")).toBe("synthesizing");
    expect(mapWorkflowPhaseToSessionStatus("booking")).toBe("booking");
    expect(mapWorkflowPhaseToSessionStatus("completed")).toBe("completed");
  });

  it("maps unknown phase to collecting status", () => {
    expect(mapWorkflowPhaseToSessionStatus("something_else")).toBe("collecting");
    expect(mapWorkflowPhaseToSessionStatus(null)).toBe("collecting");
  });

  it("maps phases to dashboard phase buckets", () => {
    expect(mapWorkflowPhaseToAgentPhase("clarification")).toBe("intake");
    expect(mapWorkflowPhaseToAgentPhase("discovery_in_progress")).toBe("discover");
    expect(mapWorkflowPhaseToAgentPhase("discovery_planning")).toBe("synthesis");
    expect(mapWorkflowPhaseToAgentPhase("booking")).toBe("booking");
    expect(mapWorkflowPhaseToAgentPhase("completed")).toBe("booking");
  });
});

describe("workflow and agent registry types", () => {
  it("supports checkpoint and booking workflow events", () => {
    const approve: WorkflowEvent = {
      type: "approve_checkpoint",
      checkpoint_id: "trip_spec_approved",
    };
    const book: WorkflowEvent = {
      type: "book_item",
      booking: {
        booking_id: "booking-1",
        quote_id: "quote-1",
      },
    };
    const retry: WorkflowEvent = {
      type: "retry_agent",
      agent_id: "transport",
    };

    const pending: PendingAction = {
      event: approve,
      label: "Approve Trip Spec",
      description: "Continue to discovery",
    };

    expect(book.booking?.booking_id).toBe("booking-1");
    expect(retry.agent_id).toBe("transport");
    expect(pending.event.type).toBe("approve_checkpoint");
  });

  it("supports registry list and card models", () => {
    const agent: RegisteredAgent = {
      agentId: "transport",
      name: "Transport",
      type: "discovery",
      status: "online",
      url: "http://localhost:8002",
      capabilities: ["search_transport"],
      lastActivity: "2026-02-22T00:00:00Z",
    };
    const card: AgentCard = {
      name: "Transport Agent",
      description: "Finds transportation options",
      version: "1.0.0",
      url: "http://localhost:8002",
      protocolVersion: "0.2.0",
      skills: [
        {
          id: "transport-search",
          name: "Transport Search",
          description: "Searches flights and trains",
          tags: ["travel", "transport"],
        },
      ],
      capabilities: {
        streaming: true,
      },
      defaultInputModes: ["text"],
      defaultOutputModes: ["text", "json"],
    };

    expect(agent.type).toBe("discovery");
    expect(card.skills[0]?.id).toBe("transport-search");
  });
});
