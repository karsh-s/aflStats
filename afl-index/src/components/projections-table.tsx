import { PROJECTIONS, TEAM_NAMES } from "@/lib/afl-data";

export function ProjectionsTable({ limit }: { limit?: number }) {
  const rows = limit ? PROJECTIONS.slice(0, limit) : PROJECTIONS;
  return (
    <div className="border border-border bg-card">
      <div className="border-b border-border bg-ink/5 p-3">
        <span className="text-[11px] font-bold uppercase tracking-wider">
          Prop Confidence Bands · Expected Value
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-border text-[10px] font-bold uppercase text-muted-foreground">
              <th className="p-3">Player</th>
              <th className="p-3">Team</th>
              <th className="p-3">Stat</th>
              <th className="p-3 text-right">E(x)</th>
              <th className="p-3 text-right">Range</th>
              <th className="p-3 text-right">Edge</th>
            </tr>
          </thead>
          <tbody className="font-mono text-sm">
            {rows.map((p) => (
              <tr
                key={p.player + p.stat}
                className="border-b border-border last:border-0 hover:bg-accent/5"
              >
                <td className="p-3 font-sans font-bold">{p.player}</td>
                <td className="p-3 text-xs text-muted-foreground">
                  {TEAM_NAMES[p.team]}
                </td>
                <td className="p-3 text-xs text-muted-foreground">{p.stat}</td>
                <td className="p-3 text-right">{p.expected.toFixed(1)}</td>
                <td className="p-3 text-right text-accent">
                  [{p.low} – {p.high}]
                </td>
                <td
                  className={`p-3 text-right ${
                    p.edge >= 0 ? "text-ink" : "text-muted-foreground"
                  }`}
                >
                  {p.edge >= 0 ? "+" : ""}
                  {p.edge.toFixed(1)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
