"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, AgentEvent, Incident } from "@/lib/api";
import AgentTimeline from "./AgentTimeline";
import LatencyChart from "./LatencyChart";
import ApprovalCard from "./ApprovalCard";
import EvidencePanel from "./EvidencePanel";

const sevColor: Record<string, string> = {
  "SEV-1": "bg-rose-600",
  "SEV-2": "bg-amber-600",
  "SEV-3": "bg-sky-700",
};

const statusColor: Record<string, string> = {
  OPEN: "text-amber-300",
  INVESTIGATING: "text-sky-300",
  RESOLVED: "text-emerald-300",
  AWAITING_APPROVAL: "text-rose-300",
};

export default function Dashboard() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [incident, setIncident] = useState<Incident | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState<string>("");
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [demoOpen, setDemoOpen] = useState(false);
  const lastEventId = useRef(0);

  const refreshIncidents = useCallback(() => {
    api.incidents().then((list) => {
      setIncidents(list);
      if (!selected && list.length) setSelected(list[0].id);
    }).catch(() => {});
  }, [selected]);

  useEffect(() => {
    refreshIncidents();
    const id = setInterval(refreshIncidents, 5000);
    return () => clearInterval(id);
  }, [refreshIncidents]);

  useEffect(() => {
    if (!selected) return;
    setEvents([]);
    lastEventId.current = 0;
    setRunId(null);
    api.incident(selected).then((inc) => {
      setIncident(inc);
      if (inc.runs?.length) setRunId(inc.runs[0].id);
    }).catch(() => {});
  }, [selected]);

  // poll events + run status for the active run
  useEffect(() => {
    if (!runId) return;
    let alive = true;
    const tick = async () => {
      try {
        const [evs, run] = await Promise.all([
          api.events(runId, lastEventId.current),
          api.run(runId),
        ]);
        if (!alive) return;
        if (evs.length) {
          lastEventId.current = evs[evs.length - 1].id;
          setEvents((prev) => [...prev, ...evs]);
        }
        setRunStatus(run.status);
        if (selected) api.incident(selected).then(setIncident).catch(() => {});
      } catch {}
    };
    tick();
    const id = setInterval(tick, 1500);
    return () => { alive = false; clearInterval(id); };
  }, [runId, selected]);

  const investigate = async () => {
    if (!selected) return;
    const { run_id } = await api.investigate(selected);
    setEvents([]);
    lastEventId.current = 0;
    setRunId(run_id);
  };

  const pendingApproval =
    runStatus === "AWAITING_APPROVAL"
      ? [...events].reverse().find((e) => e.type === "approval_required")
      : undefined;

  const report = incident?.final_report;

  return (
    <div className="flex h-screen flex-col">
      {/* Top nav */}
      <header className="flex items-center justify-between border-b border-zinc-800 px-4 py-2">
        <div className="flex items-center gap-3">
          <span className="text-sm font-bold tracking-wide">Agentic SRE Copilot</span>
          <span className="flex items-center gap-1 text-xs text-emerald-400">
            <span className="h-2 w-2 rounded-full bg-emerald-400" /> Production
          </span>
        </div>
        <div className="flex items-center gap-4 text-xs text-zinc-400">
          <span>Qwen3 · vLLM</span>
          <div className="relative">
            <button
              onClick={() => setDemoOpen(!demoOpen)}
              className="rounded border border-zinc-700 px-3 py-1 hover:bg-zinc-800"
            >
              Demo ▾
            </button>
            {demoOpen && (
              <div className="absolute right-0 z-10 mt-1 w-64 rounded border border-zinc-700 bg-zinc-900 p-1 shadow-xl">
                {[
                  ["db-pool", "DB Connection Pool Exhaustion"],
                  ["redis", "Redis Failure"],
                  ["memory-leak", "Memory Leak"],
                ].map(([key, label]) => (
                  <button
                    key={key}
                    onClick={async () => {
                      setDemoOpen(false);
                      await api.startScenario(key);
                      refreshIncidents();
                    }}
                    className="block w-full rounded px-3 py-1.5 text-left text-xs hover:bg-zinc-800"
                  >
                    Trigger: {label}
                  </button>
                ))}
                <button
                  onClick={async () => {
                    setDemoOpen(false);
                    await api.reset();
                    refreshIncidents();
                  }}
                  className="block w-full rounded px-3 py-1.5 text-left text-xs text-emerald-300 hover:bg-zinc-800"
                >
                  Reset Environment
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* Incident sidebar */}
        <aside className="w-60 shrink-0 overflow-y-auto border-r border-zinc-800 p-3">
          <div className="mb-2 text-[10px] font-bold tracking-widest text-zinc-500">
            INCIDENTS
          </div>
          {incidents.map((inc) => (
            <button
              key={inc.id}
              onClick={() => setSelected(inc.id)}
              className={`mb-2 block w-full rounded-lg border p-2 text-left ${
                selected === inc.id
                  ? "border-sky-600 bg-zinc-900"
                  : "border-zinc-800 hover:bg-zinc-900/60"
              }`}
            >
              <div className="flex items-center gap-2">
                <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold text-white ${sevColor[inc.severity] || "bg-zinc-600"}`}>
                  {inc.severity}
                </span>
                <span className={`text-[10px] ${statusColor[inc.status] || "text-zinc-400"}`}>
                  {inc.status}
                </span>
              </div>
              <div className="mt-1 truncate text-xs text-zinc-200">{inc.title}</div>
              <div className="text-[10px] text-zinc-500">
                {new Date(inc.started_at).toLocaleTimeString()}
              </div>
            </button>
          ))}
          {incidents.length === 0 && (
            <div className="text-xs text-zinc-500">
              No incidents. Use the Demo menu to trigger one.
            </div>
          )}
        </aside>

        {/* Center: incident + charts + timeline */}
        <main className="min-w-0 flex-1 overflow-y-auto p-4">
          {incident ? (
            <>
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-[10px] text-zinc-500">{incident.id}</div>
                  <h1 className="text-xl font-bold">{incident.title}</h1>
                  <div className="mt-1 flex items-center gap-2 text-xs">
                    <span className={`rounded px-1.5 py-0.5 font-bold text-white ${sevColor[incident.severity]}`}>
                      {incident.severity}
                    </span>
                    <span className={statusColor[incident.status] || "text-zinc-400"}>
                      {incident.status}
                    </span>
                    <span className="text-zinc-500">{incident.service}</span>
                  </div>
                </div>
                <button
                  onClick={investigate}
                  disabled={runStatus === "RUNNING" || runStatus === "AWAITING_APPROVAL"}
                  className="rounded bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:opacity-40"
                >
                  {runStatus === "RUNNING" ? "Investigating…" : "Investigate"}
                </button>
              </div>

              <div className="mt-4 grid grid-cols-3 gap-3">
                <LatencyChart kind="p95" title="p95 Latency" color="#38bdf8"
                              format={(v) => `${(v * 1000).toFixed(0)} ms`} />
                <LatencyChart kind="error_rate" title="5xx Rate" color="#fb7185"
                              format={(v) => `${(v * 100).toFixed(1)}%`} />
                <LatencyChart kind="db_waiting" title="DB Pool Waiting" color="#fbbf24"
                              format={(v) => v.toFixed(0)} />
              </div>

              <div className="mt-5">
                <div className="mb-2 text-[10px] font-bold tracking-widest text-zinc-500">
                  AGENT INVESTIGATION
                </div>
                <AgentTimeline events={events} />
              </div>

              {report && (
                <div className="mt-5 rounded-lg border border-emerald-800 bg-emerald-950/20 p-4">
                  <div className="mb-2 text-[10px] font-bold tracking-widest text-emerald-400">
                    INCIDENT REPORT
                  </div>
                  <pre className="whitespace-pre-wrap text-xs text-zinc-200">{report}</pre>
                </div>
              )}
            </>
          ) : (
            <div className="flex h-full items-center justify-center text-zinc-500">
              Select or trigger an incident.
            </div>
          )}
        </main>

        {/* Right: evidence / approval */}
        <aside className="w-80 shrink-0 overflow-y-auto border-l border-zinc-800 p-3">
          {pendingApproval && runId ? (
            <ApprovalCard
              runId={runId}
              payload={pendingApproval.payload}
              onDecided={() => setRunStatus("RUNNING")}
            />
          ) : (
            <EvidencePanel events={events} />
          )}
        </aside>
      </div>
    </div>
  );
}
