"use client";
import { useEffect, useState } from "react";

export default function Dashboard() {
  const [health, setHealth] = useState<string>("checking...");
  useEffect(() => {
    fetch("/api/incidents")
      .then((r) => (r.ok ? "connected" : `error ${r.status}`))
      .catch(() => "backend unreachable")
      .then(setHealth);
  }, []);
  return (
    <main className="flex h-screen items-center justify-center">
      <div className="text-center">
        <h1 className="text-3xl font-bold">Agentic SRE Copilot</h1>
        <p className="mt-2 text-zinc-400">backend: {health}</p>
      </div>
    </main>
  );
}
