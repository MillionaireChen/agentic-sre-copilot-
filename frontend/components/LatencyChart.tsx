"use client";
import { useEffect, useState } from "react";
import {
  Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "@/lib/api";

export default function LatencyChart({ kind, title, color, format }: {
  kind: string; title: string; color: string;
  format?: (v: number) => string;
}) {
  const [data, setData] = useState<{ t: number; v: number }[]>([]);
  useEffect(() => {
    let alive = true;
    const load = () =>
      api.timeseries(kind).then((d) => alive && setData(d.points)).catch(() => {});
    load();
    const id = setInterval(load, 5000);
    return () => { alive = false; clearInterval(id); };
  }, [kind]);
  const fmt = format || ((v: number) => v.toFixed(2));
  const latest = data.length ? data[data.length - 1].v : null;
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3">
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-semibold text-zinc-400">{title}</span>
        <span className="text-lg font-bold" style={{ color }}>
          {latest !== null ? fmt(latest) : "–"}
        </span>
      </div>
      <div className="h-24">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data}>
            <XAxis
              dataKey="t" hide
              tickFormatter={(t) => new Date(t * 1000).toLocaleTimeString()}
            />
            <YAxis hide domain={[0, "auto"]} />
            <Tooltip
              contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", fontSize: 11 }}
              labelFormatter={(t) => new Date(Number(t) * 1000).toLocaleTimeString()}
              formatter={(v) => [fmt(Number(v)), title]}
            />
            <Area type="monotone" dataKey="v" stroke={color} fill={color}
                  fillOpacity={0.15} strokeWidth={1.5} isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
