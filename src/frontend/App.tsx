import React, { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Mic, Plus, Send } from "lucide-react";

import {
  fetchAgents,
  fetchSessionState,
  sendEvent,
  streamChat,
  subscribeDiscovery,
  type ChatStreamChunk,
} from "./api";
import { AgentDashboard } from "./components/AgentDashboard";
import { AgentRegistry } from "./components/AgentRegistry";
import { Header } from "./components/Header";
import { Itinerary } from "./components/Itinerary";
import { Sidebar } from "./components/Sidebar";
import { SuggestionCards } from "./components/SuggestionCards";
import type {
  AgentTask,
  PendingAction,
  RegisteredAgent,
  SessionMessage,
  SessionState,
} from "./types";
import {
  applyDiscoveryProgressEvent,
  buildAgentTasks,
  isBookingFlowComplete,
  parseDiscoveryEvent,
  shouldAutoPollStatus,
  shouldRenderItinerary,
  toDisplayPhase,
} from "./workflow-ui";

const POLL_INTERVAL_MS = 3000;
const AGENT_POLL_INTERVAL_MS = 30000;
const STATUS_AUTO_POLL_INTERVAL_MS = 5000;
const DISCOVERY_EVENT_TYPES = [
  "state",
  "job_started",
  "job_completed",
  "job_failed",
  "job_cancelled",
  "agent_started",
  "agent_progress",
  "agent_completed",
  "agent_failed",
  "agent_timeout",
  "pipeline_stage_started",
  "pipeline_stage_completed",
];

const WORKFLOW_PHASES = [
  { id: "clarification", label: "Clarification" },
  { id: "discovery_in_progress", label: "Discovery" },
  { id: "discovery_planning", label: "Planning" },
  { id: "booking", label: "Booking" },
  { id: "completed", label: "Completed" },
];

function phaseIndex(phase: string | null | undefined): number {
  const idx = WORKFLOW_PHASES.findIndex((item) => item.id === phase);
  return idx >= 0 ? idx : 0;
}

