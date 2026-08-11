export type Incident = {
  id: string;
  title: string;
  service: string;
  severity: string;
  status: string;
  started_at: string;
  root_cause?: string;
  confidence?: number;
  final_report?: string;
  runs?: { id: string; status: string; started_at: string }[];
};

export type AgentEvent = {
  id: number;
  node: string | null;
  type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

const j = (r: Response) => {
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
};

export const api = {
  incidents: (): Promise<Incident[]> => fetch("/api/incidents").then(j),
  incident: (id: string): Promise<Incident> =>
    fetch(`/api/incidents/${id}`).then(j),
  investigate: (id: string): Promise<{ run_id: string }> =>
    fetch(`/api/incidents/${id}/investigate`, { method: "POST" }).then(j),
  events: (runId: string, after = 0): Promise<AgentEvent[]> =>
    fetch(`/api/runs/${runId}/events?after=${after}`).then(j),
  run: (runId: string): Promise<{ status: string }> =>
    fetch(`/api/runs/${runId}`).then(j),
  approve: (runId: string, decision: "approve" | "reject") =>
    fetch(`/api/runs/${runId}/approval`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ decision }),
    }).then(j),
  timeseries: (kind: string, minutes = 30): Promise<{ points: { t: number; v: number }[] }> =>
    fetch(`/api/metrics/timeseries?kind=${kind}&minutes=${minutes}`).then(j),
  startScenario: (key: string) =>
    fetch(`/api/demo/scenarios/${key}/start`, { method: "POST" }).then(j),
  reset: () => fetch(`/api/demo/reset`, { method: "POST" }).then(j),
};
