"use client";
import { AgentEvent } from "@/lib/api";

export default function EvidencePanel({ events }: { events: AgentEvent[] }) {
  const evidence = events.filter((e) => e.type === "evidence_found");
  const byKind: Record<string, AgentEvent> = {};
  for (const e of evidence) byKind[String((e.payload as any).kind)] = e;
  const kinds = [
    ["triage", "Triage"],
    ["metrics", "Metrics"],
    ["logs", "Logs"],
    ["deployments", "Deployments"],
    ["runbooks", "Runbooks"],
  ] as const;
  return (
    <div>
      <div className="mb-2 text-[10px] font-bold tracking-widest text-zinc-500">
        EVIDENCE
      </div>
      <div className="space-y-3">
        {kinds.map(([k, label]) => {
          const e = byKind[k];
          return (
            <div key={k} className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-zinc-300">{label}</span>
                <span className={`text-[10px] ${e ? "text-emerald-400" : "text-zinc-600"}`}>
                  {e ? "✓ collected" : "pending"}
                </span>
              </div>
              {e && (
                <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-all text-[10px] text-zinc-400">
                  {JSON.stringify((e.payload as any).summary, null, 1)}
                </pre>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
