import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  addAgent,
  createSession,
  fetchAgentCard,
  fetchAgents,
  fetchSessionState,
  removeAgent,
  sendEvent,
  sendMessage,
  streamChat,
  subscribeDiscovery,
} from "./api";

describe("frontend api client", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({ ok: true }),
        text: async () => "",
      })) as unknown as typeof fetch
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("creates a session via /chat", async () => {
    await createSession("Plan a trip to Tokyo");
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/chat"),
      expect.objectContaining({
        method: "POST",
      })
    );
  });

  it("sends a message via /chat", async () => {
    await sendMessage("sess-1", "Hello");
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/chat"),
      expect.objectContaining({
        method: "POST",
      })
    );
  });

  it("sends workflow events via /sessions/{id}/event", async () => {
    await sendEvent("sess-1", { type: "approve_checkpoint", checkpoint_id: "trip_spec_approval" });
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/sessions/sess-1/event"),
      expect.objectContaining({
        method: "POST",
      })
    );
  });

  it("loads session state via /sessions/{id}", async () => {
    await fetchSessionState("sess-1");
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/sessions/sess-1"), expect.any(Object));
  });

  it("loads agent registry endpoints", async () => {
    await fetchAgents();
    await fetchAgentCard("clarifier");
    await addAgent("Weather", "http://localhost:8999");
    await removeAgent("custom-weather");

    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/agents"), expect.any(Object));
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/agents/clarifier/card"), expect.any(Object));
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/agents/custom-weather"), expect.any(Object));
  });

  it("creates EventSource for discovery stream", () => {
    const eventSourceMock = vi.fn(() => ({ close: vi.fn() }));
    vi.stubGlobal("EventSource", eventSourceMock);

    subscribeDiscovery("sess-1");

    expect(eventSourceMock).toHaveBeenCalledWith(expect.stringContaining("/sessions/sess-1/discovery/stream"));
  });

  it("creates EventSource for chat stream", () => {
    const eventSourceMock = vi.fn(() => ({ close: vi.fn() }));
    vi.stubGlobal("EventSource", eventSourceMock);

    streamChat("hello", "sess-1");

    expect(eventSourceMock).toHaveBeenCalledWith(expect.stringContaining("/chat/stream"));
    expect(eventSourceMock).toHaveBeenCalledWith(expect.stringContaining("session_id=sess-1"));
  });
});
