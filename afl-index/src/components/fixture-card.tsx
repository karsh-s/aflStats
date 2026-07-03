import type { Fixture } from "@/lib/afl-data";
import { TEAM_COLORS } from "@/lib/afl-data";

export function FixtureCard({ f }: { f: Fixture }) {
  const homeWins = f.homeProb >= 50;
  const winner = homeWins ? f.home : f.away;
  const marginPrefix = `${winner} +${f.margin.toFixed(1)}`;
  return (
    <div className="group cursor-pointer border border-border p-3 transition-colors hover:bg-card">
      <div className="mb-4 flex items-start justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <div className="h-4 w-1" style={{ background: TEAM_COLORS[f.home] }} />
            <span className="text-sm font-bold">{f.home}</span>
            <span
              className={`px-1 font-mono text-[10px] ${
                homeWins ? "bg-ink/5" : "text-muted-foreground"
              }`}
            >
              {f.homeProb}%
            </span>
          </div>
          <div className="flex items-center gap-2">
            <div className="h-4 w-1" style={{ background: TEAM_COLORS[f.away] }} />
            <span className="text-sm font-bold">{f.away}</span>
            <span
              className={`px-1 font-mono text-[10px] ${
                !homeWins ? "bg-ink/5" : "text-muted-foreground"
              }`}
            >
              {100 - f.homeProb}%
            </span>
          </div>
        </div>
        <div className="text-right">
          <div className="text-[10px] font-bold uppercase text-muted-foreground">
            Proj. Margin
          </div>
          <div className="font-mono text-lg font-medium tracking-tighter">
            {marginPrefix}
          </div>
        </div>
      </div>
      <div className="flex h-1.5 w-full gap-1 overflow-hidden rounded-full bg-ink/5">
        <div
          className="h-full"
          style={{ width: `${f.homeProb}%`, background: TEAM_COLORS[f.home] }}
        />
        <div
          className="h-full"
          style={{ width: `${100 - f.homeProb}%`, background: TEAM_COLORS[f.away] }}
        />
      </div>
      <div className="mt-3 flex items-center justify-between border-t border-dashed border-border pt-3">
        <span className="text-[10px] font-bold text-muted-foreground">
          {f.venue} · {f.slot}
        </span>
        <span className="text-[10px] font-bold text-accent">
          Hedge: {f.totalSignal} {f.total}
        </span>
      </div>
    </div>
  );
}
