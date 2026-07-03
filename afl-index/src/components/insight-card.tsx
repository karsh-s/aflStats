import type { Insight } from "@/lib/afl-data";

export function InsightCard({ i }: { i: Insight }) {
  return (
    <div className="border border-border bg-card p-4 shadow-[4px_4px_0px_rgba(18,18,18,0.05)]">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-[10px] font-bold uppercase tracking-widest text-accent">
          {i.tag}
        </div>
        {i.delta ? (
          <span className="font-mono text-[10px] font-bold">{i.delta}</span>
        ) : null}
      </div>
      <p className="text-pretty text-xs font-medium leading-relaxed">
        <span className="font-bold">{i.title}</span> {i.body}
      </p>
    </div>
  );
}
