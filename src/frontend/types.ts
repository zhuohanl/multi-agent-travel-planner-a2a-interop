export type ChatRole = "user" | "assistant" | "agent" | "system";

export type WorkflowPhase =
  | "clarification"
  | "discovery_in_progress"
  | "discovery_planning"
  | "booking"
  | "completed";

export type AgentPhase = "intake" | "discover" | "synthesis" | "booking";

export type AgentStatus = "pending" | "running" | "completed" | "error" | "online" | "offline" | "unknown";

export type SessionStatus = "collecting" | "discovering" | "synthesizing" | "booking" | "completed" | "error";

export function mapWorkflowPhaseToSessionStatus(phase: string | null | undefined): SessionStatus {
  switch (phase) {
    case "clarification":
      return "collecting";
    case "discovery_in_progress":
      return "discovering";
    case "discovery_planning":
      return "synthesizing";
    case "booking":
      return "booking";
    case "completed":
      return "completed";
    default:
      return "collecting";
  }
}

export function mapWorkflowPhaseToAgentPhase(phase: string | null | undefined): AgentPhase {
  switch (phase) {
    case "clarification":
      return "intake";
    case "discovery_in_progress":
      return "discover";
    case "discovery_planning":
      return "synthesis";
    case "booking":
    case "completed":
    default:
      return "booking";
  }
}

export interface WorkflowEvent {
  type: string;
  checkpoint_id?: string;
  booking?: {
    booking_id: string;
    quote_id?: string;
  };
  agent_id?: string;
}

export interface PendingAction {
  event: WorkflowEvent;
  label: string;
  description?: string;
}

export interface SessionMessage {
  id: string;
  role: string;
  sender: string;
  content: string;
  created_at: string;
}

export interface AgentStatusEntry {
  agent_id: string;
  status: string;
  message?: string;
  type?: string;
  [key: string]: unknown;
}

export interface SessionState {
  session_id: string;
  phase: string | null;
  checkpoint: string | null;
  messages: SessionMessage[];
  pending_actions: PendingAction[];
  agent_statuses: AgentStatusEntry[];
  itinerary?: DraftItinerary | Record<string, unknown> | null;
  text_input_enabled: boolean;
}

export interface RegisteredAgent {
  agentId: string;
  name: string;
  type: "orchestrator" | "discovery" | "planning" | "booking" | "custom";
  status: "online" | "offline" | "unknown";
  url: string;
  capabilities: string[];
  lastActivity?: string;
}

export interface AgentCardSkill {
  id: string;
  name: string;
  description: string;
  tags: string[];
}

export interface AgentCard {
  name: string;
  description: string;
  version: string;
  url: string;
  protocolVersion: string;
  skills: AgentCardSkill[];
  capabilities: Record<string, boolean>;
  defaultInputModes: string[];
  defaultOutputModes: string[];
}

export interface TripSpec {
  destination_city: string;
  start_date: string;
  end_date: string;
  num_travelers: number;
  budget_per_person: number;
  budget_currency: string;
  origin_city: string;
  interests: string[];
  constraints: string[];
}

export interface Slot {
  time: "AM" | "PM" | "EVE" | string;
  place: string;
  mapUrl?: string | null;
  url?: string | null;
  walkMins?: number | null;
  train?: string | null;
}

export interface DayPlan {
  day: number;
  theme?: string | null;
  slots: Slot[];
}

export interface DraftItinerary {
  tripId: string;
  tripSequence: number;
  createdAt: string;
  days: DayPlan[];
  budget: {
    target: number;
    currency: string;
    total: number;
    lodging: number;
    food: number;
    activities: number;
    transport?: number | null;
  };
  deltas: Array<{ type: "over" | "under"; amount: number; where: string }>;
  suggestions: Array<Record<string, unknown>>;
  budgetStatus: string;
  validated: boolean;
  violations: Array<Record<string, unknown>>;
  nextHandoff: string[];
}

export interface AgentTask {
  id: string;
  name: string;
  phase: AgentPhase;
  status: AgentStatus;
  description?: string | null;
  headline?: string | null;
  progress?: number | null;
}

export interface TripDetails {
  destination: string;
  dates: string;
  travelers: number;
  budget: string;
  vibe: string[];
  origin: string;
}
