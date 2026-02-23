import React from "react";
import { Loader2, Sparkles } from "lucide-react";

import type { AgentStatus, AgentTask } from "../types";
import { groupAgentTasksByRole } from "../workflow-ui";

interface AgentDashboardProps {
  agents: AgentTask[];
}

const getStatusColor = (status: AgentStatus) => {
  switch (status) {
    case "running":
      return "bg-amber-500/20 border-amber-400/60 text-amber-50 shadow-[0_0_20px_rgba(245,158,11,0.25)]";
    case "completed":
    case "online":
      return "bg-emerald-500/20 border-emerald-400/50 text-emerald-50 shadow-[0_0_14px_rgba(74,222,128,0.25)]";
    case "offline":
    case "error":
      return "bg-rose-500/20 border-rose-400/40 text-rose-100";
    case "unknown":
      return "bg-slate-500/20 border-slate-300/30 text-slate-100";
    case "pending":
    default:
      return "bg-white/5 border-white/10 text-white/60";
  }
};

const getStatusPillStyle = (status: AgentStatus) => {
  switch (status) {
    case "running":
      return "bg-amber-500/20 border-amber-500/40 text-amber-200";
    case "completed":
      return "bg-emerald-500/20 border-emerald-400/40 text-emerald-200";
    case "online":
      return "bg-cyan-500/20 border-cyan-400/40 text-cyan-200";
    case "offline":
      return "bg-rose-500/20 border-rose-500/40 text-rose-200";
    case "error":
      return "bg-rose-500/20 border-rose-500/40 text-rose-200";
    case "unknown":
      return "bg-slate-500/20 border-slate-400/30 text-slate-200";
    default:
      return "bg-white/5 border-white/10 text-white/60";
  }
};

const getStatusLabel = (status: AgentStatus) => {
  switch (status) {
    case "running":
      return "Running";
    case "completed":
      return "Completed";
    case "online":
      return "Online";
    case "offline":
      return "Offline";
    case "unknown":
      return "Unknown";
    case "error":
      return "Error";
    case "pending":
    default:
      return "Pending";
  }
};

const AgentCard: React.FC<{ agent: AgentTask }> = ({ agent }) => (
  <div
    className={`relative flex flex-col justify-between p-4 rounded-xl border transition-all duration-500 h-28 backdrop-blur-md ${
      getStatusColor(agent.status)
    } ${agent.status === "running" ? "scale-[1.02] z-10" : "hover:bg-white/10"}`}
  >
    <div className="flex justify-between items-center w-full mb-1">
      <span className="text-[9px] font-bold tracking-widest uppercase opacity-70">{agent.id}</span>
      <div
        className={`px-2 py-[2px] rounded-full border text-[9px] font-bold uppercase tracking-wider flex items-center gap-1 transition-colors duration-300 ${getStatusPillStyle(
          agent.status
        )}`}
      >
        {agent.status === "running" && <Loader2 size={8} className="animate-spin" />}
        {getStatusLabel(agent.status)}
      </div>
    </div>

    <div className="flex-1 flex items-center justify-center">
      <div className="text-center w-full">
        <div className="font-semibold text-base leading-tight truncate px-2 text-gray-100">{agent.name}</div>
        {agent.description && (
          <div className="text-[9px] mt-1 text-slate-200/90 truncate font-medium">{agent.description}</div>
        )}
      </div>
    </div>
  </div>
);

const Section: React.FC<{
  title: string;
  subtitle: string;
  agents: AgentTask[];
  columns: string;
}> = ({ title, subtitle, agents, columns }) => (
  <section>
    <div className="flex justify-between items-center mb-3 px-1">
      <div className="text-[10px] font-bold text-white/70 uppercase tracking-wider">{title}</div>
      <div className="text-[10px] text-white/45 uppercase tracking-wide">{subtitle}</div>
    </div>
    <div className={`grid ${columns} gap-3`}>
      {agents.map((agent) => (
        <AgentCard key={agent.id} agent={agent} />
      ))}
    </div>
  </section>
);

export const AgentDashboard: React.FC<AgentDashboardProps> = ({ agents }) => {
  const groups = groupAgentTasksByRole(agents);

  return (
    <div className="w-[420px] bg-black/20 backdrop-blur-lg border-l border-white/10 flex flex-col h-full hidden xl:flex">
      <div className="p-6 pb-4 border-b border-white/10">
        <h2 className="font-bold text-white text-lg flex items-center gap-2 drop-shadow-sm">
          <Sparkles size={18} className="text-sky-300" />
          Agent Dashboard
        </h2>
        <p className="text-xs text-white/70 font-medium mt-1 ml-6">Live orchestration across A2A services</p>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-8 custom-scrollbar">
        <Section title="Orchestrator" subtitle="Port 10000" agents={groups.orchestrator} columns="grid-cols-1" />
        <Section
          title="Discovery Agents"
          subtitle="Ports 8001-8006"
          agents={groups.discovery}
          columns="grid-cols-2"
        />
        <Section title="Planning Agents" subtitle="Ports 8010-8013" agents={groups.planning} columns="grid-cols-2" />
        <Section title="Booking Agent" subtitle="Port 8020" agents={groups.booking} columns="grid-cols-1" />
      </div>
    </div>
  );
};
