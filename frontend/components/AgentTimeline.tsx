"use client";
import { AgentEvent } from "@/lib/api";

const NODE_LABELS: Record<string, string> = {
  triage: "TRIAGE",
  planner: "PLANNER",
  collect_metrics: "METRICS INVESTIGATOR",
  collect_logs: "LOG INVESTIGATOR",
  check_deployment: "DEPLOYMENT CHECK",
  retrieve_runbook: "RUNBOOK RAG",
  diagnose: "DIAGNOSIS",
  confidence_gate: "CONFIDENCE GATE",
  propose_remediation: "REMEDIATION PLANNER",
  risk_gate: "RISK GATE",
  execute_action: "ACTION EXECUTOR",
  verify: "VERIFICATION",
  report: "REPORT",
};

function EventLine({ e }: { e: AgentEvent }) {
  const p = e.payload as Record<string, any>;
  const time = new Date(e.created_at).toLocaleTimeString();
  switch (e.type) {
    case "tool_call":
      return (
        <div className="text-xs text-sky-300 font-mono">
          → {String(p.tool)}({JSON.stringify(p.arguments || {}).slice(1, 90)})
        </div>
      );
    case "evidence_found":
      return (
        <div className="text-xs text-emerald-300">
          ✓ evidence [{String(p.kind)}]{" "}
          <span className="text-zinc-400 font-mono">
            {JSON.stringify(p.summary).slice(0, 140)}…
          </span>
        </div>
      );
    case "hypothesis":
      return (
        <div className="text-xs text-amber-300">
          {p.root_cause ? (
            <>
              root cause: {String(p.root_cause).slice(0, 160)}{" "}
              <b>({Math.round((p.confidence || 0) * 100)}%)</b>
            </>
          ) : p.proposal ? (
            <>propose: {String(p.proposal.action)} risk={String(p.proposal.risk)}</>
          ) : (
            <>plan: {(p.plan || []).slice(0, 3).join(" · ")}</>
          )}
        </div>
      );
    case "approval_required":
      return (
        <div className="text-xs font-semibold text-rose-300">
          ⚠ APPROVAL REQUIRED — {String(p.action)} ({String(p.risk)})
        </div>
      );
    case "approval_decided":
      return (
        <div className="text-xs text-rose-200">decision: {String(p.decision)}</div>
      );
    case "action_finished":
      return (
        <div className="text-xs text-emerald-300 font-mono">
          action result: {JSON.stringify(p.result).slice(0, 120)}
        </div>
      );
    case "verification":
      return (
        <div className={`text-xs ${p.recovered ? "text-emerald-300" : "text-rose-300"}`}>
          {p.recovered ? "✓ Recovery verified" : "✗ Recovery not confirmed"}{" "}
          <span className="text-zinc-400 font-mono">
            after={JSON.stringify(p.after)}
          </span>
        </div>
      );
    case "error":
      return <div className="text-xs text-rose-400">error: {String(p.error)}</div>;
    default:
      return null;
  }
}

export default function AgentTimeline({ events }: { events: AgentEvent[] }) {
  // group consecutive events by node
  const groups: { node: string | null; events: AgentEvent[] }[] = [];
  for (const e of events) {
    const last = groups[groups.length - 1];
    if (last && last.node === e.node) last.events.push(e);
    else groups.push({ node: e.node, events: [e] });
  }
  return (
    <div className="space-y-3">
      {groups.map((g, i) => (
        <div key={i} className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3">
          <div className="mb-1 flex items-center gap-2">
            <span className="text-[10px] text-zinc-500">
              {new Date(g.events[0].created_at).toLocaleTimeString()}
            </span>
            <span className="text-xs font-bold tracking-wider text-zinc-200">
              {g.node ? NODE_LABELS[g.node] || g.node.toUpperCase() : "AGENT"}
            </span>
          </div>
          <div className="space-y-1">
            {g.events.map((e) => (
              <EventLine key={e.id} e={e} />
            ))}
          </div>
        </div>
      ))}
      {events.length === 0 && (
        <div className="text-sm text-zinc-500">No agent activity yet.</div>
      )}
    </div>
  );
}