function generateId(prefix: string): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`;
}

function TravelPlanner() {
  const [isSidebarOpen, setSidebarOpen] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [activeView, setActiveView] = useState<"chat" | "registry">("chat");
  const [inputValue, setInputValue] = useState("");
  const [session, setSession] = useState<SessionState | null>(null);
  const [discoveryOverlay, setDiscoveryOverlay] = useState<Record<string, AgentTask>>({});
  const [registryAgents, setRegistryAgents] = useState<RegisteredAgent[]>([]);
  const [bookActionsTriggered, setBookActionsTriggered] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [persistedItinerary, setPersistedItinerary] = useState<Record<string, unknown> | null>(null);
  const [persistedItinerarySessionId, setPersistedItinerarySessionId] = useState<string | null>(null);
  const [itineraryAnchorMessageId, setItineraryAnchorMessageId] = useState<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const statusAutoPollInFlightRef = useRef(false);

  const hasStarted = Boolean(session);
  const messages: SessionMessage[] = session?.messages ?? [];
  const pendingActions: PendingAction[] = session?.pending_actions ?? [];
  const currentPhase = session?.phase ?? "clarification";
  const currentCheckpoint = session?.checkpoint ?? null;
  const currentPhaseIndex = phaseIndex(currentPhase);
  const canSendText = !session || session.text_input_enabled;
  const bookingActions = pendingActions.filter((action) => action.event.type === "book_item");
  const sessionItinerary = useMemo(
    () => (session?.itinerary && typeof session.itinerary === "object" ? session.itinerary : null),
    [session?.itinerary]
  );
  const itinerary =
    session?.session_id && persistedItinerarySessionId === session.session_id
      ? sessionItinerary ?? persistedItinerary
      : sessionItinerary;
  const showItinerary = shouldRenderItinerary(currentPhase, itinerary ?? null) && itinerary !== null;
  const showBookingSummary =
    session !== null &&
    isBookingFlowComplete(session.phase, session.pending_actions, bookActionsTriggered);
  const itineraryAnchorExists = itineraryAnchorMessageId
    ? messages.some((message) => message.id === itineraryAnchorMessageId)
    : false;
  const autoStatusPollingEnabled = shouldAutoPollStatus(
    currentPhase,
    currentCheckpoint,
    session?.text_input_enabled ?? true,
    pendingActions
  );
  const showAutoStatusPollingHint = autoStatusPollingEnabled;
  const agents = useMemo(
    () => buildAgentTasks(session?.agent_statuses ?? [], discoveryOverlay, registryAgents),
    [session?.agent_statuses, discoveryOverlay, registryAgents]
  );

  useEffect(() => {
    if (!session?.session_id) {
      setPersistedItinerary(null);
      setPersistedItinerarySessionId(null);
      setItineraryAnchorMessageId(null);
      return;
    }

    if (persistedItinerarySessionId && persistedItinerarySessionId !== session.session_id) {
      setPersistedItinerary(null);
      setPersistedItinerarySessionId(null);
      setItineraryAnchorMessageId(null);
    }

    if (sessionItinerary) {
      setPersistedItinerary(sessionItinerary);
      setPersistedItinerarySessionId(session.session_id);
    }
  }, [session?.session_id, sessionItinerary, persistedItinerarySessionId]);

  useEffect(() => {
    if (!showItinerary || itineraryAnchorMessageId || messages.length === 0) {
      return;
    }

    const anchorCandidate =
      [...messages].reverse().find((message) => message.role !== "user") ??
      messages[messages.length - 1];

    if (anchorCandidate) {
      setItineraryAnchorMessageId(anchorCandidate.id);
    }
  }, [showItinerary, itineraryAnchorMessageId, messages]);

  useEffect(() => {
    let cancelled = false;
    const loadRegistryAgents = async () => {
      try {
        const list = await fetchAgents();
        if (!cancelled) {
          setRegistryAgents(list);
        }
      } catch {
        // Ignore background registry errors in chat workflow.
      }
    };

    void loadRegistryAgents();
    const interval = window.setInterval(() => {
      void loadRegistryAgents();
    }, AGENT_POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    if (!session?.session_id || isSubmitting) {
      return;
    }
    let cancelled = false;

    const refreshSession = async () => {
      try {
        const nextState = await fetchSessionState(session.session_id);
        if (!cancelled) {
          setSession(nextState);
        }
      } catch (err) {
        if (!cancelled) {
          setError((err as Error).message);
        }
      }
    };

    const interval = window.setInterval(() => {
      void refreshSession();
    }, POLL_INTERVAL_MS);
    void refreshSession();

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [session?.session_id, isSubmitting]);

  useEffect(() => {
    if (!session?.session_id || session.phase !== "discovery_in_progress") {
      return;
    }

    const onDiscoveryMessage = (raw: string) => {
      const parsed = parseDiscoveryEvent(raw);
      if (!parsed) {
        return;
      }
      setDiscoveryOverlay((previous) => applyDiscoveryProgressEvent(previous, parsed));
    };

    const subscription = subscribeDiscovery(session.session_id, {
      onMessage: (event) => onDiscoveryMessage(event.data),
      onReconnectFailed: (err) => setError((err as Error).message),
    });

    const typedListener = (event: Event) => {
      const messageEvent = event as MessageEvent<string>;
      onDiscoveryMessage(messageEvent.data);
    };

    for (const eventType of DISCOVERY_EVENT_TYPES) {
      subscription.source.addEventListener(eventType, typedListener as EventListener);
    }

    return () => {
      for (const eventType of DISCOVERY_EVENT_TYPES) {
        subscription.source.removeEventListener(eventType, typedListener as EventListener);
      }
      subscription.close();
    };
  }, [session?.session_id, session?.phase]);

  useEffect(() => {
    if (!session?.session_id || !autoStatusPollingEnabled) {
      return;
    }

    let cancelled = false;

    const pollStatus = async () => {
      if (cancelled || statusAutoPollInFlightRef.current || isSubmitting) {
        return;
      }
      statusAutoPollInFlightRef.current = true;
      try {
        const updatedState = await sendEvent(session.session_id, { type: "status" });
        if (!cancelled) {
          setSession(updatedState);
        }
      } catch (err) {
        if (!cancelled) {
          setError((err as Error).message);
        }
      } finally {
        statusAutoPollInFlightRef.current = false;
      }
    };

    const interval = window.setInterval(() => {
      void pollStatus();
    }, STATUS_AUTO_POLL_INTERVAL_MS);

    void pollStatus();

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [session?.session_id, autoStatusPollingEnabled, isSubmitting]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, pendingActions.length]);

  const handleSendMessage = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) {
      return;
    }
    setError(null);
    setInfo(null);
    setIsSubmitting(true);

    try {
      if (session && !session.text_input_enabled) {
        setInfo("Choose one of the pending actions to continue.");
        return;
      }

      setInputValue("");

      const streamTextTurn = async (
        sessionId: string,
        assistantMessageId: string
      ): Promise<void> => {
        const subscription = streamChat(trimmed, sessionId, {
          onChunk: (chunk: ChatStreamChunk) => {
            const content = (chunk.message || "").trim();
            if (!content) {
              return;
            }
            setSession((previous) => {
              if (!previous || previous.session_id !== sessionId) {
                return previous;
              }
              const existingIndex = previous.messages.findIndex((msg) => msg.id === assistantMessageId);
              const nextAssistantMessage: SessionMessage = {
                id: assistantMessageId,
                role: "assistant",
                sender: "Orchestrator",
                content,
                created_at: new Date().toISOString(),
              };
              if (existingIndex < 0) {
                return {
                  ...previous,
                  messages: [...previous.messages, nextAssistantMessage],
                };
              }
              const messages = [...previous.messages];
              messages[existingIndex] = nextAssistantMessage;
              return { ...previous, messages };
            });
          },
        });

        try {
          await subscription.done;
        } finally {
          subscription.close();
        }
      };

      if (!session) {
        const sessionId = generateId("sess");
        const userMessageId = generateId("msg-user");
        const assistantMessageId = generateId("msg-assistant");

        setSession({
          session_id: sessionId,
          phase: "clarification",
          checkpoint: null,
          messages: [
            {
              id: userMessageId,
              role: "user",
              sender: "You",
              content: trimmed,
              created_at: new Date().toISOString(),
            },
          ],
          pending_actions: [],
          agent_statuses: [],
          itinerary: null,
          text_input_enabled: false,
        });
        setInfo("Connecting to the orchestrator...");
        await streamTextTurn(sessionId, assistantMessageId);

        const sessionState = await fetchSessionState(sessionId);
        setSession(sessionState);
        setInfo(null);
      } else {
        const sessionId = session.session_id;
        const userMessageId = generateId("msg-user");
        const assistantMessageId = generateId("msg-assistant");
        const userMessage: SessionMessage = {
          id: userMessageId,
          role: "user",
          sender: "You",
          content: trimmed,
          created_at: new Date().toISOString(),
        };

        setSession((previous) => {
          if (!previous || previous.session_id !== sessionId) {
            return previous;
          }
          return {
            ...previous,
            messages: [...previous.messages, userMessage],
            text_input_enabled: false,
          };
        });
        setInfo("Sending message...");

        await streamTextTurn(sessionId, assistantMessageId);

        const sessionState = await fetchSessionState(sessionId);
        setSession(sessionState);
        setInfo(null);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleAction = async (action: PendingAction) => {
    if (!session) {
      return;
    }
    setError(null);
    setInfo(null);
    setIsSubmitting(true);
    try {
      if (action.event.type === "book_item") {
        setBookActionsTriggered((count) => count + 1);
      }
      const updatedState = await sendEvent(session.session_id, action.event);
      setSession(updatedState);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const resetChat = () => {
    setSession(null);
    setDiscoveryOverlay({});
    setBookActionsTriggered(0);
    setInputValue("");
    setError(null);
    setInfo(null);
    setPersistedItinerary(null);
    setPersistedItinerarySessionId(null);
    setItineraryAnchorMessageId(null);
  };

  return (
    <div className="h-screen flex flex-col bg-cover bg-center bg-no-repeat bg-fixed overflow-hidden font-sans text-slate-900 relative">
      <div className="fixed inset-0 -z-10">
        <img
          alt="background"
          className="w-full h-full object-cover"
          src="https://lh3.googleusercontent.com/aida-public/AB6AXuC_Cmz-0noNwGyCSJzVJv1WPmjVRbMSlyseB1F3C7GtI4M-ZMPD83pviVBw1hmnWc3y8OMq0oRcZ5iuM3NwfF7n8-fQZU39VEgVPvKq0ynbjqSPDOYlxsFPUt0lkEU0EiLQJf_Uz0PRVqMR9zLhU8X4sP_f3ud2vK1uFAeFViZYFptgyV9sp_104mv3IGnWUT_Ib8YfgDW0llEyjdhuQg57TDtxFFU5oAD1vBh7Lbze1Txh_rm7YLe0fvFE2WutZmq75P0rXW9to_Tm"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-black/10 via-transparent to-black/10"></div>
      </div>

      <div className="relative z-10 flex flex-col h-full">
        <Header
          isAuthenticated={isAuthenticated}
          onLogin={() => setIsAuthenticated(true)}
          onLogout={() => setIsAuthenticated(false)}
          activeView={activeView}
          onChangeView={setActiveView}
        />

        {session && activeView === "chat" && (
          <div className="bg-cyan-950/85 backdrop-blur-md text-white py-4 px-6 shadow-xl border-t border-white/10">
            <div className="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center gap-4">
              <div>
                <div className="text-[10px] font-bold tracking-[0.2em] text-sky-400 uppercase">Workflow</div>
                <h2 className="text-xl font-bold">{toDisplayPhase(currentPhase)}</h2>
                {currentCheckpoint && (
                  <div className="text-xs text-slate-200 mt-1">
                    Checkpoint: <span className="font-semibold">{currentCheckpoint}</span>
                  </div>
                )}
              </div>
              <div className="flex flex-wrap gap-2 md:ml-auto">
                {WORKFLOW_PHASES.map((phase, idx) => {
                  const active = idx <= currentPhaseIndex;
                  return (
                    <div
                      key={phase.id}
                      className={`px-3 py-1 rounded-full text-[10px] tracking-wider font-bold uppercase border ${
                        active
                          ? "bg-sky-500/30 border-sky-300/80 text-white"
                          : "bg-white/5 border-white/20 text-slate-300"
                      }`}
                    >
                      {phase.label}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        <div className="flex flex-1 overflow-hidden">
          {isAuthenticated && (
            <Sidebar
              isOpen={isSidebarOpen}
              toggleSidebar={() => setSidebarOpen(!isSidebarOpen)}
              onNewChat={resetChat}
              isAuthenticated={isAuthenticated}
            />
          )}

          <main className="flex-1 flex flex-col relative bg-transparent w-full">
            {activeView === "chat" ? (
              <>
                <div className="flex-1 overflow-y-auto scrollbar-hide">
                  <div className="max-w-5xl mx-auto min-h-full flex flex-col px-4 md:px-8 pb-8">
                    {!hasStarted ? (
                      <div className="flex-grow flex flex-col justify-center items-center pb-20">
                        <div className="text-center mb-8 animate-fade-in">
                          <h1 className="text-5xl md:text-6xl font-bold text-white leading-tight drop-shadow-lg">
                            Discover and Enjoy <br /> Your new Places and <br /> Experiences
                          </h1>
                          <p className="mt-4 text-lg text-white/90 font-medium drop-shadow-md">Lets plan your trip</p>
                        </div>
                        <SuggestionCards onSelect={(text) => void handleSendMessage(text)} />
                      </div>
                    ) : (
                      <div className="space-y-8 py-10 pb-36">
                        {info && (
                          <div className="bg-white/10 border border-white/20 text-white px-4 py-3 rounded-xl text-sm backdrop-blur-md">
                            {info}
                          </div>
                        )}
                        {error && (
                          <div className="bg-rose-500/20 border border-rose-400/40 text-rose-50 px-4 py-3 rounded-xl text-sm backdrop-blur-md">
                            {error}
                          </div>
                        )}

                        {messages.map((message) => {
                          const isUser = message.role === "user";
                          const isSystem = message.role === "system";
                          return (
                            <React.Fragment key={message.id}>
                              <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
                                <div className={`max-w-[85%] ${isUser ? "order-2" : "order-1"}`}>
                                  {isUser ? (
                                    <div className="relative">
                                      <div className="bg-white/90 backdrop-blur-sm border border-white/50 text-slate-900 rounded-2xl rounded-tr-none px-8 py-5 shadow-sm text-lg font-medium">
                                        {message.content}
                                      </div>
                                      <div className="text-[10px] text-white font-bold uppercase mt-2 text-right mr-1 drop-shadow-md">
                                        You
                                      </div>
                                    </div>
                                  ) : (
                                    <div className="animate-fade-in">
                                      <div
                                        className={`border rounded-2xl px-8 py-6 shadow-sm text-lg font-medium leading-relaxed backdrop-blur-md max-h-72 overflow-auto whitespace-pre-wrap break-words ${
                                          isSystem
                                            ? "bg-black/40 border-white/20 text-white"
                                            : "bg-white/90 border-white/50 text-slate-900"
                                        }`}
                                      >
                                        {message.content}
                                      </div>
                                      <div className="text-[10px] text-white font-bold uppercase mt-2 ml-1 drop-shadow-md">
                                        {message.sender || "Orchestrator"}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              </div>
                              {showItinerary && itinerary && itineraryAnchorMessageId === message.id && (
                                <div className="animate-fade-in">
                                  <Itinerary itinerary={itinerary} />
                                </div>
                              )}
                            </React.Fragment>
                          );
                        })}

                        {showItinerary && itinerary && !itineraryAnchorExists && (
                          <div className="animate-fade-in">
                            <Itinerary itinerary={itinerary} />
                          </div>
                        )}

                        {pendingActions.length > 0 && (
                          <div className="bg-black/35 border border-white/20 rounded-2xl p-4 md:p-5 backdrop-blur-md text-white">
                            <div className="text-[10px] font-bold tracking-[0.15em] uppercase text-sky-300">Next Actions</div>
                            {showAutoStatusPollingHint && (
                              <div className="text-xs text-slate-200 mt-2">
                                Auto-refresh is on. We are checking progress and will update this chat when the itinerary is ready.
                              </div>
                            )}
                            <div className="flex flex-wrap gap-2 mt-3">
                              {pendingActions.map((action, index) => {
                                const isBookingAction = action.event.type === "book_item";
                                return (
                                  <button
                                    key={`${action.label}-${index}`}
                                    onClick={() => void handleAction(action)}
                                    disabled={isSubmitting}
                                    className={`px-3 py-2 rounded-lg text-sm font-semibold border transition-colors ${
                                      isBookingAction
                                        ? "bg-emerald-500/25 border-emerald-300/60 hover:bg-emerald-500/35"
                                        : "bg-white/10 border-white/30 hover:bg-white/20"
                                    } disabled:opacity-60`}
                                  >
                                    {action.label}
                                  </button>
                                );
                              })}
                            </div>
                            {bookingActions.length > 0 && (
                              <div className="text-xs text-slate-200 mt-3">
                                Booking step: choose each item and continue until confirmations are complete.
                              </div>
                            )}
                          </div>
                        )}

                        {showBookingSummary && (
                          <div className="bg-emerald-500/20 border border-emerald-300/50 text-emerald-50 px-4 py-3 rounded-xl text-sm backdrop-blur-md">
                            Booking complete. All selected items are confirmed and ready.
                          </div>
                        )}

                        <div ref={chatEndRef} />
                      </div>
                    )}
                  </div>
                </div>

                {hasStarted && (
                  <div className="p-6 bg-transparent absolute bottom-0 left-0 right-0 z-10">
                    <div className="max-w-4xl mx-auto relative group animate-fade-in">
                      <div className="absolute inset-0 bg-white/40 backdrop-blur-xl rounded-3xl shadow-lg border border-white/40" />
                      <div className="relative z-10 flex items-center p-2">
                        <button className="text-slate-600 hover:text-sky-600 p-3 rounded-xl transition-colors hover:bg-white/50">
                          <Plus size={20} />
                        </button>
                        <button className="text-slate-600 hover:text-sky-600 p-3 rounded-xl transition-colors hover:bg-white/50">
                          <Mic size={20} />
                        </button>

                        <input
                          type="text"
                          value={inputValue}
                          onChange={(e) => setInputValue(e.target.value)}
                          onKeyDown={(e) => e.key === "Enter" && canSendText && void handleSendMessage(inputValue)}
                          placeholder={
                            canSendText
                              ? "Ask follow-up questions or adjust your plan..."
                              : "Choose a pending action to continue..."
                          }
                          autoComplete="off"
                          className="flex-1 bg-transparent border-none focus:ring-0 focus:outline-none text-slate-800 placeholder-slate-700 px-4 text-lg font-medium"
                          disabled={isSubmitting || !canSendText}
                        />

                        <button
                          onClick={() => void handleSendMessage(inputValue)}
                          disabled={!inputValue.trim() || !canSendText || isSubmitting}
                          className="bg-sky-500 text-white p-3 rounded-xl hover:bg-sky-600 disabled:opacity-50 disabled:hover:bg-sky-500 transition-all transform hover:scale-105 shadow-md"
                        >
                          {isSubmitting ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="flex-1 overflow-hidden">
                <AgentRegistry />
              </div>
            )}
          </main>

          {activeView === "chat" && hasStarted && <AgentDashboard agents={agents} />}
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const searchParams = new URLSearchParams(window.location.search);
  if (searchParams.get("mode") === "itinerary") {
    return <Itinerary standalone={true} itinerary={null} />;
  }
  return <TravelPlanner />;
}
