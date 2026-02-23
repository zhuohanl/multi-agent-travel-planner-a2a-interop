import type { RegisteredAgent } from "../types";

export function buildAgentCardValidationUrl(url: string): string {
  const trimmed = url.trim().replace(/\/+$/, "");
  return `${trimmed}/.well-known/agent.json`;
}

export function canRemoveAgent(type: RegisteredAgent["type"]): boolean {
  return type === "custom";
}

export function statusBadgeClass(status: RegisteredAgent["status"]): "online" | "offline" | "unknown" {
  if (status === "online") {
    return "online";
  }
  if (status === "offline") {
    return "offline";
  }
  return "unknown";
}
