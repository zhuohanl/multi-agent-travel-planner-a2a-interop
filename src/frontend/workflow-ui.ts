import type {
  AgentPhase,
  AgentStatus,
  AgentStatusEntry,
  AgentTask,
  PendingAction,
  RegisteredAgent,
} from "./types";

const PHASE_LABELS: Record<string, string> = {
  clarification: "Clarification",
  discovery_in_progress: "Discovery",
  discovery_planning: "Planning",
  booking: "Booking",
  completed: "Completed",
};

const PHASE_ORDER: Record<AgentPhase, number> = {
  intake: 0,
  discover: 1,
  synthesis: 2,
  booking: 3,
};

const DEFAULT_AGENT_CATALOG: Array<{ id: string; name: string; phase: AgentPhase }> = [
  { id: "orchestrator", name: "Orchestrator", phase: "intake" },
  { id: "clarifier", name: "Clarifier", phase: "discover" },
  { id: "transport", name: "Transport", phase: "discover" },
  { id: "stay", name: "Stay", phase: "discover" },
  { id: "poi", name: "POI", phase: "discover" },
  { id: "events", name: "Events", phase: "discover" },
  { id: "dining", name: "Dining", phase: "discover" },
  { id: "aggregator", name: "Aggregator", phase: "synthesis" },
  { id: "budget", name: "Budget", phase: "synthesis" },
  { id: "route", name: "Route", phase: "synthesis" },
  { id: "validator", name: "Validator", phase: "synthesis" },
  { id: "booking", name: "Booking", phase: "booking" },
];

export interface DiscoveryProgressEvent {
  type?: string;
  agent?: string;
  stage?: string;
  message?: string;
  data?: Record<string, unknown> | null;
}

export function toDisplayPhase(phase: string | null | undefined): string {
  if (!phase) {
    return PHASE_LABELS.clarification;
  }
  return PHASE_LABELS[phase] ?? "Clarification";
}

export function shouldRenderItinerary(
  phase: string | null | undefined,
  itinerary: Record<string, unknown> | null | undefined
): boolean {
  if (!itinerary) {
    return false;
  }
  return phase === "discovery_planning" || phase === "booking" || phase === "completed";
}

export function isBookingFlowComplete(
  phase: string | null | undefined,
  pendingActions: PendingAction[],
  bookingActionsTriggered: number
): boolean {
  if (bookingActionsTriggered <= 0) {
    return false;
  }

  const hasBookItemActions = pendingActions.some((action) => action.event.type === "book_item");
  if (hasBookItemActions) {
    return false;
  }

  return phase === "completed";
}

export function hasStatusPendingAction(pendingActions: PendingAction[]): boolean {
  return pendingActions.some((action) => action.event.type === "status");
}

export function shouldAutoPollStatus(
  phase: string | null | undefined,
  checkpoint: string | null | undefined,
  _textInputEnabled: boolean | null | undefined,
  _pendingActions: PendingAction[]
): boolean {
  if (phase === "discovery_in_progress") {
    return true;
  }

  if (phase === "discovery_planning" && checkpoint !== "itinerary_approval") {
    return true;
  }

  return false;
}

