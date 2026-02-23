import React, { useEffect, useState } from "react";
import { Eye, Plus, RefreshCw, Server, Trash2, X } from "lucide-react";

import { addAgent, fetchAgentCard, fetchAgents, removeAgent } from "../api";
import type { AgentCard, RegisteredAgent } from "../types";
import { buildAgentCardValidationUrl, canRemoveAgent, statusBadgeClass } from "./agent-registry-utils";

const REFRESH_INTERVAL_MS = 30000;

interface ValidationState {
  ok: boolean;
  message: string;
}

const STATUS_DOT_CLASS: Record<"online" | "offline" | "unknown", string> = {
  online: "bg-emerald-400 shadow-[0_0_8px_rgba(74,222,128,0.7)]",
  offline: "bg-rose-400 shadow-[0_0_8px_rgba(251,113,133,0.6)]",
  unknown: "bg-amber-300 shadow-[0_0_8px_rgba(252,211,77,0.5)]",
};

const TYPE_BADGE_CLASS: Record<RegisteredAgent["type"], string> = {
  orchestrator: "bg-sky-500/25 text-sky-100 border-sky-300/40",
  discovery: "bg-indigo-500/25 text-indigo-100 border-indigo-300/40",
  planning: "bg-cyan-500/25 text-cyan-100 border-cyan-300/40",
  booking: "bg-emerald-500/25 text-emerald-100 border-emerald-300/40",
  custom: "bg-amber-500/25 text-amber-100 border-amber-300/40",
};

