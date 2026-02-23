import { describe, expect, it } from "vitest";

import {
  buildAgentCardValidationUrl,
  canRemoveAgent,
  statusBadgeClass,
} from "./components/agent-registry-utils";

describe("agent registry helpers", () => {
  it("builds well-known card urls from base url", () => {
    expect(buildAgentCardValidationUrl("http://localhost:8002")).toBe(
      "http://localhost:8002/.well-known/agent.json"
    );
    expect(buildAgentCardValidationUrl("http://localhost:8002/")).toBe(
      "http://localhost:8002/.well-known/agent.json"
    );
  });

  it("only allows custom agents to be removed", () => {
    expect(canRemoveAgent("custom")).toBe(true);
    expect(canRemoveAgent("discovery")).toBe(false);
    expect(canRemoveAgent("orchestrator")).toBe(false);
  });

  it("maps statuses to style categories", () => {
    expect(statusBadgeClass("online")).toBe("online");
    expect(statusBadgeClass("offline")).toBe("offline");
    expect(statusBadgeClass("unknown")).toBe("unknown");
  });
});
