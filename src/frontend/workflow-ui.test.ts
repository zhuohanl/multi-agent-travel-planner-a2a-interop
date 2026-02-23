import { describe, expect, it } from "vitest";

import {
  applyDiscoveryProgressEvent,
  buildAgentTasks,
  hasStatusPendingAction,
  groupAgentTasksByRole,
  isBookingFlowComplete,
  shouldAutoPollStatus,
  shouldRenderItinerary,
  toDisplayPhase,
} from "./workflow-ui";
import type { PendingAction, RegisteredAgent } from "./types";

describe("workflow ui helpers", () => {
  it("maps backend phases to user-facing labels", () => {
    expect(toDisplayPhase("clarification")).toBe("Clarification");
    expect(toDisplayPhase("discovery_in_progress")).toBe("Discovery");
    expect(toDisplayPhase("discovery_planning")).toBe("Planning");
    expect(toDisplayPhase("booking")).toBe("Booking");
    expect(toDisplayPhase("completed")).toBe("Completed");
  });

  it("renders itinerary only once planning has started", () => {
    const itinerary = { days: [] };
    expect(shouldRenderItinerary("clarification", itinerary)).toBe(false);
    expect(shouldRenderItinerary("discovery_in_progress", itinerary)).toBe(false);
    expect(shouldRenderItinerary("discovery_planning", itinerary)).toBe(true);
    expect(shouldRenderItinerary("booking", itinerary)).toBe(true);
    expect(shouldRenderItinerary("completed", itinerary)).toBe(true);
  });

  it("marks booking complete after booking actions are exhausted", () => {
    const pendingActions: PendingAction[] = [
      {
        label: "Book Hotel",
        event: { type: "book_item", booking: { booking_id: "hotel-1" } },
      },
    ];
    expect(isBookingFlowComplete("booking", pendingActions, 1)).toBe(false);
    expect(isBookingFlowComplete("completed", [], 1)).toBe(true);
  });

  it("detects status pending action", () => {
    const pendingActions: PendingAction[] = [
      {
        label: "Refresh",
        event: { type: "status" },
      },
    ];
    expect(hasStatusPendingAction(pendingActions)).toBe(true);
    expect(hasStatusPendingAction([])).toBe(false);
  });

  it("auto-polls while discovery is running and status action is available", () => {
    const pendingActions: PendingAction[] = [
      {
        label: "Refresh",
        event: { type: "status" },
      },
    ];
    expect(shouldAutoPollStatus("discovery_in_progress", null, false, pendingActions)).toBe(true);
    expect(shouldAutoPollStatus("discovery_planning", null, false, pendingActions)).toBe(true);
    expect(shouldAutoPollStatus("discovery_planning", "itinerary_approval", true, pendingActions)).toBe(false);
    expect(shouldAutoPollStatus("booking", null, false, pendingActions)).toBe(false);
    expect(shouldAutoPollStatus("booking", null, true, pendingActions)).toBe(false);
  });

  it("updates discovery progress from SSE event types", () => {
    const base = {};
    const running = applyDiscoveryProgressEvent(base, {
      type: "agent_started",
      agent: "transport",
      message: "Searching flights",
    });
    expect(running.transport?.status).toBe("running");
    expect(running.transport?.description).toBe("Searching flights");

    const done = applyDiscoveryProgressEvent(running, {
      type: "agent_completed",
      agent: "transport",
      message: "Done",
    });
    expect(done.transport?.status).toBe("completed");
  });

  it("builds dashboard tasks from agent registry and runtime status", () => {
    const registry: RegisteredAgent[] = [
      {
        agentId: "orchestrator",
        name: "Orchestrator",
        type: "orchestrator",
        status: "online",
        url: "http://localhost:10000",
        capabilities: [],
      },
      {
        agentId: "transport",
        name: "Transport",
        type: "discovery",
        status: "offline",
        url: "http://localhost:8002",
        capabilities: [],
      },
    ];

    const tasks = buildAgentTasks(
      [
        { agent_id: "transport", status: "running", message: "Searching options" },
      ],
      {},
      registry
    );

    const transport = tasks.find((task) => task.id === "transport");
    const orchestrator = tasks.find((task) => task.id === "orchestrator");
    expect(transport?.status).toBe("running");
    expect(orchestrator?.status).toBe("online");
  });

  it("groups tasks by orchestrator/discovery/planning/booking roles", () => {
    const groups = groupAgentTasksByRole([
      { id: "orchestrator", name: "Orchestrator", phase: "intake", status: "online" },
      { id: "transport", name: "Transport", phase: "discover", status: "running" },
      { id: "aggregator", name: "Aggregator", phase: "synthesis", status: "pending" },
      { id: "booking", name: "Booking", phase: "booking", status: "unknown" },
    ]);

    expect(groups.orchestrator).toHaveLength(1);
    expect(groups.discovery).toHaveLength(1);
    expect(groups.planning).toHaveLength(1);
    expect(groups.booking).toHaveLength(1);
  });
});
