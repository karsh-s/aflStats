import { useMemo, useState } from "react";
import { MULTI_LEGS, type MultiLeg } from "@/lib/afl-data";

export function MultiBuilder() {
  const [legs, setLegs] = useState<MultiLeg[]>(MULTI_LEGS);
  const combined = useMemo(
    () => legs.reduce((acc, l) => acc * (l.prob / 100), 1) * 100,
    [legs],
  );
  const odds = useMemo(
    () => legs.reduce((acc, l) => acc * (100 / l.prob), 1),
    [legs],
  );

  return (
    <div className="space-y-6 bg-ink p-5 text-paper ring-8 ring-ink/5">
      <div className="space-y-4">
        {legs.map((l, i) => (
          <div key={l.id} className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="font-mono text-[10px] font-bold uppercase tracking-widest text-paper/40">
                Leg {String(i + 1).padStart(2, "0")} / {l.match}
              </div>
              <div className="truncate text-sm font-bold">
                {l.player} · {l.prop}
              </div>
            </div>
            <div className="flex items-center gap-3 text-right">
              <div>
                <div className="font-mono text-sm font-bold text-accent">
                  {l.prob.toFixed(1)}%
                </div>
                <div className="text-[9px] font-bold uppercase text-paper/40">
                  Prob.
                </div>
              </div>
              <button
                aria-label="Remove leg"
                className="text-paper/40 transition-colors hover:text-accent"
                onClick={() => setLegs((cur) => cur.filter((x) => x.id !== l.id))}
              >
                ×
              </button>
            </div>
          </div>
        ))}
        {legs.length === 0 ? (
          <div className="border border-dashed border-paper/20 p-4 text-center text-[11px] uppercase text-paper/40">
            Add legs from the projections table
          </div>
        ) : null}
      </div>

      <div className="flex items-end justify-between border-t border-paper/10 pt-4">
        <div>
          <div className="font-display text-4xl font-black italic tracking-tighter">
            {legs.length ? combined.toFixed(1) : "0.0"}%
          </div>
          <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-paper/40">
            Combined Hit Prob · ${odds.toFixed(2)} fair
          </div>
        </div>
        <button className="bg-accent px-6 py-2 text-xs font-bold uppercase tracking-widest text-accent-foreground transition-all hover:brightness-110 active:translate-y-px">
          Lock &amp; Track
        </button>
      </div>
    </div>
  );
}
