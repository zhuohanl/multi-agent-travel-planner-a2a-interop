import type { AgentCard, RegisteredAgent, SessionState, WorkflowEvent } from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:10000").replace(/\/+$/, "");

function buildUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}${normalizedPath}`;
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const message = await res.text();
    throw new Error(message || `Request failed with status ${res.status}`);
  }
  return (await res.json()) as T;
}

export interface ChatResponse {
  message: string;
  session_id: string;
  consultation_id?: string | null;
  data?: Record<string, unknown> | null;
}

export interface ChatStreamChunk {
  message: string;
  session_id: string;
  consultation_id?: string | null;
  is_complete: boolean;
  require_user_input: boolean;
  data?: Record<string, unknown> | null;
}

export interface ChatStreamHandlers {
  onChunk?: (chunk: ChatStreamChunk) => void;
  onComplete?: () => void;
  onError?: (error: unknown) => void;
}

export interface ChatStreamSubscription {
  close: () => void;
  done: Promise<void>;
}

export interface AddAgentResponse extends RegisteredAgent {}

interface DiscoveryReconnectResponse {
  status: string;
  stream_url?: string | null;
  message: string;
  itinerary_draft?: Record<string, unknown> | null;
  gaps?: Array<Record<string, unknown>> | null;
  checkpoint?: string | null;
  current_progress?: Record<string, unknown> | null;
}

export interface DiscoveryEventHandlers {
  onMessage?: (event: MessageEvent<string>) => void;
  onOpen?: (event: Event) => void;
  onError?: (event: Event) => void;
  onReconnect?: (status: DiscoveryReconnectResponse) => void;
  onReconnectFailed?: (error: unknown) => void;
}

export interface DiscoverySubscription {
  close: () => void;
  source: EventSource;
}

export async function createSession(message: string): Promise<ChatResponse> {
  const res = await fetch(buildUrl("/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  return handleResponse<ChatResponse>(res);
}

export async function sendMessage(sessionId: string, message: string): Promise<ChatResponse> {
  const res = await fetch(buildUrl("/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
  });
  return handleResponse<ChatResponse>(res);
}

export function streamChat(
  message: string,
  sessionId: string,
  handlers: ChatStreamHandlers = {}
): ChatStreamSubscription {
  const url = new URL(buildUrl("/chat/stream"));
  url.searchParams.set("message", message);
  url.searchParams.set("session_id", sessionId);

  let closed = false;
  let completed = false;
  let receivedAnyChunk = false;
  let resolveDone: () => void = () => {};
  let rejectDone: (reason?: unknown) => void = () => {};

  const done = new Promise<void>((resolve, reject) => {
    resolveDone = resolve;
    rejectDone = reject;
  });

  const source = new EventSource(url.toString());

  const completeSuccessfully = () => {
    if (closed || completed) {
      return;
    }
    completed = true;
    source.close();
    handlers.onComplete?.();
    resolveDone();
  };

  const completeWithError = (error: unknown) => {
    if (closed || completed) {
      return;
    }
    completed = true;
    source.close();
    handlers.onError?.(error);
    rejectDone(error);
  };

  source.onmessage = (event) => {
    if (closed || completed) {
      return;
    }
    try {
      const chunk = JSON.parse(event.data) as ChatStreamChunk;
      receivedAnyChunk = true;
      handlers.onChunk?.(chunk);
      if (chunk.is_complete) {
        completeSuccessfully();
      }
    } catch (err) {
      completeWithError(err);
    }
  };

  source.onerror = (event) => {
    if (closed || completed) {
      return;
    }
    if (receivedAnyChunk) {
      completeSuccessfully();
      return;
    }
    completeWithError(event);
  };

  return {
    close: () => {
      if (closed || completed) {
        return;
      }
      closed = true;
      source.close();
      resolveDone();
    },
    done,
  };
}

export async function sendEvent(sessionId: string, event: WorkflowEvent): Promise<SessionState> {
  const res = await fetch(buildUrl(`/sessions/${encodeURIComponent(sessionId)}/event`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(event),
  });
  return handleResponse<SessionState>(res);
}

export async function fetchSessionState(sessionId: string): Promise<SessionState> {
  const res = await fetch(buildUrl(`/sessions/${encodeURIComponent(sessionId)}`), {
    method: "GET",
  });
  return handleResponse<SessionState>(res);
}

export async function fetchAgents(): Promise<RegisteredAgent[]> {
  const res = await fetch(buildUrl("/agents"), { method: "GET" });
  return handleResponse<RegisteredAgent[]>(res);
}

export async function fetchAgentCard(agentId: string): Promise<AgentCard> {
  const res = await fetch(buildUrl(`/agents/${encodeURIComponent(agentId)}/card`), { method: "GET" });
  return handleResponse<AgentCard>(res);
}

export async function addAgent(name: string, url: string): Promise<AddAgentResponse> {
  const res = await fetch(buildUrl("/agents"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, url }),
  });
  return handleResponse<AddAgentResponse>(res);
}

export async function removeAgent(agentId: string): Promise<{ deleted: boolean; agent_id: string }> {
  const res = await fetch(buildUrl(`/agents/${encodeURIComponent(agentId)}`), {
    method: "DELETE",
  });
  return handleResponse<{ deleted: boolean; agent_id: string }>(res);
}

export function subscribeDiscovery(
  sessionId: string,
  handlers: DiscoveryEventHandlers = {}
): DiscoverySubscription {
  const streamUrl = buildUrl(`/sessions/${encodeURIComponent(sessionId)}/discovery/stream`);
  const reconnectUrl = buildUrl(`/sessions/${encodeURIComponent(sessionId)}/discovery/reconnect`);

  let closed = false;
  let reconnecting = false;
  let source = new EventSource(streamUrl);

  const attachHandlers = (eventSource: EventSource) => {
    eventSource.onopen = (event) => {
      handlers.onOpen?.(event);
    };

    eventSource.onmessage = (event) => {
      handlers.onMessage?.(event);
    };

    eventSource.onerror = (event) => {
      handlers.onError?.(event);
      if (!reconnecting) {
        void reconnect();
      }
    };
  };

  const reconnect = async () => {
    if (closed || reconnecting) {
      return;
    }
    reconnecting = true;

    try {
      const res = await fetch(reconnectUrl, { method: "GET" });
      const status = await handleResponse<DiscoveryReconnectResponse>(res);
      handlers.onReconnect?.(status);

      if (closed || !status.stream_url) {
        return;
      }

      const resolvedUrl = new URL(status.stream_url, `${API_BASE}/`).toString();
      source.close();
      source = new EventSource(resolvedUrl);
      attachHandlers(source);
    } catch (error) {
      handlers.onReconnectFailed?.(error);
    } finally {
      reconnecting = false;
    }
  };

  attachHandlers(source);
  return {
    source,
    close: () => {
      closed = true;
      source.close();
    },
  };
}