export function parseDiscoveryEvent(raw: string): DiscoveryProgressEvent | null {
  try {
    const parsed = JSON.parse(raw) as DiscoveryProgressEvent;
    if (!parsed || typeof parsed !== "object") {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function applyDiscoveryProgressEvent(
  previous: Record<string, AgentTask>,
  event: DiscoveryProgressEvent
): Record<string, AgentTask> {
  const agentId = (event.agent || event.stage || "").trim();
  if (!agentId) {
    return previous;
  }

  const existing = previous[agentId];
  const nextStatus = mapProgressTypeToStatus(event.type, existing?.status ?? "pending");
  const nextTask: AgentTask = {
    id: agentId,
    name: existing?.name ?? humanizeAgentName(agentId),
    phase: existing?.phase ?? inferAgentPhase(agentId),
    status: nextStatus,
    description: event.message ?? existing?.description,
    headline: event.message ?? existing?.headline,
    progress: existing?.progress,
  };
  return {
    ...previous,
    [agentId]: nextTask,
  };
}

export function buildAgentTasks(
  statuses: AgentStatusEntry[],
  discoveryOverlay: Record<string, AgentTask>,
  registryAgents: RegisteredAgent[] = []
): AgentTask[] {
  const taskMap: Record<string, AgentTask> = {};

  for (const agent of DEFAULT_AGENT_CATALOG) {
    taskMap[agent.id] = {
      id: agent.id,
      name: agent.name,
      phase: agent.phase,
      status: "pending",
    };
  }

  for (const registryAgent of registryAgents) {
    taskMap[registryAgent.agentId] = {
      id: registryAgent.agentId,
      name: registryAgent.name || humanizeAgentName(registryAgent.agentId),
      phase: taskMap[registryAgent.agentId]?.phase || inferAgentPhase(registryAgent.agentId),
      status: normalizeRegistryStatus(registryAgent.status),
      description: registryAgent.url,
      headline: taskMap[registryAgent.agentId]?.headline,
      progress: taskMap[registryAgent.agentId]?.progress,
    };
  }

  for (const [agentId, overlay] of Object.entries(discoveryOverlay)) {
    taskMap[agentId] = {
      ...taskMap[agentId],
      ...overlay,
      id: agentId,
      phase: overlay.phase ?? inferAgentPhase(agentId),
      name: overlay.name || taskMap[agentId]?.name || humanizeAgentName(agentId),
    };
  }

  for (const status of statuses) {
    const agentId = String(status.agent_id || "");
    if (!agentId) {
      continue;
    }
    taskMap[agentId] = {
      id: agentId,
      name: taskMap[agentId]?.name || humanizeAgentName(agentId),
      phase: taskMap[agentId]?.phase || inferAgentPhase(agentId),
      status: normalizeAgentStatus(status.status),
      description: typeof status.message === "string" ? status.message : undefined,
      headline: typeof status.message === "string" ? status.message : undefined,
      progress: taskMap[agentId]?.progress,
    };
  }

  return Object.values(taskMap).sort((a, b) => {
    const phaseCompare = (PHASE_ORDER[a.phase] ?? 99) - (PHASE_ORDER[b.phase] ?? 99);
    if (phaseCompare !== 0) {
      return phaseCompare;
    }
    return a.name.localeCompare(b.name);
  });
}

export function groupAgentTasksByRole(tasks: AgentTask[]): {
  orchestrator: AgentTask[];
  discovery: AgentTask[];
  planning: AgentTask[];
  booking: AgentTask[];
} {
  const grouped = {
    orchestrator: [] as AgentTask[],
    discovery: [] as AgentTask[],
    planning: [] as AgentTask[],
    booking: [] as AgentTask[],
  };

  for (const task of tasks) {
    if (task.id === "orchestrator") {
      grouped.orchestrator.push(task);
      continue;
    }
    if (task.phase === "discover") {
      grouped.discovery.push(task);
      continue;
    }
    if (task.phase === "synthesis") {
      grouped.planning.push(task);
      continue;
    }
    grouped.booking.push(task);
  }

  const sortByName = (a: AgentTask, b: AgentTask) => a.name.localeCompare(b.name);
  grouped.orchestrator.sort(sortByName);
  grouped.discovery.sort(sortByName);
  grouped.planning.sort(sortByName);
  grouped.booking.sort(sortByName);

  return grouped;
}

export function inferAgentPhase(agentId: string): AgentPhase {
  if (agentId === "orchestrator") {
    return "intake";
  }
  if (["clarifier", "transport", "stay", "poi", "events", "dining"].includes(agentId)) {
    return "discover";
  }
  if (["aggregator", "budget", "route", "validator"].includes(agentId)) {
    return "synthesis";
  }
  return "booking";
}

function mapProgressTypeToStatus(type: string | undefined, fallback: AgentStatus): AgentStatus {
  switch (type) {
    case "agent_started":
    case "agent_progress":
    case "pipeline_stage_started":
    case "job_started":
      return "running";
    case "agent_completed":
    case "pipeline_stage_completed":
    case "job_completed":
      return "completed";
    case "agent_failed":
    case "agent_timeout":
    case "job_failed":
      return "error";
    default:
      return fallback;
  }
}

function normalizeAgentStatus(raw: string): AgentStatus {
  const normalized = raw.toLowerCase();
  if (["running", "in_progress", "processing"].includes(normalized)) {
    return "running";
  }
  if (["completed", "success", "succeeded", "done"].includes(normalized)) {
    return "completed";
  }
  if (["failed", "error", "timeout"].includes(normalized)) {
    return "error";
  }
  if (normalized === "online") {
    return "online";
  }
  if (normalized === "offline") {
    return "offline";
  }
  if (normalized === "unknown") {
    return "unknown";
  }
  return "pending";
}

function normalizeRegistryStatus(status: RegisteredAgent["status"]): AgentStatus {
  if (status === "online") {
    return "online";
  }
  if (status === "offline") {
    return "offline";
  }
  return "unknown";
}

function humanizeAgentName(agentId: string): string {
  return agentId
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
