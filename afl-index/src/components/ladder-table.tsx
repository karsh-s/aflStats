import { LADDER, TEAM_COLORS, TEAM_NAMES, type TeamCode } from "@/lib/afl-data";
import { useLadder } from "@/lib/queries";

export function LadderTable({ snapshot }: { snapshot?: boolean }) {
  // Live ladder recomputed from completed games; the bundled snapshot is only
  // a fallback for when the API is unreachable.
  const { data: live } = useLadder();
  const source = live && live.length
    ? live.map((r) => ({ ...r, team: r.team as TeamCode }))
    : LADDER;
  const rows = snapshot ? source.slice(0, 8) : source;
  return (
    <div className="space-y-1">
      <div className="flex px-1 pb-1 text-[10px] font-bold uppercase text-muted-foreground">
        <span className="w-8">Pos</span>
        <span className="flex-1">Team</span>
        {!snapshot && (
          <>
            <span className="w-10 text-right">P</span>
            <span className="w-10 text-right">W</span>
            <span className="w-10 text-right">L</span>
            <span className="w-10 text-right">Pts</span>
          </>
        )}
        <span className="w-14 text-right">%</span>
      </div>
      {rows.map((r) => {
        const inEight = r.pos <= 8;
        return (
          <div
            key={r.team}
            className={`flex items-center px-2 py-1.5 text-xs font-bold ${
              r.pos === 1
                ? "bg-ink text-paper"
                : inEight
                ? "border border-border bg-card"
                : "border border-border bg-card/50 text-muted-foreground"
            }`}
          >
            <span className="w-8 font-mono">{r.pos}</span>
            <span className="flex flex-1 items-center gap-2">
              <span
                className="size-2 rounded-full"
                style={{ background: TEAM_COLORS[r.team] }}
              />
              <span>{snapshot ? r.team : TEAM_NAMES[r.team]}</span>
            </span>
            {!snapshot && (
              <>
                <span className="w-10 text-right font-mono">{r.played}</span>
                <span className="w-10 text-right font-mono">{r.wins}</span>
                <span className="w-10 text-right font-mono">{r.losses}</span>
                <span className="w-10 text-right font-mono">{r.points}</span>
              </>
            )}
            <span className="w-14 text-right font-mono">{r.pct.toFixed(1)}</span>
          </div>
        );
      })}
    </div>
  );
}
