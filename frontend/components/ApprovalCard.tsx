"use client";
import { api } from "@/lib/api";

export default function ApprovalCard({ runId, payload, onDecided }: {
  runId: string;
  payload: Record<string, any>;
  onDecided: () => void;
}) {
  const decide = async (d: "approve" | "reject") => {
    await api.approve(runId, d);
    onDecided();
  };
  return (
    <div className="rounded-lg border-2 border-rose-500/60 bg-rose-950/30 p-4">
      <div className="text-xs font-bold tracking-widest text-rose-300">
        ACTION REQUIRES APPROVAL
      </div>
      <div className="mt-2 text-lg font-bold text-zinc-100">
        {String(payload.action)}
      </div>
      <pre className="mt-1 whitespace-pre-wrap rounded bg-zinc-900 p-2 text-xs text-zinc-300">
        {JSON.stringify(payload.parameters, null, 2)}
      </pre>
      <div className="mt-2 text-sm text-zinc-300">{String(payload.reason)}</div>
      <div className="mt-2 flex gap-4 text-xs">
        <span className="font-semibold text-rose-300">Risk: {String(payload.risk)}</span>
        <span className="text-amber-300">
          Confidence: {Math.round((payload.confidence || 0) * 100)}%
        </span>
      </div>
      <div className="mt-4 flex gap-3">
        <button
          onClick={() => decide("reject")}
          className="rounded border border-zinc-600 px-4 py-1.5 text-sm text-zinc-300 hover:bg-zinc-800"
        >
          Reject
        </button>
        <button
          onClick={() => decide("approve")}
          className="rounded bg-rose-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-rose-500"
        >
          Approve
        </button>
      </div>
    </div>
  );
}