export function AgentRegistry() {
  const [agents, setAgents] = useState<RegisteredAgent[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [showAddModal, setShowAddModal] = useState(false);
  const [newAgentName, setNewAgentName] = useState("");
  const [newAgentUrl, setNewAgentUrl] = useState("");
  const [validationState, setValidationState] = useState<ValidationState | null>(null);
  const [isTesting, setIsTesting] = useState(false);
  const [isAdding, setIsAdding] = useState(false);

  const [selectedAgent, setSelectedAgent] = useState<RegisteredAgent | null>(null);
  const [selectedCard, setSelectedCard] = useState<AgentCard | null>(null);
  const [isLoadingCard, setIsLoadingCard] = useState(false);

  const loadAgents = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const list = await fetchAgents();
      setAgents(list);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadAgents();
    const interval = window.setInterval(() => {
      void loadAgents();
    }, REFRESH_INTERVAL_MS);
    return () => {
      window.clearInterval(interval);
    };
  }, []);

  const handleOpenDetails = async (agent: RegisteredAgent) => {
    setSelectedAgent(agent);
    setSelectedCard(null);
    setIsLoadingCard(true);
    try {
      const card = await fetchAgentCard(agent.agentId);
      setSelectedCard(card);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setIsLoadingCard(false);
    }
  };

  const handleTestAgent = async () => {
    if (!newAgentUrl.trim()) {
      setValidationState({ ok: false, message: "Enter an agent URL first." });
      return;
    }
    setIsTesting(true);
    setValidationState(null);
    try {
      const cardUrl = buildAgentCardValidationUrl(newAgentUrl);
      const res = await fetch(cardUrl, { method: "GET" });
      if (!res.ok) {
        throw new Error(`Validation failed with status ${res.status}`);
      }
      const payload = (await res.json()) as Record<string, unknown>;
      const cardName = typeof payload.name === "string" ? payload.name : "Unknown";
      setValidationState({
        ok: true,
        message: `Card validated: ${cardName}`,
      });
    } catch (err) {
      setValidationState({
        ok: false,
        message: (err as Error).message,
      });
    } finally {
      setIsTesting(false);
    }
  };

  const handleAddAgent = async () => {
    if (!newAgentName.trim() || !newAgentUrl.trim()) {
      setValidationState({ ok: false, message: "Name and URL are required." });
      return;
    }
    setIsAdding(true);
    setError(null);
    try {
      await addAgent(newAgentName.trim(), newAgentUrl.trim());
      setShowAddModal(false);
      setNewAgentName("");
      setNewAgentUrl("");
      setValidationState(null);
      await loadAgents();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setIsAdding(false);
    }
  };

  const handleRemove = async (agent: RegisteredAgent) => {
    if (!canRemoveAgent(agent.type)) {
      return;
    }
    const confirmed = window.confirm(`Remove custom agent "${agent.name}"?`);
    if (!confirmed) {
      return;
    }
    try {
      await removeAgent(agent.agentId);
      await loadAgents();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="h-full overflow-y-auto p-6 md:p-8 text-white">
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="bg-black/35 border border-white/15 rounded-2xl p-5 md:p-6 backdrop-blur-md">
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div>
              <div className="text-[10px] font-bold tracking-[0.2em] uppercase text-sky-300">Agent Registry</div>
              <h2 className="text-2xl font-bold mt-1">Connected A2A Agents</h2>
              <p className="text-sm text-slate-200 mt-2">
                Custom agents are UI-visible only in v1 and do not alter orchestrator routing.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => void loadAgents()}
                className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-white/25 bg-white/10 hover:bg-white/20 text-sm font-semibold"
              >
                <RefreshCw size={14} />
                Refresh
              </button>
              <button
                onClick={() => setShowAddModal(true)}
                className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-sky-300/40 bg-sky-500/25 hover:bg-sky-500/35 text-sm font-semibold"
              >
                <Plus size={14} />
                Add Agent
              </button>
            </div>
          </div>
        </div>

        {error && (
          <div className="bg-rose-500/20 border border-rose-300/40 text-rose-50 px-4 py-3 rounded-xl text-sm">
            {error}
          </div>
        )}

        {isLoading ? (
          <div className="bg-black/25 border border-white/10 rounded-xl p-6 text-sm text-slate-200">Loading agents...</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {agents.map((agent) => {
              const badge = statusBadgeClass(agent.status);
              return (
                <div
                  key={agent.agentId}
                  className="bg-black/30 border border-white/15 rounded-xl p-4 backdrop-blur-md hover:bg-black/40 transition-colors"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h3 className="text-base font-bold text-white">{agent.name}</h3>
                      <p className="text-xs text-slate-300 mt-1 break-all">{agent.url}</p>
                    </div>
                    <span
                      className={`text-[10px] uppercase tracking-wider font-bold border px-2 py-1 rounded-full ${TYPE_BADGE_CLASS[agent.type]}`}
                    >
                      {agent.type}
                    </span>
                  </div>

                  <div className="flex items-center gap-2 mt-4">
                    <span className={`w-2.5 h-2.5 rounded-full ${STATUS_DOT_CLASS[badge]}`} />
                    <span className="text-xs uppercase tracking-wider text-slate-200">{agent.status}</span>
                  </div>

                  <div className="flex flex-wrap gap-1 mt-3">
                    {agent.capabilities.slice(0, 4).map((capability) => (
                      <span
                        key={`${agent.agentId}-${capability}`}
                        className="text-[10px] px-2 py-1 rounded-full bg-white/10 border border-white/15 text-slate-100"
                      >
                        {capability}
                      </span>
                    ))}
                  </div>

                  <div className="flex items-center justify-between mt-4 pt-3 border-t border-white/10">
                    <button
                      onClick={() => void handleOpenDetails(agent)}
                      className="inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1.5 rounded-md border border-white/20 bg-white/10 hover:bg-white/20"
                    >
                      <Eye size={12} />
                      Details
                    </button>
                    {canRemoveAgent(agent.type) ? (
                      <button
                        onClick={() => void handleRemove(agent)}
                        className="inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1.5 rounded-md border border-rose-300/35 bg-rose-500/20 hover:bg-rose-500/30"
                      >
                        <Trash2 size={12} />
                        Remove
                      </button>
                    ) : (
                      <span className="text-[11px] text-slate-400">Managed</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {showAddModal && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-lg bg-slate-950 border border-white/15 rounded-2xl p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-bold">Add Custom Agent</h3>
              <button onClick={() => setShowAddModal(false)} className="p-1 rounded hover:bg-white/10">
                <X size={16} />
              </button>
            </div>

            <div className="space-y-3">
              <label className="block text-xs uppercase tracking-wider text-slate-300">
                Agent Name
                <input
                  className="mt-1 w-full bg-black/30 border border-white/15 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sky-300/50"
                  value={newAgentName}
                  onChange={(event) => setNewAgentName(event.target.value)}
                  placeholder="Weather Agent"
                />
              </label>
              <label className="block text-xs uppercase tracking-wider text-slate-300">
                Base URL
                <input
                  className="mt-1 w-full bg-black/30 border border-white/15 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sky-300/50"
                  value={newAgentUrl}
                  onChange={(event) => setNewAgentUrl(event.target.value)}
                  placeholder="http://localhost:8999"
                />
              </label>
              {validationState && (
                <div
                  className={`text-xs px-3 py-2 rounded-lg border ${
                    validationState.ok
                      ? "bg-emerald-500/20 border-emerald-300/40 text-emerald-100"
                      : "bg-rose-500/20 border-rose-300/40 text-rose-100"
                  }`}
                >
                  {validationState.message}
                </div>
              )}
            </div>

            <div className="flex justify-end gap-2">
              <button
                onClick={() => void handleTestAgent()}
                className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-white/20 bg-white/10 hover:bg-white/20 text-sm font-semibold"
                disabled={isTesting}
              >
                <Server size={14} />
                {isTesting ? "Testing..." : "Test"}
              </button>
              <button
                onClick={() => void handleAddAgent()}
                className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-sky-300/45 bg-sky-500/25 hover:bg-sky-500/35 text-sm font-semibold"
                disabled={isAdding}
              >
                <Plus size={14} />
                {isAdding ? "Adding..." : "Add"}
              </button>
            </div>
          </div>
        </div>
      )}

      {selectedAgent && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-2xl bg-slate-950 border border-white/15 rounded-2xl p-5 space-y-4 max-h-[85vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-bold">{selectedAgent.name}</h3>
              <button
                onClick={() => {
                  setSelectedAgent(null);
                  setSelectedCard(null);
                }}
                className="p-1 rounded hover:bg-white/10"
              >
                <X size={16} />
              </button>
            </div>

            {isLoadingCard ? (
              <div className="text-sm text-slate-300">Loading agent card...</div>
            ) : selectedCard ? (
              <div className="space-y-4">
                <div className="grid md:grid-cols-2 gap-3 text-sm">
                  <div className="bg-black/30 border border-white/10 rounded-lg p-3">
                    <div className="text-xs text-slate-400 uppercase tracking-wider">Version</div>
                    <div className="font-semibold mt-1">{selectedCard.version}</div>
                  </div>
                  <div className="bg-black/30 border border-white/10 rounded-lg p-3">
                    <div className="text-xs text-slate-400 uppercase tracking-wider">Protocol</div>
                    <div className="font-semibold mt-1">{selectedCard.protocolVersion}</div>
                  </div>
                </div>

                <div className="bg-black/30 border border-white/10 rounded-lg p-3">
                  <div className="text-xs text-slate-400 uppercase tracking-wider">Description</div>
                  <div className="text-sm text-slate-100 mt-1">{selectedCard.description || "No description provided."}</div>
                </div>

                <div className="bg-black/30 border border-white/10 rounded-lg p-3">
                  <div className="text-xs text-slate-400 uppercase tracking-wider mb-2">Skills</div>
                  {selectedCard.skills.length === 0 ? (
                    <div className="text-sm text-slate-300">No skills listed.</div>
                  ) : (
                    <div className="space-y-2">
                      {selectedCard.skills.map((skill) => (
                        <div key={skill.id} className="border border-white/10 rounded-md p-2 bg-black/20">
                          <div className="text-sm font-semibold">{skill.name}</div>
                          <div className="text-xs text-slate-300 mt-1">{skill.description}</div>
                          <div className="flex flex-wrap gap-1 mt-2">
                            {skill.tags.map((tag) => (
                              <span
                                key={`${skill.id}-${tag}`}
                                className="text-[10px] px-2 py-1 rounded-full bg-white/10 border border-white/15 text-slate-100"
                              >
                                {tag}
                              </span>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="text-sm text-slate-300">No card details available.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
